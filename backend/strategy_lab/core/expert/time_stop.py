"""
Exit dead trades that haven't moved toward target.

Dead trade definition:
- Held > hold_max_days (from profile) with P&L < +1%
- Held > hold_max_hours (day bot) — just approaching session end
- P&L flat (< 0.2% move in either direction over last N bars)

Returns exit signal when triggered.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_FLAT_THRESHOLD_PCT = 0.2   # % move in either direction to count as "alive"
_FLAT_BARS_WINDOW = 10      # look at last N bars for flatness


def _get_close(bar: dict) -> float | None:
    c = bar.get("c") or bar.get("close")
    try:
        return float(c) if c is not None else None
    except (TypeError, ValueError):
        return None


def check_time_stop(
    position: dict,  # {symbol, avg_cost_cents, opened_at, qty, side}
    current_price: float,
    profile_config: dict,
    current_bars: list[dict],
) -> bool:
    """Returns True if position should be exited for time-stop reason."""
    if not position or current_price <= 0:
        return False

    symbol = position.get("symbol", "?")
    avg_cost_cents = position.get("avg_cost_cents", 0)
    opened_at = position.get("opened_at")
    side = position.get("side", "buy")

    if avg_cost_cents <= 0:
        return False

    avg_cost = avg_cost_cents / 100.0
    pnl_pct = ((current_price - avg_cost) / avg_cost) * 100 if avg_cost > 0 else 0.0
    if side == "sell":
        pnl_pct = -pnl_pct  # for short positions, gain when price drops

    now = datetime.now(timezone.utc)

    # Parse opened_at
    if isinstance(opened_at, str):
        try:
            from dateutil.parser import parse
            opened_at = parse(opened_at)
        except Exception:
            opened_at = None
    if opened_at and not getattr(opened_at, "tzinfo", None):
        opened_at = opened_at.replace(tzinfo=timezone.utc)

    hold_duration = (now - opened_at).total_seconds() if opened_at else 0

    execution_cfg = profile_config.get("execution", {}) if profile_config else {}
    risk_cfg = profile_config.get("risk_overlay", {}) if profile_config else {}

    hold_max_days = execution_cfg.get("hold_max_days") or risk_cfg.get("hold_max_days") or 30
    hold_max_hours = execution_cfg.get("hold_max_hours") or risk_cfg.get("hold_max_hours") or None

    # ── 1. Held too long (swing/lt) with low P&L ─────────────────────────────
    hold_days = hold_duration / 86400.0
    if hold_days > hold_max_days and pnl_pct < 1.0:
        logger.info(
            "[time_stop:%s] Held %.1f days > max=%d with pnl=%.2f%% < 1%% → exit",
            symbol, hold_days, hold_max_days, pnl_pct,
        )
        return True

    # ── 2. Day bot: approaching session end ──────────────────────────────────
    if hold_max_hours is not None:
        hold_hours = hold_duration / 3600.0
        if hold_hours > hold_max_hours:
            logger.info(
                "[time_stop:%s] Held %.1f hours > max=%.1f hours → exit",
                symbol, hold_hours, hold_max_hours,
            )
            return True

    # ── 3. P&L flat over last N bars ──────────────────────────────────────────
    if current_bars and len(current_bars) >= _FLAT_BARS_WINDOW:
        window = current_bars[-_FLAT_BARS_WINDOW:]
        closes = [_get_close(b) for b in window]
        closes = [c for c in closes if c is not None]

        if len(closes) >= 2:
            oldest = closes[0]
            newest = closes[-1]
            if oldest > 0:
                move_pct = abs((newest - oldest) / oldest) * 100
                if move_pct < _FLAT_THRESHOLD_PCT:
                    logger.info(
                        "[time_stop:%s] Flat trade: %.4f%% move over last %d bars → exit",
                        symbol, move_pct, _FLAT_BARS_WINDOW,
                    )
                    return True

    return False
