"""
Compliance Monitor — automated regulation change detection and alerting.

Triggered when a new regulation document is uploaded to the compliance vertical.
Compares new regulation content against all existing compliance documents.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List

logger = logging.getLogger("docqa.compliance_monitor")

_MONITOR_SYSTEM_PROMPT = """You are a senior compliance analyst comparing regulatory documents.

Given:
  - NEW REGULATION: the newly uploaded regulatory text
  - EXISTING DOCUMENTS: chunks from currently stored compliance documents

Your task:
1. Identify articles/sections in the NEW REGULATION that differ from existing documents.
2. Flag any existing compliance positions that may now be outdated.
3. List specific action items required to stay compliant.

Return ONLY valid JSON:
{
  "changed_articles": ["Article 6(1)(a) — new consent requirements added"],
  "affected_existing_docs": ["GDPR Policy v2.1 — Section 3 needs update"],
  "action_required": ["Update consent forms to include explicit opt-in"],
  "severity": "HIGH" | "MEDIUM" | "LOW",
  "summary": "Brief 2-3 sentence summary of what changed."
}"""


async def run_compliance_monitor(
    store:      Any,
    cf_client:  Any,
    tenant_id:  str,
    new_doc_id: str,
    new_doc_name: str,
    new_doc_chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compare a newly uploaded regulation against existing compliance documents.
    """
    # Fetch existing compliance documents
    existing = store.get_existing_compliance_chunks(tenant_id, new_doc_id)

    if not existing:
        logger.info("ComplianceMonitor: no existing docs for tenant=%s — skipped.", tenant_id)
        return {"skipped": True, "reason": "No existing compliance documents to compare."}

    # Build context strings
    new_text = "\n\n".join(
        f"[{c.get('article_ref','?')}]\n{c['text']}"
        for c in new_doc_chunks[:80]
    )
    old_text = "\n\n".join(
        f"[{r['doc_name']} | {r.get('article_ref','?')}]\n{r['text']}"
        for r in existing[:100]
    )

    user_message = (
        f"NEW REGULATION: {new_doc_name}\n\n"
        f"{new_text}\n\n"
        f"---\n\n"
        f"EXISTING DOCUMENTS:\n\n{old_text}"
    )

    try:
        raw = await cf_client.chat(
            system_prompt=_MONITOR_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=1500,
            temperature=0.05,
        )

        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        report = json.loads(raw.strip())

    except Exception as exc:
        logger.error("ComplianceMonitor LLM call failed: %s", exc)
        return {"error": str(exc), "doc_id": new_doc_id}

    # Store alert in graph store
    alert_id = str(uuid.uuid4())
    try:
        store.store_compliance_alert(
            alert_id=alert_id,
            tenant_id=tenant_id,
            doc_id=new_doc_id,
            change_count=len(report.get("changed_articles", [])),
            severity=report.get("severity", "LOW"),
            report_json=json.dumps(report),
        )
    except Exception as exc:
        logger.warning("ComplianceMonitor: failed to store alert: %s", exc)

    logger.info(
        "ComplianceMonitor: %d changes detected, severity=%s",
        len(report.get("changed_articles", [])), report.get("severity"),
    )
    return {"alert_id": alert_id, "doc_id": new_doc_id, **report}


def get_compliance_alerts(
    store: Any, tenant_id: str, limit: int = 20
) -> List[Dict[str, Any]]:
    """Retrieve recent compliance alerts for a tenant."""
    return store.get_compliance_alerts(tenant_id, limit)
