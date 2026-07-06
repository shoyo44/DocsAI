"""
Academic Generator — University / Research Paper vertical.

Produces structured academic responses from research paper chunks.
Output schema: AcademicOutput
    - paper_title      : detected from title page chunks
    - authors          : detected from title page chunks
    - abstract_summary : condensed abstract
    - citations        : author + year + section references
    - contradictions   : conflicting findings across papers
    - related_papers   : mentioned related works

Special handling:
    - Visual description chunks (from OCR) are treated as first-class content.
    - Contradiction detection: flags when two chunks make opposing claims.
    - Author/title extraction: looks specifically at Page 1 chunks.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.interfaces import BaseGenerator
from app.core.schemas import (
    ChunkResult, AcademicOutput, ConfidenceLevel, AcademicCitation
)
from app.generators._base import (
    build_user_message, parse_json_response, not_found_output, stream_from_client
)

logger = logging.getLogger("docqa.generators.academic")

_SYSTEM_PROMPT = """You are a specialized Academic Research Assistant.

Rules:
- Answer ONLY using the provided research paper chunks.
- ALWAYS populate 'paper_title' and 'authors':
  * First look for chunks tagged [Section: Title Page] or on Page 1 — the title is usually the largest/first line of text on the title page.
  * If a clear title is not in any chunk, infer it from the document filename shown in chunks (e.g. doc_name field or text like "Research_Paper-1.pdf" → strip extension → "Research Paper 1").
  * Never leave paper_title as null if ANY identifying information is available.
- Use 'citations' to link every claim to author, year, and section.
- If two chunks make contradictory claims, list both in 'contradictions'.
- If chart/figure descriptions are provided ([VISUAL DESCRIPTION] chunks), use the data in them.
- Maintain academic rigor — do not speculate beyond the evidence.

Return ONLY valid JSON in this exact format:
{
  "answer": "Precise academic answer citing specific findings.",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "paper_title": "Full paper title or best inference from filename",
  "authors": ["Author A", "Author B"],
  "abstract_summary": "2-3 sentence abstract summary or null",
  "citations": [{"author": "Smith et al.", "year": "2023", "section": "Methods"}],
  "contradictions": ["Chunk A claims X while Chunk B claims Y"],
  "related_papers": ["Paper Title A (Year)", "Paper Title B (Year)"],
  "chunks_used": ["chunk_id_1"]
}"""


class AcademicGenerator(BaseGenerator[AcademicOutput]):
    """Generator for the university vertical. Returns AcademicOutput."""

    def __init__(self, llm_client: Any):
        self.client = llm_client

    async def generate(
        self,
        query: str,
        chunks: List[ChunkResult],
        config: Dict[str, Any],
    ) -> AcademicOutput:
        if not chunks:
            return not_found_output(AcademicOutput)

        user_msg = build_user_message(query, config)

        try:
            raw  = await self.client.chat(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_msg,
                max_tokens=2048,
                temperature=0.15,
            )
            data = parse_json_response(raw)

            citations = [
                AcademicCitation(
                    author  = c.get("author", "Unknown") if isinstance(c, dict) else "Unknown",
                    year    = str(c.get("year", "")) if isinstance(c, dict) else "",
                    section = c.get("section", "") if isinstance(c, dict) else "",
                )
                for c in (data.get("citations") or [])
                if isinstance(c, dict) and c.get("author")
            ]

            return AcademicOutput(
                answer           = data.get("answer") or "",
                confidence       = data.get("confidence") or ConfidenceLevel.LOW,
                paper_title      = data.get("paper_title"),
                authors          = data.get("authors") or [],
                abstract_summary = data.get("abstract_summary"),
                citations        = citations,
                contradictions   = data.get("contradictions") or [],
                related_papers   = data.get("related_papers") or [],
                chunks_used      = data.get("chunks_used") or [c.id for c in chunks],
            )

        except Exception as exc:
            logger.error("AcademicGenerator error: %s", exc)
            return not_found_output(AcademicOutput)

    async def stream(self, query: str, chunks: List[ChunkResult], config: Dict[str, Any]):
        print("Inside AcademicGenerator.stream. Chunks count:", len(chunks))
        if not chunks:
            yield "No relevant research content found for this query."
            return
        async for token in stream_from_client(
            self.client, _SYSTEM_PROMPT, build_user_message(query, config)
        ):
            yield token
