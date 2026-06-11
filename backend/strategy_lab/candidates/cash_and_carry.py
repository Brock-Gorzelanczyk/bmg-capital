"""
CANDIDATE — not scheduled. Graduate manually after paper trading.
Strategy: Delta-Neutral Cash-and-Carry (Perpetual Futures Basis Trade)

Alpha source: Collect 8-hour perpetual futures funding payments by
simultaneously holding long spot + short perp of equal size.
P&L = funding collected - trading fees - borrow costs.
Directional exposure: near zero (delta-neutral at entry).

IMPORTANT EXECUTION NOTE:
This strategy generates signals with reason="carry_open_*" and
reason="carry_close_*". A true implementation requires TWO simultaneous
orders per signal:
  - carry_open: BUY spot (Alpaca crypto or CCXT spot) + SHORT perp (CCXT futures)
  - carry_close: SELL spot + BUY perp (close short)
The current scan_and_execute pipeline handles single-leg orders.
Paper trade this strategy first by tracking hypothetical P&L manually
before wiring up dual-leg execution.

Academic ref: Basis trading / cash-and-carry arbitrage. Standard in
TradFi (commodity futures); applied to crypto perps circa 2019+.

GRADUATION CHECKLIST:
  - [ ] Verify CCXT futures account has sufficient margin
  - [ ] Wire dual-leg execution: spot buy via CCXT spot + perp short via CCXT futures
  - [ ] Add position tracking from DB (replace module-level dict)
  - [ ] Add margin monitoring: alert if perp short margin < 30% buffer
  - [ ] Test with 1% position size for 2 weeks before scaling
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "cash_and_carry"

CARRY_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "AVAX", "ARB"]
MIN_FUNDING_8H = 0.0002   # 0.02% = ~9% annualized minimum
TOP_N = 2
MAX_HOLD_DAYS = 14
SIZE_HINT = 0.40
ANNUAL_YIELD_BREAKEVEN = 0.05

# Module-level state: {symbol: {"opened_at": datetime, "funding_rate": float}}
_OPEN_CARRY_POSITIONS: dict = {}


def _fetch_coinglass_funding(symbol: str) -> float | None:
    """
    Fetch 8h funding rate for a symbol from Coinglass.
    Uses COINGLASS_API_KEY env var and coinglassSecret header —
    same pattern as crypto_cycle_detector._fetch_funding_rate_coinglass.
    """
    try:
        api_key = os.getenv("COINGLASS_API_KEY", "")
        if not api_key:
            return None
        url = "https://open-api.coinglass.com/public/v2/funding"
        headers = {"coinglassSecret": api_key}
        params = {"symbol": symbol}
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code != 200:
            logger.warning("[cash_and_carry] Coinglass funding %d for %s", resp.status_code, symbol)
            return None
        data = resp.json()
        rows = data.get("data", [])
        for row in rows:
            if row.get("exchangeName", "").lower() == "binance":
                rate = row.get("rate")
                if rate is not None:
                    return float(rate)
        if rows and rows[0].get("rate") is not None:
            return float(rows[0]["rate"])
        return None
    except Exception as exc:
        logger.debug("[cash_and_carry] Coinglass error for %s: %s", symbol, exc)
        return None


def _fetch_binance_funding(symbol: str) -> float | None:
    """
    Fallback: fetch latest funding rate from Binance futures public API.
    Returns the most recent funding rate (decimal, e.g. 0.0001 = 0.01%).
    """
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": f"{symbol}USDT", "limit": 3},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("[cash_and_carry] Binance fundingRate %d for %s", resp.status_code, symbol)
            return None
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            return float(data[-1].get("fundingRate", 0.0))
        return None
    except Exception as exc:
        logger.debug("[cash_and_carry] Binance funding error for %s: %s", symbol, exc)
        return None


def _get_funding_rate(symbol: str) -> float | None:
    """Try Coinglass first, fall back to Binance public API."""
    rate = _fetch_coinglass_funding(symbol)
    if rate is None:
        rate = _fetch_binance_funding(symbol)
    return rate


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """
    Scan CARRY_UNIVERSE for positive funding rates and emit carry_open /
    carry_close signals.  See module docstring before wiring execution.
    """
    signals: list[Signal] = []
    now = datetime.now(timezone.utc)

    # ── STEP 1: Fetch funding rates ───────────────────────────────────────────
    funding_rates: dict[str, float] = {}
    any_success = False
    for sym in CARRY_UNIVERSE:
        rate = _get_funding_rate(sym)
        if rate is not None:
            funding_rates[sym] = rate
            any_success = True

    if not any_success:
        logger.debug("[cash_and_carry] all funding fetches failed — returning []")
        return []

    # ── STEP 2: Filter by minimum threshold ──────────────────────────────────
    qualifying = {
        sym: rate
        for sym, rate in funding_rates.items()
        if rate >= MIN_FUNDING_8H
    }
    if not qualifying:
        logger.debug("[cash_and_carry] no symbols above MIN_FUNDING_8H=%.4f", MIN_FUNDING_8H)

    # ── STEP 3: Rank by funding rate, take top N ──────────────────────────────
    ranked = sorted(qualifying.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]

    # ── STEP 4: Dedup — skip if already open and opened <24h ago ─────────────
    # Also prune stale entries (opened >= 24h ago) from state
    stale = [
        sym for sym, pos in _OPEN_CARRY_POSITIONS.items()
        if (now - pos["opened_at"]).total_seconds() >= 86400
    ]
    for sym in stale:
        del _OPEN_CARRY_POSITIONS[sym]

    # ── STEP 5: Cycle regime gate ─────────────────────────────────────────────
    try:
        from strategy_lab.core.crypto_signal_aggregator import get_crypto_regime_snapshot
        crypto_regime = get_crypto_regime_snapshot()
        if crypto_regime.get("cycle_phase") in ("distribution", "bear"):
            logger.debug("[cash_and_carry] cycle_phase=%s — skipping carry opens", crypto_regime.get("cycle_phase"))
            ranked = []  # suppress opens; still generate closes below
    except ImportError:
        pass

    # ── STEP 6: Generate carry_open signals ───────────────────────────────────
    for sym, funding_rate_8h in ranked:
        if sym in _OPEN_CARRY_POSITIONS:
            logger.debug("[cash_and_carry] %s already open (opened <24h ago) — skipping", sym)
            continue

        annual_yield = funding_rate_8h * 3 * 365

        if annual_yield >= 0.50:
            confidence = 0.85
        elif annual_yield >= 0.25:
            confidence = 0.75
        elif annual_yield >= 0.10:
            confidence = 0.65
        else:
            confidence = 0.55

        reason = (
            f"carry_open_{sym}_funding_{funding_rate_8h:.4f}_annual_{annual_yield:.1%}"
        )

        signals.append(Signal(
            symbol=f"{sym}-USD",
            side="buy",
            confidence=confidence,
            size_hint=SIZE_HINT,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))

        _OPEN_CARRY_POSITIONS[sym] = {
            "opened_at": now,
            "funding_rate": funding_rate_8h,
        }
        logger.info(
            "[cash_and_carry] carry_open %s funding=%.4f annual=%.1%% conf=%.2f",
            sym, funding_rate_8h, annual_yield, confidence,
        )

    # ── STEP 7: Generate carry_close signals ─────────────────────────────────
    # Determine current cycle phase for close-trigger (c)
    current_cycle_phase: str | None = None
    try:
        from strategy_lab.core.crypto_signal_aggregator import get_crypto_regime_snapshot
        current_cycle_phase = get_crypto_regime_snapshot().get("cycle_phase")
    except ImportError:
        pass

    to_close: list[str] = []
    for sym, pos in list(_OPEN_CARRY_POSITIONS.items()):
        current_rate = funding_rates.get(sym)
        days_open = (now - pos["opened_at"]).total_seconds() / 86400

        close_reason: str | None = None

        # (a) funding dropped near zero
        if current_rate is not None and current_rate < 0.00005:
            close_reason = f"carry_close_{sym}_funding_below_threshold"
        # (b) funding turned negative
        elif current_rate is not None and current_rate < 0:
            close_reason = f"carry_close_{sym}_funding_below_threshold"
        # (c) adverse cycle phase
        elif current_cycle_phase in ("distribution", "bear"):
            close_reason = f"carry_close_{sym}_funding_below_threshold"
        # (d) exceeded max hold duration
        elif days_open > MAX_HOLD_DAYS:
            close_reason = f"carry_close_{sym}_funding_below_threshold"

        if close_reason:
            signals.append(Signal(
                symbol=f"{sym}-USD",
                side="sell",
                confidence=0.80,
                size_hint=SIZE_HINT,
                reason=close_reason,
                strategy=STRATEGY_NAME,
            ))
            to_close.append(sym)
            logger.info("[cash_and_carry] carry_close %s rate=%s days_open=%.1f", sym, current_rate, days_open)

    for sym in to_close:
        _OPEN_CARRY_POSITIONS.pop(sym, None)

    return signals
