"""
ContractIQ — Comparison Service  (Phase 2)
==========================================
Pipeline:
  1. Dual-query: retrieve all chunks from document A and document B in parallel
  2. Build a side-by-side context block (CONTRACT A / CONTRACT B sections)
  3. Send a strict JSON-schema delta-detection prompt to Cohere command-a-03-2025
  4. Parse the response into ClauseDelta objects grouped as added / removed / modified
  5. Compute overall_risk_shift score and direction
  6. Return a fully-typed ComparisonResult
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
    ClauseDelta,
    ComparisonResult,
    DocumentChunk,
)
from app.services.retriever import AdvancedRetriever

settings = get_settings()

# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

COMPARISON_SYSTEM_PROMPT = """You are ContractIQ, a senior legal-AI assistant specialised in commercial contract comparison.

Your task is to compare CONTRACT A (the baseline) against CONTRACT B (the revised version) and identify every meaningful legal difference.

Return ONLY a strict JSON object — no markdown, no prose, no code fences.

Output schema (all fields required):
{
  "executive_delta": "<2-4 sentence plain-English summary of the key differences between A and B>",
  "overall_risk_shift": <float between -1.0 and 1.0 — positive = B is riskier than A, negative = B is safer than A, 0 = neutral>,
  "risk_shift_direction": "<one of: improved | worsened | neutral>",
  "added_clauses": [
    {
      "delta_type": "added",
      "category": "<one of: indemnification | liability_cap | termination | ip_ownership | governing_law | payment_terms | confidentiality | force_majeure | warranty | dispute_resolution | other>",
      "text_a": null,
      "text_b": "<clause text that appears only in B, max 300 chars>",
      "significance": "<one of: low | medium | high | critical>",
      "explanation": "<what this new clause means and why it matters, 1-3 sentences>",
      "favours": "<one of: party_a | party_b | neutral | unknown>"
    }
  ],
  "removed_clauses": [
    {
      "delta_type": "removed",
      "category": "<category>",
      "text_a": "<clause text that appeared in A but not B, max 300 chars>",
      "text_b": null,
      "significance": "<low | medium | high | critical>",
      "explanation": "<why removing this clause matters, 1-3 sentences>",
      "favours": "<party_a | party_b | neutral | unknown>"
    }
  ],
  "modified_clauses": [
    {
      "delta_type": "modified",
      "category": "<category>",
      "text_a": "<original clause in A, max 300 chars>",
      "text_b": "<revised clause in B, max 300 chars>",
      "significance": "<low | medium | high | critical>",
      "explanation": "<what changed and the legal implication, 1-3 sentences>",
      "favours": "<party_a | party_b | neutral | unknown>"
    }
  ]
}

Rules:
- Only flag differences that carry legal or business significance — ignore trivial formatting or boilerplate rewording.
- Sort each list by significance (critical first).
- overall_risk_shift: +1.0 means B is catastrophically riskier; -1.0 means B is dramatically safer.
- Return ONLY valid JSON. No extra keys. No trailing commas."""


def _build_dual_context(
    chunks_a: List[DocumentChunk],
    chunks_b: List[DocumentChunk],
    doc_a: str,
    doc_b: str,
) -> str:
    """Build a side-by-side context string with labelled CONTRACT A / CONTRACT B sections."""

    def _dedup_text(chunks: List[DocumentChunk]) -> str:
        seen: set[str] = set()
        parts: list[str] = []
        for c in sorted(chunks, key=lambda x: x.metadata.get("chunk_index", 0)):
            fp = c.text.strip()[:80]
            if fp not in seen:
                seen.add(fp)
                parts.append(c.text.strip())
        return "\n\n".join(parts)

    text_a = _dedup_text(chunks_a)
    text_b = _dedup_text(chunks_b)

    return (
        f"═══ CONTRACT A — {doc_a} ═══\n{text_a}\n\n"
        f"═══ CONTRACT B — {doc_b} ═══\n{text_b}"
    )


def _parse_response(raw: str, doc_a: str, doc_b: str) -> dict:
    """Extract and validate the JSON payload, stripping any stray markdown fences."""
    clean = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.error(f"JSON parse failure for comparison {doc_a}↔{doc_b}: {exc}\nRaw: {raw[:500]}")
        raise ValueError(f"LLM returned malformed JSON: {exc}") from exc
    return data


def _hydrate_deltas(items: list, delta_type: str) -> List[ClauseDelta]:
    """Convert raw JSON dicts into typed ClauseDelta objects, skipping malformed entries."""
    out: List[ClauseDelta] = []
    for item in items:
        try:
            delta = ClauseDelta(
                delta_type=item.get("delta_type", delta_type),
                category=item.get("category", "other"),
                text_a=item.get("text_a"),
                text_b=item.get("text_b"),
                significance=item.get("significance", "medium"),
                explanation=item.get("explanation", ""),
                favours=item.get("favours", "unknown"),
            )
            out.append(delta)
        except Exception as exc:
            logger.warning(f"Skipping malformed delta item: {exc} | data={item}")
    return out


class ComparisonService:
    """
    ContractIQ Phase-2 service:
    Compares two ingested contract documents and produces a structured
    diff report with per-clause deltas and an overall risk-shift score.
    """

    def __init__(self):
        self.cohere_client = cohere.AsyncClient(api_key=settings.COHERE_API_KEY)
        self.retriever = AdvancedRetriever()

    async def _fetch_chunks(
        self,
        document_id: str,
        focus_area: Optional[str],
        label: str,
    ) -> List[DocumentChunk]:
        """Retrieve all chunks for one document; fallback to unfiltered if needed."""
        query = (
            "Extract all legal clauses, obligations, rights, payment terms, "
            "termination provisions, and risk-bearing sections from this contract"
            + (f", focusing on: {focus_area}" if focus_area else "")
        )
        filters = {"source": document_id}

        try:
            chunks = await self.retriever.retrieve(query, filters=filters)
        except Exception:
            chunks = []

        if not chunks:
            logger.warning(
                f"[{label}] Filtered retrieval empty for '{document_id}', trying unfiltered."
            )
            chunks = await self.retriever.retrieve(query, filters=None)

        if not chunks:
            raise ValueError(
                f"No content found for document '{document_id}' ({label}). "
                "Ensure it has been ingested via POST /api/v1/ingest."
            )

        logger.info(f"[{label}] {len(chunks)} chunks retrieved for '{document_id}'.")
        return chunks

    async def _call_llm(self, dual_context: str, focus_area: Optional[str]) -> str:
        """Send the comparison prompt to Cohere command-a and return raw text."""
        user_message = (
            "Compare the two contracts below and return a JSON delta report.\n"
            + (f"Pay special attention to differences in: {focus_area}\n\n" if focus_area else "\n")
            + dual_context
        )

        response = await self.cohere_client.chat(
            model="command-a-03-2025",
            message=user_message,
            preamble=COMPARISON_SYSTEM_PROMPT,
            temperature=0.05,
            max_tokens=4000,
        )
        return response.text

    async def compare(
        self,
        document_a: str,
        document_b: str,
        focus_area: Optional[str] = None,
    ) -> ComparisonResult:
        """
        Full comparison pipeline:
        1. Dual-parallel chunk retrieval (A and B simultaneously)
        2. Build side-by-side context block
        3. Call Cohere with JSON-schema delta prompt
        4. Parse + validate response
        5. Compute overall risk shift
        6. Return typed ComparisonResult
        """
        t0 = time.time()

        # Step 1 — Dual parallel retrieval
        chunks_a, chunks_b = await asyncio.gather(
            self._fetch_chunks(document_a, focus_area, "Doc-A"),
            self._fetch_chunks(document_b, focus_area, "Doc-B"),
        )

        # Step 2 — Build context
        dual_context = _build_dual_context(chunks_a, chunks_b, document_a, document_b)
        logger.debug(
            f"Dual context built: {len(dual_context)} chars "
            f"({len(chunks_a)} A-chunks, {len(chunks_b)} B-chunks)"
        )

        # Step 3 — LLM call
        raw_response = await self._call_llm(dual_context, focus_area)
        logger.debug(f"LLM comparison response: {len(raw_response)} chars.")

        # Step 4 — Parse
        data = _parse_response(raw_response, document_a, document_b)

        # Step 5 — Hydrate typed objects
        added    = _hydrate_deltas(data.get("added_clauses", []),    "added")
        removed  = _hydrate_deltas(data.get("removed_clauses", []),  "removed")
        modified = _hydrate_deltas(data.get("modified_clauses", []), "modified")

        total_deltas = len(added) + len(removed) + len(modified)

        # Clamp risk shift to [-1, 1]
        raw_shift = float(data.get("overall_risk_shift", 0.0))
        risk_shift = round(max(-1.0, min(1.0, raw_shift)), 3)

        direction = data.get("risk_shift_direction", "neutral")
        # Enforce consistency between score and direction
        if risk_shift > 0.05 and direction != "worsened":
            direction = "worsened"
        elif risk_shift < -0.05 and direction != "improved":
            direction = "improved"
        elif abs(risk_shift) <= 0.05:
            direction = "neutral"

        latency_ms = round((time.time() - t0) * 1000, 2)
        logger.info(
            f"ContractIQ comparison complete: {document_a} ↔ {document_b} | "
            f"shift={risk_shift} ({direction}) | deltas={total_deltas} | {latency_ms}ms"
        )

        return ComparisonResult(
            document_a=document_a,
            document_b=document_b,
            executive_delta=data.get("executive_delta", "Comparison complete."),
            overall_risk_shift=risk_shift,
            risk_shift_direction=direction,
            added_clauses=added,
            removed_clauses=removed,
            modified_clauses=modified,
            total_deltas=total_deltas,
            latency_ms=latency_ms,
        )
