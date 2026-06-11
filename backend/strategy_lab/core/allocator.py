"""
strategy_lab/core/allocator.py

Pure analytics / recommendations module.
Computes optimal portfolio weights using vol-targeted fractional Kelly
with Ledoit-Wolf shrunk covariance.

ADVISORY ONLY — never writes YAML files, trading configs, or live orders.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Optional Ledoit-Wolf import — gracefully degrade to identity covariance
# ---------------------------------------------------------------------------
try:
    from sklearn.covariance import LedoitWolf as _LedoitWolf  # type: ignore

    _LEDOIT_WOLF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LedoitWolf = None  # type: ignore
    _LEDOIT_WOLF_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DRAWDOWN_LADDER: list[tuple[float, float]] = [
    (0.10, 0.75),  # 10% DD → multiply allocation by 0.75
    (0.20, 0.50),  # 20% DD → multiply by 0.50
    (0.30, 0.25),  # 30% DD → multiply by 0.25
]

BOT_RECOMMENDED_ALLOCATION_DDL = """
CREATE TABLE IF NOT EXISTS bot_recommended_allocation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    current_capital_pct REAL,
    recommended_capital_pct REAL,
    delta_pct REAL,
    kelly_raw REAL,
    kelly_fractional REAL,
    vol_target_adj REAL,
    drawdown_adj REAL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bot_id, snapshot_date)
);
"""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BotMetricsInput:
    """All inputs needed for a single bot's allocation calculation."""

    bot_id: str
    sharpe: float  # annualized Sharpe ratio
    returns: list[float]  # daily returns as decimals (e.g. 0.015 = 1.5%)
    current_capital_pct: float  # current allocation as fraction of total (e.g. 0.10 = 10%)
    peak_value: float = 1.0  # normalized peak value
    current_value: float = 1.0  # normalized current value


@dataclass
class AllocationRecommendation:
    """Advisory output for a single bot."""

    bot_id: str
    current_capital_pct: float
    recommended_capital_pct: float
    delta_pct: float
    kelly_raw: float  # unconstrained Kelly fraction
    kelly_fractional: float  # after kelly_fraction multiplier
    vol_target_adj: float  # vol-targeting adjustment factor
    drawdown_adj: float  # drawdown ladder multiplier (0.25–1.0)
    reason: str


# ---------------------------------------------------------------------------
# Main allocator class
# ---------------------------------------------------------------------------


class BotAllocator:
    """
    Computes advisory portfolio weights for a collection of trading bots.

    Weight pipeline (per bot):
      1. Raw Kelly  = mean(r) / var(r)
      2. Fractional Kelly = kelly_raw * kelly_fraction
      3. Vol-target adjustment: scale so realized vol ≈ target_portfolio_vol
      4. (Optional) Ledoit-Wolf correlation adjustment
      5. Clip to [min_single_bot_weight, max_single_bot_weight]
      6. Normalize to sum = total_capital
      7. Drawdown ladder multiplier

    This class is purely advisory and never modifies any config files.
    """

    def __init__(
        self,
        target_portfolio_vol: float = 0.15,  # 15% annual
        kelly_fraction: float = 0.25,  # quarter-Kelly
        max_single_bot_weight: float = 0.30,  # 30% cap
        min_single_bot_weight: float = 0.02,  # 2% floor
        vol_lookback_days: int = 63,  # ~1 quarter
        ewma_lambda: float = 0.94,
        use_ewma: bool = True,
    ) -> None:
        if not (0.0 < target_portfolio_vol <= 1.0):
            raise ValueError("target_portfolio_vol must be in (0, 1].")
        if not (0.0 < kelly_fraction <= 1.0):
            raise ValueError("kelly_fraction must be in (0, 1].")
        if not (0.0 <= min_single_bot_weight < max_single_bot_weight <= 1.0):
            raise ValueError(
                "Require 0 <= min_single_bot_weight < max_single_bot_weight <= 1."
            )
        if not (0.0 < ewma_lambda < 1.0):
            raise ValueError("ewma_lambda must be in (0, 1).")

        self.target_portfolio_vol = target_portfolio_vol
        self.kelly_fraction = kelly_fraction
        self.max_single_bot_weight = max_single_bot_weight
        self.min_single_bot_weight = min_single_bot_weight
        self.vol_lookback_days = vol_lookback_days
        self.ewma_lambda = ewma_lambda
        self.use_ewma = use_ewma

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_portfolio_allocation(
        self,
        bot_metrics: list[BotMetricsInput],
        total_capital: float = 1.0,
        use_correlation_adjustment: bool = True,
    ) -> list[AllocationRecommendation]:
        """
        Full allocation pipeline. Returns one AllocationRecommendation per bot.

        Parameters
        ----------
        bot_metrics:
            Per-bot metrics inputs. Must be non-empty.
        total_capital:
            Target sum of all weights (default 1.0 = 100%).
        use_correlation_adjustment:
            Whether to apply Ledoit-Wolf covariance scaling. Skipped if only
            one bot or if sklearn is unavailable (falls back gracefully).

        Returns
        -------
        list[AllocationRecommendation]
            One entry per bot, in the same order as bot_metrics.
        """
        if not bot_metrics:
            raise ValueError("bot_metrics must contain at least one BotMetricsInput.")
        if total_capital <= 0:
            raise ValueError("total_capital must be positive.")

        n = len(bot_metrics)
        bot_ids = [b.bot_id for b in bot_metrics]

        # --- Step 1 + 2: Kelly raw & fractional --------------------------------
        kelly_raws: list[float] = []
        kelly_fractionals: list[float] = []
        for bm in bot_metrics:
            kr = self._compute_kelly_raw(bm.returns)
            kf = kr * self.kelly_fraction
            kelly_raws.append(kr)
            kelly_fractionals.append(kf)

        # --- Step 3: Vol-target adjustment --------------------------------------
        bot_vols: list[float] = []
        vol_target_factors: list[float] = []
        for bm in bot_metrics:
            # _compute_bot_vol returns a sentinel (target_portfolio_vol) when
            # there are fewer than 10 observations, signalling "no adjustment".
            insufficient_data = len(bm.returns) < 10
            bot_vol = self._compute_bot_vol(bm.returns)
            bot_vols.append(bot_vol)
            if insufficient_data:
                # Spec: fewer than 10 returns → vol_target_adj = 1.0 (no scaling)
                factor = 1.0
            elif bot_vol > 0:
                factor = self.target_portfolio_vol / (bot_vol * math.sqrt(252))
            else:
                factor = 1.0
            vol_target_factors.append(factor)

        weights: list[float] = [
            kf * vf for kf, vf in zip(kelly_fractionals, vol_target_factors)
        ]

        # --- Step 4: Ledoit-Wolf correlation adjustment -------------------------
        lw_adjustments: list[float] = [1.0] * n  # default: no adjustment

        if use_correlation_adjustment and n > 1:
            lw_adjustments = self._apply_ledoit_wolf_adjustment(
                bot_metrics=bot_metrics,
                raw_weights=weights,
            )
            weights = [w * adj for w, adj in zip(weights, lw_adjustments)]

        # --- Step 5: Clip ---------------------------------------------------
        weights = [
            float(np.clip(w, self.min_single_bot_weight, self.max_single_bot_weight))
            for w in weights
        ]

        # --- Step 6: Normalize -----------------------------------------------
        weight_sum = sum(weights)
        if weight_sum > 0:
            weights = [w / weight_sum * total_capital for w in weights]
        else:
            # Fallback: equal weight
            logger.warning(
                "All computed weights are zero; falling back to equal weighting."
            )
            eq = total_capital / n
            weights = [eq] * n

        # --- Step 7: Drawdown ladder -----------------------------------------
        weight_dict = dict(zip(bot_ids, weights))
        current_values = {bm.bot_id: bm.current_value for bm in bot_metrics}
        peak_values = {bm.bot_id: bm.peak_value for bm in bot_metrics}
        dd_adjs: dict[str, float] = {}
        adjusted_weight_dict = self.apply_drawdown_adjustment(
            weights=weight_dict,
            current_values=current_values,
            peak_values=peak_values,
        )
        # Record individual DD multipliers
        for bot_id in bot_ids:
            orig = weight_dict.get(bot_id, 0.0)
            adj = adjusted_weight_dict.get(bot_id, 0.0)
            dd_adjs[bot_id] = (adj / orig) if orig > 0 else 1.0

        # --- Assemble recommendations ----------------------------------------
        recommendations: list[AllocationRecommendation] = []
        for i, bm in enumerate(bot_metrics):
            rec_pct = adjusted_weight_dict.get(bm.bot_id, 0.0)
            reason = self._build_reason(
                kelly_raw=kelly_raws[i],
                kelly_fractional=kelly_fractionals[i],
                vol_target_adj=vol_target_factors[i],
                drawdown_adj=dd_adjs[bm.bot_id],
                bot_vol=bot_vols[i],
            )
            recommendations.append(
                AllocationRecommendation(
                    bot_id=bm.bot_id,
                    current_capital_pct=bm.current_capital_pct,
                    recommended_capital_pct=rec_pct,
                    delta_pct=rec_pct - bm.current_capital_pct,
                    kelly_raw=kelly_raws[i],
                    kelly_fractional=kelly_fractionals[i],
                    vol_target_adj=vol_target_factors[i],
                    drawdown_adj=dd_adjs[bm.bot_id],
                    reason=reason,
                )
            )

        return recommendations

    def apply_drawdown_adjustment(
        self,
        weights: dict[str, float],
        current_values: dict[str, float],
        peak_values: dict[str, float],
        drawdown_ladder: Optional[list[tuple[float, float]]] = None,
    ) -> dict[str, float]:
        """
        Scales each bot's weight down based on its current drawdown.

        For each bot:
          - drawdown = (peak - current) / peak
          - Find the highest ladder threshold that the drawdown meets or exceeds
          - Multiply weight by that threshold's factor

        Parameters
        ----------
        weights:
            {bot_id: weight} mapping (pre-drawdown).
        current_values:
            {bot_id: current_normalized_value}
        peak_values:
            {bot_id: peak_normalized_value}
        drawdown_ladder:
            List of (dd_threshold, multiplier) tuples. Uses DEFAULT_DRAWDOWN_LADDER
            if None.

        Returns
        -------
        dict[str, float]
            Adjusted weights.
        """
        if drawdown_ladder is None:
            drawdown_ladder = DEFAULT_DRAWDOWN_LADDER

        # Sort descending by threshold so we pick the most severe matching step
        ladder_sorted = sorted(drawdown_ladder, key=lambda t: t[0], reverse=True)

        adjusted: dict[str, float] = {}
        for bot_id, w in weights.items():
            peak = peak_values.get(bot_id, 1.0)
            current = current_values.get(bot_id, peak)

            if peak <= 0:
                logger.warning(
                    "Bot %s has non-positive peak value %.4f; skipping DD adjustment.",
                    bot_id,
                    peak,
                )
                adjusted[bot_id] = w
                continue

            dd = (peak - current) / peak
            dd = max(round(dd, 10), 0.0)  # round off floating-point noise; guard current > peak

            factor = 1.0
            for threshold, multiplier in ladder_sorted:
                if dd >= threshold:
                    factor = multiplier
                    break

            if factor < 1.0:
                logger.debug(
                    "Bot %s DD=%.1f%% → applying factor %.2f",
                    bot_id,
                    dd * 100,
                    factor,
                )

            adjusted[bot_id] = w * factor

        return adjusted

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_kelly_raw(self, returns: list[float]) -> float:
        """
        Raw (unconstrained) Kelly fraction.

        kelly_raw = mean(r) / var(r)

        Returns 0.0 if variance is zero or returns list is empty.
        """
        if not returns:
            return 0.0
        arr = np.array(returns, dtype=float)
        mean_r = float(np.mean(arr))
        var_r = float(np.var(arr, ddof=0))
        if var_r <= 0:
            return 0.0
        return mean_r / var_r

    def _compute_bot_vol(self, returns: list[float]) -> float:
        """
        Realized (annualized) daily volatility for a single bot.

        - If use_ewma=True: EWMA variance with lambda=self.ewma_lambda
            var_t = λ·var_{t-1} + (1-λ)·r_t²
          then annualized_vol = sqrt(ewma_var * 252)
        - Otherwise: rolling std over the last vol_lookback_days observations,
          annualized as sqrt(252).
        - If fewer than 10 returns are provided: returns self.target_portfolio_vol
          so that vol_target_factor = 1.0 (no adjustment).
        """
        if len(returns) < 10:
            # Not enough data — treat bot vol as equal to target so factor=1
            return self.target_portfolio_vol

        arr = np.array(returns[-self.vol_lookback_days :], dtype=float)

        if self.use_ewma:
            lam = self.ewma_lambda
            ewma_var = float(np.var(arr[:1], ddof=0))  # seed with first obs variance
            for r in arr[1:]:
                ewma_var = lam * ewma_var + (1.0 - lam) * r**2
            daily_vol = math.sqrt(max(ewma_var, 0.0))
        else:
            daily_vol = float(np.std(arr, ddof=1))

        # Annualize
        annual_vol = daily_vol * math.sqrt(252)
        return annual_vol if annual_vol > 0 else self.target_portfolio_vol

    def _apply_ledoit_wolf_adjustment(
        self,
        bot_metrics: list[BotMetricsInput],
        raw_weights: list[float],
    ) -> list[float]:
        """
        Build a return matrix, fit Ledoit-Wolf shrunk covariance, and compute
        a per-bot adjustment factor:

            adj_i = target_portfolio_vol / sqrt(cov_shrunk[i, i])

        If LedoitWolf is unavailable or fitting fails, returns [1.0] * n.

        The adjustment is applied multiplicatively to raw_weights upstream;
        normalization happens afterwards, so the absolute scale here is only
        relative.
        """
        n = len(bot_metrics)
        adjustments = [1.0] * n

        if not _LEDOIT_WOLF_AVAILABLE:
            logger.warning(
                "sklearn not installed — skipping Ledoit-Wolf covariance adjustment."
            )
            return adjustments

        # Align returns to the shortest series to build a rectangular matrix
        min_len = min(len(bm.returns) for bm in bot_metrics)
        if min_len < 2:
            logger.warning(
                "Insufficient overlapping return history for LW fit; skipping."
            )
            return adjustments

        # Shape: (min_len, n) — each column is one bot's return series
        try:
            returns_matrix = np.column_stack(
                [np.array(bm.returns[-min_len:], dtype=float) for bm in bot_metrics]
            )

            lw = _LedoitWolf().fit(returns_matrix)
            cov_shrunk: np.ndarray = lw.covariance_  # shape (n, n), daily scale

            for i in range(n):
                diag_var = float(cov_shrunk[i, i])
                if diag_var > 0:
                    # Scale so that if this bot's weight were 1.0, its
                    # contribution to portfolio vol ≈ target_portfolio_vol
                    daily_vol_i = math.sqrt(diag_var)
                    annual_vol_i = daily_vol_i * math.sqrt(252)
                    adjustments[i] = (
                        self.target_portfolio_vol / annual_vol_i
                        if annual_vol_i > 0
                        else 1.0
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LedoitWolf fit failed (%s); falling back to identity covariance.",
                exc,
            )
            return [1.0] * n

        return adjustments

    def _build_reason(
        self,
        kelly_raw: float,
        kelly_fractional: float,
        vol_target_adj: float,
        drawdown_adj: float,
        bot_vol: float,
    ) -> str:
        """Construct a brief human-readable reason string for the recommendation."""
        parts: list[str] = []
        parts.append(f"Kelly raw={kelly_raw:.4f}")
        parts.append(f"fractional={kelly_fractional:.4f}")
        parts.append(f"vol_adj={vol_target_adj:.3f}")
        parts.append(f"ann_vol={bot_vol:.1%}")
        if drawdown_adj < 1.0:
            parts.append(f"DD_scale={drawdown_adj:.2f}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def format_recommendation(rec: AllocationRecommendation) -> str:
    """
    Returns a human-readable advisory string.

    Example:
        'Current 10.0% | Recommended 17.3% (+7.3%)'
    """
    sign = "+" if rec.delta_pct >= 0 else ""
    return (
        f"Current {rec.current_capital_pct * 100:.1f}% | "
        f"Recommended {rec.recommended_capital_pct * 100:.1f}% "
        f"({sign}{rec.delta_pct * 100:.1f}%)"
    )
