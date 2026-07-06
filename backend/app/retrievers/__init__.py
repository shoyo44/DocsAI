"""
Graph, hybrid, and vector retrieval strategies.

Each implements BaseRetriever and is wired to its vertical in factory.py:
    law, startup    → GraphRetriever
    compliance      → HybridRetriever
    university      → HybridRetriever
    hr              → VectorRetriever
"""
from app.retrievers.vector import VectorRetriever
from app.retrievers.graph  import GraphRetriever
from app.retrievers.hybrid import HybridRetriever

__all__ = ["VectorRetriever", "GraphRetriever", "HybridRetriever"]
