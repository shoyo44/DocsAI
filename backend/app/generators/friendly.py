"""
Friendly Generator — HR vertical.

Produces plain-English HR policy answers.
Output schema: FriendlyOutput (answer + policy_section + applies_to + related_policies)

Design:
    - Instructs the LLM to be jargon-free and cite exact policy sections.
    - Parses JSON response from the LLM.
    - Falls back to plain text answer if JSON parsing fails.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.core.interfaces import BaseGenerator
from app.core.schemas import ChunkResult, FriendlyOutput, ConfidenceLevel
from app.generators._base import (
    build_user_message,
    parse_json_response,
    not_found_output,
    stream_from_client,
)

logger = logging.getLogger("docqa.generators.friendly")

_SYSTEM_PROMPT = """You are a helpful, friendly HR assistant.

Rules:
- Answer ONLY using the provided document chunks.
- Be clear, concise, and jargon-free.
- Always cite the exact policy section (e.g. "Section 4.2 — Remote Work").
- If the policy applies differently to different employee types, state that explicitly.
- Do NOT make up information not found in the chunks.

Return ONLY valid JSON in this exact format:
{
  "answer": "Clear, friendly answer here.",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "policy_section": "Section X.Y — Policy Name or null",
  "applies_to": ["full-time", "part-time"],
  "related_policies": ["Policy Name 1", "Policy Name 2"],
  "chunks_used": ["chunk_id_1", "chunk_id_2"]
}"""


class FriendlyGenerator(BaseGenerator[FriendlyOutput]):
    """Generator for the HR vertical. Returns FriendlyOutput."""

    def __init__(self, llm_client: Any):
        self.client = llm_client

    async def generate(
        self,
        query: str,
        chunks: List[ChunkResult],
        config: Dict[str, Any],
    ) -> FriendlyOutput:
        if not chunks:
            return not_found_output(FriendlyOutput)

        user_msg = build_user_message(query, config)

        try:
            raw = await self.client.chat(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_msg,
                max_tokens=1024,
                temperature=0.1,
            )
            data = parse_json_response(raw)

            return FriendlyOutput(
                answer          = data.get("answer") or "",
                confidence      = data.get("confidence") or ConfidenceLevel.LOW,
                policy_section  = data.get("policy_section"),
                applies_to      = data.get("applies_to") or [],
                related_policies= data.get("related_policies") or [],
                chunks_used     = data.get("chunks_used") or [c.id for c in chunks],
            )

        except Exception as exc:
            logger.error("FriendlyGenerator error: %s", exc)
            return not_found_output(FriendlyOutput)

    async def stream(self, query: str, chunks: List[ChunkResult], config: Dict[str, Any]):
        if not chunks:
            yield "I couldn't find relevant HR policy information for your question."
            return
        async for token in stream_from_client(
            self.client, _SYSTEM_PROMPT, build_user_message(query, config)
        ):
            yield token
