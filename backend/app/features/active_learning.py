"""
Active Learning — user feedback collection for retrieval improvement.

Stores thumbs-up / thumbs-down feedback on query answers in the graph store.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("docqa.active_learning")


def store_feedback(
    store:     Any,
    tenant_id: str,
    vertical:  str,
    query:     str,
    answer:    str,
    rating:    str,                    # "positive" or "negative"
    chunk_ids: Optional[List[str]] = None,
    comment:   Optional[str]       = None,
) -> str:
    """
    Persist user feedback on a query/answer pair.

    Returns:
        feedback_id (UUID string)
    """
    feedback_id = store.store_feedback(
        tenant_id=tenant_id,
        vertical=vertical,
        query=query,
        answer=answer,
        rating=rating,
        comment=comment or "",
        chunk_ids=chunk_ids,
    )

    logger.info(
        "Feedback stored: tenant=%s vertical=%s rating=%s",
        tenant_id, vertical, rating,
    )
    return feedback_id


def get_feedback_stats(store: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """Return per-vertical feedback counts (positive / negative / total)."""
    return store.get_feedback_stats(tenant_id)
