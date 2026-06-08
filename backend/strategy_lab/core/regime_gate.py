"""Regime gate — position-size multiplier based on VIX regime.

Called before _execute_signal for stock_day and stock_swing only.
Returns 0.0 to halt new entries, 0.5 to halve size, 1.0 for full size.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_VIX_EXTREME_THRESHOLD = 40.0
_VIX_HIGH_THRESHOLD = 25.0


def _classify_vix(vix: float) -> str:
    if vix >= _VIX_EXTREME_THRESHOLD:
        return "extreme"
    if vix >= _VIX_HIGH_THRESHOLD:
        return "high"
    return "normal"


def regime_position_size_multiplier(bot_config: dict, regime_snapshot: dict | None = None) -> float:
    """Return a size multiplier derived from the current VIX regime.

    Priority: pre-computed regime_snapshot > live VIX fetch.
    """
    overrides = bot_config.get("regime_overrides", {})
    regime = regime_snapshot or {}

    vix_regime = regime.get("vix_regime", "")
    if not vix_regime:
        try:
            from app.services.live_prices import fetch_live_prices
            vix_map = fetch_live_prices(["VIX"])
            vix_val = float(vix_map.get("VIX") or vix_map.get("^VIX") or 0)
            if vix_val > 0:
                vix_regime = _classify_vix(vix_val)
                logger.debug("[regime_gate] live VIX=%.1f → %s", vix_val, vix_regime)
        except Exception as exc:
            logger.warning("[regime_gate] VIX fetch failed: %s", exc)

    if vix_regime in ("extreme", "panic"):
        if overrides.get("vix_extreme_halt_new_entries", True):
            logger.warning("[regime_gate] VIX %s — halting new entries", vix_regime)
            return 0.0

    if vix_regime == "high":
        mult = float(overrides.get("vix_high_position_size_multiplier", 0.5))
        logger.info("[regime_gate] VIX high — size_multiplier=%.2f", mult)
        return mult

    return 1.0
