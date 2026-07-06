"""
Graph Retriever — entity-enriched graph traversal retrieval.

Used for Law and Startup verticals where related clauses are connected
through shared named entities (companies, persons, legal terms).

Strategy (2-phase):
    Phase 1 — Seed: find top-K chunks by vector similarity.
    Phase 2 — Expand: from each seed chunk, traverse:
        (Chunk)-[:MENTIONS]->(Entity)<-[:MENTIONS]-(neighbor:Chunk)
        (Chunk)-[:NEXT_CHUNK]-(adjacent:Chunk)

    Neighbors get a discounted score (seed_score × NEIGHBOR_DISCOUNT).
    All chunks are deduplicated and re-sorted by best score.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.interfaces import BaseRetriever
from app.core.schemas import ChunkResult

logger = logging.getLogger("docqa.retrievers.graph")

_NEIGHBOR_DISCOUNT = 0.80   # score multiplier for entity/adjacency neighbors
_NEXT_CHUNK_SCORE  = 0.75   # score multiplier for sequential neighbors


class GraphRetriever(BaseRetriever):
    """
    Vector seed → entity-graph expansion retriever.

    Vertical: law, startup
    Speed:    moderate (vector scan + graph expansion)
    Accuracy: best for cross-clause relational queries
    """

    async def retrieve(
        self,
        embedding: List[float],
        store: Any,
        tenant_id: str,
        top_k: int = 15,
        **kwargs: Any,
    ) -> List[ChunkResult]:
        """
        Retrieve seed chunks by vector similarity, then expand via entity graph.

        Args:
            embedding:  Query embedding vector.
            store:      GraphStore instance.
            tenant_id:  Enforced for tenant isolation.
            top_k:      Number of seed chunks (expansion may return more).

        Returns:
            Deduplicated List[ChunkResult] sorted by best score descending.
        """
        try:
            # ── Phase 1: vector seed ──────────────────────────────────────────
            seed_records = store.vector_search(embedding, tenant_id, top_k)

            if not seed_records:
                logger.debug("GraphRetriever: no seeds found for tenant=%s", tenant_id)
                return []

            # Build seed score map for fast lookup
            seed_score_map: Dict[str, float] = {
                r["id"]: float(r["score"]) for r in seed_records
            }
            seed_ids = list(seed_score_map.keys())

            # ── Phase 2: graph expansion ──────────────────────────────────────
            neighbor_records = store.expand_from_seeds(seed_ids, tenant_id)

            # ── Merge + deduplicate ───────────────────────────────────────────
            seen: Dict[str, ChunkResult] = {}

            # Add seeds first (highest priority)
            for r in seed_records:
                chunk = _to_chunk_result(r, float(r["score"]))
                seen[chunk.id] = chunk

            # Add neighbors with discounted scores
            for r in neighbor_records:
                cid = r["id"]
                if cid in seen:
                    continue   # seed takes priority

                # Derive score: use the highest seed's score × discount
                base_score = max(seed_score_map.values(), default=0.5)
                discount = (
                    _NEIGHBOR_DISCOUNT if r.get("source") == "entity"
                    else _NEXT_CHUNK_SCORE
                )
                chunk = _to_chunk_result(r, base_score * discount)
                seen[cid] = chunk

            # Sort by best_score descending, cap at top_k * 2
            results = sorted(seen.values(), key=lambda c: c.score, reverse=True)
            results = results[: top_k * 2]

            logger.debug(
                "GraphRetriever: tenant=%s → %d seeds + %d neighbors = %d total",
                tenant_id, len(seed_records), len(neighbor_records), len(results),
            )
            return results

        except Exception as exc:
            logger.error("GraphRetriever failed: %s", exc)
            return []


# ─── Helper ──────────────────────────────────────────────────────────────────

def _to_chunk_result(record: dict, score: float) -> ChunkResult:
    return ChunkResult(
        id           = record["id"],
        text         = record["text"] or "",
        page         = record.get("page"),
        doc_id       = record.get("doc_id"),
        doc_name     = record.get("doc_name"),
        chunk_type   = record.get("chunk_type"),
        clause_ref   = record.get("clause_ref"),
        defined_term = record.get("defined_term"),
        superseded   = record.get("superseded", False),
        score        = round(score, 4),
    )
