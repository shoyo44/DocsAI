"""
Pipeline Factory — assembles a RAGPipeline for a given vertical.

KEY FIX over original:
    build_pipeline() now accepts pre-built singleton objects (reranker, llm_client)
    instead of constructing them internally on every call.

    Original bug:
        CrossEncoderReranker() was constructed INSIDE build_pipeline() →
        the ~80MB sentence-transformer model was loaded on EVERY request.
        At ~2–5s load time, this made every query feel cold.

    Fix:
        Reranker and LLM client are loaded ONCE in main.py lifespan,
        stored on app.state, and passed in here as singletons.

Wiring table:
    vertical    indexer          retriever        reranker             generator
    ─────────────────────────────────────────────────────────────────────────────
    law         ClauseIndexer    GraphRetriever   VerticalReranker     RiskGenerator
    compliance  ArticleIndexer   HybridRetriever  CrossEncoderReranker ComplianceGenerator
    hr          TopicIndexer     VectorRetriever  NoReranker           FriendlyGenerator
    startup     TermIndexer      GraphRetriever   VerticalReranker     RiskGenerator
    university  SectionIndexer   HybridRetriever  CrossEncoderReranker AcademicGenerator
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.pipeline import RAGPipeline
from app.config.verticals import VERTICAL_CONFIGS, SUPPORTED_VERTICALS

from app.indexers   import ClauseIndexer, ArticleIndexer, TopicIndexer, TermIndexer, SectionIndexer
from app.retrievers import GraphRetriever, HybridRetriever, VectorRetriever
from app.rerankers.vertical     import VerticalReranker
from app.rerankers.noop         import NoReranker
from app.rerankers.cross_encoder import CrossEncoderReranker
from app.generators import RiskGenerator, ComplianceGenerator, FriendlyGenerator, AcademicGenerator

logger = logging.getLogger("docqa.factory")


def build_pipeline(
    vertical:    str,
    llm_client:  Any,   # CloudflareAI singleton — passed in, NOT created here
    reranker:    Any,   # CrossEncoderReranker singleton for compliance/university
) -> RAGPipeline:
    """
    Assemble a fully wired RAGPipeline for the given vertical.

    Args:
        vertical:   One of: law, compliance, hr, startup, university
        llm_client: CloudflareAI singleton (from app.state.cf_client)
        reranker:   CrossEncoderReranker singleton (from app.state.reranker)
                    Only used for compliance and university verticals.
                    Law/startup use VerticalReranker, hr uses NoReranker.

    Returns:
        RAGPipeline ready to handle queries.

    Raises:
        ValueError: if vertical is not supported.
    """
    if vertical not in SUPPORTED_VERTICALS:
        raise ValueError(
            f"Unsupported vertical: '{vertical}'. Supported: {SUPPORTED_VERTICALS}"
        )

    config = {**VERTICAL_CONFIGS[vertical], "vertical": vertical}

    chunk_size    = config["chunk_size"]
    chunk_overlap = config["chunk_overlap"]
    token_budget  = config.get("token_budget", 4096)

    # ── Vertical wiring ───────────────────────────────────────────────────────

    if vertical == "law":
        indexer   = ClauseIndexer(chunk_size, chunk_overlap)
        retriever = GraphRetriever()
        _reranker = VerticalReranker(vertical="law")
        generator = RiskGenerator(llm_client)

    elif vertical == "compliance":
        indexer   = ArticleIndexer(chunk_size, chunk_overlap)
        retriever = HybridRetriever()
        _reranker = reranker if reranker is not None else CrossEncoderReranker()
        generator = ComplianceGenerator(llm_client)

    elif vertical == "hr":
        indexer   = TopicIndexer(chunk_size, chunk_overlap)
        retriever = VectorRetriever()
        _reranker = NoReranker()          # no reranking needed for HR
        generator = FriendlyGenerator(llm_client)

    elif vertical == "startup":
        indexer   = TermIndexer(chunk_size, chunk_overlap)
        retriever = GraphRetriever()
        _reranker = VerticalReranker(vertical="startup")
        generator = RiskGenerator(llm_client)

    elif vertical == "university":
        indexer   = SectionIndexer(chunk_size, chunk_overlap)
        retriever = HybridRetriever()
        _reranker = reranker if reranker is not None else CrossEncoderReranker()
        generator = AcademicGenerator(llm_client)

    else:
        # Unreachable (guarded above) — for type-checker satisfaction
        raise ValueError(f"No pipeline config for: '{vertical}'")

    logger.info("Built pipeline: vertical=%s token_budget=%d", vertical, token_budget)

    return RAGPipeline(
        indexer      = indexer,
        retriever    = retriever,
        reranker     = _reranker,
        generator    = generator,
        config       = config,
        token_budget = token_budget,
    )
