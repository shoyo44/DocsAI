"""
Red-Flag Auto-Scanner — triggered immediately after every Law/Startup upload.

Scans ALL chunks in a document without user input, detecting 10 categories
of risky or unusual legal clauses.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger("docqa.redflag")

# Chunks sent per LLM call — prevents context window overflow on large contracts
_CHUNKS_PER_BATCH = 60

_SYSTEM_PROMPT = """You are a senior legal risk analyst performing an automatic red-flag scan.

SCAN FOR (10 categories):
1. Uncapped liability         — no maximum liability limit stated
2. Unilateral termination     — one party can exit without cause or notice period
3. Auto-renewal               — contract renews automatically without notice
4. Broad indemnification      — indemnifying the other party for their own negligence
5. One-sided IP assignment    — all IP assigned to counterparty without carve-outs
6. Missing governing law      — no jurisdiction or governing law clause
7. Non-standard damages       — unusually high or punitive liquidated damages
8. Unlimited audit rights     — counterparty can audit at any time without restriction
9. Perpetual license grants   — license grants with no termination right
10. Excessive non-compete     — non-compete/non-solicitation with excessive scope or duration

RULES:
- Only flag clauses ACTUALLY PRESENT in the provided chunks.
- Each flag must cite a specific clause reference or page number.
- Do NOT hallucinate clauses that are not shown.
- Assign severity: HIGH, MEDIUM, or LOW.
- Return ONLY valid JSON. No markdown. No preamble.

OUTPUT FORMAT:
{
  "document_risk_level": "HIGH" | "MEDIUM" | "LOW",
  "red_flags": [
    {
      "type":           "Uncapped Liability",
      "severity":       "HIGH",
      "clause_ref":     "Section 12.3",
      "page":           7,
      "excerpt":        "The Company shall be liable for all losses...",
      "recommendation": "Negotiate a liability cap of 12 months fees."
    }
  ],
  "summary": "Brief 2-3 sentence overall risk assessment."
}"""


def _parse_redflag_json(raw: str) -> Dict[str, Any]:
    """Robustly parse the LLM red-flag JSON response."""
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Cannot parse red-flag JSON: {raw[:100]}")


def _merge_batch_results(batch_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge multiple batch scan results into a single report."""
    all_flags: List[Dict] = []
    risk_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    max_risk = 0

    for result in batch_results:
        all_flags.extend(result.get("red_flags", []))
        lvl = risk_levels.get(result.get("document_risk_level", "LOW"), 1)
        max_risk = max(max_risk, lvl)

    # Deduplicate flags by type+clause_ref
    seen = set()
    unique_flags = []
    for flag in all_flags:
        key = (flag.get("type"), flag.get("clause_ref"))
        if key not in seen:
            seen.add(key)
            unique_flags.append(flag)

    risk_label = {3: "HIGH", 2: "MEDIUM", 1: "LOW"}.get(max_risk, "LOW")
    return {
        "document_risk_level": risk_label,
        "red_flags":           unique_flags,
        "summary":             f"{len(unique_flags)} red flags found. Overall risk: {risk_label}.",
    }


async def run_redflag_scan(
    doc_id:    str,
    tenant_id: str,
    doc_name:  str,
    store:     Any,
    cf_client: Any,
) -> Dict[str, Any]:
    """
    Fetch all chunks for a document and run the 10-category red-flag scan.
    Processes in batches of 60 chunks to avoid context window overflow.
    Stores the merged result as a RedFlagReport node in the graph store.
    """
    # Fetch all chunks
    chunks = store.get_document_chunks(doc_id, tenant_id)

    if not chunks:
        logger.warning("RedFlag scan: no chunks found for doc %s", doc_id)
        return {"error": "No chunks found.", "doc_id": doc_id}

    logger.info("RedFlag scan: '%s' — %d chunks in %d batch(es)",
                doc_name, len(chunks),
                (len(chunks) + _CHUNKS_PER_BATCH - 1) // _CHUNKS_PER_BATCH)

    # Process in batches
    batch_results: List[Dict[str, Any]] = []
    for i in range(0, len(chunks), _CHUNKS_PER_BATCH):
        batch = chunks[i : i + _CHUNKS_PER_BATCH]

        context_parts = []
        for c in batch:
            ref = c.get("clause_ref") or f"Page {c.get('page', '?')}"
            context_parts.append(f"[{ref}]\n{c['text']}")
        context = "\n\n---\n\n".join(context_parts)

        try:
            raw = await cf_client.chat(
                system_prompt=_SYSTEM_PROMPT,
                user_message=(
                    f"DOCUMENT: {doc_name} (batch {i // _CHUNKS_PER_BATCH + 1})\n\n"
                    f"CHUNKS:\n{context}"
                ),
                max_tokens=2000,
                temperature=0.05,
            )
            batch_result = _parse_redflag_json(raw)
            batch_results.append(batch_result)

        except json.JSONDecodeError as exc:
            logger.error("RedFlag batch %d parse error: %s", i, exc)
        except Exception as exc:
            logger.error("RedFlag batch %d failed: %s", i, exc)

    if not batch_results:
        return {"error": "All batches failed.", "doc_id": doc_id}

    # Merge batch results
    report = _merge_batch_results(batch_results)

    # Persist to graph store
    try:
        store.upsert_redflag_report(
            doc_id=doc_id,
            tenant_id=tenant_id,
            risk_level=report["document_risk_level"],
            flag_count=len(report["red_flags"]),
            summary=report["summary"],
            report_json=json.dumps(report),
        )
    except Exception as exc:
        logger.warning("RedFlag: failed to store report: %s", exc)

    logger.info(
        "RedFlag scan complete: '%s' — risk=%s flags=%d",
        doc_name, report["document_risk_level"], len(report["red_flags"]),
    )
    return {"doc_id": doc_id, "doc_name": doc_name, **report}


def get_stored_report(store: Any, doc_id: str, tenant_id: str) -> Dict | None:
    """Retrieve a previously computed red-flag report from the graph store."""
    return store.get_redflag_report(doc_id, tenant_id)
