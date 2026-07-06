"""
Async Job Queue — background task management for long-running ingestion.

Uploading a 200-page PDF takes 30–90 seconds. The API must return immediately
with a job_id and process ingestion in the background.

Architecture:
    - Jobs are tracked in an in-memory dict (fast, simple)
    - Redis is used as the persistent store when available (survives restarts)
    - Job status: pending → running → completed | failed

Usage (in route handler):
    job_id = await job_queue.submit(ingest_task, doc_id=doc_id, ...)
    # Returns immediately — client polls /jobs/{job_id}

    status = job_queue.get_status(job_id)
    # Returns: {status, result, error, created_at, completed_at}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger("docqa.jobs")

# ── Job status constants ──────────────────────────────────────────────────────
PENDING   = "pending"
RUNNING   = "running"
COMPLETED = "completed"
FAILED    = "failed"

_REDIS_TTL = 3600 * 6   # keep job records for 6 hours


class JobQueue:
    """
    In-memory + Redis-backed async job queue.
    Thread-safe for concurrent FastAPI workers.
    """

    def __init__(self, redis_client: Optional[Any] = None):
        self._redis   = redis_client
        self._local:  Dict[str, Dict[str, Any]] = {}   # local fallback

    # ── Submit ────────────────────────────────────────────────────────────────

    async def submit(
        self,
        coro_fn:  Callable[..., Coroutine],
        **kwargs: Any,
    ) -> str:
        """
        Submit a coroutine for background execution.
        Returns a job_id immediately without waiting for completion.

        Args:
            coro_fn:  Async function to run (e.g. ingest_document).
            **kwargs: Arguments forwarded to coro_fn.
        """
        job_id = str(uuid.uuid4())
        self._set_status(job_id, {
            "status":       PENDING,
            "result":       None,
            "error":        None,
            "created_at":   time.time(),
            "completed_at": None,
        })

        # Fire and forget — asyncio.create_task schedules background execution
        asyncio.create_task(self._run(job_id, coro_fn, kwargs))
        logger.info("Job submitted: %s", job_id)
        return job_id

    async def _run(self, job_id: str, coro_fn: Callable, kwargs: Dict) -> None:
        """Execute the job coroutine and update its status."""
        self._set_status(job_id, {"status": RUNNING})
        try:
            result = await coro_fn(**kwargs)
            self._set_status(job_id, {
                "status":       COMPLETED,
                "result":       result,
                "completed_at": time.time(),
            })
            logger.info("Job completed: %s → %s", job_id, result)
        except Exception as exc:
            self._set_status(job_id, {
                "status":       FAILED,
                "error":        str(exc),
                "completed_at": time.time(),
            })
            logger.error("Job failed: %s — %s", job_id, exc)

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return current job status dict, or None if job not found."""
        # Try Redis first
        if self._redis:
            try:
                raw = self._redis.get(f"job:{job_id}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        # Fall back to local dict
        return self._local.get(job_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_status(self, job_id: str, updates: Dict[str, Any]) -> None:
        """Merge updates into the existing job record."""
        current = self._local.get(job_id, {})
        current.update(updates)
        self._local[job_id] = current

        if self._redis:
            try:
                self._redis.setex(f"job:{job_id}", _REDIS_TTL, json.dumps(current))
            except Exception:
                pass   # Redis unavailable — in-memory is the fallback


# ── Module-level singleton (initialised in main.py lifespan) ──────────────────
# Access via: request.app.state.job_queue

def create_job_queue(redis_client: Optional[Any] = None) -> JobQueue:
    """Factory — call once in lifespan and store on app.state."""
    return JobQueue(redis_client=redis_client)
