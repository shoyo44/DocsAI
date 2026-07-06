"""
Vertical-specific document chunkers/indexers.

Each indexer implements BaseIndexer and is wired to its vertical in factory.py.
"""
from app.indexers.clause  import ClauseIndexer
from app.indexers.article import ArticleIndexer
from app.indexers.topic   import TopicIndexer
from app.indexers.term    import TermIndexer
from app.indexers.section import SectionIndexer

__all__ = [
    "ClauseIndexer",
    "ArticleIndexer",
    "TopicIndexer",
    "TermIndexer",
    "SectionIndexer",
]
