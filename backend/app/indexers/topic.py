"""
Topic Indexer — HR vertical.

Chunks HR policy documents by topic/heading boundaries.

Metadata extracted per chunk:
    - employee_type : who the policy applies to (full-time, contractor, intern, etc.)
    - chunk_type    : "topic"

Employee type detection scans for explicit role mentions in the chunk text.
This enables role-filtered retrieval ("Does this apply to contractors?").
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.core.interfaces import BaseIndexer
from app.indexers._base import split_into_chunks, build_chunk_record

logger = logging.getLogger("docqa.indexers.topic")

# ── Employee type patterns ────────────────────────────────────────────────────
# Maps canonical label → regex pattern to detect in chunk text

_EMPLOYEE_TYPE_PATTERNS: Dict[str, re.Pattern] = {
    "full-time":    re.compile(r'\b(?:full[- ]time|permanent|FTE)\b', re.IGNORECASE),
    "part-time":    re.compile(r'\bpart[- ]time\b', re.IGNORECASE),
    "contractor":   re.compile(r'\b(?:contractor|independent contractor|freelancer|consultant)\b', re.IGNORECASE),
    "intern":       re.compile(r'\b(?:intern|internship|trainee)\b', re.IGNORECASE),
    "manager":      re.compile(r'\b(?:manager|supervisor|team lead|director)\b', re.IGNORECASE),
    "executive":    re.compile(r'\b(?:executive|VP|vice president|C-suite|CEO|CTO|CFO)\b', re.IGNORECASE),
    "remote":       re.compile(r'\b(?:remote|work from home|WFH|telecommute)\b', re.IGNORECASE),
}


def _detect_employee_type(text: str) -> Optional[str]:
    """
    Return the first matched employee type, or None if no specific type is found.
    Priority order: more specific types checked first.
    """
    priority = [
        "executive", "manager", "contractor", "intern",
        "part-time", "full-time", "remote",
    ]
    for emp_type in priority:
        if _EMPLOYEE_TYPE_PATTERNS[emp_type].search(text):
            return emp_type
    return None   # applies to all employees


class TopicIndexer(BaseIndexer):
    """
    Splits HR policy text into topic-level chunks with role metadata.

    Vertical: hr
    Chunk type: topic
    Retriever: VectorRetriever (straight cosine similarity works well for HR)
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── chunk() ──────────────────────────────────────────────────────────────

    def chunk(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Split HR policy page text into topic chunks, tagging by employee type.

        Args:
            text:     Full text of one PDF page.
            metadata: Must contain: doc_id, tenant_id, page (int).

        Returns:
            List of chunk dicts with employee_type metadata.
        """
        if not text or not text.strip():
            logger.debug("TopicIndexer: empty page %s — skipped.", metadata.get("page"))
            return []

        raw_chunks = split_into_chunks(text, self.chunk_size, self.chunk_overlap)
        records: List[Dict[str, Any]] = []

        for i, chunk_text in enumerate(raw_chunks):
            emp_type = _detect_employee_type(chunk_text)
            record = build_chunk_record(
                text       = chunk_text,
                page       = metadata.get("page", 0),
                chunk_type = "topic",
                doc_id     = metadata.get("doc_id", ""),
                tenant_id  = metadata.get("tenant_id", ""),
                order      = metadata.get("chunk_offset", 0) + i,
                extra      = {"employee_type": emp_type},
            )
            records.append(record)

        logger.debug(
            "TopicIndexer: page %s → %d chunks.", metadata.get("page"), len(records)
        )
        return records

    # ── index() ──────────────────────────────────────────────────────────────

    def index(self, chunks: List[Dict[str, Any]], store: Any) -> None:
        """Persist pre-embedded topic chunks to the graph store."""
        if not chunks:
            return
        from app.graph.ingestion import write_chunks_to_graph
        write_chunks_to_graph(store, chunks)
