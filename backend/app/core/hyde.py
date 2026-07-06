"""
HyDE — Hypothetical Document Embedding query expansion.

How it works:
    1. Given a user query, ask the LLM to generate a hypothetical document
       that would answer the question (no retrieval needed yet).
    2. Embed the hypothetical document — its embedding is closer to relevant
       chunks than the raw query embedding alone.
    3. Use this enriched embedding for the actual vector retrieval.

Performance improvement: +15–30% retrieval accuracy vs. raw query embedding.

KEY FIX over original:
    Cache HyDE results in Redis keyed by (vertical, hash(query)).
    Original called the LLM on every single query — even duplicates.
    Cache TTL = 30 minutes (shorter than query result TTL since this is intermediate).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger("docqa.hyde")

_HYDE_TTL_SECONDS = 1800   # 30-minute cache for HyDE documents

# Per-vertical prompts — tell the LLM what kind of document to hallucinate
_VERTICAL_PROMPTS = {
    "law": (
        "Write a hypothetical legal contract clause that directly answers this question. "
        "Use formal legal language, clause numbers, and citation style. "
        "Question: {query}"
    ),
    "compliance": (
        "Write a hypothetical regulatory article or compliance guideline that directly "
        "addresses this question. Use regulation IDs and article references. "
        "Question: {query}"
    ),
    "hr": (
        "Write a hypothetical HR policy section that directly answers this question. "
        "Use clear, jargon-free language and cite a policy section number. "
        "Question: {query}"
    ),
    "startup": (
        "Write a hypothetical term sheet or shareholder agreement clause that directly "
        "answers this question. Use plain English and flag any founder risk. "
        "Question: {query}"
    ),
    "university": (
        "Write a hypothetical paragraph from an academic research paper that directly "
        "answers this question. Use academic language, cite methods and results. "
        "Question: {query}"
    ),
}

_DEFAULT_PROMPT = "Write a short document that directly answers: {query}"


class HyDEExpander:
    """
    Generates and caches hypothetical document embeddings for query expansion.
    Must be constructed with a CF AI client and optional Redis client.
    """

    def __init__(self, cf_client: Any, redis_client: Optional[Any] = None):
        self.cf     = cf_client
        self.redis  = redis_client

    async def expand(self, query: str, vertical: str) -> str:
        """
        Generate a hypothetical document for the query.
        Returns the hypothetical document text (not the embedding — embed separately).
        Falls back to the raw query on any failure.
        """
        cache_key = self._cache_key(query, vertical)

        # ── Cache read ────────────────────────────────────────────────────────
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug("HyDE cache hit: %s", cache_key)
                    return cached
            except Exception:
                pass   # Redis unavailable — continue without cache

        # ── LLM generation ────────────────────────────────────────────────────
        prompt_template = _VERTICAL_PROMPTS.get(vertical, _DEFAULT_PROMPT)
        system_prompt   = (
            "You are generating a hypothetical document fragment for query expansion. "
            "Write ONLY the document content — no preamble, no explanation."
        )
        user_message = prompt_template.format(query=query)

        try:
            hypothetical_doc = await self.cf.chat(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=256,    # short — just enough for a good embedding
                temperature=0.3,   # slight creativity to improve coverage
            )
            hypothetical_doc = hypothetical_doc.strip()
        except Exception as exc:
            logger.warning("HyDE generation failed (%s) — using raw query.", exc)
            return query

        if not hypothetical_doc:
            return query

        # ── Cache write ───────────────────────────────────────────────────────
        if self.redis:
            try:
                self.redis.setex(cache_key, _HYDE_TTL_SECONDS, hypothetical_doc)
            except Exception:
                pass

        logger.debug("HyDE expanded query for vertical='%s'.", vertical)
        return hypothetical_doc

    @staticmethod
    def _cache_key(query: str, vertical: str) -> str:
        query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]
        return f"hyde:{vertical}:{query_hash}"
