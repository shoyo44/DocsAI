"""
JSON Fallback Database
======================

A local file-based database that mimics a subset of the PyMongo client API.
Used as a transparent fallback when MongoDB Atlas is offline or misconfigured.
Saves data as JSON lists under backend/data/json_db/*.json.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("docqa.json_fallback_db")


class JSONFallbackCollection:
    """Mimics a PyMongo collection with basic query support."""

    def __init__(self, db_dir: str, coll_name: str) -> None:
        self.file_path = os.path.join(db_dir, f"{coll_name}.json")
        os.makedirs(db_dir, exist_ok=True)
        self._load_data()

    def _load_data(self) -> None:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                    if not isinstance(self.data, list):
                        self.data = []
            except Exception as e:
                logger.error("Failed to load local JSON collection %s: %s", self.file_path, e)
                self.data = []
        else:
            self.data = []

    def _save_data(self) -> None:
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save local JSON collection %s: %s", self.file_path, e)

    def insert_one(self, doc: Dict[str, Any]) -> Any:
        """Insert a single document, copying it to avoid modifying the original."""
        doc_copy = dict(doc)
        if "id" in doc_copy and "_id" not in doc_copy:
            doc_copy["_id"] = doc_copy["id"]
        elif "_id" not in doc_copy:
            import uuid
            doc_copy["_id"] = str(uuid.uuid4())
        
        self.data.append(doc_copy)
        self._save_data()
        
        class InsertResult:
            def __init__(self, inserted_id):
                self.inserted_id = inserted_id
        
        return InsertResult(doc_copy["_id"])

    def count_documents(self, filter_query: Dict[str, Any]) -> int:
        """Count documents matching filter."""
        return len(list(self.find(filter_query)))

    def find(self, filter_query: Dict[str, Any]) -> "JSONFallbackCursor":
        """Find documents matching simple key-value filters."""
        results = []
        for doc in self.data:
            match = True
            for k, v in filter_query.items():
                # Simple exact matching or nested matching
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                results.append(doc)
        
        return JSONFallbackCursor(results)

    def delete_many(self, filter_query: Dict[str, Any]) -> Any:
        """Delete matching documents."""
        initial_len = len(self.data)
        self.data = [doc for doc in self.data if not self._match_doc(doc, filter_query)]
        deleted_count = initial_len - len(self.data)
        if deleted_count > 0:
            self._save_data()
        
        class DeleteResult:
            def __init__(self, count):
                self.deleted_count = count
        
        return DeleteResult(deleted_count)

    def _match_doc(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for k, v in query.items():
            if doc.get(k) != v:
                return False
        return True


class JSONFallbackCursor:
    """Cursor mimicking PyMongo cursor with chaining methods."""

    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data
        self._sort_key: Optional[str] = None
        self._sort_direction: int = 1
        self._limit: Optional[int] = None

    def sort(self, key: str, direction: int = 1) -> "JSONFallbackCursor":
        """Sort documents: 1 for ascending, -1 for descending."""
        self._sort_key = key
        self._sort_direction = direction
        return self

    def limit(self, count: int) -> "JSONFallbackCursor":
        """Limit document count."""
        self._limit = count
        return self

    def __iter__(self):
        docs = list(self.data)
        
        # Apply sorting
        if self._sort_key:
            def get_val(doc):
                return doc.get(self._sort_key, 0)
            reverse_order = (self._sort_direction == -1)
            try:
                docs.sort(key=get_val, reverse=reverse_order)
            except Exception:
                pass  # Fallback if types are un-sortable
        
        # Apply limit
        if self._limit is not None:
            docs = docs[:self._limit]
            
        return iter(docs)


class JSONFallbackDatabase:
    """Mimics a PyMongo Database instance."""

    def __init__(self, db_dir: str) -> None:
        self.db_dir = db_dir
        self.collections: Dict[str, JSONFallbackCollection] = {}

    def __getitem__(self, name: str) -> JSONFallbackCollection:
        if name not in self.collections:
            self.collections[name] = JSONFallbackCollection(self.db_dir, name)
        return self.collections[name]


class JSONFallbackClient:
    """Mimics a PyMongo Client instance."""

    def __init__(self, db_dir: str) -> None:
        self.db_dir = db_dir

    def __getitem__(self, db_name: str) -> JSONFallbackDatabase:
        return JSONFallbackDatabase(os.path.join(self.db_dir, db_name))

    class _Admin:
        def command(self, cmd_name: str, *args, **kwargs) -> Dict[str, Any]:
            if cmd_name == 'ping':
                return {"ok": 1.0}
            return {}

    @property
    def admin(self) -> _Admin:
        return self._Admin()

    def close(self) -> None:
        pass
