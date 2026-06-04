"""
VWAP Volume Curve Execution — Weekend 6, Module 11.

Slices a parent order proportionally to the intraday volume forecast.
Fits a U-shaped volume curve from the last 20 trading days and dispatches
child orders that participate at each time bucket's forecasted volume share.

Re-rates each bucket against realized volume — if actual volume is 2× forecast,
we trade 2× the slice. Ensures we never miss participation opportunities.

Use when: urgency low + order size > 0.5% of ADV.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default U-shape weights for 13 half-hour buckets (9:30–4:00)
# Reflects typical market microstructure: high open, moderate midday, high close
DEFAULT_VOLUME_PROFILE = np.array([
    0.120,  # 9:30–10:00
    0.085,  # 10:00–10:30
    0.075,  # 10:30–11:00
    0.065,  # 11:00–11:30
    0.058,  # 11:30–12:00
    0.052,  # 12:00–12:30
    0.050,  # 12:30–13:00
    0.055,  # 13:00–13:30
    0.060,  # 13:30–14:00
    0.065,  # 14:00–14:30
    0.070,  # 14:30–15:00
    0.085,  # 15:00–15:30
    0.160,  # 15:30–16:00  ← close auction spike
])


@dataclass
class VWAPSlice:
    bucket_idx: int          # 0–12 (half-hour buckets)
    time_label: str          # "09:30", "10:00", ...
    forecast_vol_share: float
    shares_targeted: float
    shares_executed: float = 0.0
    vwap_px: Optional[float] = None


class VWAPVolumeCurve:
    """
    Fits historical volume curves and builds adaptive VWAP execution plan.
    """

    BUCKET_LABELS = [
        "09:30", "10:00", "10:30", "11:00", "11:30", "12:00",
        "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30",
    ]

    def __init__(self) -> None:
        self._fitted_profiles: dict[str, np.ndarray] = {}

    def fit(self, symbol: str, historical_volume_by_bucket: list[list[float]]) -> None:
        """
        Fit volume curve from historical data.

        Parameters
        ----------
        symbol : ticker
        historical_volume_by_bucket : list of 20 days, each a list of 13 bucket volumes
        """
        if not historical_volume_by_bucket:
            return
        matrix = np.array(historical_volume_by_bucket)  # (days, 13)
        avg = matrix.mean(axis=0)
        total = avg.sum()
        if total > 0:
            profile = avg / total
            self._fitted_profiles[symbol] = profile
            logger.info("[vwap_curve] fitted %s profile from %d days", symbol, len(matrix))

    def get_profile(self, symbol: str) -> np.ndarray:
        """Return fitted profile for symbol, or default U-shape."""
        return self._fitted_profiles.get(symbol, DEFAULT_VOLUME_PROFILE).copy()

    def build_plan(
        self,
        symbol: str,
        total_shares: float,
        start_bucket: int = 0,
        end_bucket: int = 12,
    ) -> list[VWAPSlice]:
        """
        Build VWAP execution plan for a given bucket window.

        Parameters
        ----------
        symbol : ticker
        total_shares : parent order quantity
        start_bucket : first bucket index to trade (0 = 9:30)
        end_bucket : last bucket index (inclusive)

        Returns
        -------
        list of VWAPSlice with targeted shares per bucket
        """
        profile = self.get_profile(symbol)
        window = profile[start_bucket: end_bucket + 1]
        window_sum = window.sum()
        if window_sum <= 0:
            window = np.ones(end_bucket - start_bucket + 1)
            window_sum = window.sum()

        normalized = window / window_sum
        slices = []
        for i, share in enumerate(normalized):
            bucket = start_bucket + i
            slices.append(VWAPSlice(
                bucket_idx=bucket,
                time_label=self.BUCKET_LABELS[bucket] if bucket < len(self.BUCKET_LABELS) else str(bucket),
                forecast_vol_share=round(float(share), 4),
                shares_targeted=round(total_shares * float(share), 4),
            ))
        return slices

    def rerate(
        self,
        plan: list[VWAPSlice],
        current_bucket: int,
        realized_volume: float,
        forecasted_volume: float,
    ) -> list[VWAPSlice]:
        """
        Adjust remaining slices based on realized vs forecasted volume in current bucket.

        If realized > 2× forecast, scale up remaining participation.
        If realized < 0.5× forecast, scale down.
        """
        if forecasted_volume <= 0:
            return plan

        vol_ratio = min(2.0, max(0.5, realized_volume / forecasted_volume))
        for slc in plan:
            if slc.bucket_idx > current_bucket and slc.shares_executed == 0:
                slc.shares_targeted = round(slc.shares_targeted * vol_ratio, 4)

        logger.debug(
            "[vwap_curve] re-rated bucket %d: realized/forecast=%.2f",
            current_bucket, vol_ratio,
        )
        return plan


_curve = VWAPVolumeCurve()


def get_vwap_curve() -> VWAPVolumeCurve:
    return _curve
