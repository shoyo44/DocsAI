"""
Article Indexer — Compliance vertical.

Chunks regulatory documents (GDPR, HIPAA, ISO standards, etc.) by article boundaries.

Metadata extracted per chunk:
    - article_ref : regulation article reference (e.g. "Article 6", "Regulation 2016/679")
    - chunk_type  : "article"

Patterns detected:
    Article 6 / ARTICLE 6
    Art. 13 / Art 13
    Regulation (EU) 2016/679
    Section 164.308 (HIPAA-style)
    Rule 10b-5 (SEC-style)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.core.interfaces import BaseIndexer
from app.indexers._base import split_into_chunks, build_chunk_record

logger = logging.getLogger("docqa.indexers.article")

_ARTICLE_REF_PATTERN = re.compile(
    r"""
    (?:
        (?:ARTICLE|Article|Art\.?)\s+\d+(?:\.\d+)*        # Article 6 / Art. 13
        | (?:Regulation|REGULATION)\s+(?:\([\w\s]+\)\s*)?\d+/\d+  # Regulation (EU) 2016/679
        | (?:Section|SECTION)\s+\d+(?:\.\d+)*[a-zA-Z]?    # Section 164.308
        | (?:Rule|RULE)\s+\d+[a-z]?-\d+                   # Rule 10b-5
        | (?:Annex|Annex|Schedule)\s+[IVXLCDM\d]+          # Annex III / Schedule 2
    )
    """,
    re.VERBOSE | re.MULTILINE,
)


def _extract_article_ref(text: str) -> Optional[str]:
    """Extract the first regulation article reference from chunk text."""
    match = _ARTICLE_REF_PATTERN.search(text)
    return match.group(0).strip() if match else None


class ArticleIndexer(BaseIndexer):
    """
    Splits compliance/regulation document text into article-level chunks.

    Vertical: compliance
    Chunk type: article
    Retriever: HybridRetriever (vector + BM25 keyword for regulation IDs)
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── chunk() ──────────────────────────────────────────────────────────────

    def chunk(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Split page text into article-level compliance chunks.

        Args:
            text:     Full text of one PDF page.
            metadata: Must contain: doc_id, tenant_id, page (int).

        Returns:
            List of chunk dicts with article metadata.
        """
        if not text or not text.strip():
            logger.debug("ArticleIndexer: empty page %s — skipped.", metadata.get("page"))
            return []

        raw_chunks = split_into_chunks(text, self.chunk_size, self.chunk_overlap)
        records: List[Dict[str, Any]] = []

        for i, chunk_text in enumerate(raw_chunks):
            article_ref = _extract_article_ref(chunk_text)
            record = build_chunk_record(
                text       = chunk_text,
                page       = metadata.get("page", 0),
                chunk_type = "article",
                doc_id     = metadata.get("doc_id", ""),
                tenant_id  = metadata.get("tenant_id", ""),
                order      = metadata.get("chunk_offset", 0) + i,
                extra      = {"article_ref": article_ref},
            )
            records.append(record)

        logger.debug(
            "ArticleIndexer: page %s → %d chunks.", metadata.get("page"), len(records)
        )
        return records

    # ── index() ──────────────────────────────────────────────────────────────

    def index(self, chunks: List[Dict[str, Any]], store: Any) -> None:
        """Persist pre-embedded article chunks to the graph store."""
        if not chunks:
            return
        from app.graph.ingestion import write_chunks_to_graph
        write_chunks_to_graph(store, chunks)
