"""
Risk Generator — Law and Startup verticals.

Produces structured risk assessments from legal clauses.
Output schema: RiskOutput
    - risk_level    : HIGH / MEDIUM / LOW
    - citations     : clause + page references
    - red_flags     : list of specific risk descriptions
    - plain_english : startup variant — plain-language summary
    - founder_risk  : startup variant — founder-specific risk level
    - market_standard: startup variant — comparison to typical terms

The same generator handles both law and startup verticals.
The vertical's system_prompt (from config) controls the tone:
    - law:     formal, cite clause number, legal terminology OK
    - startup: plain English, flag founder-unfriendly terms explicitly
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.interfaces import BaseGenerator
from app.core.schemas import (
    ChunkResult, RiskOutput, RiskLevel, ConfidenceLevel, Citation
)
from app.generators._base import (
    build_user_message, parse_json_response, not_found_output, stream_from_client
)

logger = logging.getLogger("docqa.generators.risk")

# Base prompt — the vertical-specific system_prompt from config is appended at call time
_BASE_SYSTEM_PROMPT = """You are an expert legal risk analyst.

Rules:
- Answer ONLY using the provided document chunks.
- Every claim must cite a specific clause reference and page number.
- Assign an overall risk level: HIGH, MEDIUM, or LOW.
- List specific red flags found in the clauses (empty list if none).
- Do NOT hallucinate clauses that are not in the provided chunks.

Return ONLY valid JSON in this exact format:
{
  "answer": "Detailed risk analysis here.",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "risk_level": "HIGH" | "MEDIUM" | "LOW",
  "red_flags": ["Uncapped liability in Section 12.3", "..."],
  "citations": [{"clause": "Section 12.3", "article": null, "page": 7}],
  "plain_english": "Plain English summary (startup vertical only, else null)",
  "founder_risk": "HIGH" | "MEDIUM" | "LOW" | null,
  "market_standard": "This term is more restrictive than market standard because..." | null,
  "related_terms": ["Indemnity", "Liquidation Preference"],
  "chunks_used": ["chunk_id_1", "chunk_id_2"]
}"""


def _build_system_prompt(config: Dict[str, Any]) -> str:
    """Combine base prompt with the vertical-specific instruction from config."""
    vertical_instruction = config.get("system_prompt", "")
    if vertical_instruction:
        return f"{_BASE_SYSTEM_PROMPT}\n\nVERTICAL INSTRUCTION:\n{vertical_instruction}"
    return _BASE_SYSTEM_PROMPT


class RiskGenerator(BaseGenerator[RiskOutput]):
    """Generator for law and startup verticals. Returns RiskOutput."""

    def __init__(self, llm_client: Any):
        self.client = llm_client

    async def generate(
        self,
        query: str,
        chunks: List[ChunkResult],
        config: Dict[str, Any],
    ) -> RiskOutput:
        if not chunks:
            return not_found_output(RiskOutput)

        system_prompt = _build_system_prompt(config)
        user_msg      = build_user_message(query, config)

        try:
            raw  = await self.client.chat(
                system_prompt=system_prompt,
                user_message=user_msg,
                max_tokens=2048,
                temperature=0.1,
            )
            data = parse_json_response(raw)

            citations = [
                Citation(
                    clause  = c.get("clause") if isinstance(c, dict) else None,
                    article = c.get("article") if isinstance(c, dict) else None,
                    page    = c.get("page") if isinstance(c, dict) else None,
                )
                for c in (data.get("citations") or [])
                if isinstance(c, dict)
            ]

            # founder_risk is startup-only; law vertical will return null → None
            founder_risk_raw = data.get("founder_risk")
            founder_risk = RiskLevel(founder_risk_raw) if founder_risk_raw else None

            return RiskOutput(
                answer         = data.get("answer") or "",
                confidence     = data.get("confidence") or ConfidenceLevel.LOW,
                risk_level     = data.get("risk_level") or RiskLevel.LOW,
                red_flags      = data.get("red_flags") or [],
                citations      = citations,
                plain_english  = data.get("plain_english"),
                founder_risk   = founder_risk,
                market_standard= data.get("market_standard"),
                related_terms  = data.get("related_terms") or [],
                chunks_used    = data.get("chunks_used") or [c.id for c in chunks],
            )

        except Exception as exc:
            logger.error("RiskGenerator error: %s", exc)
            return not_found_output(RiskOutput)

    async def stream(self, query: str, chunks: List[ChunkResult], config: Dict[str, Any]):
        if not chunks:
            yield "No relevant clauses found for this query."
            return
        system_prompt = _build_system_prompt(config)
        async for token in stream_from_client(
            self.client, system_prompt, build_user_message(query, config)
        ):
            yield token
