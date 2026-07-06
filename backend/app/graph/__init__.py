"""
Graph layer — in-process graph store, ingestion, OCR.

Primary entry points:
    GraphStore            — in-process graph database (NetworkX + NumPy)
    ingest_document()     — full PDF ingestion pipeline
    supersede_document()  — version management
    extract_pages()       — multi-tier OCR text extraction
    write_chunks_to_graph() — batch chunk writer (used by indexers)
"""
from app.graph.store     import GraphStore
from app.graph.ingestion import ingest_document, supersede_document, write_chunks_to_graph
from app.graph.ocr       import extract_pages

__all__ = [
    "GraphStore",
    "ingest_document",
    "supersede_document",
    "write_chunks_to_graph",
    "extract_pages",
]
