"""
Analytics — query metrics, audit log, and usage reporting.

Writes a QueryLog node to both the GraphStore and MongoDB (if connected).
Provides aggregated stats for the analytics dashboard.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("docqa.analytics")


# ── Audit log writer ──────────────────────────────────────────────────────────

def write_query_log(
    store:      Any,
    tenant_id:  str,
    vertical:   str,
    query:      str,
    answer:     str,
    confidence: str,
    not_found:  bool,
    latency_ms: float,
    mongodb_db: Optional[Any] = None,
) -> None:
    """
    Persist a QueryLog node for every completed query in GraphStore and MongoDB.
    Called at the end of each /query route handler.
    Failures are swallowed — logging must never break query responses.
    """
    # 1. Local GraphStore Log (as a backup/topology node)
    try:
        store.create_query_log(
            tenant_id=tenant_id,
            vertical=vertical,
            query=query,
            answer=answer,
            confidence=confidence,
            not_found=not_found,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.warning("Failed to write query log to GraphStore: %s", exc)

    # 2. MongoDB Shared History Sync
    if mongodb_db is not None:
        try:
            coll_name = os.getenv("MONGODB_COLLECTION", "chat_history")
            doc = {
                "type": "query_log",
                "tenant_id": tenant_id,
                "vertical": vertical,
                "query": query,
                "answer": answer,
                "confidence": confidence,
                "not_found": not_found,
                "latency_ms": latency_ms,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            mongodb_db[coll_name].insert_one(doc)
            logger.info("Successfully synced query log history to MongoDB: %s", coll_name)
        except Exception as exc:
            logger.warning("Failed to sync query log to MongoDB: %s", exc)


# ── Stats aggregation ─────────────────────────────────────────────────────────

def get_dashboard_stats(
    store: Any, tenant_id: str, mongodb_db: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Return all dashboard metrics for a tenant in one call.
    Overwrites query metrics with shared MongoDB data if available.
    """
    try:
        # Get baseline local document and chunk count stats
        stats = store.get_dashboard_stats(tenant_id)

        # Aggregate query log statistics from MongoDB if available
        if mongodb_db is not None:
            try:
                coll_name = os.getenv("MONGODB_COLLECTION", "chat_history")
                cursor = mongodb_db[coll_name].find({"tenant_id": tenant_id, "type": "query_log"})

                total_queries = 0
                not_found_count = 0
                total_latency = 0.0
                latency_by_vertical: Dict[str, List[float]] = {}
                unanswered: Dict[str, int] = {}

                for doc in cursor:
                    total_queries += 1
                    lat = doc.get("latency_ms", 0)
                    total_latency += lat

                    vert = doc.get("vertical", "unknown")
                    latency_by_vertical.setdefault(vert, []).append(lat)

                    if doc.get("not_found"):
                        not_found_count += 1
                        q = doc.get("query", "")
                        unanswered[q] = unanswered.get(q, 0) + 1

                nf_rate = round(not_found_count / total_queries * 100, 1) if total_queries else 0.0
                avg_lat = round(total_latency / total_queries, 1) if total_queries else 0.0

                top_unanswered = sorted(
                    [{"query": q, "times_asked": c} for q, c in unanswered.items()],
                    key=lambda x: x["times_asked"],
                    reverse=True,
                )[:10]

                lat_by_vert = [
                    {"vertical": v, "avg_ms": round(sum(lats) / len(lats), 1)}
                    for v, lats in sorted(
                        latency_by_vertical.items(),
                        key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
                        reverse=True,
                    )
                ]

                stats.update({
                    "total_queries": total_queries,
                    "not_found_count": not_found_count,
                    "not_found_rate_pct": nf_rate,
                    "avg_latency_ms": avg_lat,
                    "top_unanswered": top_unanswered,
                    "latency_by_vertical": lat_by_vert,
                })
            except Exception as db_exc:
                logger.warning("Failed to aggregate dashboard stats from MongoDB: %s", db_exc)

        return stats
    except Exception as exc:
        logger.error("get_dashboard_stats failed: %s", exc)
        return {"tenant_id": tenant_id, "error": str(exc)}


def get_recent_queries(
    store: Any, tenant_id: str, limit: int = 50, mongodb_db: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Return the most recent query logs for a tenant from MongoDB or local GraphStore."""
    if mongodb_db is not None:
        try:
            coll_name = os.getenv("MONGODB_COLLECTION", "chat_history")
            cursor = mongodb_db[coll_name].find(
                {"tenant_id": tenant_id, "type": "query_log"}
            ).sort("created_at", -1).limit(limit)

            results = []
            for doc in cursor:
                results.append({
                    "query": doc.get("query", ""),
                    "answer": doc.get("answer", ""),
                    "confidence": doc.get("confidence", ""),
                    "not_found": doc.get("not_found", False),
                    "latency_ms": doc.get("latency_ms", 0),
                    "created_at": doc.get("created_at", ""),
                })
            return results
        except Exception as db_exc:
            logger.warning("Failed to fetch recent queries from MongoDB: %s. Falling back to local store.", db_exc)

    try:
        return store.get_query_logs(tenant_id, limit)
    except Exception as exc:
        logger.error("get_recent_queries failed: %s", exc)
        return []
