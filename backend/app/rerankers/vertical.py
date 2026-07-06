"""
Vertical Reranker — keyword-boosted score reranker.

Used for Law and Startup verticals where specific legal keywords
(e.g. "liability", "termination", "indemnity") strongly signal relevance.

Strategy:
    1. Start with the vector similarity score.
    2. Boost by a multiplier for each vertical-specific keyword found in the chunk.
    3. Re-sort by the boosted score.

No ML model needed — fast, deterministic, explainable.
"""
from __future__ import annotations

import asyncio
from typing import Dict, List

from app.core.interfaces import BaseReranker
from app.core.schemas import ChunkResult

# ── Keyword boost tables per vertical ────────────────────────────────────────
# Each keyword found in a chunk text boosts its score by BOOST_STEP.

KEYWORD_BOOSTS: Dict[str, List[str]] = {
    "law": [
        "liability", "indemnif", "terminat", "warrant", "govern", "jurisdict",
        "liquidat", "damages", "clause", "breach", "remedy", "obligation",
        "intellectual property", "confidential", "non-compete", "non-solicitat",
        "force majeure", "arbitrat",
    ],
    "startup": [
        "dilut", "vesting", "cliff", "pro-rata", "drag-along", "tag-along",
        "liquidation preference", "anti-dilution", "board seat", "founder",
        "cap table", "option pool", "convertible", "safe note", "warrant",
    ],
}

BOOST_STEP = 0.05   # score boost per keyword hit
MAX_BOOST  = 0.30   # cap total boost to avoid domination


class VerticalReranker(BaseReranker):
    """
    Boosts chunk scores based on vertical-specific legal/startup keywords.
    CPU-light — runs in the event loop (no ML model).
    """

    def __init__(self, vertical: str):
        self.keywords = [kw.lower() for kw in KEYWORD_BOOSTS.get(vertical, [])]

    async def rerank(self, query: str, chunks: List[ChunkResult]) -> List[ChunkResult]:
        """Boost scores by keyword presence then re-sort descending."""
        # Offload to thread since it's pure CPU iteration (no I/O needed
        # but keeps the interface consistent with async contract)
        return await asyncio.to_thread(self._boost_and_sort, chunks)

    def _boost_and_sort(self, chunks: List[ChunkResult]) -> List[ChunkResult]:
        boosted = []
        for chunk in chunks:
            text_lower = chunk.text.lower()
            hits  = sum(1 for kw in self.keywords if kw in text_lower)
            boost = min(hits * BOOST_STEP, MAX_BOOST)
            # Write into rerank_score so downstream best_score picks it up
            chunk.rerank_score = round(chunk.score + boost, 4)
            boosted.append(chunk)

        return sorted(boosted, key=lambda c: c.rerank_score, reverse=True)
