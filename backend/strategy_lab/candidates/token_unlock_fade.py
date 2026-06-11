"""CANDIDATE — not scheduled. Graduate manually after paper trading.
Strategy: Token Unlock Cliff Fade

Fades (shorts) tokens in the days leading up to large cliff unlocks (>5% supply).
The thesis: insiders and early investors who receive unlocked tokens often sell
immediately, creating predictable pre-unlock price weakness and post-unlock
pressure. When a token has also pumped >15% in the prior 14 days (late buyers
are at risk), the setup has higher probability.

Entry: SELL signal N days before a cliff unlock (profile must allow shorting).
Exit:  BUY signal once the unlock date has passed.

Only generates signals when profile_config["allow_short"] is True.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from strategy_lab.core.signals import Signal
from strategy_lab.core.altdata.token_unlock_monitor import get_upcoming_unlocks

logger = logging.getLogger(__name__)

STRATEGY_NAME = "token_unlock_fade"
MIN_PUMP_PCT = 15.0     # minimum prior 14d return to consider a fade setup
MIN_SELL_PRESSURE = 0.5  # minimum sell_pressure_score to act
MAX_DAYS_AHEAD = 14      # only look at unlocks within this window


def _trailing_return_pct(closes: list[float], lookback: int) -> float | None:
    """Compute trailing return in % over `lookback` periods."""
    if len(closes) < lookback:
        return None
    p0 = closes[-lookback]
    if p0 <= 0:
        return None
    return ((closes[-1] - p0) / p0) * 100.0


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    """
    Generate SELL signals for tokens approaching a large cliff unlock
    that have pumped >15% in the prior 14 days.

    Also generates BUY exit signals for tokens whose unlock date has passed
    (post-unlock bounce opportunity).

    Parameters
    ----------
    bars          : {symbol: [bar_dict, ...]} — bar_dicts have "c" (close) key
    profile_config: strategy config; must have allow_short=True to generate SELL
    regime        : market regime dict (unused directly; unlock logic is self-contained)

    Returns
    -------
    List[Signal]
    """
    allow_short = profile_config.get("allow_short", False)

    # ── Step 1: Fetch upcoming unlocks ────────────────────────────────────────
    try:
        unlocks = get_upcoming_unlocks(days_ahead=MAX_DAYS_AHEAD)
    except Exception as exc:
        logger.warning("[%s] get_upcoming_unlocks failed: %s", STRATEGY_NAME, exc)
        return []

    if not unlocks:
        logger.debug("[%s] No upcoming unlocks within %d days", STRATEGY_NAME, MAX_DAYS_AHEAD)
        return []

    # Build a lookup: symbol → list of unlock events
    unlock_by_symbol: dict[str, list[dict]] = {}
    for unlock in unlocks:
        sym = unlock.get("symbol", "").upper()
        unlock_by_symbol.setdefault(sym, []).append(unlock)

    out: List[Signal] = []
    now_dt = datetime.now(timezone.utc)

    # ── Step 2 & 3: Iterate cliff unlocks with high sell pressure ─────────────
    for unlock in unlocks:
        # Only target cliff unlocks above threshold
        if unlock.get("unlock_type") != "cliff":
            continue
        sell_pressure = unlock.get("sell_pressure_score", 0.0)
        if sell_pressure <= MIN_SELL_PRESSURE:
            continue

        symbol = unlock.get("symbol", "").upper()
        days_until = unlock.get("days_until", 0)
        unlock_pct = unlock.get("unlock_pct_supply", 0.0)

        # ── Match symbol to bars ──────────────────────────────────────────────
        # Bars may use formats like "SOL/USD", "SOL-USD", "SOLUSDT"
        bar_key = None
        for key in bars.keys():
            key_upper = key.upper()
            if (
                key_upper == symbol
                or key_upper.startswith(symbol + "-")
                or key_upper.startswith(symbol + "/")
                or key_upper == symbol + "USD"
                or key_upper == symbol + "USDT"
            ):
                bar_key = key
                break

        if bar_key is None:
            logger.debug("[%s] No bars found for unlock symbol %s", STRATEGY_NAME, symbol)
            continue

        bar_list = bars[bar_key]
        if not bar_list:
            continue

        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < 14:
            continue

        # ── Step 3: 14-day return filter ──────────────────────────────────────
        ret_14d = _trailing_return_pct(closes, 14)
        if ret_14d is None or ret_14d < MIN_PUMP_PCT:
            logger.debug(
                "[%s] %s 14d return=%.1f%% below threshold=%.1f%%; skip",
                STRATEGY_NAME, symbol, ret_14d or 0.0, MIN_PUMP_PCT,
            )
            continue

        # ── Step 4: Generate SELL signal (pre-unlock) ─────────────────────────
        if days_until > 0 and allow_short:
            confidence = min(0.75, 0.50 + (sell_pressure * 0.25) + (ret_14d / 200.0))
            size_hint = min(1.0, sell_pressure * 0.6)
            reason = f"unlock_fade_{unlock_pct:.1f}pct_in_{days_until}d"

            out.append(Signal(
                symbol=bar_key,
                side="sell",
                confidence=round(confidence, 4),
                size_hint=round(size_hint, 4),
                reason=reason,
                strategy=STRATEGY_NAME,
            ))
            logger.info(
                "[%s] SELL %s: pressure=%.2f 14d_ret=%.1f%% conf=%.3f %s",
                STRATEGY_NAME, symbol, sell_pressure, ret_14d, confidence, reason,
            )

        elif days_until == 0 and not allow_short:
            logger.debug(
                "[%s] %s has cliff unlock today but allow_short=False; skip SELL",
                STRATEGY_NAME, symbol,
            )

    # ── Step 5: Exit signals — BUY after unlock date passes ───────────────────
    # Look for recently-passed unlocks (days_until < 0 within last 3 days)
    try:
        all_recent = get_upcoming_unlocks(days_ahead=0)
    except Exception:
        all_recent = []

    # Also scan bars for any symbol we might have shorted
    # Post-unlock bounce: look for cliff unlocks that passed in last 3 days
    # We re-fetch with days_ahead=0 returns empty, so check unlock_by_symbol
    # for symbols where the last unlock_date is today or yesterday
    today_str = now_dt.date().isoformat()
    for symbol_upper, symbol_unlocks in unlock_by_symbol.items():
        for unlock in symbol_unlocks:
            if unlock.get("unlock_type") != "cliff":
                continue
            unlock_date = unlock.get("unlock_date", "")
            if not unlock_date:
                continue
            # Check if unlock was within last 3 days (passed)
            try:
                unlock_dt = datetime.fromisoformat(unlock_date)
                days_since = (now_dt.date() - unlock_dt.date()).days
                if not (0 <= days_since <= 3):
                    continue
            except Exception:
                continue

            # Find bar key for this symbol
            bar_key = None
            for key in bars.keys():
                key_upper = key.upper()
                if (
                    key_upper == symbol_upper
                    or key_upper.startswith(symbol_upper + "-")
                    or key_upper.startswith(symbol_upper + "/")
                    or key_upper == symbol_upper + "USD"
                    or key_upper == symbol_upper + "USDT"
                ):
                    bar_key = key
                    break

            if bar_key is None:
                continue

            # Post-unlock bounce exit
            out.append(Signal(
                symbol=bar_key,
                side="buy",
                confidence=0.65,
                size_hint=1.0,  # close full short position
                reason="unlock_fade_exit_post_unlock",
                strategy=STRATEGY_NAME,
            ))
            logger.info(
                "[%s] BUY exit %s: unlock passed %d day(s) ago",
                STRATEGY_NAME, symbol_upper, days_since,
            )

    return out
