"""
ContractIQ — Obligation Extractor Service  (Phase 3)
=====================================================
Pipeline:
  1. Retrieve all chunks for the target document
  2. Build a full contract context with party name substitution hints
  3. Send a structured JSON-schema extraction prompt to Cohere command-a
  4. Parse the response into typed Obligation objects
  5. Group obligations by responsible party
  6. Compute priority counts, identify earliest deadline
  7. Return a fully-typed ObligationRegistry
"""
import asyncio
import json
import re
import time
from typing import List, Optional

import cohere
from loguru import logger

from app.config import get_settings
from app.schemas import Obligation, ObligationRegistry, DocumentChunk
from app.services.retriever import AdvancedRetriever

settings = get_settings()

# ---------------------------------------------------------------------------
# Prompt Template
# ---------------------------------------------------------------------------

OBLIGATION_SYSTEM_PROMPT = """You are ContractIQ, a senior legal-AI assistant specialised in commercial contract analysis.

Your task is to extract every actionable obligation, duty, deadline, milestone, and recurring commitment from the contract text provided.

Return ONLY a strict JSON object — no markdown, no prose, no code fences.

Output schema (all fields required):
{
  "executive_summary": "<2-4 sentence plain-English overview of the contract's key obligations and who bears the most burden>",
  "earliest_deadline": "<ISO 8601 date string of the soonest deadline, or null if none are absolute dates>",
  "obligations": [
    {
      "obligation_id": "OBL-001",
      "obligation_type": "<one of: payment | delivery | reporting | approval | notice | non_compete | confidentiality | insurance | indemnification | termination_right | renewal | other>",
      "description": "<clear one-sentence plain-English description of what must be done>",
      "verbatim_text": "<verbatim or near-verbatim text from the contract, max 400 characters>",
      "responsible_party": "<one of: party_a | party_b | both | unknown>",
      "counterparty": "<one of: party_a | party_b | both | unknown>",
      "due_date": "<ISO date string, relative expression like '30 days after signing', 'monthly', or null>",
      "is_recurring": <true | false>,
      "recurrence_schedule": "<e.g. 'monthly', 'quarterly', 'on each invoice date', or null>",
      "priority": "<one of: critical | high | medium | low>",
      "status": "<one of: pending | recurring | conditional | expired>",
      "penalty_clause": "<verbatim penalty/consequence text if stated, or null>",
      "conditions": "<any conditions that must be met before this obligation triggers, or null>"
    }
  ]
}

Priority guidelines:
- critical: financial obligations, termination triggers, IP transfers, penalties with defined amounts
- high: reporting deadlines, notice requirements, insurance minimums, non-compete scope
- medium: approval processes, delivery milestones, renewal windows
- low: administrative duties, minor notice requirements, housekeeping

Rules:
- Extract EVERY obligation — do not skip minor ones.
- Number obligation_ids sequentially: OBL-001, OBL-002, ...
- If the contract uses party names, map them to party_a / party_b based on the hints provided.
- Return ONLY valid JSON. No extra keys. No trailing commas."""


def _dedup_context(chunks: List[DocumentChunk]) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for c in sorted(chunks, key=lambda x: x.metadata.get("chunk_index", 0)):
        fp = c.text.strip()[:80]
        if fp not in seen:
            seen.add(fp)
            parts.append(c.text.strip())
    return "\n\n".join(parts)


def _parse_response(raw: str, document_id: str) -> dict:
    clean = re.sub(r"```(?:json)?", "", raw).strip()
    # Remove trailing ``` if any
    clean = clean.rstrip("`").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.error(f"JSON parse failure for obligations '{document_id}': {exc}\nRaw: {raw[:600]}")
        raise ValueError(f"LLM returned malformed JSON: {exc}") from exc


def _hydrate_obligation(item: dict) -> Optional[Obligation]:
    """Convert a raw dict into a typed Obligation, returning None on failure."""
    try:
        return Obligation(
            obligation_id=item.get("obligation_id", "OBL-???"),
            obligation_type=item.get("obligation_type", "other"),
            description=item.get("description", ""),
            verbatim_text=item.get("verbatim_text", "")[:400],
            responsible_party=item.get("responsible_party", "unknown"),
            counterparty=item.get("counterparty", "unknown"),
            due_date=item.get("due_date"),
            is_recurring=bool(item.get("is_recurring", False)),
            recurrence_schedule=item.get("recurrence_schedule"),
            priority=item.get("priority", "medium"),
            status=item.get("status", "pending"),
            penalty_clause=item.get("penalty_clause"),
            conditions=item.get("conditions"),
        )
    except Exception as exc:
        logger.warning(f"Skipping malformed obligation: {exc} | data={item}")
        return None


PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class ObligationExtractor:
    """
    ContractIQ Phase-3 service:
    Extracts every obligation from an ingested contract document and
    returns a structured, party-grouped ObligationRegistry.
    """

    def __init__(self):
        self.cohere_client = cohere.AsyncClient(api_key=settings.COHERE_API_KEY)
        self.retriever = AdvancedRetriever()

    async def _fetch_chunks(self, document_id: str) -> List[DocumentChunk]:
        """Retrieve all chunks for the document; fallback to unfiltered search."""
        query = (
            "Extract all obligations, duties, payments, deadlines, milestones, "
            "reporting requirements, notice periods, penalties, and recurring commitments "
            "from this contract"
        )
        filters = {"source": document_id}
        try:
            chunks = await self.retriever.retrieve(query, filters=filters)
        except Exception:
            chunks = []

        if not chunks:
            logger.warning(f"Filtered retrieval empty for '{document_id}', trying unfiltered.")
            chunks = await self.retriever.retrieve(query, filters=None)

        if not chunks:
            raise ValueError(
                f"No content found for document '{document_id}'. "
                "Ensure it has been ingested via POST /api/v1/ingest."
            )
        logger.info(f"[ObligationExtractor] {len(chunks)} chunks retrieved for '{document_id}'.")
        return chunks

    async def _call_llm(
        self,
        context: str,
        party_a_name: str,
        party_b_name: str,
    ) -> str:
        party_hints = (
            f"\nParty mapping hints:\n"
            f"  - '{party_a_name}' → party_a\n"
            f"  - '{party_b_name}' → party_b\n"
            "  Use these mappings when attributing obligations to responsible_party and counterparty.\n"
        )
        user_message = (
            "Extract all obligations from the contract text below and return the JSON registry.\n"
            + party_hints
            + "\n\n"
            + context
        )
        response = await self.cohere_client.chat(
            model="command-a-03-2025",
            message=user_message,
            preamble=OBLIGATION_SYSTEM_PROMPT,
            temperature=0.05,
            max_tokens=5000,
        )
        return response.text

    async def extract(
        self,
        document_id: str,
        party_a_name: str = "Party A",
        party_b_name: str = "Party B",
    ) -> ObligationRegistry:
        """
        Full extraction pipeline:
        1. Retrieve + deduplicate chunks
        2. Call Cohere with structured obligation-extraction prompt
        3. Parse and hydrate Obligation objects
        4. Group by responsible_party, sort by priority
        5. Compute aggregate stats and earliest deadline
        6. Return typed ObligationRegistry
        """
        t0 = time.time()

        chunks  = await self._fetch_chunks(document_id)
        context = _dedup_context(chunks)
        logger.debug(f"Obligation context: {len(context)} chars from {len(chunks)} chunks.")

        raw     = await self._call_llm(context, party_a_name, party_b_name)
        logger.debug(f"LLM obligation response: {len(raw)} chars.")

        data = _parse_response(raw, document_id)

        raw_obligations: list[dict] = data.get("obligations", [])
        all_obligations: List[Obligation] = []
        for item in raw_obligations:
            obj = _hydrate_obligation(item)
            if obj:
                all_obligations.append(obj)

        # Sort all by priority then obligation_id
        all_obligations.sort(key=lambda o: (PRIORITY_ORDER.get(o.priority, 99), o.obligation_id))

        # Group by responsible party
        party_a = [o for o in all_obligations if o.responsible_party == "party_a"]
        party_b = [o for o in all_obligations if o.responsible_party == "party_b"]
        shared  = [o for o in all_obligations if o.responsible_party in ("both", "unknown")]

        # Priority counts
        def _count(p: str) -> int:
            return sum(1 for o in all_obligations if o.priority == p)

        latency_ms = round((time.time() - t0) * 1000, 2)
        logger.info(
            f"ContractIQ obligations: '{document_id}' | "
            f"{len(all_obligations)} obligations extracted | "
            f"critical={_count('critical')} high={_count('high')} | {latency_ms}ms"
        )

        return ObligationRegistry(
            document_id=document_id,
            total_obligations=len(all_obligations),
            critical_count=_count("critical"),
            high_count=_count("high"),
            medium_count=_count("medium"),
            low_count=_count("low"),
            party_a_obligations=party_a,
            party_b_obligations=party_b,
            shared_obligations=shared,
            executive_summary=data.get("executive_summary", "Obligation extraction complete."),
            earliest_deadline=data.get("earliest_deadline"),
            latency_ms=latency_ms,
        )
