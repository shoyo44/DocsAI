"""
Vector Retriever — pure cosine similarity search via in-process GraphStore.

Fastest retriever. Used for the HR vertical where semantic similarity
alone gives good results (policy questions are well-scoped).

Guarantees:
    - Only returns chunks belonging to the requesting tenant (tenant isolation)
    - Never returns superseded (old-version) chunks
    - Returns a List[ChunkResult] sorted by score descending
"""
from __future__ import annotations

import logging
from typing import Any, List

from app.core.interfaces import BaseRetriever
from app.core.schemas import ChunkResult

logger = logging.getLogger("docqa.retrievers.vector")


class VectorRetriever(BaseRetriever):
    """
    Retrieves top-K chunks by cosine similarity to the query embedding.

    Vertical: hr
    Speed:    fastest (in-memory vector scan, no graph traversal)
    Accuracy: good for straightforward policy questions
    """

    async def retrieve(
        self,
        embedding: List[float],
        store: Any,
        tenant_id: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[ChunkResult]:
        """
        Run a vector similarity search and return ranked ChunkResult objects.

        Args:
            embedding:  Float vector from Nomic embedding API.
            store:      GraphStore instance.
            tenant_id:  Caller's tenant — enforced at query level.
            top_k:      Number of results to return.

        Returns:
            List[ChunkResult] sorted by cosine similarity score (highest first).
        """
        try:
            records = store.vector_search(embedding, tenant_id, top_k)
            chunks = [_to_chunk_result(r) for r in records]
            logger.debug(
                "VectorRetriever: tenant=%s top_k=%d → %d results",
                tenant_id, top_k, len(chunks),
            )
            return chunks

        except Exception as exc:
            logger.error("VectorRetriever failed: %s", exc)
            return []


# ─── Helper ──────────────────────────────────────────────────────────────────

def _to_chunk_result(record: dict) -> ChunkResult:
    """Map a raw record dict to a typed ChunkResult."""
    return ChunkResult(
        id           = record["id"],
        text         = record["text"] or "",
        page         = record.get("page"),
        doc_id       = record.get("doc_id"),
        doc_name     = record.get("doc_name"),
        chunk_type   = record.get("chunk_type"),
        employee_type= record.get("employee_type"),
        superseded   = record.get("superseded", False),
        score        = float(record.get("score", 0.0)),
    )
