"""
Context Window Manager — token-budget-aware context packing.

Improvements over original:
    1. Uses tiktoken (cl100k_base) for accurate token counting —
       original used a naive word/0.75 approximation (off by up to 30%).
    2. Deduplication uses Jaccard similarity (unchanged — works well).
    3. Per-vertical rich metadata headers (unchanged — good design).
    4. Fallback to word-count if tiktoken is unavailable (e.g. offline env).
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from app.core.schemas import ChunkResult

logger = logging.getLogger("docqa.context")

# ── Token counter ─────────────────────────────────────────────────────────────

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_enc.encode(text))

    logger.debug("Token counter: tiktoken cl100k_base.")

except ImportError:
    logger.warning("tiktoken not installed — using word-count fallback (less accurate).")

    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        # Rough approximation: 1 token ≈ 0.75 words
        return int(len(text.split()) / 0.75)


# ── Context Manager ───────────────────────────────────────────────────────────

class ContextManager:
    """
    Packs retrieved chunks into an LLM-safe context string within a token budget.

    Algorithm:
        1. Sort chunks by best_score descending.
        2. Deduplicate near-identical chunks (Jaccard ≥ dedup_threshold).
        3. Format each chunk with vertical-specific metadata headers.
        4. Add chunks until the token budget is exhausted.
        5. Return the context string, used chunk IDs, and a truncation flag.
    """

    def __init__(self, token_budget: int = 4096, dedup_threshold: float = 0.85):
        self.token_budget    = token_budget
        self.dedup_threshold = dedup_threshold

    # ── Public API ────────────────────────────────────────────────────────────

    def build_context(
        self,
        chunks: List[ChunkResult],
        vertical: str,
    ) -> Tuple[str, List[str], bool]:
        """
        Build a formatted context string within the token budget.

        Returns:
            context_str  : formatted string for the LLM prompt
            used_ids     : list of chunk IDs included
            was_truncated: True if chunks were dropped due to budget
        """
        sorted_chunks = sorted(chunks, key=lambda c: c.best_score, reverse=True)
        deduped       = self._deduplicate(sorted_chunks)

        # For the university vertical, always surface Title Page chunks first
        # so the LLM can extract paper_title and authors reliably.
        if vertical == "university":
            title_page = [c for c in deduped if getattr(c, "section", None) == "Title Page"]
            rest       = [c for c in deduped if getattr(c, "section", None) != "Title Page"]
            deduped    = title_page + rest

        parts:    List[str] = []
        used_ids: List[str] = []
        tokens_used = 0

        for chunk in deduped:
            formatted    = self._format_chunk(chunk, vertical)
            chunk_tokens = _count_tokens(formatted)

            if tokens_used + chunk_tokens > self.token_budget:
                break   # budget exhausted

            parts.append(formatted)
            used_ids.append(chunk.id)
            tokens_used += chunk_tokens

        was_truncated = len(used_ids) < len(deduped)
        context_str   = "\n\n---\n\n".join(parts)

        logger.debug(
            "Context built: %d/%d chunks used, %d tokens, truncated=%s",
            len(used_ids), len(deduped), tokens_used, was_truncated,
        )
        return context_str, used_ids, was_truncated

    # ── Deduplication ─────────────────────────────────────────────────────────

    def _deduplicate(self, chunks: List[ChunkResult]) -> List[ChunkResult]:
        """
        Remove chunks with near-identical text using Jaccard word-overlap.
        Keeps the higher-scored chunk when two are above the similarity threshold.
        O(n²) — acceptable for top_k ≤ 50 in all current verticals.
        """
        seen: List[ChunkResult] = []
        for chunk in chunks:
            words_a = set(chunk.text.lower().split())
            is_dup  = False
            for existing in seen:
                words_b  = set(existing.text.lower().split())
                union    = words_a | words_b
                if not union:
                    continue
                jaccard = len(words_a & words_b) / len(union)
                if jaccard >= self.dedup_threshold:
                    is_dup = True
                    break
            if not is_dup:
                seen.append(chunk)
        return seen

    # ── Chunk formatting ──────────────────────────────────────────────────────

    def _format_chunk(self, chunk: ChunkResult, vertical: str) -> str:
        """Produce a richly annotated context block with vertical-specific headers."""
        header = self._make_header(chunk, vertical)
        text   = (chunk.enriched_text or chunk.text).strip()
        return f"{header}\n{text}"

    @staticmethod
    def _make_header(chunk: ChunkResult, vertical: str) -> str:
        doc = chunk.doc_name or "Unknown"
        pg  = chunk.page or "?"

        if vertical == "law":
            ref = chunk.clause_ref or f"Page {pg}"
            return f"[CLAUSE: {ref} | Doc: {doc}]"

        if vertical == "compliance":
            ref = chunk.article_ref or f"Page {pg}"
            return f"[ARTICLE: {ref} | Doc: {doc}]"

        if vertical == "hr":
            emp = chunk.employee_type or "all employees"
            return f"[POLICY | Applies to: {emp} | Page {pg} | Doc: {doc}]"

        if vertical == "startup":
            term = chunk.defined_term or "General"
            return f"[TERM: {term} | Page {pg} | Doc: {doc}]"

        if vertical == "university":
            sec = chunk.section or "Body"
            return f"[{doc} | Section: {sec} | Page {pg}]"

        return f"[Page {pg} | Doc: {doc}]"
