"""RSS memory probe for scheduled jobs + request handlers.

Brock 2026-08-13: container OOMs at ~12min after deploy with no traceback.
Suspected memory leak in a scheduled job. This module wraps job/request
execution with resident-set-size (RSS) sampling and aggregates deltas
per job so we can identify which one grows RSS monotonically.

Read the tally via GET /admin/mem-probe/snapshot after 24h uptime.
The job with consistently positive avg_delta_mb is the leak.
"""
from __future__ import annotations

import logging
import os
import threading
from collections import defaultdict
from typing import Any, Callable, Dict

logger = logging.getLogger("mem_probe")

try:
    import psutil
    _PROC = psutil.Process(os.getpid())

    def _rss_mb() -> float:
        try:
            return _PROC.memory_info().rss / (1024 * 1024)
        except Exception:
            return -1.0
except Exception:
    def _rss_mb() -> float:
        return -1.0


# tally[key] = [count, sum_delta_mb, max_delta_mb, last_after_mb]
_tally: Dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
_lock = threading.Lock()

# Threshold above which we emit a WARN log (in MB).
_WARN_DELTA_MB = float(os.getenv("MEM_PROBE_WARN_DELTA_MB", "5.0"))


def probe_job(job_name: str, fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Wrap a callable with RSS probe. Records delta into tally.

    Returns fn's return value; propagates exceptions. Never raises from
    the probe itself.
    """
    before = _rss_mb()
    try:
        return fn(*args, **kwargs)
    finally:
        after = _rss_mb()
        delta = after - before if before >= 0 and after >= 0 else 0.0
        try:
            with _lock:
                row = _tally[job_name]
                row[0] += 1
                row[1] += delta
                row[2] = max(row[2], delta)
                row[3] = after
            if delta >= _WARN_DELTA_MB:
                logger.warning(
                    "[mem-probe] %s +%.1fMB rss=%.0fMB", job_name, delta, after
                )
        except Exception:
            pass


def snapshot() -> Dict[str, Any]:
    """Return per-job RSS tally + process totals."""
    with _lock:
        per_job = {
            job: {
                "runs": row[0],
                "avg_delta_mb": round(row[1] / max(1, row[0]), 3),
                "max_delta_mb": round(row[2], 3),
                "cumulative_delta_mb": round(row[1], 3),
                "last_after_mb": round(row[3], 1),
            }
            for job, row in _tally.items()
        }
    top_leakers = sorted(
        per_job.items(),
        key=lambda kv: kv[1]["cumulative_delta_mb"],
        reverse=True,
    )[:10]
    return {
        "process_rss_mb": round(_rss_mb(), 1),
        "tally": per_job,
        "top_leakers_cumulative": [{"job": k, **v} for k, v in top_leakers],
    }


def apscheduler_job_count() -> int:
    """Live APScheduler job count. Returns -1 on error."""
    try:
        from app.main import scheduler  # type: ignore
        return len(scheduler.get_jobs())
    except Exception:
        return -1
