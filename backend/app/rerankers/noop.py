"""
NoOp Reranker — pass-through, no reranking.

Used for the HR vertical where speed matters more than
precision reranking, and vector similarity is sufficient.
"""
from __future__ import annotations

from typing import List
from app.core.interfaces import BaseReranker
from app.core.schemas import ChunkResult


class NoReranker(BaseReranker):
    """
    Returns chunks in their original vector-similarity order.
    Zero latency — ideal for high-volume, low-stakes queries.
    """

    async def rerank(self, query: str, chunks: List[ChunkResult]) -> List[ChunkResult]:
        # Already sorted by score from the retriever — return as-is
        return chunks
