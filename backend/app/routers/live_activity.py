"""Live bot-activity feed for the Trading Desk UI.

Returns recent signals + trades + a session summary since a client-supplied
watermark, so the frontend can drive its cinematic animations from real
data instead of scripted price walks. Designed for polling (frontend hits
this every 5-10s) — deliberately lightweight so it can be called cheaply.

Route: GET /api/live/bot-activity?since_signal_id=N&since_trade_id=M

Response shape:
    {
        "as_of": "2026-06-30T22:00:00Z",
        "signals": [
            {
                "id": 12345,
                "bot_id": "stock_day",
                "bot_display_name": "Stock Day",
                "symbol": "AMD",
                "side": "buy",
                "confidence": 0.72,
                "strategy": "momentum_breakout",
                "ts": "2026-06-30T21:58:11Z"
            },
            ...
        ],
        "trades": [
            {
                "id": 67890,
                "bot_id": "crypto_quant_aggressive",
                "bot_display_name": "Quant Aggressive",
                "symbol": "BTC/USD",
                "side": "buy",
                "qty": 0.01,
                "fill_price_usd": 64123.45,
                "ts": "2026-06-30T21:59:03Z"
            },
            ...
        ],
        "summary": {
            "active_bot_count": 11,
            "signals_last_hour": 47,
            "trades_last_hour": 5,
            "session_pnl_usd": 208.42
        }
    }

Design constraints:
- No unbounded queries — hard limit of 50 signals + 20 trades per response.
- since_* watermarks are integer bot_signals.id / bot_trades.id — client
  starts at 0 for first call and updates from the max id it observes.
- Never fails hard — errors return {"signals": [], "trades": [], ...}
  so the Trading Desk falls back gracefully to its scripted animations.
- Cached at the router level for 3 seconds to absorb burst polling
  (multiple tabs open) without hammering the DB.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.canonical import DISPLAY_NAMES
from app.db.models.users import User
from app.dependencies import get_current_user, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

MAX_SIGNALS_PER_CALL = 50
MAX_TRADES_PER_CALL = 20
CACHE_TTL_SECONDS = 3


def _display(bot_id: str) -> str:
    """Human-friendly display name for a bot_id."""
    return DISPLAY_NAMES.get(bot_id) or bot_id.replace("_", " ").title()


# ── Per-request cache to absorb burst polling ────────────────────────────────
# Keyed by (user_id, since_signal_id, since_trade_id). 3-second TTL is short
# enough that stale data isn't visible but long enough that if 3 tabs poll
# simultaneously, only one hits the DB.
_cache: dict = {}


def _cache_get(key: tuple) -> dict | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if (time.monotonic() - ts) > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: tuple, value: dict) -> None:
    _cache[key] = (time.monotonic(), value)
    # Bound the cache — never let it grow beyond ~200 entries.
    if len(_cache) > 200:
        # Drop oldest half; simplest bounded eviction.
        pairs = sorted(_cache.items(), key=lambda kv: kv[1][0])
        for k, _ in pairs[:100]:
            _cache.pop(k, None)


@router.get("/bot-activity")
def get_bot_activity(
    since_signal_id: int = Query(0, ge=0),
    since_trade_id: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return signals + trades + session summary since the client's last watermark."""
    cache_key = (current_user.id, since_signal_id, since_trade_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    result: dict = {
        "as_of": now.isoformat(),
        "signals": [],
        "trades": [],
        "summary": {
            "active_bot_count": 0,
            "signals_last_hour": 0,
            "trades_last_hour": 0,
            "session_pnl_usd": 0.0,
        },
    }

    try:
        # ── Signals since watermark, scoped to current user's allocations ──
        # Cold-start (since=0): return the MOST RECENT N ordered DESC then
        # reversed so client's watermark advances to the true tail. Otherwise
        # the poller would churn through weeks of historical signals before
        # reaching real-time — first observed 2026-06-30 evening: cold client
        # got signals #1-50 all from 2026-06-08 test rows.
        # Warm poll (since>0): return anything newer, ascending, capped.
        if since_signal_id == 0:
            signal_rows = db.execute(
                text(
                    "SELECT * FROM ("
                    "  SELECT s.id, s.ts, s.symbol, s.side, s.confidence, s.strategy, "
                    "         bp.name AS bot_id "
                    "  FROM bot_signals s "
                    "  JOIN bot_allocations a ON a.id = s.allocation_id "
                    "  JOIN bot_profiles bp ON bp.id = a.profile_id "
                    "  WHERE a.user_id = :uid "
                    "  ORDER BY s.id DESC LIMIT :lim"
                    ") AS recent ORDER BY id ASC"
                ),
                {"uid": current_user.id, "lim": MAX_SIGNALS_PER_CALL},
            ).fetchall()
        else:
            signal_rows = db.execute(
                text(
                    "SELECT s.id, s.ts, s.symbol, s.side, s.confidence, s.strategy, "
                    "       bp.name AS bot_id "
                    "FROM bot_signals s "
                    "JOIN bot_allocations a ON a.id = s.allocation_id "
                    "JOIN bot_profiles bp ON bp.id = a.profile_id "
                    "WHERE a.user_id = :uid AND s.id > :since "
                    "ORDER BY s.id ASC LIMIT :lim"
                ),
                {"uid": current_user.id, "since": since_signal_id, "lim": MAX_SIGNALS_PER_CALL},
            ).fetchall()
        for r in signal_rows:
            result["signals"].append({
                "id": int(r[0]),
                "ts": str(r[1]),
                "symbol": r[2],
                "side": r[3],
                "confidence": float(r[4] or 0),
                "strategy": r[5],
                "bot_id": r[6],
                "bot_display_name": _display(r[6]),
            })
    except Exception as exc:
        logger.warning("[live-activity] signal query failed: %s", exc)

    try:
        # ── Trades since watermark (exclude quarantined) ──
        # Same cold-start semantics as signals — return most-recent N so the
        # client's watermark advances to the true tail instead of dredging
        # historical trades.
        if since_trade_id == 0:
            trade_rows = db.execute(
                text(
                    "SELECT * FROM ("
                    "  SELECT t.id, t.ts, t.symbol, t.side, t.qty, t.fill_price_cents, "
                    "         bp.name AS bot_id "
                    "  FROM bot_trades t "
                    "  JOIN bot_allocations a ON a.id = t.allocation_id "
                    "  JOIN bot_profiles bp ON bp.id = a.profile_id "
                    "  WHERE a.user_id = :uid AND t.quarantined_at IS NULL "
                    "  ORDER BY t.id DESC LIMIT :lim"
                    ") AS recent ORDER BY id ASC"
                ),
                {"uid": current_user.id, "lim": MAX_TRADES_PER_CALL},
            ).fetchall()
        else:
            trade_rows = db.execute(
                text(
                    "SELECT t.id, t.ts, t.symbol, t.side, t.qty, t.fill_price_cents, "
                    "       bp.name AS bot_id "
                    "FROM bot_trades t "
                    "JOIN bot_allocations a ON a.id = t.allocation_id "
                    "JOIN bot_profiles bp ON bp.id = a.profile_id "
                    "WHERE a.user_id = :uid AND t.id > :since "
                    "  AND t.quarantined_at IS NULL "
                    "ORDER BY t.id ASC LIMIT :lim"
                ),
                {"uid": current_user.id, "since": since_trade_id, "lim": MAX_TRADES_PER_CALL},
            ).fetchall()
        for r in trade_rows:
            result["trades"].append({
                "id": int(r[0]),
                "ts": str(r[1]),
                "symbol": r[2],
                "side": r[3],
                "qty": float(r[4] or 0),
                "fill_price_usd": round(float(r[5] or 0) / 100.0, 4),
                "bot_id": r[6],
                "bot_display_name": _display(r[6]),
            })
    except Exception as exc:
        logger.warning("[live-activity] trade query failed: %s", exc)

    try:
        # ── Summary: hourly volumes + active bot count ──
        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        counts = db.execute(
            text(
                "SELECT "
                "  (SELECT COUNT(*) FROM bot_allocations "
                "     WHERE user_id = :uid AND enabled = 1) AS active_bots, "
                "  (SELECT COUNT(*) FROM bot_signals s "
                "     JOIN bot_allocations a ON a.id = s.allocation_id "
                "     WHERE a.user_id = :uid AND s.ts >= :since) AS sig_1h, "
                "  (SELECT COUNT(*) FROM bot_trades t "
                "     JOIN bot_allocations a ON a.id = t.allocation_id "
                "     WHERE a.user_id = :uid AND t.ts >= :since "
                "       AND t.quarantined_at IS NULL) AS trade_1h"
            ),
            {"uid": current_user.id, "since": one_hour_ago},
        ).fetchone()
        if counts:
            result["summary"]["active_bot_count"] = int(counts[0] or 0)
            result["summary"]["signals_last_hour"] = int(counts[1] or 0)
            result["summary"]["trades_last_hour"] = int(counts[2] or 0)
    except Exception as exc:
        logger.warning("[live-activity] summary query failed: %s", exc)

    # session_pnl derives from today's realized fills across the user's bots.
    try:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        pnl_row = db.execute(
            text(
                "SELECT COALESCE(SUM(realized_cents), 0) "
                "FROM bot_daily_pnl p "
                "JOIN bot_allocations a ON a.id = p.allocation_id "
                "WHERE a.user_id = :uid AND p.date = date('now')"
            ),
            {"uid": current_user.id},
        ).fetchone()
        if pnl_row and pnl_row[0] is not None:
            result["summary"]["session_pnl_usd"] = round(int(pnl_row[0]) / 100.0, 2)
    except Exception as exc:
        logger.warning("[live-activity] session_pnl query failed: %s", exc)

    _cache_set(cache_key, result)
    return result
