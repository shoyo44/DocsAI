"""
Semantic Query Cache — stores past vector embeddings and LLM responses.
Returns cached answers instantly (similarity >= 0.95), saving API calls and costs.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import List, Optional

import numpy as np

logger = logging.getLogger("docqa.core.cache")


def _default_cache_path() -> str:
    data_dir = os.getenv(
        "GRAPH_STORE_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"),
    )
    return os.path.abspath(os.path.join(data_dir, "semantic_cache.db"))


class SemanticCache:
    """
    Local SQLite semantic cache.
    Stores query text, query vector blob, and response JSON payloads.
    """

    def __init__(self, db_path: Optional[str] = None):
        db_path = db_path or _default_cache_path()
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT,
                    vertical TEXT,
                    query TEXT,
                    response_json TEXT,
                    embedding_blob BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Failed to initialize semantic cache SQLite: %s", exc)

    def get(
        self,
        tenant_id: str,
        vertical: str,
        query_vector: List[float] | np.ndarray,
        threshold: float = 0.95,
    ) -> Optional[dict]:
        """
        Scan cache records, calculate cosine similarity, and return hit if similarity >= threshold.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT query, response_json, embedding_blob FROM cache WHERE tenant_id = ? AND vertical = ?",
                (tenant_id, vertical)
            )
            rows = cursor.fetchall()
            conn.close()
        except Exception as exc:
            logger.error("Error reading from semantic cache: %s", exc)
            return None

        if not rows:
            return None

        q_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return None
        q_vec_normed = q_vec / q_norm

        best_score = -1.0
        best_response: Optional[str] = None

        for query, resp_json, emb_blob in rows:
            try:
                emb = np.frombuffer(emb_blob, dtype=np.float32)
                if len(emb) != len(q_vec_normed):
                    continue
                emb_norm = np.linalg.norm(emb)
                emb_normed = emb / (emb_norm if emb_norm > 0 else 1.0)

                similarity = float(np.dot(q_vec_normed, emb_normed))
                if similarity > best_score:
                    best_score = similarity
                    best_response = resp_json
            except Exception:
                continue

        if best_score >= threshold and best_response:
            logger.info("🎯 Semantic Cache HIT! Similarity: %.4f (threshold %.2f)", best_score, threshold)
            try:
                # Add cache hit info to metadata
                cached_data = json.loads(best_response)
                if isinstance(cached_data, dict):
                    cached_data["_cache_hit"] = True
                    cached_data["_cache_similarity"] = round(best_score, 4)
                return cached_data
            except json.JSONDecodeError:
                return None

        return None

    def set(
        self,
        tenant_id: str,
        vertical: str,
        query: str,
        query_vector: List[float] | np.ndarray,
        response_data: dict,
    ) -> None:
        """
        Cache a new query response.
        """
        try:
            q_vec = np.array(query_vector, dtype=np.float32)
            blob = q_vec.tobytes()
            
            # Clean cached flags before saving
            clean_data = {k: v for k, v in response_data.items() if not k.startswith("_")}

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO cache (tenant_id, vertical, query, response_json, embedding_blob) VALUES (?, ?, ?, ?, ?)",
                (tenant_id, vertical, query, json.dumps(clean_data), blob)
            )
            conn.commit()
            conn.close()
            logger.info("📝 Cached query response semantically (size: %d floats)", len(q_vec))
        except Exception as exc:
            logger.error("Failed to write to semantic cache: %s", exc)

    def clear_tenant_cache(self, tenant_id: str) -> None:
        """Clear all cached queries for a tenant when documents change."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cache WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
            conn.close()
            logger.info("🧹 Cleared semantic cache for tenant: %s", tenant_id)
        except Exception as exc:
            logger.error("Failed to clear tenant cache: %s", exc)
