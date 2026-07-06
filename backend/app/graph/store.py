"""
In-Process Graph Database — replaces Neo4j with NetworkX + NumPy.

Optimizations:
1. Implements a thread-safe, re-entrant Reader-Writer Lock (RWLock).
2. Offloads disk saving to a background thread.
3. Implements high-performance VectorIndex using FAISS (Facebook AI Similarity Search)
   with fallback to optimized NumPy.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np

logger = logging.getLogger("docqa.graph_store")


# ─── High-Performance FAISS / NumPy Vector Index ───────────────────────────

class VectorIndex:
    """
    High-performance vector index manager.
    Uses FAISS if available, otherwise falls back to optimized NumPy.
    """
    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.ids: List[str] = []
        self._vectors: List[np.ndarray] = []
        self._index = None
        self._use_faiss = False
        try:
            import faiss
            self._index = faiss.IndexFlatIP(self.dimension)
            self._use_faiss = True
            logger.info("✅ FAISS CPU vector index initialized successfully.")
        except ImportError:
            logger.info("ℹ️ FAISS is not installed/loaded. Falling back to numpy.")

    def reset(self) -> None:
        self.ids = []
        self._vectors = []
        if self._use_faiss and self._index is not None:
            self._index.reset()

    def add(self, chunk_id: str, vector: np.ndarray) -> None:
        if self._use_faiss and self._index is not None:
            norm = np.linalg.norm(vector)
            normed_vec = vector / (norm if norm > 0.0 else 1.0)
            self._index.add(np.array([normed_vec], dtype=np.float32))
        else:
            self._vectors.append(vector)
        self.ids.append(chunk_id)

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[str, float]]:
        if not self.ids:
            return []

        q_norm = np.linalg.norm(query_vector)
        q_vec = query_vector / (q_norm if q_norm > 0.0 else 1.0)

        if self._use_faiss and self._index is not None:
            try:
                scores, indices = self._index.search(
                    np.array([q_vec], dtype=np.float32), top_k
                )
                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx >= 0 and idx < len(self.ids):
                        results.append((self.ids[idx], float(score)))
                return results
            except Exception as e:
                logger.error("FAISS search failed, falling back to numpy: %s", e)

        # NumPy fallback
        if not self._vectors:
            return []
        matrix = np.stack(self._vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        matrix_normed = matrix / norms
        
        scores = matrix_normed @ q_vec
        
        # Sort and return top_k
        indices = np.argsort(scores)[::-1][:top_k]
        return [(self.ids[idx], float(scores[idx])) for idx in indices]


# ─── Re-entrant Reader-Writer Lock ──────────────────────────────────────────

class RWLock:
    """
    Re-entrant Reader-Writer Lock implementation.
    Allows multiple concurrent reader threads, single writer thread,
    and supports re-entrancy for both reads and writes from the same thread.
    """
    def __init__(self):
        self._mutex = threading.Lock()
        self._read_ready = threading.Condition(self._mutex)
        self._readers = 0
        self._writers = 0
        self._writer_thread = None
        self._write_recursion = 0
        self._reader_threads: Dict[int, int] = {}  # thread_id -> recursion count

    def acquire_read(self) -> None:
        tid = threading.get_ident()
        with self._mutex:
            if tid in self._reader_threads:
                self._reader_threads[tid] += 1
                return
            if self._writer_thread == tid:
                return
            
            while self._writers > 0:
                self._read_ready.wait()
            self._readers += 1
            self._reader_threads[tid] = 1

    def release_read(self) -> None:
        tid = threading.get_ident()
        with self._mutex:
            if self._writer_thread == tid:
                return
            if tid not in self._reader_threads:
                return
            self._reader_threads[tid] -= 1
            if self._reader_threads[tid] == 0:
                del self._reader_threads[tid]
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()

    def acquire_write(self) -> None:
        tid = threading.get_ident()
        with self._mutex:
            if self._writer_thread == tid:
                self._write_recursion += 1
                return
            
            while self._readers > 0 or self._writers > 0:
                self._read_ready.wait()
            self._writers = 1
            self._writer_thread = tid
            self._write_recursion = 1

    def release_write(self) -> None:
        with self._mutex:
            if self._writer_thread != threading.get_ident():
                raise RuntimeError("Release write lock from non-owner thread")
            self._write_recursion -= 1
            if self._write_recursion == 0:
                self._writers = 0
                self._writer_thread = None
                self._read_ready.notify_all()

    def read_lock(self):
        class ReadLockContext:
            def __init__(self, rwlock: RWLock):
                self.rwlock = rwlock
            def __enter__(self):
                self.rwlock.acquire_read()
            def __exit__(self, exc_type, exc_val, exc_tb):
                self.rwlock.release_read()
        return ReadLockContext(self)

    def write_lock(self):
        class WriteLockContext:
            def __init__(self, rwlock: RWLock):
                self.rwlock = rwlock
            def __enter__(self):
                self.rwlock.acquire_write()
            def __exit__(self, exc_type, exc_val, exc_tb):
                self.rwlock.release_write()
        return WriteLockContext(self)


# ─── Graph Store Database ───────────────────────────────────────────────────

class GraphStore:
    """
    In-process graph database using NetworkX + NumPy + FAISS.
    Thread-safe concurrent access. Persistent to JSON on disk.
    """

    def __init__(self, data_dir: str = "./data"):
        self._lock = RWLock()
        self._graph = nx.DiGraph()
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._filepath = self._data_dir / "graph_store.json"

        # Embedding cache for fast vector search
        # Maps chunk_id → numpy array
        self._embedding_cache: Dict[str, np.ndarray] = {}
        
        # Per-tenant high-performance VectorIndex objects
        self._indices: Dict[str, VectorIndex] = {}

        self._load()
        logger.info("GraphStore initialized. Nodes=%d, Edges=%d, Path=%s",
                     self._graph.number_of_nodes(),
                     self._graph.number_of_edges(),
                     self._filepath)

    def _rebuild_indices(self) -> None:
        """Rebuild high-performance vector indices for all tenants."""
        logger.info("Rebuilding vector indices...")
        self._indices = {}
        for nid, data in self._graph.nodes(data=True):
            if data.get("label") == "Chunk":
                tenant_id = data.get("tenant_id")
                chunk_id = data.get("id")
                if tenant_id and chunk_id in self._embedding_cache:
                    emb = self._embedding_cache[chunk_id]
                    if tenant_id not in self._indices:
                        self._indices[tenant_id] = VectorIndex(emb.shape[0])
                    self._indices[tenant_id].add(chunk_id, emb)

    # ─── Tenant Operations ────────────────────────────────────────────────────

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant details."""
        with self._lock.read_lock():
            node_id = f"tenant:{tenant_id}"
            if not self._graph.has_node(node_id):
                return None
            data = self._graph.nodes[node_id]
            return {
                "id": tenant_id,
                "vertical": data.get("vertical"),
                "created_at": data.get("created_at")
            }

    def upsert_tenant(self, tenant_id: str, vertical: str) -> None:
        """Create or update a Tenant node."""
        with self._lock.write_lock():
            node_id = f"tenant:{tenant_id}"
            if not self._graph.has_node(node_id):
                self._graph.add_node(node_id,
                    label="Tenant",
                    id=tenant_id,
                    name=tenant_id,
                    vertical=vertical,
                    created_at=self._now(),
                )
            else:
                self._graph.nodes[node_id]["vertical"] = vertical
            self._save()

    # ─── Document Operations ──────────────────────────────────────────────────

    def create_document(
        self,
        tenant_id: str,
        doc_id: str,
        doc_name: str,
        version: str,
        vertical: str,
    ) -> None:
        """Create a Document node and link it to its Tenant via OWNS."""
        with self._lock.write_lock():
            tenant_nid = f"tenant:{tenant_id}"
            doc_nid = f"doc:{doc_id}"

            # Ensure tenant exists
            if not self._graph.has_node(tenant_nid):
                self.upsert_tenant(tenant_id, vertical)

            self._graph.add_node(doc_nid,
                label="Document",
                id=doc_id,
                name=doc_name,
                version=version,
                vertical=vertical,
                tenant_id=tenant_id,
                superseded=False,
                superseded_by=None,
                created_at=self._now(),
            )
            self._graph.add_edge(tenant_nid, doc_nid, type="OWNS")
            self._save()

    def list_documents(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List all active (non-superseded) documents for a tenant with chunk counts."""
        with self._lock.read_lock():
            results = []
            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "Document"
                        and data.get("tenant_id") == tenant_id
                        and not data.get("superseded", False)):
                    # Count chunks
                    chunk_count = sum(
                        1 for _, target, edata in self._graph.out_edges(nid, data=True)
                        if edata.get("type") == "HAS_CHUNK"
                    )
                    results.append({
                        "id": data["id"],
                        "name": data.get("name", ""),
                        "version": data.get("version", "1.0"),
                        "vertical": data.get("vertical", ""),
                        "created_at": data.get("created_at", ""),
                        "chunks_count": chunk_count,
                    })
            # Sort by created_at descending
            results.sort(key=lambda d: d.get("created_at", ""), reverse=True)
            return results

    def get_document(self, doc_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a single document's metadata."""
        with self._lock.read_lock():
            doc_nid = f"doc:{doc_id}"
            if not self._graph.has_node(doc_nid):
                return None
            data = self._graph.nodes[doc_nid]
            if data.get("tenant_id") != tenant_id:
                return None
            return {
                "id": data["id"],
                "name": data.get("name", ""),
                "version": data.get("version", "1.0"),
                "vertical": data.get("vertical", ""),
                "superseded": data.get("superseded", False),
                "created_at": data.get("created_at", ""),
            }

    def delete_document(self, doc_id: str, tenant_id: str) -> None:
        """Delete a document and all its chunks, reports, and relationships."""
        with self._lock.write_lock():
            doc_nid = f"doc:{doc_id}"
            if not self._graph.has_node(doc_nid):
                return

            data = self._graph.nodes[doc_nid]
            if data.get("tenant_id") != tenant_id:
                return

            # Collect nodes to remove: chunks, reports
            nodes_to_remove = [doc_nid]
            for _, target, edata in list(self._graph.out_edges(doc_nid, data=True)):
                if edata.get("type") in ("HAS_CHUNK", "HAS_REPORT"):
                    nodes_to_remove.append(target)
                    # Remove chunk from embedding cache
                    target_data = self._graph.nodes.get(target, {})
                    chunk_id = target_data.get("id")
                    if chunk_id and chunk_id in self._embedding_cache:
                        del self._embedding_cache[chunk_id]

            for nid in nodes_to_remove:
                if self._graph.has_node(nid):
                    self._graph.remove_node(nid)

            self._save()
            self._rebuild_indices()

    def delete_all_documents(self, tenant_id: str) -> None:
        """Delete all documents owned by a tenant."""
        with self._lock.write_lock():
            docs = self.list_documents(tenant_id)
            for doc in docs:
                self.delete_document(doc["id"], tenant_id)

    def supersede_document(
        self, old_doc_id: str, new_doc_id: str, tenant_id: str
    ) -> None:
        """Mark old document as superseded by new document."""
        with self._lock.write_lock():
            old_nid = f"doc:{old_doc_id}"
            new_nid = f"doc:{new_doc_id}"

            if self._graph.has_node(old_nid):
                self._graph.nodes[old_nid]["superseded"] = True
                self._graph.nodes[old_nid]["superseded_by"] = new_doc_id

                # Mark all old chunks as superseded
                for _, target, edata in self._graph.out_edges(old_nid, data=True):
                    if edata.get("type") == "HAS_CHUNK":
                        self._graph.nodes[target]["superseded"] = True

                # Create SUPERSEDED_BY edge
                if self._graph.has_node(new_nid):
                    self._graph.add_edge(old_nid, new_nid, type="SUPERSEDED_BY")

            self._save()

    # ─── Chunk Operations ─────────────────────────────────────────────────────

    def create_chunks_batch(self, chunks: List[Dict[str, Any]]) -> None:
        """Create Chunk nodes in batch and link to their Documents via HAS_CHUNK."""
        with self._lock.write_lock():
            for c in chunks:
                chunk_nid = f"chunk:{c['id']}"
                doc_nid = f"doc:{c['doc_id']}"

                embedding = c.get("embedding")

                self._graph.add_node(chunk_nid,
                    label="Chunk",
                    id=c["id"],
                    text=c.get("text", ""),
                    page=c.get("page"),
                    tenant_id=c.get("tenant_id", ""),
                    doc_id=c.get("doc_id", ""),
                    doc_name=c.get("doc_name", ""),
                    order=c.get("order", 0),
                    chunk_type=c.get("chunk_type"),
                    clause_ref=c.get("clause_ref"),
                    article_ref=c.get("article_ref"),
                    section=c.get("section"),
                    employee_type=c.get("employee_type"),
                    defined_term=c.get("defined_term"),
                    superseded=False,
                )

                # Cache embedding for vector search
                if embedding:
                    self._embedding_cache[c["id"]] = np.array(embedding, dtype=np.float32)

                # Link to document
                if self._graph.has_node(doc_nid):
                    self._graph.add_edge(doc_nid, chunk_nid, type="HAS_CHUNK")

            self._save()
            self._rebuild_indices()

    def create_next_chunk_chain(self, pairs: List[Dict[str, str]]) -> None:
        """Create NEXT_CHUNK edges between sequential chunks."""
        with self._lock.write_lock():
            for p in pairs:
                a_nid = f"chunk:{p['a']}"
                b_nid = f"chunk:{p['b']}"
                if self._graph.has_node(a_nid) and self._graph.has_node(b_nid):
                    self._graph.add_edge(a_nid, b_nid, type="NEXT_CHUNK")
            self._save()

    def get_document_chunks(
        self, doc_id: str, tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Get all chunks for a document, ordered by chunk order."""
        with self._lock.read_lock():
            doc_nid = f"doc:{doc_id}"
            if not self._graph.has_node(doc_nid):
                return []

            chunks = []
            for _, target, edata in self._graph.out_edges(doc_nid, data=True):
                if edata.get("type") == "HAS_CHUNK":
                    cdata = self._graph.nodes[target]
                    if cdata.get("tenant_id") == tenant_id:
                        chunks.append({
                            "text": cdata.get("text", ""),
                            "page": cdata.get("page"),
                            "clause_ref": cdata.get("clause_ref"),
                            "article_ref": cdata.get("article_ref"),
                            "section": cdata.get("section"),
                            "order": cdata.get("order", 0),
                        })

            chunks.sort(key=lambda c: c.get("order", 0))
            return chunks

    # ─── Entity Operations ────────────────────────────────────────────────────

    def create_entities_batch(self, entities: List[Dict[str, str]]) -> None:
        """Create Entity nodes and MENTIONS edges from chunks."""
        with self._lock.write_lock():
            for ent in entities:
                ent_nid = f"entity:{ent['name']}"

                # Merge entity node
                if not self._graph.has_node(ent_nid):
                    self._graph.add_node(ent_nid,
                        label="Entity",
                        canonical_name=ent["name"],
                        type=ent.get("type", "UNKNOWN"),
                    )

                # Create MENTIONS edge from chunk
                chunk_nid = f"chunk:{ent['chunk_id']}"
                if self._graph.has_node(chunk_nid):
                    if not self._graph.has_edge(chunk_nid, ent_nid):
                        self._graph.add_edge(chunk_nid, ent_nid, type="MENTIONS")

            self._save()

    # ─── Vector Search ────────────────────────────────────────────────────────

    def vector_search(
        self,
        embedding: List[float],
        tenant_id: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Cosine similarity search over all non-superseded chunk embeddings
        belonging to the specified tenant, accelerated by FAISS.
        """
        with self._lock.read_lock():
            tenant_index = self._indices.get(tenant_id)
            if not tenant_index or not tenant_index.ids:
                return []

            query_vec = np.array(embedding, dtype=np.float32)
            
            # Query index (which defaults to FAISS or NumPy fallback internally)
            raw_hits = tenant_index.search(query_vec, top_k * 2)

            results = []
            for chunk_id, score in raw_hits:
                chunk_nid = f"chunk:{chunk_id}"
                if not self._graph.has_node(chunk_nid):
                    continue
                cdata = self._graph.nodes[chunk_nid]
                if cdata.get("superseded", False):
                    continue

                results.append({
                    "id": chunk_id,
                    "text": cdata.get("text", ""),
                    "page": cdata.get("page"),
                    "doc_id": cdata.get("doc_id"),
                    "doc_name": cdata.get("doc_name"),
                    "chunk_type": cdata.get("chunk_type"),
                    "clause_ref": cdata.get("clause_ref"),
                    "article_ref": cdata.get("article_ref"),
                    "section": cdata.get("section"),
                    "employee_type": cdata.get("employee_type"),
                    "defined_term": cdata.get("defined_term"),
                    "superseded": cdata.get("superseded", False),
                    "score": score,
                })

            # Sort and trim to final top_k
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_k]

    # ─── Graph Expansion ──────────────────────────────────────────────────────

    def expand_from_seeds(
        self, seed_ids: List[str], tenant_id: str
    ) -> List[Dict[str, Any]]:
        """
        From seed chunk IDs, find entity and sequential adjacent neighbors.
        """
        with self._lock.read_lock():
            seed_set = set(seed_ids)
            neighbors: Dict[str, Dict[str, Any]] = {}

            for seed_id in seed_ids:
                seed_nid = f"chunk:{seed_id}"
                if not self._graph.has_node(seed_nid):
                    continue

                # 1. Entity-connected neighbors
                for _, ent_nid, edata in self._graph.out_edges(seed_nid, data=True):
                    if edata.get("type") != "MENTIONS":
                        continue
                    for other_nid, _, edata2 in self._graph.in_edges(ent_nid, data=True):
                        if edata2.get("type") != "MENTIONS":
                            continue
                        other_data = self._graph.nodes[other_nid]
                        if other_data.get("label") != "Chunk":
                            continue
                        other_id = other_data.get("id")
                        if (other_id not in seed_set
                                and other_data.get("tenant_id") == tenant_id
                                and not other_data.get("superseded", False)
                                and other_id not in neighbors):
                            neighbors[other_id] = {
                                **self._chunk_to_dict(other_data),
                                "source": "entity",
                            }

                # 2. Sequential neighbors (NEXT_CHUNK — both directions)
                for _, adj_nid, edata in self._graph.out_edges(seed_nid, data=True):
                    if edata.get("type") == "NEXT_CHUNK":
                        self._add_adjacent(adj_nid, tenant_id, seed_set, neighbors)

                for adj_nid, _, edata in self._graph.in_edges(seed_nid, data=True):
                    if edata.get("type") == "NEXT_CHUNK":
                        self._add_adjacent(adj_nid, tenant_id, seed_set, neighbors)

            return list(neighbors.values())

    def _add_adjacent(
        self, nid: str, tenant_id: str, seed_set: Set[str],
        neighbors: Dict[str, Dict[str, Any]]
    ) -> None:
        """Helper: add an adjacent chunk to neighbors if valid."""
        if not self._graph.has_node(nid):
            return
        data = self._graph.nodes[nid]
        if data.get("label") != "Chunk":
            return
        cid = data.get("id")
        if (cid not in seed_set
                and data.get("tenant_id") == tenant_id
                and not data.get("superseded", False)
                and cid not in neighbors):
            neighbors[cid] = {
                **self._chunk_to_dict(data),
                "source": "adjacent",
            }

    # ─── Query Log / Audit ────────────────────────────────────────────────────

    def create_query_log(
        self,
        tenant_id: str,
        vertical: str,
        query: str,
        answer: str,
        confidence: str,
        not_found: bool,
        latency_ms: float,
    ) -> str:
        """Create a QueryLog node linked to the Tenant."""
        with self._lock.write_lock():
            log_id = str(uuid.uuid4())
            log_nid = f"log:{log_id}"
            tenant_nid = f"tenant:{tenant_id}"

            self._graph.add_node(log_nid,
                label="QueryLog",
                id=log_id,
                tenant_id=tenant_id,
                vertical=vertical,
                query=query,
                answer=answer[:500],
                confidence=confidence,
                not_found=not_found,
                latency_ms=round(latency_ms, 2),
                created_at=self._now(),
            )

            if self._graph.has_node(tenant_nid):
                self._graph.add_edge(tenant_nid, log_nid, type="HAS_LOG")

            self._save()
            return log_id

    def get_query_logs(
        self, tenant_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent query logs for a tenant."""
        with self._lock.read_lock():
            logs = []
            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "QueryLog"
                        and data.get("tenant_id") == tenant_id):
                    logs.append({
                        "query": data.get("query", ""),
                        "answer": data.get("answer", ""),
                        "confidence": data.get("confidence", ""),
                        "not_found": data.get("not_found", False),
                        "latency_ms": data.get("latency_ms", 0),
                        "created_at": data.get("created_at", ""),
                    })
            logs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return logs[:limit]

    def get_dashboard_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Aggregate dashboard statistics for a tenant."""
        with self._lock.read_lock():
            total_queries = 0
            not_found_count = 0
            total_latency = 0.0
            latency_by_vertical: Dict[str, List[float]] = {}
            unanswered: Dict[str, int] = {}

            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "QueryLog"
                        and data.get("tenant_id") == tenant_id):
                    total_queries += 1
                    lat = data.get("latency_ms", 0)
                    total_latency += lat

                    vert = data.get("vertical", "unknown")
                    latency_by_vertical.setdefault(vert, []).append(lat)

                    if data.get("not_found"):
                        not_found_count += 1
                        q = data.get("query", "")
                        unanswered[q] = unanswered.get(q, 0) + 1

            # Document + chunk counts
            doc_count = 0
            chunk_count = 0
            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "Document"
                        and data.get("tenant_id") == tenant_id
                        and not data.get("superseded", False)):
                    doc_count += 1
                elif (data.get("label") == "Chunk"
                      and data.get("tenant_id") == tenant_id
                      and not data.get("superseded", False)):
                    chunk_count += 1

            nf_rate = round(not_found_count / total_queries * 100, 1) if total_queries else 0.0
            avg_lat = round(total_latency / total_queries, 1) if total_queries else 0.0

            top_unanswered = sorted(
                [{"query": q, "times_asked": c} for q, c in unanswered.items()],
                key=lambda x: x["times_asked"],
                reverse=True,
            )[:10]

            lat_by_vert = [
                {"vertical": v, "avg_ms": round(sum(lats) / len(lats), 1)}
                for v, lats in sorted(
                    latency_by_vertical.items(),
                    key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
                    reverse=True,
                )
            ]

            return {
                "tenant_id": tenant_id,
                "total_queries": total_queries,
                "not_found_count": not_found_count,
                "not_found_rate_pct": nf_rate,
                "avg_latency_ms": avg_lat,
                "document_count": doc_count,
                "chunk_count": chunk_count,
                "top_unanswered": top_unanswered,
                "latency_by_vertical": lat_by_vert,
            }

    # ─── RedFlag Reports ──────────────────────────────────────────────────────

    def upsert_redflag_report(
        self,
        doc_id: str,
        tenant_id: str,
        risk_level: str,
        flag_count: int,
        summary: str,
        report_json: str,
    ) -> None:
        """Create or update a RedFlagReport node linked to a Document."""
        with self._lock.write_lock():
            report_nid = f"redflag:{doc_id}"
            doc_nid = f"doc:{doc_id}"

            self._graph.add_node(report_nid,
                label="RedFlagReport",
                doc_id=doc_id,
                tenant_id=tenant_id,
                risk_level=risk_level,
                flag_count=flag_count,
                summary=summary,
                report_json=report_json,
                updated_at=self._now(),
            )

            if self._graph.has_node(doc_nid):
                if self._graph.has_edge(doc_nid, report_nid):
                    self._graph.remove_edge(doc_nid, report_nid)
                self._graph.add_edge(doc_nid, report_nid, type="HAS_REPORT")

            self._save()

    def get_redflag_report(
        self, doc_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a stored red-flag report."""
        with self._lock.read_lock():
            report_nid = f"redflag:{doc_id}"
            if not self._graph.has_node(report_nid):
                return None
            data = self._graph.nodes[report_nid]
            rj = data.get("report_json")
            if rj:
                try:
                    return json.loads(rj)
                except json.JSONDecodeError:
                     return None
            return None

    # ─── Compliance Alerts ────────────────────────────────────────────────────

    def store_compliance_alert(
        self,
        alert_id: str,
        tenant_id: str,
        doc_id: str,
        change_count: int,
        severity: str,
        report_json: str,
    ) -> None:
        """Store a compliance monitoring alert."""
        with self._lock.write_lock():
            alert_nid = f"alert:{alert_id}"
            tenant_nid = f"tenant:{tenant_id}"
            doc_nid = f"doc:{doc_id}"

            self._graph.add_node(alert_nid,
                label="ComplianceAlert",
                id=alert_id,
                tenant_id=tenant_id,
                new_doc_id=doc_id,
                change_count=change_count,
                severity=severity,
                report_json=report_json,
                created_at=self._now(),
            )

            if self._graph.has_node(tenant_nid):
                self._graph.add_edge(tenant_nid, alert_nid, type="HAS_ALERT")
            if self._graph.has_node(doc_nid):
                self._graph.add_edge(doc_nid, alert_nid, type="TRIGGERED_ALERT")

            self._save()

    def get_compliance_alerts(
        self, tenant_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent compliance alerts for a tenant."""
        with self._lock.read_lock():
            alerts = []
            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "ComplianceAlert"
                        and data.get("tenant_id") == tenant_id):
                    row = {
                        "id": data.get("id", ""),
                        "new_doc_id": data.get("new_doc_id", ""),
                        "change_count": data.get("change_count", 0),
                        "severity": data.get("severity", "LOW"),
                        "created_at": data.get("created_at", ""),
                    }
                    try:
                        row["report"] = json.loads(data.get("report_json", "{}"))
                    except json.JSONDecodeError:
                        row["report"] = {}
                    alerts.append(row)

            alerts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return alerts[:limit]

    # ─── User Feedback (Active Learning) ──────────────────────────────────────

    def store_feedback(
        self,
        tenant_id: str,
        vertical: str,
        query: str,
        answer: str,
        rating: str,
        comment: str = "",
        chunk_ids: Optional[List[str]] = None,
    ) -> str:
        """Store user feedback on a query/answer pair."""
        with self._lock.write_lock():
            feedback_id = str(uuid.uuid4())
            fb_nid = f"feedback:{feedback_id}"
            tenant_nid = f"tenant:{tenant_id}"

            self._graph.add_node(fb_nid,
                label="Feedback",
                id=feedback_id,
                tenant_id=tenant_id,
                vertical=vertical,
                query=query,
                answer=answer,
                rating=rating,
                comment=comment,
                chunk_ids=chunk_ids or [],
                created_at=self._now(),
            )

            if self._graph.has_node(tenant_nid):
                self._graph.add_edge(tenant_nid, fb_nid, type="HAS_FEEDBACK")

            self._save()
            return feedback_id

    def get_feedback_stats(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Per-vertical feedback counts."""
        with self._lock.read_lock():
            stats: Dict[str, Dict[str, int]] = {}
            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "Feedback"
                        and data.get("tenant_id") == tenant_id):
                    vert = data.get("vertical", "unknown")
                    if vert not in stats:
                        stats[vert] = {"total": 0, "positive": 0, "negative": 0}
                    stats[vert]["total"] += 1
                    rating = data.get("rating", "")
                    if rating == "positive":
                        stats[vert]["positive"] += 1
                    elif rating == "negative":
                        stats[vert]["negative"] += 1

            return [
                {"vertical": v, **counts}
                for v, counts in sorted(stats.items(), key=lambda x: x[1]["total"], reverse=True)
            ]

    # ─── Knowledge Graph Visualization ────────────────────────────────────────

    _COLOR_MAP = {
        "hr":         "#4dabf7",
        "law":        "#f06595",
        "compliance": "#63e6be",
        "startup":    "#ffd43b",
        "university": "#da77f2",
    }

    def get_knowledge_graph(self, tenant_id: str) -> Dict[str, Any]:
        """Build ForceGraph2D nodes and links payload."""
        with self._lock.read_lock():
            nodes = []
            links = []
            seen_nodes: Set[str] = set()

            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "Document"
                        and data.get("tenant_id") == tenant_id
                        and not data.get("superseded", False)):

                    doc_id = data.get("id")
                    doc_name = data.get("name", "Untitled")
                    vertical = data.get("vertical", "hr")

                    if doc_id and doc_id not in seen_nodes:
                        seen_nodes.add(doc_id)
                        nodes.append({
                            "id": doc_id,
                            "name": doc_name,
                            "type": "document",
                            "color": self._COLOR_MAP.get(vertical, "#4dabf7"),
                            "val": 8,
                        })

                    for _, chunk_nid, edata in self._graph.out_edges(nid, data=True):
                        if edata.get("type") != "HAS_CHUNK":
                            continue
                        for _, ent_nid, edata2 in self._graph.out_edges(chunk_nid, data=True):
                            if edata2.get("type") != "MENTIONS":
                                continue
                            ent_data = self._graph.nodes.get(ent_nid, {})
                            ent_name = ent_data.get("canonical_name", "?")
                            ent_key = f"ent:{ent_name}"

                            if ent_key not in seen_nodes:
                                seen_nodes.add(ent_key)
                                nodes.append({
                                    "id": ent_key,
                                    "name": ent_name,
                                    "type": "entity",
                                    "color": "#ff922b",
                                    "val": 4,
                                })
                            if doc_id:
                                links.append({"source": doc_id, "target": ent_key})

            return {"nodes": nodes, "links": links}

    # ─── Existing Compliance Chunks ───────────────────────────────────────────

    def get_existing_compliance_chunks(
        self, tenant_id: str, exclude_doc_id: str, limit: int = 300
    ) -> List[Dict[str, Any]]:
        """Get chunks from existing non-superseded compliance documents."""
        with self._lock.read_lock():
            results = []
            for nid, data in self._graph.nodes(data=True):
                if (data.get("label") == "Document"
                        and data.get("tenant_id") == tenant_id
                        and data.get("vertical") == "compliance"
                        and not data.get("superseded", False)
                        and data.get("id") != exclude_doc_id):

                    doc_name = data.get("name", "")
                    for _, chunk_nid, edata in self._graph.out_edges(nid, data=True):
                        if edata.get("type") != "HAS_CHUNK":
                            continue
                        cdata = self._graph.nodes.get(chunk_nid, {})
                        results.append({
                            "doc_name": doc_name,
                            "doc_id": data.get("id"),
                            "text": cdata.get("text", ""),
                            "article_ref": cdata.get("article_ref"),
                        })
                        if len(results) >= limit:
                            return results
            return results

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Serialize graph to JSON and queue background write to disk."""
        try:
            with self._lock.read_lock():
                nodes = {}
                for nid, data in self._graph.nodes(data=True):
                    node_data = {}
                    for k, v in data.items():
                        if isinstance(v, (list, dict, str, int, float, bool, type(None))):
                            node_data[k] = v
                        else:
                            node_data[k] = str(v)
                    nodes[nid] = node_data

                edges = []
                for src, dst, data in self._graph.edges(data=True):
                    edges.append({"src": src, "dst": dst, "data": dict(data)})

                embeddings = {
                    cid: vec.tolist()
                    for cid, vec in self._embedding_cache.items()
                }

                payload = {
                    "nodes": nodes,
                    "edges": edges,
                    "embeddings": embeddings,
                    "saved_at": self._now(),
                }

            threading.Thread(target=self._write_file, args=(payload,), daemon=True).start()

        except Exception as exc:
            logger.error("GraphStore save serialization failed: %s", exc)

    def _write_file(self, payload: dict) -> None:
        """Atomic write execution running on a background worker thread."""
        try:
            tmp_path = self._filepath.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            tmp_path.replace(self._filepath)
        except Exception as exc:
            logger.error("GraphStore background disk write failed: %s", exc)

    def _load(self) -> None:
        """Load graph from JSON file on disk."""
        if not self._filepath.exists():
            logger.info("No existing graph store found. Starting fresh.")
            return

        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)

            # Reconstruct nodes
            for nid, data in payload.get("nodes", {}).items():
                self._graph.add_node(nid, **data)

            # Reconstruct edges
            for edge in payload.get("edges", []):
                self._graph.add_edge(edge["src"], edge["dst"], **edge.get("data", {}))

            # Reconstruct embedding cache
            for cid, vec_list in payload.get("embeddings", {}).items():
                self._embedding_cache[cid] = np.array(vec_list, dtype=np.float32)

            # Build indices after load
            self._rebuild_indices()

            logger.info("GraphStore loaded: %d nodes, %d edges, %d embeddings",
                        self._graph.number_of_nodes(),
                        self._graph.number_of_edges(),
                        len(self._embedding_cache))

        except Exception as exc:
            logger.error("GraphStore load failed: %s. Starting fresh.", exc)
            self._graph = nx.DiGraph()
            self._embedding_cache = {}

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _chunk_to_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": data.get("id"),
            "text": data.get("text", ""),
            "page": data.get("page"),
            "doc_id": data.get("doc_id"),
            "doc_name": data.get("doc_name"),
            "chunk_type": data.get("chunk_type"),
            "clause_ref": data.get("clause_ref"),
            "article_ref": data.get("article_ref"),
            "section": data.get("section"),
            "employee_type": data.get("employee_type"),
            "defined_term": data.get("defined_term"),
            "superseded": data.get("superseded", False),
        }

    def verify_connectivity(self) -> bool:
        """Health check — always True for in-process store."""
        return True
