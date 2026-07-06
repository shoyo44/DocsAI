"""
Section Indexer — University / Research Paper vertical.

Chunks academic papers and research documents by section boundaries.

Metadata extracted per chunk:
    - section    : detected section name (Abstract, Introduction, Methods, etc.)
    - chunk_type : "section"

Standard academic paper sections detected:
    Abstract, Keywords, Introduction, Background, Related Work,
    Methodology / Methods, Experiments, Results, Discussion,
    Conclusion, Future Work, References, Appendix, Acknowledgements

This enables targeted retrieval — e.g. "What methodology was used?"
goes directly to the Methods section chunks.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.core.interfaces import BaseIndexer
from app.indexers._base import split_into_chunks, build_chunk_record

logger = logging.getLogger("docqa.indexers.section")

# Ordered list of standard academic section names (checked by prefix match)
_ACADEMIC_SECTIONS = [
    "abstract",
    "keywords",
    "introduction",
    "background",
    "related work",
    "literature review",
    "theoretical framework",
    "methodology",
    "methods",
    "materials and methods",
    "experimental setup",
    "experiments",
    "results",
    "findings",
    "discussion",
    "analysis",
    "evaluation",
    "conclusion",
    "conclusions",
    "future work",
    "limitations",
    "references",
    "bibliography",
    "appendix",
    "acknowledgements",
    "acknowledgments",
    "supplementary",
]

# Submission portal metadata noise — these lines are injected by paper submission
# systems (e.g. Turnitin, EasyChair, arXiv) and contain no useful research content.
_SUBMISSION_NOISE_PATTERN = re.compile(
    r"(?:WORD\s+COUNT|TIME\s+SUBMITTED|PAPER\s+ID|SUBMISSION\s+ID|ASSIGNMENT\s+TITLE"
    r"|SUBMISSION\s+TITLE|AUTHOR|STUDENT\s+ID|FILE\s+NAME|PAGE\s+COUNT"
    r"|IDENTIFIER|DIGITAL\s+RECEIPT|TURNITIN|RECEIPT\s+ID|GRADING\s+MARK)\s*[:\-–]?",
    re.IGNORECASE | re.MULTILINE,
)

# Matches "1. Introduction", "2.3 Methods", "Abstract", "ABSTRACT", etc.
_SECTION_HEADER_PATTERN = re.compile(
    r"""
    (?:
        ^\d+(?:\.\d+)*\.?\s+      # Numbered: "1." or "2.3."
        | ^[IVXLCDM]+\.\s+        # Roman numeral: "II."
    )?
    ([A-Z][A-Za-z\s]{2,40})       # Section name (capitalized)
    $
    """,
    re.VERBOSE | re.MULTILINE,
)


def _detect_section(text: str) -> Optional[str]:
    """
    Detect which academic section this chunk belongs to.
    Checks for known section headers in the first 3 lines of the chunk.
    """
    first_lines = "\n".join(text.strip().splitlines()[:3]).lower()

    # Direct match against known sections
    for section in _ACADEMIC_SECTIONS:
        if section in first_lines:
            return section.title()

    # Regex match for numbered/roman-numeral headers
    match = _SECTION_HEADER_PATTERN.search(text[:200])
    if match:
        candidate = match.group(1).strip().lower()
        for section in _ACADEMIC_SECTIONS:
            if section in candidate:
                return section.title()
        # Return the raw header if not a known section
        return match.group(1).strip().title()

    return None


def _strip_submission_noise(text: str) -> str:
    """
    Remove submission-portal metadata lines from chunk text.
    Lines like 'WORD COUNT: 3485', 'TIME SUBMITTED: 17-APR-2026', etc.
    are injected by Turnitin / EasyChair and add noise to embeddings.
    """
    lines = text.splitlines()
    cleaned = [line for line in lines if not _SUBMISSION_NOISE_PATTERN.match(line.strip())]
    return "\n".join(cleaned).strip()


class SectionIndexer(BaseIndexer):
    """
    Splits academic paper text into section-level chunks with section metadata.

    Vertical: university
    Chunk type: section
    Retriever: HybridRetriever (vector + keyword for citation/author lookups)
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── chunk() ──────────────────────────────────────────────────────────────

    def chunk(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Split academic paper page text into section chunks.

        Args:
            text:     Full text of one PDF page.
            metadata: Must contain: doc_id, tenant_id, page (int).

        Returns:
            List of chunk dicts with section metadata.
        """
        if not text or not text.strip():
            logger.debug("SectionIndexer: empty page %s — skipped.", metadata.get("page"))
            return []

        page_num = metadata.get("page", 0)

        # Strip submission-portal noise from ALL pages (especially page 1)
        clean_text = _strip_submission_noise(text)
        if not clean_text:
            logger.debug("SectionIndexer: page %s — all content was submission noise, skipped.", page_num)
            return []

        raw_chunks = split_into_chunks(clean_text, self.chunk_size, self.chunk_overlap)
        records: List[Dict[str, Any]] = []

        for i, chunk_text in enumerate(raw_chunks):
            # Page 1 = title page — always tag as "Title Page" so the LLM
            # can retrieve title/author information directly.
            if page_num == 1:
                section = "Title Page"
            else:
                section = _detect_section(chunk_text)

            record = build_chunk_record(
                text       = chunk_text,
                page       = page_num,
                chunk_type = "section",
                doc_id     = metadata.get("doc_id", ""),
                tenant_id  = metadata.get("tenant_id", ""),
                order      = metadata.get("chunk_offset", 0) + i,
                extra      = {"section": section},
            )
            records.append(record)

        logger.debug(
            "SectionIndexer: page %s → %d chunks.", page_num, len(records)
        )
        return records

    # ── index() ──────────────────────────────────────────────────────────────

    def index(self, chunks: List[Dict[str, Any]], store: Any) -> None:
        """Persist pre-embedded section chunks to the graph store."""
        if not chunks:
            return
        from app.graph.ingestion import write_chunks_to_graph
        write_chunks_to_graph(store, chunks)
