"""Funding Rate Carry — long spot / short perp when funding rate > 0.05%/8hr.

PAPER SIMULATION ONLY — this strategy simulates cash-and-carry arbitrage.
It does NOT execute real perpetual futures trades.

BLOCKED: Requires live perpetual futures funding rate feed (Binance/Bybit API).
Without funding data, this candidate is flagged BLOCKED and will not fire signals.

Strategy:
  - When BTC perp funding rate > 0.05% per 8hr: enter long spot + conceptual short perp
  - When funding rate drops to 0 or negative: exit
  - Paper-tracks the carry income
"""
from __future__ import annotations

import logging
import os
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "id":             "funding_rate_carry",
    "name":           "Funding Rate Carry",
    "asset_class":    "crypto",
    "strategy_type":  "carry",
    "universe":       ["BTC/USD"],
    "cadence":        "daily",
    "claimed_sharpe": 1.5,
    "evidence_tier":  1,
    "complexity":     "high",
    "description":    "Long spot + short perp when funding > 0.05%/8hr — PAPER SIMULATION ONLY",
    "blocked":        True,
    "blocked_reason": "Requires live perpetual futures funding rate feed (Binance/Bybit API). "
                      "Stub implementation until funding data is connected.",
    "data_dependencies": ["perpetual_funding_rate_btc"],
}

STRATEGY_NAME = "funding_rate_carry"

_FUNDING_THRESHOLD = 0.0005  # 0.05% per 8hr


def _get_live_funding_rate() -> float | None:
    """Fetch BTC perpetual funding rate. Returns None if feed unavailable."""
    try:
        import requests
        # Binance public API — no auth required
        url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            data = resp.json()
            return float(data.get("lastFundingRate", 0))
    except Exception:
        pass
    return None


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    funding = _get_live_funding_rate()

    if funding is None:
        logger.debug("[funding_rate_carry] BLOCKED — no funding rate feed available")
        return []

    if funding < _FUNDING_THRESHOLD:
        return []

    conf = min(0.80, 0.55 + funding / 0.002)
    return [Signal(
        symbol="BTC/USD", side="buy", confidence=conf, size_hint=0.25,
        reason=f"Funding rate carry: BTC funding {funding:.4%}/8hr > {_FUNDING_THRESHOLD:.4%} threshold — PAPER sim",
        strategy=STRATEGY_NAME,
    )]
