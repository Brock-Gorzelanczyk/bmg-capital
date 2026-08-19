"""alpaca_activity_ledger — persisted record of every Alpaca-initiated action.

Ledger #28 (Brock exposure #3): I25 invariant already catches Alpaca FILL
activities that don't have a matching BMG bot_trade. But non-FILL activities
(DIV, INT, ACATC, CFEE, MA, JNL, FEE, etc.) are broker-initiated events that
BMG doesn't submit but that DO affect the account — dividends credited,
margin interest charged, ACATS transfers, corporate actions.

This module:
  1. Creates alpaca_activity_ledger table (id, activity_type, activity_id,
     ts, symbol, qty, price, net_amount, description, raw_json).
  2. Provides write_activity() — called from the I25 loop for non-FILL types.
  3. Provides list_activities() — read for /admin/alpaca-activity-ledger.

Called from startup migration (like human_ack). Idempotent.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


# Activity types Alpaca reports beyond FILL — these are broker-initiated.
# https://alpaca.markets/docs/api-references/trading-api/account-activities/
NON_FILL_ACTIVITY_TYPES: tuple[str, ...] = (
    "DIV", "DIVCGL", "DIVCGS", "DIVFEE", "DIVFT", "DIVNRA",
    "DIVROC", "DIVTXEX", "DIVTW", "INT", "INTNRA", "INTTW",
    "ACATC", "ACATS", "CFEE", "FEE", "MA", "JNLC", "JNLS",
    "MISC", "PTC", "PTR", "REORG", "SPIN", "SPLIT", "SC",
    "SSO", "SSP", "SUB", "SBLOC", "COUP", "PC", "PM",
    "OPASN", "OPEXP", "OPXRC",
)


def ensure_table(conn) -> None:
    """Idempotent — creates table if missing. Called from startup migration."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alpaca_activity_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_type TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            symbol TEXT,
            qty REAL,
            price REAL,
            net_amount REAL,
            description TEXT,
            raw_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            UNIQUE(activity_type, activity_id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_alpaca_activity_type_ts "
        "ON alpaca_activity_ledger(activity_type, ts DESC)"
    ))


def write_activity(db, activity: dict[str, Any]) -> bool:
    """Insert an activity if not already present. Returns True if new."""
    a_type = activity.get("activity_type")
    a_id = activity.get("id") or activity.get("activity_id") or ""
    if not a_type or not a_id:
        return False
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Extract common fields — different types have different shapes.
        def _f(k):
            v = activity.get(k)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None
        db.execute(text("""
            INSERT OR IGNORE INTO alpaca_activity_ledger
                (activity_type, activity_id, ts, symbol, qty, price,
                 net_amount, description, raw_json, recorded_at)
            VALUES
                (:t, :i, :ts, :s, :q, :p, :n, :d, :r, :rec)
        """), {
            "t": a_type,
            "i": str(a_id),
            "ts": activity.get("date") or activity.get("transaction_time") or now_iso,
            "s": activity.get("symbol"),
            "q": _f("qty"),
            "p": _f("price"),
            "n": _f("net_amount"),
            "d": (activity.get("description") or "")[:500],
            "r": json.dumps(activity)[:4000],
            "rec": now_iso,
        })
        db.commit()
        return True
    except Exception as exc:
        logger.warning("[alpaca_activity_ledger] write failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def list_activities(
    db,
    activity_type: Optional[str] = None,
    since_hours: int = 168,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read recent entries. Default = last 7 days, 100 rows."""
    sql = (
        "SELECT id, activity_type, activity_id, ts, symbol, qty, price, "
        "net_amount, description, recorded_at "
        "FROM alpaca_activity_ledger "
        "WHERE ts >= datetime('now', :hours)"
    )
    params: dict[str, Any] = {"hours": f"-{int(since_hours)} hours"}
    if activity_type:
        sql += " AND activity_type = :t"
        params["t"] = activity_type
    sql += " ORDER BY ts DESC LIMIT :n"
    params["n"] = int(limit)
    try:
        rows = db.execute(text(sql), params).fetchall()
        return [
            {
                "id": r[0], "activity_type": r[1], "activity_id": r[2],
                "ts": r[3], "symbol": r[4], "qty": r[5], "price": r[6],
                "net_amount": r[7], "description": r[8], "recorded_at": r[9],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[alpaca_activity_ledger] list failed: %s", exc)
        return []


def counts_by_type(db, since_hours: int = 168) -> dict[str, int]:
    """Aggregate — activity_type → count within window."""
    try:
        rows = db.execute(text(
            "SELECT activity_type, COUNT(*) FROM alpaca_activity_ledger "
            "WHERE ts >= datetime('now', :h) GROUP BY 1 ORDER BY 2 DESC"
        ), {"h": f"-{int(since_hours)} hours"}).fetchall()
        return {r[0]: int(r[1]) for r in rows}
    except Exception:
        return {}
