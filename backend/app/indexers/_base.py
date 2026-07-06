"""
Internal shared chunking engine for all vertical indexers.

This module is NOT imported by anything outside the indexers/ package.
It provides the core text-splitting algorithm used by all 5 vertical indexers.

Algorithm (paragraph-aware sliding window):
    1. Split text into paragraphs at double-newlines.
    2. If a paragraph exceeds chunk_size words, split it further at sentences.
    3. Merge consecutive small segments until the chunk_size budget is reached.
    4. Apply overlap by carrying the last `chunk_overlap` words of the previous
       chunk as a prefix for the next one.
    5. Strip empty/whitespace-only chunks.

This approach is significantly better than blind character-count splitting because:
    - It preserves paragraph boundaries (legal clauses, HR policies, etc.)
    - It respects sentence boundaries (no mid-sentence cuts)
    - Overlap ensures no context is lost at chunk edges
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ─── Sentence tokenizer (no NLTK dependency) ─────────────────────────────────

_SENT_ENDINGS = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation boundaries."""
    sentences = _SENT_ENDINGS.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _word_count(text: str) -> int:
    return len(text.split())


# ─── Core splitting function ──────────────────────────────────────────────────

def split_into_chunks(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> List[str]:
    """
    Split text into overlapping chunks of approximately `chunk_size` words.

    Args:
        text:          Full page or section text.
        chunk_size:    Target word count per chunk.
        chunk_overlap: Words of overlap carried over from previous chunk.

    Returns:
        List of non-empty text strings, each ≈ chunk_size words.
    """
    if not text or not text.strip():
        return []

    # Step 1: split into paragraphs
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]

    # Step 2: break large paragraphs into sentences
    segments: List[str] = []
    for para in paragraphs:
        if _word_count(para) <= chunk_size:
            segments.append(para)
        else:
            segments.extend(_split_sentences(para))

    # Step 3: merge segments into chunks
    chunks:     List[str] = []
    current:    List[str] = []
    cur_words:  int       = 0

    for seg in segments:
        seg_words = _word_count(seg)

        if cur_words + seg_words > chunk_size and current:
            # Flush current chunk
            chunk_text = " ".join(current).strip()
            if chunk_text:
                chunks.append(chunk_text)

            # Apply overlap: keep last N words as prefix
            if chunk_overlap > 0:
                all_words   = chunk_text.split()
                overlap_txt = " ".join(all_words[-chunk_overlap:])
                current     = [overlap_txt]
                cur_words   = _word_count(overlap_txt)
            else:
                current   = []
                cur_words = 0

        current.append(seg)
        cur_words += seg_words

    # Flush remaining
    if current:
        remainder = " ".join(current).strip()
        if remainder:
            chunks.append(remainder)

    return chunks


# ─── Metadata builder ─────────────────────────────────────────────────────────

def build_chunk_record(
    text:       str,
    page:       int,
    chunk_type: str,
    doc_id:     str,
    tenant_id:  str,
    order:      int,
    extra:      Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produce a standardised chunk dict ready for Neo4j ingestion.
    All fields map directly to Chunk node properties in schema.cypher.
    """
    record: Dict[str, Any] = {
        "text":       text,
        "page":       page,
        "chunk_type": chunk_type,
        "doc_id":     doc_id,
        "tenant_id":  tenant_id,
        "order":      order,
        "superseded": False,
    }
    if extra:
        record.update(extra)
    return record
