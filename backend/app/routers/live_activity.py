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

    # Ticker tape: unique symbols the fund is holding right now, priced live
    # + change_pct computed from prior close. Falls back to a curated default
    # set when no open positions. Max 12 symbols so the marquee stays readable.
    try:
        held_rows = db.execute(
            text(
                "SELECT DISTINCT p.symbol "
                "FROM bot_positions p "
                "JOIN bot_allocations a ON a.id = p.allocation_id "
                "WHERE a.user_id = :uid "
                "  AND p.closed_at IS NULL "
                "  AND p.quarantined_at IS NULL "
                # Skip OCC contracts on the tape — retail tape only knows
                # underlyings; users can't read 'AAPL250816P00184000' at a glance.
                "  AND p.option_type IS NULL "
                "LIMIT 20"
            ),
            {"uid": current_user.id},
        ).fetchall()
        held_symbols = [r[0] for r in held_rows if r[0]]

        # Curated default when nothing held — big-liquidity names by asset class
        # so the tape is always populated for the desk's visual continuity.
        DEFAULT_TAPE = [
            "SPY", "QQQ", "AAPL", "NVDA",
            "BTC/USD", "ETH/USD", "SOL/USD",
        ]
        seed = list(dict.fromkeys(held_symbols + DEFAULT_TAPE))[:12]

        # Price via the shared live_prices service (cached, batched).
        try:
            from app.services.live_prices import fetch_live_prices
            live_map = fetch_live_prices(seed) or {}
        except Exception as _lp_exc:
            logger.debug("[live-activity] ticker live_prices failed: %s", _lp_exc)
            live_map = {}

        # Prior close for change_pct — module-level 5min TTL cache so we're
        # not hammering Alpaca on every bot-activity poll. prev_close only
        # changes at market close so 5min is generous.
        prev_map = _get_ticker_prev_closes(tuple(sorted(seed)))

        ticker = []
        for sym in seed:
            px = live_map.get(sym)
            if px is None or not isinstance(px, (int, float)) or px <= 0:
                continue
            prev = prev_map.get(sym)
            change_pct = 0.0
            if prev is not None and prev > 0:
                change_pct = round((float(px) - prev) / prev * 100.0, 2)
            ticker.append({
                "symbol": sym,
                "price": round(float(px), 4 if float(px) < 10 else 2),
                "change_pct": change_pct,
            })
        result["summary"]["ticker"] = ticker
    except Exception as exc:
        logger.warning("[live-activity] ticker query failed: %s", exc)
        result["summary"]["ticker"] = []

    _cache_set(cache_key, result)
    return result


# ── Candles endpoint (Trading Desk Phase 3) ─────────────────────────────────
# Serves recent OHLC bars for a single symbol so the desk's chart can render
# actual price action instead of the scripted price walk. Deliberately
# lightweight — one symbol, capped bar count, 60s cache. Equity + crypto
# only; OCC option symbols return 400 (chart doesn't make sense for a
# specific contract, and yfinance option-chain calls are too slow).

MAX_CANDLES = 128
CANDLES_CACHE_TTL_SECONDS = 60

_candles_cache: dict = {}


def _candles_cache_get(key: tuple) -> dict | None:
    entry = _candles_cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if (time.monotonic() - ts) > CANDLES_CACHE_TTL_SECONDS:
        _candles_cache.pop(key, None)
        return None
    return value


def _candles_cache_set(key: tuple, value: dict) -> None:
    _candles_cache[key] = (time.monotonic(), value)
    if len(_candles_cache) > 100:
        pairs = sorted(_candles_cache.items(), key=lambda kv: kv[1][0])
        for k, _ in pairs[:50]:
            _candles_cache.pop(k, None)


# ── Ticker prior-close cache (5min TTL) ─────────────────────────────────────
# prev_close is anchored to the previous session's close and doesn't change
# intraday, so a long TTL is safe. Keyed by the sorted symbol tuple so
# multi-tab / multi-user polls converge on one Alpaca call per ~5min.
_TICKER_PREV_TTL_SECONDS = 300
_ticker_prev_cache: dict = {}


def _get_ticker_prev_closes(symbols: tuple) -> dict:
    """Return {symbol: prior_close_price}. Cached 5min. Fail-safe (empty on error)."""
    if not symbols:
        return {}
    entry = _ticker_prev_cache.get(symbols)
    if entry is not None:
        ts, value = entry
        if (time.monotonic() - ts) < _TICKER_PREV_TTL_SECONDS:
            return value
        _ticker_prev_cache.pop(symbols, None)
    try:
        from app.screener.daily_runner import _get_prev_closes_sync
        result = _get_prev_closes_sync(list(symbols)) or {}
    except Exception as exc:
        logger.debug("[live-activity] prev-close fetch failed: %s", exc)
        result = {}
    _ticker_prev_cache[symbols] = (time.monotonic(), result)
    # Bound cache growth — trading desk typically hits ~5-10 unique seed
    # tuples, but be defensive.
    if len(_ticker_prev_cache) > 50:
        pairs = sorted(_ticker_prev_cache.items(), key=lambda kv: kv[1][0])
        for k, _ in pairs[:25]:
            _ticker_prev_cache.pop(k, None)
    return result


@router.get("/candles")
def get_candles(
    symbol: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(64, ge=1, le=MAX_CANDLES),
    timeframe: str = Query("5m", pattern="^(1m|5m|15m|30m|1h|1d)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return recent OHLC bars for a single symbol.

    Args:
        symbol:    Equity ticker (AMD, SPY) or crypto pair (BTC/USD).
        limit:     Number of most-recent bars (default 64, max 128).
        timeframe: Bar interval; "5m" default matches most bot cadences.

    Returns:
        {
            "symbol": "AMD",
            "timeframe": "5m",
            "candles": [{"ts": "...", "o": 142.1, "h": 142.5, "l": 141.9, "c": 142.4, "v": 12345}, ...]
        }
    """
    sym = symbol.strip().upper()
    # Reject empties and obvious garbage; classify_instrument handles the rest.
    if not sym:
        return {"symbol": symbol, "timeframe": timeframe, "candles": [], "error": "empty_symbol"}

    try:
        from app.services.asset_class_registry import classify_instrument
        kind = classify_instrument(sym)
    except Exception:
        return {"symbol": sym, "timeframe": timeframe, "candles": [], "error": "unclassifiable_symbol"}

    if kind == "option":
        # OCC contracts have their own quote feed; use option_marks endpoint instead.
        return {"symbol": sym, "timeframe": timeframe, "candles": [], "error": "options_not_supported"}

    cache_key = (sym, timeframe, limit)
    cached = _candles_cache_get(cache_key)
    if cached is not None:
        return cached

    candles: list[dict] = []
    try:
        if kind == "crypto":
            from app.screener.crypto_runner import _fetch_crypto_bars
            raw = _fetch_crypto_bars([sym], timeframe=timeframe, limit=limit)
        else:
            from app.screener.runner import _fetch_bars_sync
            # Map our TF to yfinance-compatible interval/period.
            if timeframe in ("1m", "5m", "15m", "30m"):
                period = "1d" if timeframe in ("1m", "5m") else "5d"
                interval = timeframe
            elif timeframe == "1h":
                period, interval = "1mo", "60m"
            else:  # 1d
                period, interval = "6mo", "1d"
            raw = _fetch_bars_sync([sym], period=period, interval=interval)

        df = raw.get(sym)
        if df is not None and not df.empty:
            # Take the tail so we don't ship 5000 daily bars for a 1d ask.
            tail = df.tail(limit)
            for idx, r in tail.iterrows():
                ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                candles.append({
                    "ts": ts,
                    "o": round(float(r["open"]), 6),
                    "h": round(float(r["high"]), 6),
                    "l": round(float(r["low"]), 6),
                    "c": round(float(r["close"]), 6),
                    "v": round(float(r.get("volume", 0) or 0), 4),
                })
    except Exception as exc:
        logger.warning("[live-candles] fetch failed for %s (%s): %s", sym, timeframe, exc)
        result_err = {"symbol": sym, "timeframe": timeframe, "candles": [], "error": "fetch_failed"}
        _candles_cache_set(cache_key, result_err)
        return result_err

    result = {"symbol": sym, "timeframe": timeframe, "candles": candles}
    _candles_cache_set(cache_key, result)
    return result

