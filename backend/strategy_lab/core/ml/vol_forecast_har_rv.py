"""
HAR-RV Volatility Forecaster — Priority 8.

Heterogeneous Autoregressive model for Realized Volatility.
Uses daily (d), weekly (w=5d), and monthly (m=22d) realized vol
as predictors to forecast tomorrow's RV.

Forecast is used to:
  1. Scale position size via vol_target_sizer (before ML Phase 3)
  2. Gate option-selling strategies (avoid selling into vol expansion)
  3. Surface predicted vol on bot detail page

Reference: Corsi (2009) — A Simple Approximate Long-Memory Model
           for the Realized Volatility, SSRN 626064.

Usage
-----
model = HARRVModel()
model.fit(rv_series)                     # 1-D array of daily realized vol
tomorrow_vol = model.forecast(rv_series) # annualized float
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class HARRVModel:
    """
    HAR-RV: RV(t+1) = c + β_d·RV_d(t) + β_w·RV_w(t) + β_m·RV_m(t) + ε

    Fit via OLS.  Parameters stored as attributes after fit().
    """

    def __init__(self) -> None:
        self.c: float = 0.0
        self.beta_d: float = 0.4
        self.beta_w: float = 0.3
        self.beta_m: float = 0.3
        self._fitted = False

    # ── Public API ──────────────────────────────────────────────────────────

    def fit(self, rv: np.ndarray) -> None:
        """
        Fit HAR-RV on historical realized volatility.

        Parameters
        ----------
        rv : 1-D array of daily realized volatility values (annualized).
             Minimum 30 observations; 252+ recommended.
        """
        rv = np.asarray(rv, dtype=float)
        if len(rv) < 30:
            logger.warning("[har_rv] insufficient data (%d obs) — using defaults", len(rv))
            return

        # Build feature matrix
        X, y = self._build_features(rv)
        if len(X) < 10:
            logger.warning("[har_rv] insufficient lagged observations — using defaults")
            return

        # OLS: β = (X'X)^-1 X'y
        try:
            # Add intercept column
            X_aug = np.column_stack([np.ones(len(X)), X])
            beta, _, _, _ = np.linalg.lstsq(X_aug, y, rcond=None)
            self.c = float(beta[0])
            self.beta_d = float(beta[1])
            self.beta_w = float(beta[2])
            self.beta_m = float(beta[3])
            self._fitted = True
            logger.info(
                "[har_rv] fitted: c=%.4f β_d=%.4f β_w=%.4f β_m=%.4f",
                self.c, self.beta_d, self.beta_w, self.beta_m,
            )
        except np.linalg.LinAlgError as exc:
            logger.warning("[har_rv] OLS failed: %s", exc)

    def forecast(self, rv: np.ndarray) -> float:
        """
        Forecast tomorrow's annualized realized volatility.

        Parameters
        ----------
        rv : recent realized vol series (at least 22 observations)

        Returns
        -------
        Forecasted annualized vol (float).  Returns last rv if insufficient data.
        """
        rv = np.asarray(rv, dtype=float)
        if len(rv) < 22:
            return float(rv[-1]) if len(rv) > 0 else 0.15

        rv_d = rv[-1]
        rv_w = float(np.mean(rv[-5:]))
        rv_m = float(np.mean(rv[-22:]))

        forecast = self.c + self.beta_d * rv_d + self.beta_w * rv_w + self.beta_m * rv_m
        # Clamp to reasonable range
        return max(0.05, min(2.0, float(forecast)))

    def forecast_horizon(self, rv: np.ndarray, horizon: int = 5) -> list[float]:
        """
        Multi-step iterative forecast.

        For h steps ahead, use the previous forecast as RV_d input.
        """
        series = list(rv[-22:])  # keep a rolling window
        forecasts: list[float] = []
        for _ in range(horizon):
            f = self.forecast(np.array(series))
            forecasts.append(f)
            series.append(f)
            series = series[-22:]
        return forecasts

    # ── Realized Vol Computation ─────────────────────────────────────────────

    @staticmethod
    def compute_rv(returns: np.ndarray, window: int = 1) -> np.ndarray:
        """
        Compute daily realized volatility (annualized) from intraday returns.

        For daily returns: RV_d = std(returns[-window:]) * sqrt(252).
        For 5-min bars: sum of squared returns per day * sqrt(252).
        """
        returns = np.asarray(returns, dtype=float)
        if window == 1:
            # Rolling realized vol from daily returns
            rv = np.array([
                float(np.std(returns[max(0, i - 20):i + 1]) * np.sqrt(252))
                for i in range(len(returns))
            ])
        else:
            rv = np.array([
                float(np.std(returns[max(0, i - window):i + 1]) * np.sqrt(252))
                for i in range(len(returns))
            ])
        return rv

    # ── Private ──────────────────────────────────────────────────────────────

    def _build_features(self, rv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Build (X, y) matrices for OLS fitting."""
        min_lag = 22
        X_rows, y_rows = [], []
        for t in range(min_lag, len(rv) - 1):
            rv_d = rv[t]
            rv_w = float(np.mean(rv[t - 4:t + 1]))
            rv_m = float(np.mean(rv[t - 21:t + 1]))
            X_rows.append([rv_d, rv_w, rv_m])
            y_rows.append(rv[t + 1])
        return np.array(X_rows), np.array(y_rows)


# ── Convenience functions ────────────────────────────────────────────────────

_model_cache: dict[str, HARRVModel] = {}


def get_har_model(symbol: str) -> HARRVModel:
    if symbol not in _model_cache:
        _model_cache[symbol] = HARRVModel()
    return _model_cache[symbol]


def forecast_vol(symbol: str, returns: np.ndarray) -> float:
    """
    Fit (or reuse) a HAR model for `symbol` and return tomorrow's vol forecast.

    Parameters
    ----------
    symbol : ticker for model registry
    returns : 1-D array of daily log returns (252+ recommended)

    Returns
    -------
    Annualized volatility forecast for next trading day.
    """
    model = get_har_model(symbol)
    rv = HARRVModel.compute_rv(returns)
    if not model._fitted:
        model.fit(rv)
    return model.forecast(rv)
