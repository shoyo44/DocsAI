"""
RAG Pipeline Orchestrator — wires all stages together.

Stages (all async):
    1. Retrieve  → BaseRetriever.retrieve_with_fallback()
    2. Rerank    → BaseReranker.rerank()             [async, uses to_thread internally]
    3. Gate      → drop chunks below score_floor
    4. Context   → ContextManager.build_context()    [token-budget packing]
    5. Generate  → BaseGenerator.generate()          [with retry + timeout]

KEY FIXES over original:
    1. asyncio.get_event_loop().time() → asyncio.get_running_loop().time()
       (get_event_loop is deprecated in Python 3.10+)
    2. reranker.rerank() is now awaited — BaseReranker is async.
       CPU-heavy CrossEncoder calls are offloaded to thread pool inside the
       reranker implementation itself.
    3. PipelineTrace uses to_dict() for clean JSON serialization.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, AsyncIterator, Dict, List

from app.core.interfaces import BaseIndexer, BaseRetriever, BaseReranker, BaseGenerator
from app.core.schemas    import ChunkResult, VerticalOutput
from app.core.context    import ContextManager
from app.core.observability import PipelineTrace, with_timeout

logger = logging.getLogger("docqa.pipeline")

# ── Retry helper ─────────────────────────────────────────────────────────────

async def _retry(coro_fn, retries: int = 3, base_delay: float = 0.5) -> Any:
    """Exponential back-off retry for async coroutine factories."""
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(retries):
        try:
            return await coro_fn()
        except Exception as exc:
            last_exc = exc
            wait = base_delay * (2 ** attempt)
            logger.warning("Retry %d/%d after %.1fs — %s", attempt + 1, retries, wait, exc)
            await asyncio.sleep(wait)
    raise last_exc


# ── RAG Pipeline ─────────────────────────────────────────────────────────────

class RAGPipeline:
    """
    Orchestrates the full Retrieve → Rerank → Pack → Generate pipeline.
    Each component is a swappable implementation of its abstract interface.
    Constructed by factory.py — never instantiated directly.
    """

    def __init__(
        self,
        indexer:              BaseIndexer,
        retriever:            BaseRetriever,
        reranker:             BaseReranker,
        generator:            BaseGenerator,
        config:               Dict[str, Any],
        token_budget:         int   = 4096,
        retrieval_timeout_s:  float = 10.0,
        generation_timeout_s: float = 30.0,
    ):
        self.indexer    = indexer
        self.retriever  = retriever
        self.reranker   = reranker
        self.generator  = generator
        self.config     = config
        self.vertical   = config.get("vertical", "generic")
        self.ctx_mgr    = ContextManager(token_budget=token_budget)
        self.retrieval_timeout  = retrieval_timeout_s
        self.generation_timeout = generation_timeout_s

    # ── Ingestion (sync — called from background worker) ──────────────────────

    def ingest(self, text: str, metadata: Dict[str, Any], store: Any) -> int:
        """Chunk and persist one page of text. Returns chunk count."""
        chunks = self.indexer.chunk(text, metadata)
        self.indexer.index(chunks, store)
        return len(chunks)

    # ── Query (full async pipeline) ───────────────────────────────────────────

    async def query(
        self,
        query_text: str,
        embedding:  List[float],
        store:      Any,
        tenant_id:  str,
        keyword:    str = "",
    ) -> Dict[str, Any]:
        """
        Execute the full RAG pipeline and return a serialised VerticalOutput dict.

        Args:
            query_text: Raw user query string.
            embedding:  Query embedding vector.
            store:      GraphStore instance.
            tenant_id:  Tenant identifier — enforced at query level.
            keyword:    Optional keyword hint for HybridRetriever boosting.
        """
        loop      = asyncio.get_running_loop()   # FIX: not get_event_loop()
        query_hash = hashlib.md5(f"{tenant_id}:{query_text}".encode()).hexdigest()[:8]
        trace     = PipelineTrace(tenant_id=tenant_id, vertical=self.vertical, query_hash=query_hash)
        top_k     = self.config.get("top_k", 10)

        # ── 1. Retrieve ───────────────────────────────────────────────────────
        t0 = loop.time()
        raw_chunks: List[ChunkResult] = await with_timeout(
            self.retriever.retrieve_with_fallback(
                embedding, store, tenant_id, top_k, keyword=keyword
            ),
            timeout_s=self.retrieval_timeout,
            stage="retrieval",
        )
        trace.record("retrieval_ms", (loop.time() - t0) * 1000)
        trace.add_meta("chunks_retrieved", len(raw_chunks))

        if not raw_chunks:
            logger.info("[%s] No chunks retrieved.", query_hash)
            return self._not_found(trace)

        # ── 2. Rerank (async — CPU work offloaded inside reranker) ────────────
        t1 = loop.time()
        reranked: List[ChunkResult] = await self.reranker.rerank(query_text, raw_chunks)
        trace.record("rerank_ms", (loop.time() - t1) * 1000)

        # ── 3. Score gate ─────────────────────────────────────────────────────
        floor     = self.config.get("score_floor", 0.40)
        qualified = [c for c in reranked if c.best_score >= floor]
        if not qualified:
            logger.info("[%s] All chunks below floor %.2f.", query_hash, floor)
            return self._not_found(trace)

        # ── 4. Context packing ────────────────────────────────────────────────
        context_str, used_ids, truncated = self.ctx_mgr.build_context(
            qualified, self.vertical
        )
        trace.add_meta("chunks_used", len(used_ids))
        trace.add_meta("context_truncated", truncated)

        # ── 5. Generate (with retry + timeout) ───────────────────────────────
        t2 = loop.time()

        async def _gen():
            return await self.generator.generate(
                query_text,
                qualified,
                {**self.config, "_context": context_str, "_used_ids": used_ids},
            )

        output: VerticalOutput = await with_timeout(
            _retry(_gen, retries=3, base_delay=0.5),
            timeout_s=self.generation_timeout,
            stage="generation",
        )
        trace.record("generation_ms", (loop.time() - t2) * 1000)
        trace.log_summary()

        result        = output.model_dump()
        result["_trace"] = trace.to_dict()
        return result

    # ── Streaming variant ─────────────────────────────────────────────────────

    async def stream_query(
        self,
        query_text: str,
        embedding:  List[float],
        store:      Any,
        tenant_id:  str,
        keyword:    str = "",
    ) -> AsyncIterator[str]:
        """
        Streaming pipeline — retrieval + reranking happen first (blocking),
        then LLM tokens are yielded as they arrive.
        """
        top_k      = self.config.get("top_k", 10)
        raw_chunks = await self.retriever.retrieve_with_fallback(
            embedding, store, tenant_id, top_k, keyword=keyword
        )

        if not raw_chunks:
            yield "I could not find relevant information in the provided documents."
            return

        reranked    = await self.reranker.rerank(query_text, raw_chunks)
        floor       = self.config.get("score_floor", 0.40)
        qualified   = [c for c in reranked if c.best_score >= floor] or reranked[:5]
        context_str, used_ids, _ = self.ctx_mgr.build_context(qualified, self.vertical)

        async for token in self.generator.stream(
            query_text,
            qualified,
            {**self.config, "_context": context_str, "_used_ids": used_ids},
        ):
            yield token

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _not_found(self, trace: PipelineTrace) -> Dict[str, Any]:
        return {
            "answer":      "The information you requested was not found in the provided documents.",
            "confidence":  "LOW",
            "not_found":   True,
            "chunks_used": [],
            "_trace":      trace.to_dict(),
        }
