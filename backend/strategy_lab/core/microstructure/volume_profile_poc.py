"""
Volume Profile — POC + Value Area — Weekend 7, Module 18.

Composite multi-day volume profile per ticker.
POC (Point of Control) = price bin with highest total traded volume.
Value Area = price range containing 70% of volume (VAH/VAL).

POC acts as a price magnet (price returns to POC).
VA edges are high-conviction support/resistance.
Distance-to-POC (normalized by ATR) is a signal feature.

Usage
-----
profile = VolumeProfile("AAPL")
profile.add_day(bars_list)    # list of {high, low, close, volume}
poc, vah, val = profile.key_levels()
feature = profile.distance_to_poc(current_price, atr)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

N_BINS = 100            # price bins per session
VALUE_AREA_PCT = 0.70   # 70% of volume defines value area


@dataclass
class VolumeProfileSnapshot:
    symbol: str
    poc: float          # point of control price
    vah: float          # value area high
    val: float          # value area low
    n_days: int
    total_volume: float
    price_low: float
    price_high: float


class VolumeProfile:
    """
    Multi-day composite volume profile.

    Accumulate bars across sessions. Key levels recompute on each call.
    """

    def __init__(self, symbol: str, n_bins: int = N_BINS) -> None:
        self.symbol = symbol
        self.n_bins = n_bins
        self._bins: Optional[np.ndarray] = None    # price bin edges
        self._volume: Optional[np.ndarray] = None  # volume per bin
        self._n_days = 0
        self._price_lo: float = 0.0
        self._price_hi: float = 0.0

    def add_day(self, bars: list[dict]) -> None:
        """
        Add one trading session's bars to the composite profile.

        Parameters
        ----------
        bars : list of dicts with keys: high, low, close, volume
        """
        if not bars:
            return

        prices = [(b["high"] + b["low"]) / 2 for b in bars]
        volumes = [b["volume"] for b in bars]
        day_lo = min(b["low"] for b in bars)
        day_hi = max(b["high"] for b in bars)

        if self._bins is None:
            self._price_lo = day_lo
            self._price_hi = day_hi
            self._bins = np.linspace(day_lo, day_hi, self.n_bins + 1)
            self._volume = np.zeros(self.n_bins)
        else:
            # Extend range if needed
            new_lo = min(self._price_lo, day_lo)
            new_hi = max(self._price_hi, day_hi)
            if new_lo < self._price_lo or new_hi > self._price_hi:
                new_bins = np.linspace(new_lo, new_hi, self.n_bins + 1)
                # Re-map existing volume to new bins
                old_vol = self._volume.copy()
                old_bins = self._bins.copy()
                self._bins = new_bins
                self._volume = np.zeros(self.n_bins)
                for i, v in enumerate(old_vol):
                    mid = (old_bins[i] + old_bins[i + 1]) / 2
                    idx = int(np.searchsorted(new_bins, mid, side="right")) - 1
                    idx = max(0, min(self.n_bins - 1, idx))
                    self._volume[idx] += v
                self._price_lo = new_lo
                self._price_hi = new_hi

        # Accumulate today's volume into bins
        for price, vol in zip(prices, volumes):
            idx = int(np.searchsorted(self._bins, price, side="right")) - 1
            idx = max(0, min(self.n_bins - 1, idx))
            self._volume[idx] += vol

        self._n_days += 1

    def key_levels(self) -> VolumeProfileSnapshot:
        """Compute POC, VAH, VAL from accumulated profile."""
        if self._volume is None or self._volume.sum() == 0:
            mid = (self._price_lo + self._price_hi) / 2 or 100.0
            return VolumeProfileSnapshot(
                symbol=self.symbol, poc=mid, vah=mid, val=mid,
                n_days=self._n_days, total_volume=0.0,
                price_low=self._price_lo, price_high=self._price_hi,
            )

        bin_mids = (self._bins[:-1] + self._bins[1:]) / 2
        poc_idx = int(np.argmax(self._volume))
        poc = float(bin_mids[poc_idx])

        # Value Area: expand from POC until we cover 70% of total volume
        total_vol = float(self._volume.sum())
        target = total_vol * VALUE_AREA_PCT
        lo_idx = poc_idx
        hi_idx = poc_idx
        cumvol = float(self._volume[poc_idx])

        while cumvol < target and (lo_idx > 0 or hi_idx < self.n_bins - 1):
            # Expand to whichever side has more volume
            add_lo = float(self._volume[lo_idx - 1]) if lo_idx > 0 else 0.0
            add_hi = float(self._volume[hi_idx + 1]) if hi_idx < self.n_bins - 1 else 0.0
            if add_lo >= add_hi and lo_idx > 0:
                lo_idx -= 1
                cumvol += add_lo
            elif hi_idx < self.n_bins - 1:
                hi_idx += 1
                cumvol += add_hi
            elif lo_idx > 0:
                lo_idx -= 1
                cumvol += add_lo
            else:
                break

        return VolumeProfileSnapshot(
            symbol=self.symbol,
            poc=round(poc, 4),
            vah=round(float(bin_mids[hi_idx]), 4),
            val=round(float(bin_mids[lo_idx]), 4),
            n_days=self._n_days,
            total_volume=round(total_vol, 0),
            price_low=round(self._price_lo, 4),
            price_high=round(self._price_hi, 4),
        )

    def distance_to_poc_atr(self, current_price: float, atr: float) -> float:
        """
        Return (current_price - POC) / ATR — normalized distance.
        Positive = above POC, Negative = below POC.
        """
        snap = self.key_levels()
        if atr <= 0:
            return 0.0
        return round((current_price - snap.poc) / atr, 3)

    def is_in_value_area(self, price: float) -> bool:
        snap = self.key_levels()
        return snap.val <= price <= snap.vah

    def reset(self) -> None:
        self._bins = None
        self._volume = None
        self._n_days = 0


_profiles: dict[str, VolumeProfile] = {}


def get_profile(symbol: str) -> VolumeProfile:
    if symbol not in _profiles:
        _profiles[symbol] = VolumeProfile(symbol)
    return _profiles[symbol]
