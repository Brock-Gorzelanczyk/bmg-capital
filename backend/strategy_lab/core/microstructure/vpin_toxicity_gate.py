"""
VPIN Flow Toxicity Gate — Weekend 7, Module 19.

Volume-Synchronized Probability of Informed Trading.
Predicted the May 2010 Flash Crash with a 2-hour lead.

When VPIN > 0.7:
  - Pull all passive limit orders
  - Switch to aggressive marketable orders only
  - Toxic flow punishes passive participants

VPIN computed from buy/sell-classified volume buckets.
Each bucket = V/50 of daily ADV (volume-synchronized, not time-synchronized).

Reference: Easley, López de Prado, O'Hara (2012) — "Flow Toxicity and
           Liquidity in a High Frequency World"
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque

import numpy as np

logger = logging.getLogger(__name__)

VPIN_TOXIC_THRESHOLD = 0.70
VPIN_WARNING_THRESHOLD = 0.55
N_BUCKETS = 50          # VPIN computed over last 50 volume buckets
BUCKET_VOLUME_FRACTION = 1 / 50  # each bucket = 1/50 of daily ADV


class VPINCalculator:
    """
    Online VPIN calculator using volume-clock bucketing.

    Feed each trade print via update(). VPIN updates in real-time.
    """

    def __init__(
        self,
        adv_shares: float,
        n_buckets: int = N_BUCKETS,
        bucket_fraction: float = BUCKET_VOLUME_FRACTION,
    ) -> None:
        self._adv = adv_shares
        self._n_buckets = n_buckets
        self._bucket_vol = adv_shares * bucket_fraction
        self._current_buy = 0.0
        self._current_sell = 0.0
        self._current_total = 0.0
        self._buckets: Deque[tuple[float, float]] = deque()  # (buy_vol, sell_vol) per bucket
        self._vpin: float = 0.5  # initialize to neutral

    def update(self, buy_volume: float, sell_volume: float) -> float:
        """
        Feed volume classified by aggressor side (from LeeReadyClassifier).

        Returns current VPIN estimate.
        """
        self._current_buy += buy_volume
        self._current_sell += sell_volume
        self._current_total += buy_volume + sell_volume

        # Check if we've filled a bucket
        while self._current_total >= self._bucket_vol:
            # Proportionally allocate bucket volume
            bucket_total = self._bucket_vol
            fraction = bucket_total / max(self._current_total, 1e-10)
            b_buy = self._current_buy * fraction
            b_sell = self._current_sell * fraction

            self._buckets.append((b_buy, b_sell))
            if len(self._buckets) > self._n_buckets:
                self._buckets.popleft()

            self._current_buy -= b_buy
            self._current_sell -= b_sell
            self._current_total -= bucket_total

            self._vpin = self._compute_vpin()

        return self._vpin

    def vpin(self) -> float:
        return self._vpin

    def is_toxic(self) -> bool:
        return self._vpin >= VPIN_TOXIC_THRESHOLD

    def regime(self) -> str:
        if self._vpin >= VPIN_TOXIC_THRESHOLD:
            return "toxic"
        if self._vpin >= VPIN_WARNING_THRESHOLD:
            return "elevated"
        return "normal"

    def update_adv(self, new_adv: float) -> None:
        """Recalibrate bucket size when ADV changes (e.g. daily update)."""
        self._adv = new_adv
        self._bucket_vol = new_adv * BUCKET_VOLUME_FRACTION

    def _compute_vpin(self) -> float:
        if not self._buckets:
            return 0.5
        imbalances = [abs(b - s) / max(b + s, 1e-10) for b, s in self._buckets]
        return round(float(np.mean(imbalances)), 4)


def make_gate(
    vpin_calc: VPINCalculator,
) -> dict:
    """
    Return an execution gate instruction based on current VPIN.

    Returns dict:
      passive_allowed : bool — whether passive limit orders are safe
      order_type_recommendation : str — "passive" | "aggressive" | "halt"
      vpin : float
      regime : str
    """
    v = vpin_calc.vpin()
    r = vpin_calc.regime()

    if v >= VPIN_TOXIC_THRESHOLD:
        logger.warning("[vpin] TOXIC flow detected (VPIN=%.3f) — pulling passives", v)
        return {
            "passive_allowed": False,
            "order_type_recommendation": "aggressive",
            "vpin": v,
            "regime": r,
            "message": f"VPIN={v:.3f} — toxic flow. Use aggressive orders only.",
        }
    elif v >= VPIN_WARNING_THRESHOLD:
        return {
            "passive_allowed": True,
            "order_type_recommendation": "neutral",
            "vpin": v,
            "regime": r,
            "message": f"VPIN={v:.3f} — elevated toxicity. Tighten limit prices.",
        }
    else:
        return {
            "passive_allowed": True,
            "order_type_recommendation": "passive",
            "vpin": v,
            "regime": r,
            "message": f"VPIN={v:.3f} — normal flow. Passive orders safe.",
        }


_calculators: dict[str, VPINCalculator] = {}


def get_vpin_calc(symbol: str, adv_shares: float = 1_000_000) -> VPINCalculator:
    if symbol not in _calculators:
        _calculators[symbol] = VPINCalculator(adv_shares)
    return _calculators[symbol]
