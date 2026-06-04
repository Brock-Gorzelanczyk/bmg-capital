"""
Volatility Target Sizer — Weekend 3, Module 3.  AQR 10% TARGET.

Scales position size so the portfolio targets 10% annualized volatility.
Position size = base_size × (target_vol / realized_vol_60d)
Capped at 2× base, floor 0.25× base.

Replaces the fixed position_size_pct in RiskManager with a dynamic
vol-adjusted quantity.

Reference: AQR Risk Parity methodology, Moreira & Muir (2017).
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

TARGET_VOL_ANNUAL = 0.10    # 10% annualized
MAX_MULTIPLIER = 2.0
MIN_MULTIPLIER = 0.25
DEFAULT_LOOKBACK_DAYS = 60


def compute_realized_vol(returns: np.ndarray, lookback: int = DEFAULT_LOOKBACK_DAYS) -> float:
    """
    Compute annualized realized volatility from daily returns.

    Parameters
    ----------
    returns : 1-D array of daily returns (e.g. 0.003 = +0.3%)
    lookback : number of trading days to use

    Returns
    -------
    Annualized vol as float (e.g. 0.15 = 15%)
    """
    if len(returns) < 5:
        return TARGET_VOL_ANNUAL  # default to target when no history
    window = returns[-lookback:]
    daily_vol = float(np.std(window))
    return daily_vol * np.sqrt(252)


def vol_adjusted_multiplier(
    asset_realized_vol: float,
    target_vol: float = TARGET_VOL_ANNUAL,
) -> float:
    """
    Compute the size multiplier: target_vol / asset_realized_vol.
    Clamped to [MIN_MULTIPLIER, MAX_MULTIPLIER].
    """
    if asset_realized_vol <= 0.001:
        return MAX_MULTIPLIER
    raw = target_vol / asset_realized_vol
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, raw))


def size_with_vol_target(
    base_shares: float,
    asset_returns: np.ndarray,
    target_vol: float = TARGET_VOL_ANNUAL,
    lookback: int = DEFAULT_LOOKBACK_DAYS,
) -> float:
    """
    Return vol-adjusted position size in shares/units.

    Parameters
    ----------
    base_shares : size from RiskManager.position_size() (pre-vol-adjust)
    asset_returns : historical daily returns for this asset
    target_vol : target annualized portfolio vol
    lookback : realized vol lookback window in days

    Returns
    -------
    Adjusted share quantity (float)
    """
    realized_vol = compute_realized_vol(asset_returns, lookback)
    multiplier = vol_adjusted_multiplier(realized_vol, target_vol)

    adjusted = base_shares * multiplier
    logger.debug(
        "[vol_target] realized_vol=%.2f%% target=%.2f%% multiplier=%.3f "
        "base=%.2f adjusted=%.2f",
        realized_vol * 100, target_vol * 100, multiplier, base_shares, adjusted,
    )
    return adjusted


class VolTargetSizer:
    """
    Stateful vol-target sizer that tracks return history per asset.

    Usage
    -----
    sizer = VolTargetSizer()
    sizer.update("AAPL", daily_return=0.003)
    shares = sizer.size("AAPL", base_shares=100)
    """

    def __init__(
        self,
        target_vol: float = TARGET_VOL_ANNUAL,
        lookback: int = DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self.target_vol = target_vol
        self.lookback = lookback
        self._returns: dict[str, list[float]] = {}

    def update(self, symbol: str, daily_return: float) -> None:
        """Feed daily return observation for a symbol."""
        if symbol not in self._returns:
            self._returns[symbol] = []
        self._returns[symbol].append(daily_return)
        # Keep rolling window
        if len(self._returns[symbol]) > self.lookback * 2:
            self._returns[symbol] = self._returns[symbol][-self.lookback:]

    def realized_vol(self, symbol: str) -> float:
        """Return current annualized realized vol for symbol."""
        data = self._returns.get(symbol, [])
        if not data:
            return self.target_vol
        return compute_realized_vol(np.array(data), self.lookback)

    def size(self, symbol: str, base_shares: float) -> float:
        """Return vol-adjusted position size."""
        rv = self.realized_vol(symbol)
        multiplier = vol_adjusted_multiplier(rv, self.target_vol)
        return base_shares * multiplier

    def multiplier(self, symbol: str) -> float:
        """Return vol multiplier for symbol (1.0 when on target)."""
        rv = self.realized_vol(symbol)
        return vol_adjusted_multiplier(rv, self.target_vol)

    def summary(self) -> dict[str, dict]:
        """Return vol stats for all tracked symbols."""
        return {
            sym: {
                "realized_vol_pct": round(self.realized_vol(sym) * 100, 2),
                "multiplier": round(self.multiplier(sym), 3),
                "n_observations": len(data),
            }
            for sym, data in self._returns.items()
        }
