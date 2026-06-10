"""
Observability helpers: structured JSON logging, Prometheus-style metrics,
and the /api/sentinel/stats query used by the dashboard.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# ── Structured logging ────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record — Railway friendly."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Attach any extra fields passed via extra={}
        for key, val in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
                "exc_info", "exc_text",
            ):
                payload[key] = val
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


# ── In-process metrics counter ────────────────────────────────────────────────

class Metrics:
    """Lightweight in-memory counters; exported as Prometheus text format."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._start = time.time()

    # --- mutation helpers ---

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        key = self._key(name, labels)
        self._counters[key] = self._counters.get(key, 0.0) + amount

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = self._key(name, labels)
        self._gauges[key] = value

    # --- export ---

    def prometheus_text(self) -> str:
        lines: list[str] = []
        lines.append(f"# sentinel process uptime\nsentinel_uptime_seconds {time.time() - self._start:.1f}")
        for key, val in self._counters.items():
            lines.append(f"sentinel_{key}_total {val}")
        for key, val in self._gauges.items():
            lines.append(f"sentinel_{key} {val}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _key(name: str, labels: dict[str, str]) -> str:
        if not labels:
            return name
        lbl = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{lbl}}}"


# Singleton
metrics = Metrics()


# ── Stats query used by the /admin/sentinel dashboard ────────────────────────

def get_sentinel_stats(db: Session, daily_cap_usd: float, daily_pr_cap: int) -> dict:
    today_cost = db.execute(text("""
        SELECT COALESCE(SUM(llm_cost_usd), 0)
        FROM agent_fixes
        WHERE created_at >= CURRENT_DATE
    """)).scalar() or 0.0

    today_prs = db.execute(text("""
        SELECT COUNT(*) FROM agent_fixes
        WHERE created_at >= CURRENT_DATE
          AND outcome IN ('pr_opened', 'merged')
    """)).scalar() or 0

    open_events = db.execute(text("""
        SELECT COUNT(*) FROM agent_events WHERE status = 'open'
    """)).scalar() or 0

    # 7-day resolution rate = resolved / (resolved + open + escalated)
    resolved_7d = db.execute(text("""
        SELECT COUNT(*) FROM agent_events
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND status = 'resolved'
    """)).scalar() or 0

    total_7d = db.execute(text("""
        SELECT COUNT(*) FROM agent_events
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """)).scalar() or 0

    resolution_rate = (resolved_7d / total_7d) if total_7d > 0 else 1.0

    # Push live values into metrics
    metrics.set_gauge("today_cost_usd", float(today_cost))
    metrics.set_gauge("today_pr_count", int(today_prs))
    metrics.set_gauge("open_events", int(open_events))
    metrics.set_gauge("resolution_rate_7d", float(resolution_rate))

    return {
        "today_cost_usd": float(today_cost),
        "daily_cap_usd": daily_cap_usd,
        "today_pr_count": int(today_prs),
        "daily_pr_cap": daily_pr_cap,
        "open_events": int(open_events),
        "resolution_rate_7d": float(resolution_rate),
    }
