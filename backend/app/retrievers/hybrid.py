"""
Hybrid Retriever — vector similarity + keyword boosting.

Used for Compliance and University verticals where exact regulation IDs
or author names must match precisely (pure semantic search can miss them).

Strategy:
    1. Run vector similarity search for top-K * 2 candidates.
    2. Boost scores for chunks that contain the keyword (BM25-style).
    3. Re-sort and trim to top-K.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.core.interfaces import BaseRetriever
from app.core.schemas import ChunkResult

logger = logging.getLogger("docqa.retrievers.hybrid")

_KEYWORD_BOOST   = 0.20   # additive boost when keyword found in chunk text
_EXACT_BOOST     = 0.35   # additive boost when keyword found in chunk metadata ref


class HybridRetriever(BaseRetriever):
    """
    Hybrid retriever combining cosine similarity with keyword boosting.

    Vertical: compliance, university
    Speed:    fast (in-memory vector scan + in-memory boost)
    Accuracy: best for queries with specific identifiers (regulation IDs, paper titles)
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
        Retrieve chunks by hybrid vector + keyword scoring.

        Extra kwargs:
            keyword (str): Optional keyword to boost matching chunks.
        """
        keyword: Optional[str] = kwargs.get("keyword", "").strip().lower()

        # Fetch 2× top_k so keyword boosting has room to reorder
        fetch_k = top_k * 2

        try:
            records = store.vector_search(embedding, tenant_id, fetch_k)
            chunks = [_to_chunk_result(r) for r in records]

            # Apply keyword boost in-memory
            if keyword:
                chunks = _apply_keyword_boost(chunks, keyword)

            # Trim to requested top_k after boosting
            chunks = chunks[:top_k]

            logger.debug(
                "HybridRetriever: tenant=%s keyword='%s' → %d results",
                tenant_id, keyword or "(none)", len(chunks),
            )
            return chunks

        except Exception as exc:
            logger.error("HybridRetriever failed: %s", exc)
            return []


# ─── Keyword Boost ────────────────────────────────────────────────────────────

def _apply_keyword_boost(
    chunks: List[ChunkResult],
    keyword: str,
) -> List[ChunkResult]:
    """
    Boost chunks whose text or metadata reference contains the keyword.
    Returns chunks re-sorted by boosted score descending.
    """
    boosted: List[ChunkResult] = []

    for chunk in chunks:
        boost = 0.0
        text_lower = chunk.text.lower()

        # Boost if keyword appears anywhere in chunk text
        if keyword in text_lower:
            boost += _KEYWORD_BOOST

        # Extra boost if keyword appears in structured metadata references
        meta_fields = [
            (chunk.article_ref or "").lower(),
            (chunk.section or "").lower(),
            (chunk.doc_name or "").lower(),
        ]
        if any(keyword in field for field in meta_fields if field):
            boost += _EXACT_BOOST

        chunk.rerank_score = round(chunk.score + boost, 4)
        boosted.append(chunk)

    return sorted(boosted, key=lambda c: c.best_score, reverse=True)


# ─── Helper ──────────────────────────────────────────────────────────────────

def _to_chunk_result(record: dict) -> ChunkResult:
    return ChunkResult(
        id          = record["id"],
        text        = record["text"] or "",
        page        = record.get("page"),
        doc_id      = record.get("doc_id"),
        doc_name    = record.get("doc_name"),
        chunk_type  = record.get("chunk_type"),
        article_ref = record.get("article_ref"),
        section     = record.get("section"),
        superseded  = record.get("superseded", False),
        score       = float(record.get("score", 0.0)),
    )
