"""
Observability — per-query tracing and timeout wrapper.

PipelineTrace:
    Tracks timing of each pipeline stage (retrieval, rerank, generation).
    Attached to every query response as `_trace` for debugging and monitoring.

with_timeout:
    Wraps any coroutine with a configurable timeout.
    Raises TimeoutError with a descriptive message on expiry.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict

logger = logging.getLogger("docqa.observability")


# ─── Pipeline Trace ──────────────────────────────────────────────────────────

class PipelineTrace:
    """
    Lightweight per-query telemetry container.
    Records wall-clock timing (ms) for each pipeline stage.

    Usage:
        trace = PipelineTrace(tenant_id="t1", vertical="law", query_hash="abc123")
        t0 = asyncio.get_running_loop().time()
        # ... do retrieval ...
        trace.record("retrieval_ms", (asyncio.get_running_loop().time() - t0) * 1000)
        trace.add_meta("chunks_retrieved", 12)
        trace.log_summary()
    """

    def __init__(self, tenant_id: str, vertical: str, query_hash: str):
        self.tenant_id   = tenant_id
        self.vertical    = vertical
        self.query_hash  = query_hash
        self.timings:  Dict[str, float] = {}
        self.metadata: Dict[str, Any]   = {}
        self._wall_start = time.perf_counter()

    def record(self, stage: str, duration_ms: float) -> None:
        """Record the duration of a named pipeline stage in milliseconds."""
        self.timings[stage] = round(duration_ms, 2)

    def add_meta(self, key: str, value: Any) -> None:
        """Attach arbitrary metadata (chunk counts, flags, etc.)."""
        self.metadata[key] = value

    def total_ms(self) -> float:
        """Wall-clock time since trace was created."""
        return round((time.perf_counter() - self._wall_start) * 1000, 2)

    def log_summary(self) -> None:
        """Emit a single INFO log line summarising the full query trace."""
        stage_str = " | ".join(f"{k}={v}ms" for k, v in self.timings.items())
        meta_str  = " | ".join(f"{k}={v}" for k, v in self.metadata.items())
        logger.info(
            "[%s/%s] query=%s | total=%sms | %s | %s",
            self.vertical,
            self.tenant_id,
            self.query_hash,
            self.total_ms(),
            stage_str,
            meta_str,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON embedding in API response."""
        return {
            "query_hash": self.query_hash,
            "vertical":   self.vertical,
            "total_ms":   self.total_ms(),
            "stages":     self.timings,
            "meta":       self.metadata,
        }


# ─── Timeout Wrapper ─────────────────────────────────────────────────────────

async def with_timeout(coro: Any, timeout_s: float, stage: str) -> Any:
    """
    Awaits a coroutine with a hard timeout.

    Args:
        coro:      The coroutine to await.
        timeout_s: Seconds before raising asyncio.TimeoutError.
        stage:     Human-readable stage name for error messages.

    Raises:
        asyncio.TimeoutError: if the coroutine exceeds timeout_s.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.error("Stage '%s' timed out after %.1fs", stage, timeout_s)
        raise asyncio.TimeoutError(
            f"Pipeline stage '{stage}' exceeded {timeout_s}s timeout."
        )
