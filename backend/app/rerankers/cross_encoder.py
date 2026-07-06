"""
Cross-Encoder Reranker — high-fidelity deep learning ranker.

Retrieves chunks via standard vector search first, then scores them
against the query text using a local CrossEncoder transformer.
Falls back to a semantic TF-IDF lexical overlap matcher if
the transformer model is not pre-installed or fails.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List

from app.core.interfaces import BaseReranker
from app.core.schemas import ChunkResult

logger = logging.getLogger("docqa.rerankers.cross_encoder")


class CrossEncoderReranker(BaseReranker):
    """
    Reranks chunks using sentence-transformers CrossEncoder.
    Falls back to a TF-IDF lexical overlap ranker if model fails or isn't installed.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = None
        self.model_name = model_name
        try:
            # sentence_transformers is optional — try to import it
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(model_name)
            logger.info("✅ CrossEncoderReranker loaded model: %s", model_name)
        except Exception as exc:
            logger.warning(
                "⚠️ Failed to load sentence-transformers CrossEncoder (%s). "
                "Using lexical token overlap fallback for reranking compliance/university.",
                exc,
            )

    async def rerank(
        self, query: str, chunks: List[ChunkResult]
    ) -> List[ChunkResult]:
        """
        Rerank a set of chunks relative to the user query text.
        """
        if not chunks:
            return []

        # 1. Try deep learning reranking
        if self.model is not None:
            try:
                pairs = [[query, c.text] for c in chunks]
                # Offload heavy CPU prediction model to worker thread
                scores = await asyncio.to_thread(self.model.predict, pairs)
                for chunk, score in zip(chunks, scores):
                    chunk.rerank_score = float(score)
                logger.debug("Reranked %d chunks using CrossEncoder model.", len(chunks))
                return sorted(chunks, key=lambda c: c.best_score, reverse=True)
            except Exception as exc:
                logger.error("CrossEncoder inference failed, falling back: %s", exc)

        # 2. Fallback Lexical Jaccard/TF-IDF Overlap Reranker
        return await asyncio.to_thread(self._lexical_rerank, query, chunks)

    def _lexical_rerank(self, query: str, chunks: List[ChunkResult]) -> List[ChunkResult]:
        query_words = set(query.lower().split())
        for chunk in chunks:
            chunk_words = set(chunk.text.lower().split())
            intersection = query_words.intersection(chunk_words)
            union = query_words.union(chunk_words)
            jaccard = len(intersection) / len(union) if union else 0.0

            # Scale Jaccard match up and combine with vector similarity score
            chunk.rerank_score = round(chunk.score + jaccard * 0.40, 4)

        return sorted(chunks, key=lambda c: c.best_score, reverse=True)
