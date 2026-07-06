"""
Generator shared utilities — internal to generators/ package.

Provides:
    build_user_message()   — format the user prompt with context + query
    parse_json_response()  — clean and parse LLM JSON output robustly
    not_found_output()     — typed not-found response for any vertical
    stream_from_client()   — delegate streaming to llm_client.stream_chat()
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Type, TypeVar

from app.core.schemas import VerticalOutput

logger = logging.getLogger("docqa.generators._base")

T = TypeVar("T", bound=VerticalOutput)


# ─── User message builder ─────────────────────────────────────────────────────

def build_user_message(query: str, config: Dict[str, Any]) -> str:
    """
    Assemble the user turn of the LLM prompt.
    Uses pre-built context string from ContextManager (stored in config["_context"]).
    """
    context   = config.get("_context", "No context provided.")
    used_ids  = config.get("_used_ids", [])

    return (
        f"QUESTION: {query}\n\n"
        f"DOCUMENT CHUNKS ({len(used_ids)} used):\n"
        f"---\n{context}\n---\n\n"
        "Answer based ONLY on the chunks above. Return valid JSON."
    )


# ─── JSON response parser ─────────────────────────────────────────────────────

def parse_json_response(raw: Any) -> Dict[str, Any]:
    """
    Robustly parse the LLM's JSON response.
    Handles:
        - Dict objects (already parsed)
        - Bare JSON strings
        - JSON wrapped in ```json ... ``` markdown blocks
        - JSON with leading/trailing whitespace or stray characters
    Raises:
        ValueError: if JSON cannot be parsed after all cleanup attempts.
    """
    if isinstance(raw, dict):
        return raw
        
    if not isinstance(raw, str):
        raw = str(raw)
        
    text = raw.strip()

    # Strip markdown code block wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Attempt direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract the first {...} or [...] block
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    logger.warning("parse_json_response: could not parse LLM output as JSON. Raw: %s", raw[:200])
    raise ValueError(f"Invalid JSON from LLM: {raw[:100]}")


# ─── Not-found response ───────────────────────────────────────────────────────

def not_found_output(model_class: Type[T]) -> T:
    """
    Return a typed 'not found' response for any vertical output model.
    Uses model-specific defaults — never hallucinate.
    """
    return model_class(
        answer    = "The information you requested was not found in the provided documents.",
        not_found = True,
    )


# ─── Streaming helper ─────────────────────────────────────────────────────────

async def stream_from_client(
    client: Any,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """
    Delegate streaming to the LLM client's stream_chat method.
    Works with CloudflareAI.stream_chat() and the Anthropic-compatible shim.
    """
    try:
        async for token in client.stream_chat(system_prompt, user_message, max_tokens):
            yield token
    except Exception as exc:
        logger.error("stream_from_client error: %s", exc)
        yield "\n[Stream interrupted. Please retry.]"
