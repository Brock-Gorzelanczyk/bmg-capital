"""
50/25/25 pyramid entry. 1/3-1/3-1/3 scale-out.

Entry: 50% of intended position
Add1:  +25% when price +1 ATR from avg cost AND signal still valid
Add2:  +25% when price +2 ATR from avg cost AND trend confirmed

Scale-out:
  1st trim: 1/3 at first_target_pct (config, default +5%)
  2nd trim: 1/3 at second_target_pct (default +10%)
  Trail:    1/3 trail by smart_stops.py

BotPosition.pyramid_state stores:
  {phase: 0|1|2|3, avg_cost, add1_triggered, add2_triggered,
   trim1_triggered, trim2_triggered, trail_active}
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def initial_size_pct(intended_pct: float) -> float:
    """Returns 50% of intended_pct (first pyramid leg)."""
    return intended_pct * 0.5


def should_add(
    pyramid_state: dict,
    current_price: float,
    current_atr: float,
    signal_still_valid: bool,  # re-run strategy, check if still buy
) -> dict | None:
    """Returns {add_size_pct: 0.25} if pyramid add warranted, else None."""
    if not signal_still_valid:
        return None

    phase = pyramid_state.get("phase", 0)
    avg_cost = pyramid_state.get("avg_cost", 0.0)
    add1_triggered = pyramid_state.get("add1_triggered", False)
    add2_triggered = pyramid_state.get("add2_triggered", False)

    if avg_cost <= 0 or current_atr <= 0:
        return None

    price_gain = current_price - avg_cost

    # Phase 0 → 1: Add1 at +1 ATR
    if phase < 1 and not add1_triggered:
        if price_gain >= current_atr * 1.0:
            logger.debug(
                "[pyramid] Add1 triggered: price_gain=%.4f >= 1x ATR=%.4f",
                price_gain, current_atr,
            )
            return {"add_size_pct": 0.25}

    # Phase 1 → 2: Add2 at +2 ATR
    if phase < 2 and add1_triggered and not add2_triggered:
        if price_gain >= current_atr * 2.0:
            logger.debug(
                "[pyramid] Add2 triggered: price_gain=%.4f >= 2x ATR=%.4f",
                price_gain, current_atr,
            )
            return {"add_size_pct": 0.25}

    return None


def should_trim(
    pyramid_state: dict,
    current_price: float,
    profile_config: dict,
) -> dict | None:
    """Returns {trim_size_pct: 0.333, reason: 'first_target'|'second_target'|'trail'} or None."""
    avg_cost = pyramid_state.get("avg_cost", 0.0)
    trim1_triggered = pyramid_state.get("trim1_triggered", False)
    trim2_triggered = pyramid_state.get("trim2_triggered", False)
    trail_active = pyramid_state.get("trail_active", False)

    if avg_cost <= 0:
        return None

    exit_cfg = profile_config.get("exit", {}) if profile_config else {}
    first_target_pct = exit_cfg.get("first_target_pct", 5.0)
    second_target_pct = exit_cfg.get("second_target_pct", 10.0)

    pnl_pct = ((current_price - avg_cost) / avg_cost) * 100 if avg_cost > 0 else 0.0

    # First trim: 1/3 at first_target_pct
    if not trim1_triggered and pnl_pct >= first_target_pct:
        logger.debug(
            "[pyramid] Trim1 triggered: pnl=%.2f%% >= first_target=%.2f%%",
            pnl_pct, first_target_pct,
        )
        return {"trim_size_pct": 1 / 3, "reason": "first_target"}

    # Second trim: 1/3 at second_target_pct
    if trim1_triggered and not trim2_triggered and pnl_pct >= second_target_pct:
        logger.debug(
            "[pyramid] Trim2 triggered: pnl=%.2f%% >= second_target=%.2f%%",
            pnl_pct, second_target_pct,
        )
        return {"trim_size_pct": 1 / 3, "reason": "second_target"}

    # Trail: activate after second trim (smart_stops handles actual trail price)
    if trim2_triggered and not trail_active:
        logger.debug("[pyramid] Trail activated after second trim")
        return {"trim_size_pct": 0.0, "reason": "trail"}  # size_pct=0 means just activate trail flag

    return None
