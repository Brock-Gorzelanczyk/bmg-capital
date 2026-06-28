"""capital_audit_log — instrumentation for every bot_allocations capital write.

Two layers:
  1. SQLAlchemy `before_update` event listener on BotAllocation catches every
     ORM-level capital field change and writes a row to capital_audit_log.
  2. ensure_capital_audit_table() called at app startup creates the table if
     it doesn't exist.

Raw-SQL writes via `text("UPDATE bot_allocations ...")` are NOT caught by
the ORM listener (by design — only m024/m025/m026/m027 use raw SQL, and
they write their own audit rows). Any new runtime code path that wants to
touch capital MUST go through the ORM session so it's logged.

The acceptance test for "auto-grow source is dead" is: capital_audit_log
shows zero rows for 60 minutes after m027 runs, except the m027_pre_reset
and m027_post_reset rows that m027 writes explicitly.
"""
from __future__ import annotations

import inspect
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS capital_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id INTEGER,
    allocation_id INTEGER,
    bot_name TEXT,
    field TEXT NOT NULL,
    old_value INTEGER,
    new_value INTEGER,
    delta_cents INTEGER,
    source TEXT,
    note TEXT
)
"""

_AUDIT_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_capital_audit_ts ON capital_audit_log (ts)
"""


def ensure_capital_audit_table(conn) -> None:
    """Idempotent table create. Safe to call on every boot."""
    conn.execute(text(_AUDIT_DDL))
    conn.execute(text(_AUDIT_INDEX_DDL))
    conn.commit()


_TRACKED_FIELDS = ("starting_capital_cents", "current_capital_cents",
                   "inception_capital_cents", "capital_cents_within_portfolio")


def _callsite_label(skip_frames: int = 3) -> str:
    """Walk the stack looking for the first frame OUTSIDE this file and
    SQLAlchemy. Returns 'module:function' for the audit source column.
    """
    try:
        frame = inspect.currentframe()
        # Walk up
        for _ in range(skip_frames):
            if frame is None:
                return "unknown"
            frame = frame.f_back
        while frame is not None:
            fn = frame.f_code.co_filename
            if "/sqlalchemy/" in fn or fn.endswith("/capital_audit.py"):
                frame = frame.f_back
                continue
            mod = os.path.basename(fn).replace(".py", "")
            return f"{mod}:{frame.f_code.co_name}:L{frame.f_lineno}"
    except Exception:
        pass
    return "unknown"


def register_capital_audit_listener() -> None:
    """Register a SQLAlchemy before_update event for BotAllocation.

    Captures any ORM write to a tracked capital field, logs old/new/delta
    plus the originating callsite into capital_audit_log.
    """
    try:
        from app.db.models.bots import BotAllocation
        from app.db.session import SessionLocal
    except Exception as exc:
        logger.warning("[capital_audit] cannot register listener: %s", exc)
        return

    @event.listens_for(BotAllocation, "before_update")
    def _capture(mapper, connection, target):
        from sqlalchemy import inspect as sa_inspect
        state = sa_inspect(target)
        rows_to_insert: list[dict] = []
        ts = datetime.now(timezone.utc).isoformat()
        source = _callsite_label(skip_frames=2)
        for field in _TRACKED_FIELDS:
            if field not in state.attrs:
                continue
            hist = state.attrs[field].history
            if not hist.has_changes():
                continue
            old_val = hist.deleted[0] if hist.deleted else None
            new_val = hist.added[0] if hist.added else None
            try:
                old_int = int(old_val) if old_val is not None else None
            except Exception:
                old_int = None
            try:
                new_int = int(new_val) if new_val is not None else None
            except Exception:
                new_int = None
            delta = (new_int or 0) - (old_int or 0) if old_int is not None and new_int is not None else None
            rows_to_insert.append({
                "ts": ts,
                "user_id": getattr(target, "user_id", None),
                "allocation_id": getattr(target, "id", None),
                "bot_name": None,
                "field": field,
                "old_value": old_int,
                "new_value": new_int,
                "delta_cents": delta,
                "source": source,
                "note": "orm_update",
            })
        if not rows_to_insert:
            return
        try:
            for row in rows_to_insert:
                connection.execute(text("""
                    INSERT INTO capital_audit_log
                        (ts, user_id, allocation_id, bot_name, field,
                         old_value, new_value, delta_cents, source, note)
                    VALUES
                        (:ts, :user_id, :allocation_id, :bot_name, :field,
                         :old_value, :new_value, :delta_cents, :source, :note)
                """), row)
        except Exception as exc:
            logger.warning("[capital_audit] insert failed: %s", exc)

    logger.info("[capital_audit] before_update listener registered for BotAllocation")


def write_manual_audit(conn, user_id: int, allocation_id: int, bot_name: str,
                       field: str, old_value: Optional[int], new_value: Optional[int],
                       source: str, note: str) -> None:
    """Used by migrations + the m027 pre/post snapshot to record explicit audit rows."""
    delta = (new_value or 0) - (old_value or 0) if old_value is not None and new_value is not None else None
    conn.execute(text("""
        INSERT INTO capital_audit_log
            (ts, user_id, allocation_id, bot_name, field,
             old_value, new_value, delta_cents, source, note)
        VALUES (:ts, :uid, :aid, :bn, :f, :ov, :nv, :d, :s, :note)
    """), {
        "ts": datetime.now(timezone.utc).isoformat(),
        "uid": user_id,
        "aid": allocation_id,
        "bn": bot_name,
        "f": field,
        "ov": old_value,
        "nv": new_value,
        "d": delta,
        "s": source,
        "note": note,
    })
