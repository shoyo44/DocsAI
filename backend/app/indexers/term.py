"""
Term Indexer — Startup vertical.

Chunks startup legal documents (term sheets, SHA, SAFE notes, NDAs)
with extraction of defined terms.

Metadata extracted per chunk:
    - defined_term : primary defined term used/defined in this chunk
    - chunk_type   : "term"

Defined terms in startup docs typically appear in one of:
    "Term" means ... (definition sentence)
    "Term" shall mean ...
    TERM (ALL-CAPS definitions)
    "Term" (quoted in body text)

This enables targeted retrieval — e.g. "What does 'Pro-Rata Right' mean?"
can retrieve the exact chunk defining it.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.core.interfaces import BaseIndexer
from app.indexers._base import split_into_chunks, build_chunk_record

logger = logging.getLogger("docqa.indexers.term")

# Pattern 1: "Defined Term" means / shall mean ...
_DEFINITION_PATTERN = re.compile(
    r'"([A-Z][A-Za-z\s\-]{2,40})"\s+(?:means|shall mean|refers to|is defined as)',
    re.IGNORECASE,
)

# Pattern 2: ALL-CAPS TERM at start of sentence (e.g. VESTING SCHEDULE means...)
_ALLCAPS_PATTERN = re.compile(
    r'\b([A-Z]{2,}(?:\s+[A-Z]{2,}){0,3})\s+(?:means|shall mean|is defined)',
)

# High-value startup terms to always flag when present in a chunk
_IMPORTANT_TERMS = {
    "liquidation preference", "anti-dilution", "pro-rata right", "drag-along",
    "tag-along", "vesting", "cliff", "cap table", "option pool", "valuation cap",
    "discount rate", "conversion", "maturity date", "board seat", "blocking right",
    "most favored nation", "right of first refusal", "co-sale right",
}


def _extract_defined_term(text: str) -> Optional[str]:
    """
    Extract the primary defined term from a chunk.
    Priority: explicit definition pattern > all-caps pattern > important term scan.
    """
    # Try explicit definition patterns first
    match = _DEFINITION_PATTERN.search(text)
    if match:
        return match.group(1).strip()

    match = _ALLCAPS_PATTERN.search(text)
    if match:
        return match.group(1).strip().title()

    # Fall back to scanning for important startup terms
    text_lower = text.lower()
    for term in _IMPORTANT_TERMS:
        if term in text_lower:
            return term.title()

    return None


class TermIndexer(BaseIndexer):
    """
    Splits startup legal documents into term-level chunks with defined term metadata.

    Vertical: startup
    Chunk type: term
    Retriever: GraphRetriever (entity + defined term graph traversal)
    """

    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 80):
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── chunk() ──────────────────────────────────────────────────────────────

    def chunk(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Split startup document page text into term chunks.

        Args:
            text:     Full text of one PDF page.
            metadata: Must contain: doc_id, tenant_id, page (int).

        Returns:
            List of chunk dicts with defined_term metadata.
        """
        if not text or not text.strip():
            logger.debug("TermIndexer: empty page %s — skipped.", metadata.get("page"))
            return []

        raw_chunks = split_into_chunks(text, self.chunk_size, self.chunk_overlap)
        records: List[Dict[str, Any]] = []

        for i, chunk_text in enumerate(raw_chunks):
            defined_term = _extract_defined_term(chunk_text)
            record = build_chunk_record(
                text       = chunk_text,
                page       = metadata.get("page", 0),
                chunk_type = "term",
                doc_id     = metadata.get("doc_id", ""),
                tenant_id  = metadata.get("tenant_id", ""),
                order      = metadata.get("chunk_offset", 0) + i,
                extra      = {"defined_term": defined_term},
            )
            records.append(record)

        logger.debug(
            "TermIndexer: page %s → %d chunks.", metadata.get("page"), len(records)
        )
        return records

    # ── index() ──────────────────────────────────────────────────────────────

    def index(self, chunks: List[Dict[str, Any]], store: Any) -> None:
        """Persist pre-embedded term chunks to the graph store."""
        if not chunks:
            return
        from app.graph.ingestion import write_chunks_to_graph
        write_chunks_to_graph(store, chunks)
