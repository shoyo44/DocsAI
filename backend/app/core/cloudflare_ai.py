"""
Cloudflare Workers AI Client.

Models used:
    LLM       → @cf/meta/llama-3.3-70b-instruct-fp8-fast
    Embeddings → @cf/baai/bge-large-en-v1.5  (1024 dims)
    Vision     → @cf/llava-hf/llava-1.5-7b-hf  (better than uform for complex charts)

KEY FIX over original:
    httpx.AsyncClient is created ONCE at construction time and reused across all
    calls (connection pooling). Original created/destroyed a client per call.

Usage:
    # Created once at app startup (in lifespan), injected everywhere
    cf = CloudflareAI(account_id="...", api_token="...")
    embedding = await cf.embed("What is the liability clause?")
    answer    = await cf.chat(system_prompt, user_message)
    await cf.close()   # call at shutdown
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Dict, List, Optional

import httpx

logger = logging.getLogger("docqa.cloudflare_ai")

_BASE_URL  = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

CF_LLM_MODEL    = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
CF_EMBED_MODEL  = "@cf/baai/bge-large-en-v1.5"
CF_VISION_MODEL = "@cf/llava-hf/llava-1.5-7b-hf"
CF_EMBED_DIMS   = 768    # Nomic Atlas nomic-embed-text-v1.5 produces 768-dim vectors

_BATCH_SIZE = 100   # Cloudflare allows up to 100 texts per embed request


class CloudflareAI:
    """
    Async Cloudflare Workers AI client with persistent connection pooling.
    Create once per app lifecycle — never per-request.
    """

    def __init__(self, account_id: str, api_token: str, timeout: float = 60.0):
        self.account_id = account_id
        self._timeout   = timeout
        # Persistent client — shared across ALL calls to this instance
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type":  "application/json",
            },
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        """Call this in FastAPI lifespan shutdown to release connections cleanly."""
        await self._client.aclose()

    def _url(self, model: str) -> str:
        return _BASE_URL.format(account_id=self.account_id, model=model)

    # ── Embeddings ────────────────────────────────────────────────────────────

    async def embed(self, text: str) -> List[float]:
        """Embed a single text string. Returns a 1024-dim float vector."""
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Batch embed up to 100 texts per request.
        Automatically splits larger lists into batches.
        """
        if not texts:
            return []

        all_vectors: List[List[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            resp  = await self._client.post(
                self._url(CF_EMBED_MODEL),
                json={"text": batch},
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                raise RuntimeError(f"CF embed failed: {data.get('errors')}")

            all_vectors.extend(data["result"]["data"])
            logger.debug("Embedded batch %d–%d (%d dims).", i, i + len(batch), CF_EMBED_DIMS)

        return all_vectors

    # ── Chat / Generation ─────────────────────────────────────────────────────

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int  = 1024,
        temperature: float = 0.1,
    ) -> str:
        """Non-streaming chat completion. Returns the raw response string."""
        resp = await self._client.post(
            self._url(CF_LLM_MODEL),
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                "max_tokens":  max_tokens,
                "temperature": temperature,
                "stream":      False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise RuntimeError(f"CF chat failed: {data.get('errors')}")

        return data["result"]["response"]

    async def stream_chat(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Streaming chat — yields tokens as they arrive via SSE."""
        async with self._client.stream(
            "POST",
            self._url(CF_LLM_MODEL),
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                "max_tokens": max_tokens,
                "stream":     True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        token = chunk.get("response", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue

    # ── Vision ────────────────────────────────────────────────────────────────

    async def describe_image(
        self,
        image_bytes: bytes,
        prompt: str = "Describe this image, chart, or table in precise detail for a research database.",
    ) -> str:
        """Analyze an image using Cloudflare LLaVA vision model."""
        resp = await self._client.post(
            self._url(CF_VISION_MODEL),
            json={"image": list(image_bytes), "prompt": prompt},
        )
        if resp.status_code != 200:
            logger.warning("CF Vision failed (%d): %s", resp.status_code, resp.text[:200])
            return "Visual description unavailable."

        data = resp.json()
        if not data.get("success"):
            return "Visual description failed."

        result = data.get("result", {})
        return result.get("description") or result.get("response") or "Visual description failed."

    # ── Anthropic-compatible shim ─────────────────────────────────────────────
    # Allows this client to be passed directly into generators that were written
    # for the Anthropic SDK — no code changes needed in generators when switching.

    class _Messages:
        def __init__(self, parent: "CloudflareAI"):
            self._p = parent

        async def create(
            self,
            model: str = CF_LLM_MODEL,
            max_tokens: int = 1024,
            system: str = "",
            messages: Optional[List[Dict]] = None,
            **kwargs,
        ):
            user_msg = ((messages or [{}])[-1]).get("content", "")
            text     = await self._p.chat(system, user_msg, max_tokens)

            class _Content:
                def __init__(self, t): self.text = t

            class _Response:
                def __init__(self, t): self.content = [_Content(t)]

            return _Response(text)

        def stream(self, **kwargs):
            p        = self._p
            system   = kwargs.get("system", "")
            messages = kwargs.get("messages", [{}])
            user_msg = messages[-1].get("content", "")
            max_tok  = kwargs.get("max_tokens", 1024)

            class _StreamCtx:
                async def __aenter__(s):
                    s._gen = p.stream_chat(system, user_msg, max_tok)
                    return s

                async def __aexit__(s, *_): pass

                @property
                def text_stream(s) -> AsyncIterator[str]:
                    return s._gen

            return _StreamCtx()

    @property
    def messages(self) -> "_Messages":
        return self._Messages(self)
