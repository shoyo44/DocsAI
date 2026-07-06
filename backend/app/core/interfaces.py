"""
Core Abstract Interfaces — Async-first, strongly typed.

All pipeline stages implement these contracts. This file defines the
"shape" of every pluggable component. Concrete implementations live in:
    indexers/    → BaseIndexer
    retrievers/  → BaseRetriever
    rerankers/   → BaseReranker
    generators/  → BaseGenerator

Rules:
- All I/O operations must be async.
- Sync CPU-heavy work (CrossEncoder, spaCy) must use asyncio.to_thread().
- Every method must be type-annotated.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Generic, TypeVar

from app.core.schemas import ChunkResult, VerticalOutput

T = TypeVar("T", bound=VerticalOutput)


# ─── Indexer ─────────────────────────────────────────────────────────────────

class BaseIndexer(ABC):
    """
    Transforms raw document text into structured, typed chunks.
    One concrete implementation per vertical (clause/article/topic/term/section).
    """

    @abstractmethod
    def chunk(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Split text into indexable chunks with enriched metadata.
        Returns a list of dicts — each dict becomes one Chunk node in the graph store.
        """
        ...

    @abstractmethod
    def index(self, chunks: List[Dict[str, Any]], store: Any) -> None:
        """
        Persist chunks to the graph store.
        Delegates to graph/ingestion.py for the actual writes.
        """
        ...


# ─── Retriever ───────────────────────────────────────────────────────────────

class BaseRetriever(ABC):
    """
    Retrieves relevant chunks from the graph given a query embedding.
    Three strategies: graph traversal, hybrid (vector+keyword), pure vector.
    """

    @abstractmethod
    async def retrieve(
        self,
        embedding: List[float],
        store: Any,
        tenant_id: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[ChunkResult]:
        """
        Returns a ranked list of ChunkResult objects.
        Must filter by tenant_id and exclude superseded chunks.
        """
        ...

    async def retrieve_with_fallback(
        self,
        embedding: List[float],
        store: Any,
        tenant_id: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[ChunkResult]:
        """
        Wraps retrieve() with an automatic fallback:
        if zero results are returned, widens the search by doubling top_k.
        Built into the base class — no need to override in concrete implementations.
        """
        results = await self.retrieve(embedding, store, tenant_id, top_k, **kwargs)
        if not results:
            results = await self.retrieve(
                embedding, store, tenant_id, top_k * 2, **kwargs
            )
        return results


# ─── Reranker ────────────────────────────────────────────────────────────────

class BaseReranker(ABC):
    """
    Re-scores and re-orders retrieved chunks for better relevance.
    Must be async — CPU-heavy models (CrossEncoder) use asyncio.to_thread().
    """

    @abstractmethod
    async def rerank(
        self, query: str, chunks: List[ChunkResult]
    ) -> List[ChunkResult]:
        """
        Return chunks sorted by reranked score, highest first.
        Must set chunk.rerank_score on each returned chunk.
        """
        ...


# ─── Generator ───────────────────────────────────────────────────────────────

class BaseGenerator(ABC, Generic[T]):
    """
    Generates structured, vertical-specific answers from retrieved chunks.
    One concrete implementation per vertical.
    """

    @abstractmethod
    async def generate(
        self,
        query: str,
        chunks: List[ChunkResult],
        config: Dict[str, Any],
    ) -> T:
        """
        Calls the LLM and returns a fully validated Pydantic output model.
        Must NEVER hallucinate — if chunks are insufficient, return not_found=True.
        """
        ...

    async def stream(
        self,
        query: str,
        chunks: List[ChunkResult],
        config: Dict[str, Any],
    ) -> AsyncIterator[str]:
        """
        Streaming variant — yields answer tokens as they arrive.
        Default implementation falls back to non-streaming generate().
        Override in concrete classes for true token streaming.
        """
        result = await self.generate(query, chunks, config)
        yield result.answer
