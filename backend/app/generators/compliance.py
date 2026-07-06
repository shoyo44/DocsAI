"""
Compliance Generator — Compliance vertical.

Produces structured compliance verdicts mapped to regulation IDs.
Output schema: ComplianceOutput
    - compliance_status : COMPLIANT / NON-COMPLIANT / UNCLEAR
    - regulation_id     : e.g. "GDPR", "HIPAA", "ISO 27001"
    - section           : e.g. "Article 6(1)(a)"
    - version_warning   : True if document version may be outdated
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.interfaces import BaseGenerator
from app.core.schemas import (
    ChunkResult, ComplianceOutput, ComplianceStatus, ConfidenceLevel, Citation
)
from app.generators._base import (
    build_user_message, parse_json_response, not_found_output, stream_from_client
)

logger = logging.getLogger("docqa.generators.compliance")

_SYSTEM_PROMPT = """You are a senior compliance officer with expertise in GDPR, HIPAA, SOC2, ISO 27001, and financial regulations.

Rules:
- Answer ONLY using the provided document chunks.
- Always map your answer to a specific regulation ID and section number.
- Verdict must be one of: COMPLIANT, NON-COMPLIANT, or UNCLEAR.
- Set version_warning=true if the document may be outdated relative to current regulation.
- Do NOT interpret beyond what is written.

Return ONLY valid JSON in this exact format:
{
  "answer": "Detailed compliance analysis here.",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "compliance_status": "COMPLIANT" | "NON-COMPLIANT" | "UNCLEAR",
  "regulation_id": "GDPR" | "HIPAA" | "SOC2" | "ISO 27001" | null,
  "section": "Article 6(1)(a)" or null,
  "version_warning": false,
  "citations": [{"clause": "Section X", "article": "Article Y", "page": 1}],
  "chunks_used": ["chunk_id_1"]
}"""


class ComplianceGenerator(BaseGenerator[ComplianceOutput]):
    """Generator for the compliance vertical. Returns ComplianceOutput."""

    def __init__(self, llm_client: Any):
        self.client = llm_client

    async def generate(
        self,
        query: str,
        chunks: List[ChunkResult],
        config: Dict[str, Any],
    ) -> ComplianceOutput:
        if not chunks:
            return not_found_output(ComplianceOutput)

        user_msg = build_user_message(query, config)

        try:
            raw  = await self.client.chat(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_msg,
                max_tokens=1500,
                temperature=0.05,   # very low — compliance needs determinism
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

            return ComplianceOutput(
                answer            = data.get("answer") or "",
                confidence        = data.get("confidence") or ConfidenceLevel.LOW,
                compliance_status = data.get("compliance_status") or ComplianceStatus.UNCLEAR,
                regulation_id     = data.get("regulation_id"),
                section           = data.get("section"),
                version_warning   = bool(data.get("version_warning", False)),
                citations         = citations,
                chunks_used       = data.get("chunks_used") or [c.id for c in chunks],
            )

        except Exception as exc:
            logger.error("ComplianceGenerator error: %s", exc)
            return not_found_output(ComplianceOutput)

    async def stream(self, query: str, chunks: List[ChunkResult], config: Dict[str, Any]):
        if not chunks:
            yield "No compliance information found for this query."
            return
        async for token in stream_from_client(
            self.client, _SYSTEM_PROMPT, build_user_message(query, config)
        ):
            yield token
