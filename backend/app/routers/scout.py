"""Strategy Scout API — per-ticker strategy evaluation and personal setup alerts.

Feature-flagged: set ENABLE_STRATEGY_SCOUT=true in Railway to activate.

Endpoints:
  POST /api/scout/evaluate        — evaluate one (strategy, ticker) pair
  POST /api/scout/scan-ticker     — run all catalog strategies on a ticker
  GET  /api/scout/setups          — list user's active setups
  POST /api/scout/setups          — create a setup
  DELETE /api/scout/setups/{id}   — remove a setup
  GET  /api/scout/signals         — user's fired scout signals
  GET  /api/scout/catalog         — list all available strategies
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from strategy_lab.scout_catalog import SCOUT_CATALOG, list_catalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scout", tags=["scout"])

# ── Feature flag guard ─────────────────────────────────────────────────────────

def _scout_enabled() -> None:
    if not os.getenv("ENABLE_STRATEGY_SCOUT", "true").strip().lower() == "true":
        raise HTTPException(status_code=404, detail="Strategy Scout not enabled")


# ── Simple in-process TTL cache for scan-ticker results ───────────────────────

_SCAN_CACHE: dict[str, tuple[float, Any]] = {}
_SCAN_CACHE_TTL = 60  # seconds


def _cache_get(key: str) -> Any | None:
    entry = _SCAN_CACHE.get(key)
    if entry and time.time() - entry[0] < _SCAN_CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _SCAN_CACHE[key] = (time.time(), value)


# ── Scout-specific confidence calculators ─────────────────────────────────────
# Strategy modules are shared with the bot runner (different sensitivity needs).
# Scout needs tighter thresholds and recency weighting to avoid every large-cap
# stock returning the same Golden Cross / RSI-2 / VWAP results at 90%.

def _mean(arr: list[float]) -> float:
    return sum(arr) / len(arr) if arr else 0.0


def _atr14(bars: list[dict]) -> float:
    if len(bars) < 2:
        return bars[-1]["c"] * 0.02 if bars else 1.0
    n = min(14, len(bars) - 1)
    trs = []
    for i in range(-n, 0):
        b, prev_c = bars[i], bars[i - 1]["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - prev_c), abs(b["l"] - prev_c)))
    return sum(trs) / len(trs) if trs else bars[-1]["c"] * 0.02


def _golden_cross_scout(bars: list[dict]) -> tuple[str, float] | None:
    """Confidence driven by recency of the actual SMA50/SMA200 cross event.
    A cross that happened 200 days ago is NOT a 90% entry — it's a hold.
    """
    if len(bars) < 210:
        return None
    closes = [b["c"] for b in bars]
    sma50 = [_mean(closes[i - 50:i]) for i in range(200, len(closes))]
    sma200 = [_mean(closes[i - 200:i]) for i in range(200, len(closes))]
    if not sma50:
        return None
    current_above = sma50[-1] > sma200[-1]
    side = "buy" if current_above else "sell"
    cross_days_ago: int | None = None
    for i in range(len(sma50) - 1, 0, -1):
        prev_above = sma50[i - 1] > sma200[i - 1]
        is_above = sma50[i] > sma200[i]
        if is_above != prev_above and is_above == current_above:
            cross_days_ago = len(sma50) - 1 - i
            break
    if cross_days_ago is None:
        cross_days_ago = 999
    if cross_days_ago <= 5:
        return (side, 0.90)
    if cross_days_ago <= 15:
        return (side, 0.78)
    if cross_days_ago <= 30:
        return (side, 0.65)
    if cross_days_ago <= 63:
        return (side, 0.52)
    return None  # cross is stale — not an actionable entry


def _rsi2_scout(bars: list[dict]) -> tuple[str, float] | None:
    """Tighter thresholds. RSI(2) < 10 fires too broadly. Use < 5 for real signal."""
    if len(bars) < 3:
        return None
    closes = [b["c"] for b in bars]
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(-2, 0)]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(-2, 0)]
    avg_gain, avg_loss = sum(gains) / 2, sum(losses) / 2
    rsi2 = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    if rsi2 < 2:
        return ("buy", 0.88)
    if rsi2 < 5:
        return ("buy", 0.72)
    if rsi2 < 10:
        return ("buy", 0.52)
    if rsi2 > 95:
        return ("sell", 0.86)
    if rsi2 > 90:
        return ("sell", 0.72)
    if rsi2 > 65:
        return ("sell", 0.48)
    return None


def _vwap_reversion_scout(bars: list[dict]) -> tuple[str, float] | None:
    """VWAP is an intraday concept — meaningless across a full year of daily bars.
    Use rolling 20-bar VWAP; confidence scaled by deviation in ATR units.
    """
    if len(bars) < 20:
        return None
    recent = bars[-20:]
    cum_tp_vol = sum(((b["h"] + b["l"] + b["c"]) / 3.0) * (b.get("v") or 0) for b in recent)
    cum_vol = sum((b.get("v") or 0) for b in recent)
    if cum_vol <= 0:
        return None
    vwap = cum_tp_vol / cum_vol
    atr_val = _atr14(bars)
    if atr_val <= 0:
        return None
    dev_atrs = (bars[-1]["c"] - vwap) / atr_val
    if dev_atrs < -1.5:
        return ("buy", round(min(0.88, 0.50 + abs(dev_atrs) * 0.10), 3))
    if dev_atrs > 1.5:
        return ("sell", round(min(0.88, 0.50 + dev_atrs * 0.10), 3))
    return None


_SCOUT_CONFIDENCE_OVERRIDES: dict[str, Any] = {
    "golden_cross": _golden_cross_scout,
    "rsi2_mean_reversion": _rsi2_scout,
    "vwap_reversion": _vwap_reversion_scout,
}


def _build_override_reason(strategy_id: str, bars: list[dict], side: str, conf: float) -> str:
    last = bars[-1]["c"] if bars else 0
    if strategy_id == "golden_cross":
        closes = [b["c"] for b in bars]
        sma50 = _mean(closes[-50:])
        sma200 = _mean(closes[-200:]) if len(closes) >= 200 else _mean(closes)
        spread = (sma50 - sma200) / sma200 * 100 if sma200 else 0
        label = "Golden" if side == "buy" else "Death"
        return f"{label} cross: SMA50={sma50:.2f}, SMA200={sma200:.2f} (spread {spread:+.1f}%)"
    if strategy_id == "rsi2_mean_reversion":
        closes = [b["c"] for b in bars]
        gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(-2, 0)]
        losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(-2, 0)]
        avg_gain, avg_loss = sum(gains) / 2, sum(losses) / 2
        rsi2 = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        label = "oversold" if side == "buy" else "overbought"
        return f"RSI(2)={rsi2:.1f} — extreme {label} reading"
    if strategy_id == "vwap_reversion":
        recent = bars[-20:]
        cum_tp_vol = sum(((b["h"] + b["l"] + b["c"]) / 3.0) * (b.get("v") or 0) for b in recent)
        cum_vol = sum((b.get("v") or 0) for b in recent)
        vwap = cum_tp_vol / cum_vol if cum_vol > 0 else 0
        label = "below" if side == "buy" else "above"
        return f"Price {last:.2f} is {label} 20-bar VWAP {vwap:.2f}"
    return f"Setup detected ({conf*100:.0f}% confidence)"


# ── Bar fetching ──────────────────────────────────────────────────────────────

def _fetch_bars_for_ticker(ticker: str, period: str = "1y") -> list[dict]:
    """Fetch daily OHLCV bars for a single ticker via yfinance Ticker.history().

    Uses Ticker.history() instead of yf.download() because the latter returns
    a MultiIndex DataFrame for single-symbol calls (yfinance ≥ 0.2), causing
    column-name mismatches. Ticker.history() always returns a flat DataFrame.

    Normalizes crypto-style "BTC/USD" → "BTC-USD" via the same helper bars.py
    uses, so quick-lookup works for crypto symbols.
    """
    try:
        import yfinance as yf
        from app.routers.bars import _normalize_symbol
        hist = yf.Ticker(_normalize_symbol(ticker)).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        hist.columns = [str(c).lower() for c in hist.columns]
        needed = ["open", "high", "low", "close", "volume"]
        if any(c not in hist.columns for c in needed):
            logger.warning("[scout] unexpected columns for %s: %s", ticker, list(hist.columns))
            return []
        hist = hist[needed].dropna()
        return [
            {
                "c": float(row["close"]),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "v": float(row.get("volume", 0) or 0),
                "ts": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
            }
            for idx, row in hist.iterrows()
        ]
    except Exception as exc:
        logger.warning("[scout] bar fetch failed for %s: %s", ticker, exc)
        return []


# ── Strategy runner ───────────────────────────────────────────────────────────

def _run_strategy(strategy_id: str, ticker: str, bars: list[dict]) -> dict | None:
    """Run one strategy against (ticker, bars), return result dict or None."""
    meta = SCOUT_CATALOG.get(strategy_id)
    if not meta:
        return None
    if len(bars) < meta.get("min_bars", 1):
        return None

    last_close = bars[-1]["c"] if bars else None
    threshold = meta["confidence_threshold"]

    # Scout-specific overrides produce real, per-ticker differentiated confidence.
    # The generic strategy modules use confidence formulas that saturate at 0.9
    # for all large-cap stocks in a bull market — these overrides fix that.
    if strategy_id in _SCOUT_CONFIDENCE_OVERRIDES:
        result = _SCOUT_CONFIDENCE_OVERRIDES[strategy_id](bars)
        if result is None:
            return None
        side, conf = result
        if conf < threshold:
            return None
        is_buy = side in ("buy", "cover")
        return {
            "strategy_id": strategy_id,
            "display_name": meta["display_name"],
            "category": meta["category"],
            "setup_quality": min(100, int(conf * 100)),
            "confidence": round(conf, 4),
            "side": side,
            "threshold": threshold,
            "armed": conf >= threshold,
            "entry": last_close,
            "stop": round(last_close * (0.93 if is_buy else 1.07), 4) if last_close else None,
            "target": round(last_close * (1.15 if is_buy else 0.85), 4) if last_close else None,
            "reason": _build_override_reason(strategy_id, bars, side, conf),
            "indicators": {},
        }

    # Generic path: import and run the strategy module
    try:
        mod = importlib.import_module(meta["module"])
    except ImportError as exc:
        logger.debug("[scout] cannot import %s: %s", meta["module"], exc)
        return None

    signals = []
    try:
        if hasattr(mod, "generate_signals"):
            signals = mod.generate_signals({ticker: bars}, {}, {}) or []
        elif hasattr(mod, "generate_signal"):
            closes = [b["c"] for b in bars]
            sig = mod.generate_signal(ticker, closes)
            if sig:
                signals = [sig]
    except Exception as exc:
        logger.debug("[scout] %s strategy raised: %s", strategy_id, exc)
        return None

    sig = next(
        (s for s in signals if s.symbol == ticker and s.side != "hold"),
        next((s for s in signals if s.symbol == ticker), None),
    )
    if not sig:
        return None

    conf = float(sig.confidence or 0)
    # Cap non-override strategies at 0.85 — prevents blanket saturation at 0.90
    conf = min(0.85, conf)
    side = sig.side or "neutral"

    if conf < threshold or side == "hold":
        return None

    is_buy = side in ("buy", "cover")
    return {
        "strategy_id": strategy_id,
        "display_name": meta["display_name"],
        "category": meta["category"],
        "setup_quality": min(100, int(conf * 100)),
        "confidence": round(conf, 4),
        "side": side,
        "threshold": threshold,
        "armed": conf >= threshold,
        "entry": last_close,
        "stop": round(last_close * (0.93 if is_buy else 1.07), 4) if last_close else None,
        "target": round(last_close * (1.15 if is_buy else 0.85), 4) if last_close else None,
        "reason": getattr(sig, "reason", "") or "",
        "indicators": {},
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog(_: None = Depends(_scout_enabled)):
    return {"strategies": list_catalog()}


@router.post("/evaluate")
def evaluate_setup(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
):
    strategy_id = (body.get("strategy_id") or "").strip()
    ticker = (body.get("ticker") or "").strip().upper()

    if not strategy_id or strategy_id not in SCOUT_CATALOG:
        raise HTTPException(status_code=422, detail="Unknown strategy_id")
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    bars = _fetch_bars_for_ticker(ticker)
    if not bars:
        raise HTTPException(status_code=422, detail=f"No bar data found for {ticker}")

    result = _run_strategy(strategy_id, ticker, bars)
    if result is None:
        meta = SCOUT_CATALOG[strategy_id]
        return {
            "strategy_id": strategy_id,
            "display_name": meta["display_name"],
            "category": meta["category"],
            "setup_quality": 0,
            "confidence": 0.0,
            "side": "neutral",
            "threshold": meta["confidence_threshold"],
            "armed": False,
            "entry": bars[-1]["c"] if bars else None,
            "stop": None,
            "target": None,
            "reason": f"Insufficient data or no signal ({len(bars)} bars, need {meta['min_bars']})",
            "indicators": {},
        }
    return result


@router.post("/scan-ticker")
def scan_ticker(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
):
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    cached = _cache_get(ticker)
    if cached is not None:
        return cached

    bars = _fetch_bars_for_ticker(ticker)
    if not bars:
        raise HTTPException(status_code=422, detail=f"No bar data found for {ticker}")

    results = []
    for strategy_id in SCOUT_CATALOG:
        r = _run_strategy(strategy_id, ticker, bars)
        if r:
            results.append(r)

    results.sort(key=lambda x: (-x["setup_quality"], -x["confidence"]))
    top10 = results[:10]

    # Empty state — no strategies firing for this ticker right now
    if not top10:
        response = {
            "ticker": ticker,
            "bar_count": len(bars),
            "results": [],
            "conflict_warning": None,
            "message": f"No high-confidence setups currently for {ticker}. "
                       f"Market conditions don't favor any tracked strategy right now.",
        }
        _cache_set(ticker, response)
        return response

    # Conflict detection — flag when both meaningful long and short signals exist
    buy_high = [r for r in top10 if r["side"] in ("buy", "cover") and r["confidence"] >= 0.55]
    sell_high = [r for r in top10 if r["side"] in ("sell", "short") and r["confidence"] >= 0.55]
    conflict_warning = None
    if buy_high and sell_high:
        top_buy_conf = buy_high[0]["confidence"] * 100
        top_sell_conf = sell_high[0]["confidence"] * 100
        conflict_warning = (
            f"Conflicting signals: {buy_high[0]['display_name']} ({top_buy_conf:.0f}% long) "
            f"vs {sell_high[0]['display_name']} ({top_sell_conf:.0f}% short). "
            f"Mixed-regime conditions — size down or wait for resolution."
        )

    response = {
        "ticker": ticker,
        "bar_count": len(bars),
        "results": top10,
        "conflict_warning": conflict_warning,
        "message": None,
    }
    _cache_set(ticker, response)
    return response


# ── Quick-lookup: 2y walk-forward ranking per ticker ──────────────────────────

_LOOKUP_CACHE: dict[str, tuple[float, Any]] = {}
_LOOKUP_CACHE_TTL = 3600  # 1 hour


def _lookup_cache_get(key: str) -> Any | None:
    entry = _LOOKUP_CACHE.get(key)
    if entry and time.time() - entry[0] < _LOOKUP_CACHE_TTL:
        return entry[1]
    return None


def _lookup_cache_set(key: str, value: Any) -> None:
    _LOOKUP_CACHE[key] = (time.time(), value)


def _is_crypto_symbol(symbol: str) -> bool:
    s = symbol.upper()
    return "/" in s or s.endswith(("USD", "USDT", "BTC", "ETH")) or "-USD" in s


def _strategies_for_symbol(symbol: str) -> list[str]:
    """Return catalog strategy IDs relevant to this symbol's asset class."""
    is_crypto = _is_crypto_symbol(symbol)
    _CRYPTO_CAT_KEYWORDS = {"crypto", "bitcoin", "ethereum", "defi", "onchain"}
    relevant, generic = [], []
    for sid, meta in SCOUT_CATALOG.items():
        cat = meta.get("category", "").lower()
        is_crypto_cat = any(k in cat for k in _CRYPTO_CAT_KEYWORDS)
        if is_crypto == is_crypto_cat:
            relevant.append(sid)
        elif not is_crypto_cat and not is_crypto:
            generic.append(sid)
    return relevant if relevant else list(SCOUT_CATALOG.keys())


# ── SHIP 4 — Reconciliation helper ─────────────────────────────────────────────
#
# The quick-lookup listing and Past Triggers panel previously called two
# different backtest implementations with different windows and hold periods,
# producing different numbers for the same (symbol, strategy) pair. This is
# the "portfolio split-brain" pattern from vault/known-issues #1 applied to a
# new surface.
#
# CANONICAL SOURCE for both surfaces is now `run_backtest` from
# `app.services.strategy_backtest`. We call it with the SAME parameters used
# by the Past Triggers panel (5y window, hold_days=30) so the two surfaces
# reconcile exactly within ±0.1 on sharpe, ±1% on win rate, ±0.1% on
# avg_return — and trigger counts match exactly.
#
# Min sample: strategies with <20 triggers over the lookback are excluded
# from the listing entirely. A 2-trade 100% win rate is statistical noise.

# Listing parameters MUST match BacktestPanel.tsx default (years=5) and the
# /api/strategy/{id}/backtest endpoint default (hold_days=30) so the two
# surfaces are computing the same backtest, full stop.
_LISTING_YEARS = 5
_LISTING_HOLD_DAYS = 30
_LISTING_MIN_TRIGGERS = 20


def _reconciled_stats_for_strategy(strategy_id: str, ticker: str, bars: list[dict]) -> dict | None:
    """Run the CANONICAL Past Triggers backtest and shape the result for the
    quick-lookup listing.

    Returns None if the strategy has fewer than _LISTING_MIN_TRIGGERS over the
    lookback window — these are excluded from default ranks to avoid promoting
    statistically meaningless results (e.g. 2 trades, 100% win rate).

    Returns the same keys the legacy `_simulate_strategy_on_bars` produced
    (sharpe, win_rate_pct, trades_per_year, composite_score) plus a new
    `avg_return_pct` field formatted as a signed percent (×100 of the decimal
    return). Caller is responsible for the canonical source — do NOT
    recompute these in JSX.
    """
    import math

    from app.services.strategy_backtest import run_backtest

    if SCOUT_CATALOG.get(strategy_id) is None:
        return None

    result = run_backtest(
        strategy_id,
        ticker,
        bars,
        years_requested=_LISTING_YEARS,
        hold_days=_LISTING_HOLD_DAYS,
    )

    n = int(result.trigger_count or 0)
    if n < _LISTING_MIN_TRIGGERS:
        return None

    # Past Triggers reports decimals (0.05 = 5%). Listing UI used percent
    # numbers. We expose BOTH in the response: win_rate_pct (percent for
    # display), avg_return_pct (percent for display + sort), and keep
    # sharpe/trigger_count exactly as the canonical function returned them.
    sharpe = float(result.sharpe) if result.sharpe is not None else 0.0
    win_rate_pct = (float(result.win_rate) * 100.0) if result.win_rate is not None else 0.0
    avg_return_decimal = float(result.avg_return) if result.avg_return is not None else 0.0
    avg_return_pct = avg_return_decimal * 100.0

    # trades_per_year normalises the trigger count over the bar window so
    # users still get a "fires per year" sense without comparing absolute
    # counts across strategies with different histories.
    years_avail = max(0.1, float(result.years_available or 0.0))
    trades_per_year = max(1, round(n / years_avail))

    # composite_score kept in the payload for diagnostics; no longer the
    # primary sort key (default sort is now avg_return_pct desc).
    composite = sharpe * (win_rate_pct / 100.0) * math.log(max(2, n))

    return {
        "sharpe":          round(sharpe, 2),
        "win_rate_pct":    round(win_rate_pct, 1),
        "avg_return_pct":  round(avg_return_pct, 2),
        "trigger_count":   n,
        "trades_per_year": trades_per_year,
        "composite_score": round(max(0.0, composite), 3),
    }


@router.post("/quick-lookup")
def quick_lookup(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
):
    """
    Rank all asset-class-relevant strategies against a ticker using the same
    backtest engine the Past Triggers panel uses (run_backtest, 5y window,
    hold_days=30). Strategies with <20 triggers are excluded. Default sort is
    AVG RETURN desc. Results cached 1h per symbol.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    symbol = (body.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol is required")

    # Cache prefix bumped from "ql:" → "ql2:" so stale 2y/walk-forward results
    # from the previous implementation do not poison post-deploy lookups.
    cache_key = f"ql2:{symbol}"
    cached = _lookup_cache_get(cache_key)
    if cached is not None:
        cached_copy = dict(cached)
        cached_copy["cached"] = True
        return cached_copy

    # Fetch 5y of bars to match the Past Triggers default. yfinance accepts
    # "5y" as a period string.
    bars = _fetch_bars_for_ticker(symbol, period=f"{_LISTING_YEARS}y")
    if not bars:
        raise HTTPException(status_code=422, detail=f"No price data found for {symbol}")

    strategy_ids = _strategies_for_symbol(symbol)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_reconciled_stats_for_strategy, sid, symbol, bars): sid
            for sid in strategy_ids
        }
        for future in as_completed(futures, timeout=60):
            sid = futures[future]
            try:
                stats = future.result(timeout=30)
            except Exception as exc:
                logger.debug("[quick-lookup] %s failed: %s", sid, exc)
                stats = None
            if stats:
                meta = SCOUT_CATALOG[sid]
                results.append({
                    "strategy_id":   sid,
                    "display_name":  meta["display_name"],
                    "category":      meta["category"],
                    **stats,
                })

    # Default sort: AVG RETURN desc. composite_score remains in the payload
    # for diagnostic visibility but is no longer the primary rank key.
    results.sort(key=lambda x: -x["avg_return_pct"])
    response = {
        "symbol":    symbol,
        "bar_count": len(bars),
        "results":   results[:10],
        "cached":    False,
        "lookback_years": _LISTING_YEARS,
        "hold_days":      _LISTING_HOLD_DAYS,
        "min_triggers":   _LISTING_MIN_TRIGGERS,
    }
    _lookup_cache_set(cache_key, response)
    return response


@router.get("/screen")
def screen_strategy(
    strategy: str = Query(..., description="Strategy ID from catalog"),
    universe: str = Query("sp500_plus_top_crypto", description="Symbol universe preset"),
    limit: int = Query(25, ge=1, le=100),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Screen an entire universe for tickers matching a strategy's entry conditions."""
    if strategy not in SCOUT_CATALOG:
        raise HTTPException(status_code=422, detail=f"Unknown strategy: {strategy}")

    valid_universes = {"sp500", "russell1000", "crypto_top50", "sp500_plus_top_crypto", "watchlist"}
    if universe not in valid_universes:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown universe: {universe}. Valid: {sorted(valid_universes)}",
        )

    from app.services.scout_screener import run_screen

    # For watchlist universe, pull the user's watchlist symbols from DB
    watchlist_symbols: list[str] = []
    if universe == "watchlist":
        try:
            from app.db.models.bots import BotAllocation  # noqa: F401
            # Use existing watchlist data if available, otherwise empty
            watchlist_symbols = []  # placeholder — populate from user's saved symbols if the model exists
        except Exception:
            pass

    try:
        result = run_screen(strategy, universe, limit=limit, watchlist_symbols=watchlist_symbols)
        return result
    except Exception as exc:
        logger.error("[scout] screen failed for %s/%s: %s", strategy, universe, exc)
        raise HTTPException(status_code=500, detail="Screener error — please try again")


@router.get("/setups")
def get_setups(
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSetup
    rows = (
        db.query(UserScoutSetup)
        .filter(
            UserScoutSetup.user_id == current_user.id,
            UserScoutSetup.status != "deleted",
        )
        .order_by(UserScoutSetup.created_at.desc())
        .all()
    )
    return {
        "setups": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "strategy_id": r.strategy_id,
                "display_name": SCOUT_CATALOG.get(r.strategy_id, {}).get("display_name", r.strategy_id),
                "category": SCOUT_CATALOG.get(r.strategy_id, {}).get("category", ""),
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_scanned_at": r.last_scanned_at.isoformat() if r.last_scanned_at else None,
                "last_confidence": r.last_confidence,
                "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            }
            for r in rows
        ]
    }


@router.post("/setups")
def create_setup(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSetup
    from sqlalchemy.exc import IntegrityError

    ticker = (body.get("ticker") or "").strip().upper()
    strategy_id = (body.get("strategy_id") or "").strip()

    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")
    if not strategy_id or strategy_id not in SCOUT_CATALOG:
        raise HTTPException(status_code=422, detail="Unknown strategy_id")

    # Check per-user cap (max 25 active setups)
    active_count = (
        db.query(UserScoutSetup)
        .filter(UserScoutSetup.user_id == current_user.id, UserScoutSetup.status == "active")
        .count()
    )
    if active_count >= 25:
        raise HTTPException(status_code=422, detail="Maximum 25 active setups per user")

    setup = UserScoutSetup(
        user_id=current_user.id,
        ticker=ticker,
        strategy_id=strategy_id,
        status="active",
    )
    db.add(setup)
    try:
        db.commit()
        db.refresh(setup)
    except IntegrityError:
        db.rollback()
        # Already exists — re-activate if paused/fired
        existing = (
            db.query(UserScoutSetup)
            .filter(
                UserScoutSetup.user_id == current_user.id,
                UserScoutSetup.ticker == ticker,
                UserScoutSetup.strategy_id == strategy_id,
            )
            .first()
        )
        if existing and existing.status != "active":
            existing.status = "active"
            existing.fired_at = None
            db.commit()
            setup = existing
        elif existing:
            return {
                "id": existing.id,
                "ticker": existing.ticker,
                "strategy_id": existing.strategy_id,
                "status": existing.status,
                "already_exists": True,
            }

    return {
        "id": setup.id,
        "ticker": setup.ticker,
        "strategy_id": setup.strategy_id,
        "status": setup.status,
        "already_exists": False,
    }


@router.delete("/setups/{setup_id}")
def delete_setup(
    setup_id: int,
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSetup
    setup = db.get(UserScoutSetup, setup_id)
    if not setup or setup.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Setup not found")
    setup.status = "deleted"
    db.commit()
    return {"ok": True}


@router.get("/signals")
def get_signals(
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSignal
    rows = (
        db.query(UserScoutSignal)
        .filter(UserScoutSignal.user_id == current_user.id)
        .order_by(UserScoutSignal.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "signals": [
            {
                "id": r.id,
                "setup_id": r.setup_id,
                "ticker": r.ticker,
                "strategy_id": r.strategy_id,
                "display_name": SCOUT_CATALOG.get(r.strategy_id, {}).get("display_name", r.strategy_id),
                "side": r.side,
                "confidence": r.confidence,
                "entry_price": r.entry_price,
                "stop_price": r.stop_price,
                "target_price": r.target_price,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
