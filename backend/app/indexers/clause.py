"""
Clause Indexer — Law vertical.

Chunks legal contracts and agreements by clause boundaries.

Metadata extracted per chunk:
    - clause_ref : detected clause/section reference (e.g. "Section 12.3", "Clause 4")
    - chunk_type : "clause"

Clause detection patterns (regex):
    Section 12.3 / Section 12 / SECTION 12
    Clause 4 / CLAUSE 4
    Article VII / ARTICLE 7
    12.3 / 12.3.1 (numbered sub-clauses)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.core.interfaces import BaseIndexer
from app.indexers._base import split_into_chunks, build_chunk_record

logger = logging.getLogger("docqa.indexers.clause")

# Regex to detect common legal clause references at the start of a paragraph
_CLAUSE_REF_PATTERN = re.compile(
    r"""
    (?:
        (?:SECTION|Section|section)\s+[\d\.]+[a-zA-Z]?   # Section 12.3
        | (?:CLAUSE|Clause|clause)\s+[\d\.]+[a-zA-Z]?    # Clause 4a
        | (?:ARTICLE|Article|article)\s+(?:[IVXLCDM]+|\d+)  # Article VII / Article 7
        | ^\d+(?:\.\d+)+(?:\s+[A-Z])                      # 12.3 Heading
    )
    """,
    re.VERBOSE | re.MULTILINE,
)


def _extract_clause_ref(text: str) -> Optional[str]:
    """Extract the first clause/section reference from chunk text."""
    match = _CLAUSE_REF_PATTERN.search(text)
    return match.group(0).strip() if match else None


class ClauseIndexer(BaseIndexer):
    """
    Splits legal document text into clause-level chunks.

    Vertical: law
    Chunk type: clause
    Retriever: GraphRetriever (entity + clause graph traversal)
    """

    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 80):
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── chunk() ──────────────────────────────────────────────────────────────

    def chunk(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Split page text into clause-level chunks with legal metadata.

        Args:
            text:     Full text of one PDF page.
            metadata: Must contain: doc_id, tenant_id, page (int).

        Returns:
            List of chunk dicts, each with text + extracted clause metadata.
        """
        if not text or not text.strip():
            logger.debug("ClauseIndexer: empty page %s — skipped.", metadata.get("page"))
            return []

        raw_chunks = split_into_chunks(text, self.chunk_size, self.chunk_overlap)
        records: List[Dict[str, Any]] = []

        for i, chunk_text in enumerate(raw_chunks):
            clause_ref = _extract_clause_ref(chunk_text)
            record = build_chunk_record(
                text       = chunk_text,
                page       = metadata.get("page", 0),
                chunk_type = "clause",
                doc_id     = metadata.get("doc_id", ""),
                tenant_id  = metadata.get("tenant_id", ""),
                order      = metadata.get("chunk_offset", 0) + i,
                extra      = {"clause_ref": clause_ref},
            )
            records.append(record)

        logger.debug(
            "ClauseIndexer: page %s → %d chunks.", metadata.get("page"), len(records)
        )
        return records

    # ── index() ──────────────────────────────────────────────────────────────

    def index(self, chunks: List[Dict[str, Any]], store: Any) -> None:
        """
        Persist pre-embedded clause chunks to the graph store.
        Chunks must already have 'embedding' and 'id' fields added by ingestion.py.
        """
        if not chunks:
            return

        # Delegate to graph/ingestion batch writer
        from app.graph.ingestion import write_chunks_to_graph
        write_chunks_to_graph(store, chunks)
