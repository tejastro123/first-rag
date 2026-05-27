"""
ContractIQ — Risk Analysis Service  (Phase 1)
=============================================
Pipeline:
  1. Pull all chunks for the target document from Qdrant via the AdvancedRetriever
  2. Assemble a compact context block (~full contract text, de-duplicated)
  3. Send a structured JSON-schema prompt to Cohere command-a-03-2025
  4. Parse the strictly-typed JSON response into RiskClause + ContractAnalysis objects
  5. Compute the aggregate risk score and tier
"""
import asyncio
import json
import re
import time
from typing import List, Optional

import cohere
from loguru import logger

from app.config import get_settings
from app.schemas import (
    RiskClause,
    ContractAnalysis,
    DocumentChunk,
)
from app.services.retriever import AdvancedRetriever

settings = get_settings()

# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

RISK_ANALYSIS_SYSTEM_PROMPT = """You are ContractIQ, a senior legal-AI assistant specialised in commercial contract risk analysis.

Your task is to analyse the provided contract text and return a STRICT JSON object — no markdown, no prose, no code fences.

Output schema (every field required):
{
  "executive_summary": "<2-4 sentence plain-English summary of the overall risk profile>",
  "clause_count": <integer — total distinct clauses you identified>,
  "flagged_clauses": [
    {
      "clause_text": "<verbatim or tightly paraphrased clause, max 300 chars>",
      "category": "<one of: indemnification | liability_cap | termination | ip_ownership | governing_law | payment_terms | confidentiality | force_majeure | warranty | dispute_resolution | other>",
      "risk_score": <float 0.0–1.0>,
      "risk_level": "<one of: low | medium | high | critical>",
      "explanation": "<why this clause is risky, 1-3 sentences>",
      "recommendation": "<suggested negotiation position or mitigation, 1-2 sentences>"
    }
  ]
}

Risk scoring guide:
  0.0–0.25 → low       (standard, market-norm clause)
  0.26–0.50 → medium   (mildly one-sided, worth flagging)
  0.51–0.75 → high     (significantly unfavourable, negotiate hard)
  0.76–1.00 → critical (unacceptable — do NOT sign without amendment)

Rules:
- Only flag clauses that carry genuine legal or business risk.
- Do NOT include boilerplate recitals or definitional sections unless they hide risk.
- Sort flagged_clauses by risk_score descending.
- Return ONLY valid JSON. No extra keys. No trailing commas."""


def _build_contract_context(chunks: List[DocumentChunk]) -> str:
    """
    De-duplicate and concatenate retrieved chunks into a coherent contract text block.
    Chunks are already ordered by relevance; re-order by original position if available.
    """
    seen_texts: set[str] = set()
    ordered: list[str] = []

    # Sort by chunk index metadata if available (preserves clause ordering)
    sorted_chunks = sorted(
        chunks,
        key=lambda c: c.metadata.get("chunk_index", 0),
    )

    for chunk in sorted_chunks:
        text = chunk.text.strip()
        # Use first 80 chars as a fingerprint to catch near-duplicates
        fingerprint = text[:80]
        if fingerprint not in seen_texts:
            seen_texts.add(fingerprint)
            ordered.append(text)

    return "\n\n".join(ordered)


def _score_to_level(score: float) -> str:
    if score <= 0.25:
        return "low"
    elif score <= 0.50:
        return "medium"
    elif score <= 0.75:
        return "high"
    else:
        return "critical"


def _parse_llm_response(raw: str, document_id: str) -> dict:
    """
    Extract and validate the JSON payload from the LLM response.
    Handles minor formatting artefacts (stray markdown fences, etc.).
    """
    # Strip markdown code fences if present
    clean = re.sub(r"```(?:json)?", "", raw).strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.error(f"JSON parse failure for '{document_id}': {exc}\nRaw: {raw[:500]}")
        raise ValueError(f"LLM returned malformed JSON: {exc}") from exc

    return data


class RiskAnalysisService:
    """
    ContractIQ Phase-1 service:
    Analyses an ingested contract document and produces a structured
    risk report with per-clause scores and an executive summary.
    """

    def __init__(self):
        self.cohere_client = cohere.AsyncClient(api_key=settings.COHERE_API_KEY)
        self.retriever = AdvancedRetriever()

    async def _fetch_document_chunks(
        self,
        document_id: str,
        focus_area: Optional[str],
    ) -> List[DocumentChunk]:
        """
        Retrieve all chunks belonging to the target document.
        Uses a broad metadata-filtered search so we capture the full contract text,
        then a focus-area query to surface the most legally relevant sections first.
        """
        # Primary: metadata-filtered retrieval to get document-specific chunks
        query = (
            f"Identify and extract all legal clauses, obligations, rights, "
            f"and risk provisions from this contract"
            + (f", focusing on: {focus_area}" if focus_area else "")
        )
        filters = {"source": document_id}

        try:
            chunks = await self.retriever.retrieve(query, filters=filters)
        except Exception:
            # Fallback: unfiltered retrieval if metadata filter returns nothing
            logger.warning(
                f"Filtered retrieval returned 0 chunks for '{document_id}', "
                "falling back to unfiltered."
            )
            chunks = await self.retriever.retrieve(query, filters=None)

        if not chunks:
            raise ValueError(
                f"No content found for document '{document_id}'. "
                "Ensure the document has been ingested via POST /api/v1/ingest."
            )

        logger.info(f"Fetched {len(chunks)} chunks for '{document_id}'.")
        return chunks

    async def _call_llm(self, contract_text: str, focus_area: Optional[str]) -> str:
        """Send the analysis prompt to Cohere command-a and return raw text."""
        user_message = (
            f"Analyse the following contract text and return a JSON risk report.\n"
            + (f"Pay special attention to: {focus_area}\n\n" if focus_area else "\n")
            + f"CONTRACT TEXT:\n{'─' * 60}\n{contract_text}\n{'─' * 60}"
        )

        response = await self.cohere_client.chat(
            model="command-a-03-2025",
            message=user_message,
            preamble=RISK_ANALYSIS_SYSTEM_PROMPT,
            temperature=0.05,        # Near-deterministic for structured output
            max_tokens=3000,
        )
        return response.text

    async def analyze(
        self,
        document_id: str,
        focus_area: Optional[str] = None,
    ) -> ContractAnalysis:
        """
        Full analysis pipeline:
        1. Fetch document chunks
        2. Build contract context
        3. Call Cohere with JSON-schema prompt
        4. Parse + validate response
        5. Compute aggregate risk score
        """
        t0 = time.time()

        # Step 1 — Retrieve
        chunks = await self._fetch_document_chunks(document_id, focus_area)

        # Step 2 — Build context
        contract_text = _build_contract_context(chunks)
        logger.debug(f"Contract context built: {len(contract_text)} chars.")

        # Step 3 — LLM call
        raw_response = await self._call_llm(contract_text, focus_area)
        logger.debug(f"LLM raw response ({len(raw_response)} chars) received.")

        # Step 4 — Parse
        data = _parse_llm_response(raw_response, document_id)

        # Step 5 — Hydrate typed objects
        flagged_clauses: List[RiskClause] = []
        for item in data.get("flagged_clauses", []):
            score = float(item.get("risk_score", 0.0))
            # Enforce risk_level consistency even if LLM drifts
            level = item.get("risk_level") or _score_to_level(score)
            try:
                clause = RiskClause(
                    clause_text=item.get("clause_text", ""),
                    category=item.get("category", "other"),
                    risk_score=round(score, 3),
                    risk_level=level,
                    explanation=item.get("explanation", ""),
                    recommendation=item.get("recommendation", ""),
                )
                flagged_clauses.append(clause)
            except Exception as exc:
                logger.warning(f"Skipping malformed clause item: {exc} | data={item}")

        # Aggregate score = weighted mean (top clauses weigh more)
        if flagged_clauses:
            scores = [c.risk_score for c in flagged_clauses]
            # Weight top-3 heavier to surface worst-case risk
            scores_sorted = sorted(scores, reverse=True)
            top = scores_sorted[:3]
            rest = scores_sorted[3:]
            weighted = (sum(top) * 2 + sum(rest)) / (len(top) * 2 + len(rest))
            overall_score = round(min(weighted, 1.0), 3)
        else:
            overall_score = 0.0

        overall_level = _score_to_level(overall_score)

        latency_ms = round((time.time() - t0) * 1000, 2)
        logger.info(
            f"ContractIQ analysis complete for '{document_id}': "
            f"score={overall_score}, level={overall_level}, "
            f"clauses={len(flagged_clauses)}, latency={latency_ms}ms"
        )

        return ContractAnalysis(
            document_id=document_id,
            overall_risk_score=overall_score,
            overall_risk_level=overall_level,
            executive_summary=data.get("executive_summary", "Analysis complete."),
            flagged_clauses=flagged_clauses,
            clause_count=data.get("clause_count", len(flagged_clauses)),
            latency_ms=latency_ms,
        )
