"""
Analytics routes — query logging metrics, feedback storage, compliance alerts.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.dependencies import get_graph_store, get_mongodb_db
from app.features.analytics import get_dashboard_stats, get_recent_queries
from app.features.active_learning import store_feedback, get_feedback_stats
from app.features.compliance_monitor import get_compliance_alerts

logger = logging.getLogger("docqa.api.analytics")
router = APIRouter()


# ─── Pydantic Request Models ──────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    tenant_id: str
    vertical:  str
    query:     str
    answer:    str
    rating:    str  # "positive" or "negative"
    chunk_ids: Optional[List[str]] = None
    comment:   Optional[str] = None


# ─── Knowledge Graph Visualizer endpoint ─────────────────────────────────────

@router.get("/analytics/{tenant_id}/graph")
def get_knowledge_graph(tenant_id: str, store: Any = Depends(get_graph_store)):
    """
    Return a ForceGraph2D-compatible {nodes, links} payload for the tenant's
    knowledge graph.
    """
    try:
        return store.get_knowledge_graph(tenant_id)
    except Exception as exc:
        logger.exception("Failed to build knowledge graph:")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Dashboard Stats Endpoints ────────────────────────────────────────────────

@router.get("/analytics/dashboard")
def get_dashboard(
    tenant_id: str,
    store: Any = Depends(get_graph_store),
    mongodb_db: Any = Depends(get_mongodb_db)
):
    """Retrieve full dashboard metadata metrics for a tenant."""
    try:
        stats = get_dashboard_stats(store, tenant_id, mongodb_db)
        if "error" in stats:
            raise HTTPException(status_code=500, detail=stats["error"])
        return stats
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load dashboard statistics:")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/analytics/recent")
def get_recent(
    tenant_id: str,
    limit: int = 50,
    store: Any = Depends(get_graph_store),
    mongodb_db: Any = Depends(get_mongodb_db)
):
    """Audit endpoint: fetch recent queries logged for the tenant."""
    try:
        records = get_recent_queries(store, tenant_id, limit, mongodb_db)
        return {"queries": records}
    except Exception as exc:
        logger.exception("Failed to load recent queries:")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── User Feedback (Active Learning) Endpoints ────────────────────────────────

@router.post("/analytics/feedback")
def submit_feedback(payload: FeedbackRequest, store: Any = Depends(get_graph_store)):
    """Submit thumbs up/down user rating for a search result."""
    rating_val = payload.rating.lower()
    if rating_val not in ("positive", "negative"):
        raise HTTPException(
            status_code=400,
            detail="Invalid rating. Supported ratings are: 'positive' (thumbs up) or 'negative' (thumbs down).",
        )
    try:
        feedback_id = store_feedback(
            store=store,
            tenant_id=payload.tenant_id,
            vertical=payload.vertical,
            query=payload.query,
            answer=payload.answer,
            rating=rating_val,
            chunk_ids=payload.chunk_ids,
            comment=payload.comment,
        )
        return {"success": True, "feedback_id": feedback_id}
    except Exception as exc:
        logger.exception("Failed to save feedback:")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/analytics/feedback/stats")
def get_feedback_statistics(tenant_id: str, store: Any = Depends(get_graph_store)):
    """Retrieve cumulative helpfulness feedback statistics grouped by vertical."""
    try:
        stats = get_feedback_stats(store, tenant_id)
        return {"stats": stats}
    except Exception as exc:
        logger.exception("Failed to fetch feedback stats:")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Compliance Alerts Endpoints ──────────────────────────────────────────────

@router.get("/compliance/alerts")
def get_alerts(tenant_id: str, limit: int = 20, store: Any = Depends(get_graph_store)):
    """Retrieve active compliance monitoring alerts for a tenant."""
    try:
        alerts = get_compliance_alerts(store, tenant_id, limit)
        return {"alerts": alerts}
    except Exception as exc:
        logger.exception("Failed to load compliance alerts:")
        raise HTTPException(status_code=500, detail=str(exc))
