"""
Dependency providers — supplies GraphStore, AI clients, and cache to the app.

Dependency injection pattern:
    Singletons are stored on app.state in main.py lifespan.
    FastAPI endpoint functions receive them via Depends() functions defined here.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Request
from dotenv import load_dotenv

load_dotenv()
parent_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
if os.path.exists(parent_env):
    load_dotenv(parent_env)
logger = logging.getLogger("docqa.dependencies")


# ─── GraphStore ──────────────────────────────────────────────────────────────
# The in-process graph database lives on app.state — created once in lifespan.

def get_graph_store(request: Request):
    """Returns the GraphStore singleton from app.state."""
    return request.app.state.graph_store


# ─── MongoDB ─────────────────────────────────────────────────────────────────

def get_mongodb_db(request: Request):
    """Returns the MongoDB database singleton from app.state, or None if offline."""
    return getattr(request.app.state, "mongodb_db", None)


# ─── Cloudflare AI Client ─────────────────────────────────────────────────────

def get_llm_client(request: Request):
    """
    Returns the CloudflareAI singleton from app.state.
    """
    return request.app.state.cf_client


# ─── Embedding ────────────────────────────────────────────────────────────────

async def get_embedding(
    text: str,
    request: Optional[Request] = None,
    task_type: str = "search_query"
) -> list[float]:
    """
    Embed text using Nomic Atlas API (nomic-embed-text-v1.5) with exponential backoff retries.
    """
    nomic_key = os.getenv("NOMIC_API_KEY")
    if not nomic_key:
        raise EnvironmentError(
            "No embedding provider available. Set NOMIC_API_KEY in your .env file."
        )

    import httpx
    import asyncio

    retries = 3
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api-atlas.nomic.ai/v1/embedding/text",
                    headers={
                        "Authorization": f"Bearer {nomic_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "nomic-embed-text-v1.5",
                        "texts": [text],
                        "task_type": task_type
                    }
                )
                resp.raise_for_status()
                return resp.json()["embeddings"][0]

        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            if attempt == retries - 1:
                logger.error("Nomic embedding API call permanently failed: %s", exc)
                raise exc
            wait = 0.5 * (2 ** attempt)
            logger.warning("Nomic embedding retry %d/%d after %.1fs due to: %s", attempt + 1, retries, wait, exc)
            await asyncio.sleep(wait)
        except Exception as exc:
            logger.error("Unexpected error in get_embedding: %s", exc)
            raise exc


# ─── Redis ────────────────────────────────────────────────────────────────────

def get_redis_client(request: Optional[Request] = None):
    """
    Returns the Redis client from app.state, or None if unavailable.
    Callers must handle None (caching disabled silently).
    """
    if request is not None:
        return getattr(request.app.state, "redis", None)
    return _create_redis_client()


def _create_redis_client():
    """Redis is disabled / excluded per user request. Always returns None."""
    return None


def get_reranker(request: Request):
    """Returns the pre-loaded CrossEncoderReranker singleton from app.state."""
    return request.app.state.reranker


# ─── Semantic Cache ──────────────────────────────────────────────────────────

def get_semantic_cache(request: Request):
    """Returns the pre-loaded SemanticCache singleton from app.state."""
    return request.app.state.semantic_cache


# ─── OpenAI (optional, for embedding fallback) ────────────────────────────────

def get_async_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=api_key)
    return None
