"""
Document Ingestion Pipeline.

Full flow:
    PDF file → OCR/text extraction → vertical chunking → batch embeddings
    → GraphStore: Tenant + Document + Chunks + NEXT_CHUNK chain
    → spaCy NER (in thread) → Entity MENTIONS

Uses the in-process GraphStore instead of Neo4j.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import asyncio

logger    = logging.getLogger("docqa.ingestion")


# ─── spaCy NER (loaded once at module import) ─────────────────────────────────

try:
    import spacy
    _nlp = spacy.load("en_core_web_lg")   # lg model for better entity coverage
    logger.info("✅ spaCy en_core_web_lg loaded.")
except OSError:
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
        logger.warning("⚠️  spaCy en_core_web_sm loaded (lg preferred). Run: python -m spacy download en_core_web_lg")
    except OSError:
        _nlp = None
        logger.warning("⚠️  spaCy not available. NER disabled.")

_ENTITY_LABELS = {"ORG", "PERSON", "GPE", "LAW", "PRODUCT", "WORK_OF_ART"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_entities(text: str) -> List[Dict[str, str]]:
    """
    Extract named entities using spaCy. Pure CPU — called via asyncio.to_thread().
    Returns list of {canonical_name, type} dicts.
    """
    if _nlp is None:
        return []
    doc  = _nlp(text)
    seen = set()
    ents = []
    for ent in doc.ents:
        if ent.label_ not in _ENTITY_LABELS:
            continue
        canonical = ent.text.strip().upper()
        if canonical and canonical not in seen:
            seen.add(canonical)
            ents.append({"canonical_name": canonical, "type": ent.label_})
    return ents


async def embed_texts(texts: List[str], cf_client: Any) -> List[List[float]]:
    """
    Batch embed texts using Nomic Atlas API (nomic-embed-text-v1.5) with exponential backoff retries.
    """
    if not texts:
        return []
    logger.info("Embedding %d chunks via Nomic Atlas API...", len(texts))
    nomic_key = os.getenv("NOMIC_API_KEY")
    if not nomic_key:
        raise EnvironmentError(
            "No embedding provider available. Set NOMIC_API_KEY in your .env file."
        )

    import httpx
    import asyncio

    retries = 3
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api-atlas.nomic.ai/v1/embedding/text",
                    headers={
                        "Authorization": f"Bearer {nomic_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "nomic-embed-text-v1.5",
                        "texts": texts,
                        "task_type": "search_document"
                    }
                )
                resp.raise_for_status()
                return resp.json()["embeddings"]
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            if attempt == retries - 1:
                logger.error("Nomic batch embedding API permanently failed: %s", exc)
                raise exc
            wait = 0.5 * (2 ** attempt)
            logger.warning("Nomic batch embedding retry %d/%d after %.1fs due to: %s", attempt + 1, retries, wait, exc)
            await asyncio.sleep(wait)
        except Exception as exc:
            logger.error("Unexpected error in embed_texts: %s", exc)
            raise exc


# ─── Write helper (used by indexers' index() method) ─────────────────────────

def write_chunks_to_graph(store: Any, chunks: List[Dict[str, Any]]) -> None:
    """
    Persist pre-embedded chunks to the graph store in batch.
    Called by indexers' index() method. Chunks must already have 'id' and 'embedding'.
    """
    if not chunks:
        return
    store.create_chunks_batch(chunks)


# ─── Main ingestion entry point ───────────────────────────────────────────────

async def ingest_document(
    store:     Any,                  # GraphStore instance
    cf_client: Any,                  # CloudflareAI singleton
    tenant_id: str,
    doc_name:  str,
    vertical:  str,
    chunks:    List[Dict[str, Any]], # pre-chunked by vertical indexer
    doc_id:    Optional[str] = None,
    version:   str = "1.0",
    doc_name_full: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full ingestion pipeline for a document's chunks.

    Args:
        store:     GraphStore instance.
        cf_client: CloudflareAI singleton for batch embeddings.
        tenant_id: Owning tenant ID.
        doc_name:  Short display name of the document.
        vertical:  One of: law, compliance, hr, startup, university.
        chunks:    List of chunk dicts from vertical indexer (no embeddings yet).
        doc_id:    Optional document ID (auto-generated if not provided).
        version:   Document version string (for versioning/supersession).
        doc_name_full: Full document name for chunk metadata.

    Returns:
        {"doc_id": str, "chunks_created": int, "entities_extracted": int}
    """
    doc_id     = doc_id or str(uuid.uuid4())
    display_name = doc_name_full or doc_name

    # ── 1. Batch embed all chunk texts ────────────────────────────────────────
    texts      = [c["text"] for c in chunks]
    embeddings = await embed_texts(texts, cf_client)

    # ── 2. Build chunk records (assign IDs, inject embeddings + doc_name) ─────
    chunk_records: List[Dict[str, Any]] = []
    all_entity_rows: List[Dict[str, str]] = []

    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        chunk_id = str(uuid.uuid4())
        record   = {
            **chunk,
            "id":        chunk_id,
            "doc_id":    doc_id,
            "doc_name":  display_name,
            "tenant_id": tenant_id,
            "order":     i,
            "embedding": embedding,
        }
        chunk_records.append(record)

    # ── 3. NER — run spaCy in thread pool (CPU-heavy, must not block event loop) ──
    logger.info("Running NER on %d chunks...", len(chunk_records))

    async def _ner_chunk(record: Dict[str, Any]) -> List[Dict[str, str]]:
        ents = await asyncio.to_thread(_extract_entities, record["text"])
        return [{"chunk_id": record["id"], **e} for e in ents]

    ner_results = await asyncio.gather(*[_ner_chunk(r) for r in chunk_records])
    for ents in ner_results:
        all_entity_rows.extend(ents)

    # ── 4. Write to GraphStore ────────────────────────────────────────────────

    # 4a. Upsert tenant
    store.upsert_tenant(tenant_id, vertical)

    # 4b. Create document node
    store.create_document(
        tenant_id=tenant_id,
        doc_id=doc_id,
        doc_name=doc_name,
        version=version,
        vertical=vertical,
    )

    # 4c. Create all chunks in batch
    store.create_chunks_batch(chunk_records)

    # 4d. NEXT_CHUNK chain
    if len(chunk_records) > 1:
        pairs = [
            {"a": chunk_records[i]["id"], "b": chunk_records[i + 1]["id"]}
            for i in range(len(chunk_records) - 1)
        ]
        store.create_next_chunk_chain(pairs)

    # 4e. Entity MENTIONS in batch
    if all_entity_rows:
        entity_params = [
            {
                "name":     e["canonical_name"],
                "type":     e["type"],
                "chunk_id": e["chunk_id"],
            }
            for e in all_entity_rows
        ]
        store.create_entities_batch(entity_params)

    unique_entities = len({e["canonical_name"] for e in all_entity_rows})
    logger.info(
        "Ingested '%s' → doc_id=%s | %d chunks | %d entities",
        doc_name, doc_id, len(chunk_records), unique_entities,
    )
    return {
        "doc_id":             doc_id,
        "chunks_created":     len(chunk_records),
        "entities_extracted": unique_entities,
    }


# ─── Document supersession ────────────────────────────────────────────────────

def supersede_document(
    store:      Any,
    old_doc_id: str,
    new_doc_id: str,
    tenant_id:  str,
) -> None:
    """
    Mark old_doc_id as superseded by new_doc_id.
    Sets superseded=true on the old document and all its chunks.
    Creates a SUPERSEDED_BY relationship between the two documents.
    """
    store.supersede_document(old_doc_id, new_doc_id, tenant_id)
    logger.info("Document %s superseded by %s.", old_doc_id, new_doc_id)
