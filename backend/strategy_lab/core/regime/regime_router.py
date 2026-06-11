"""Composite regime routing: classify market state and scale strategy allocations."""

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from strategy_lab.core.regime.regime_signals import (
    credit_spread_state,
    dxy_momentum_state,
    hurst_dfa,
    market_breadth_state,
    rolling_hurst,
    vix_regime,
    yield_curve_state,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGIME_MULTIPLIERS: dict[str, dict[str, float]] = {
    "momentum": {
        "bull_trending": 1.5,
        "bear_trending": 0.8,
        "sideways_choppy": 0.3,
        "crisis": 0.0,
    },
    "mean_reversion": {
        "bull_trending": 0.3,
        "bear_trending": 0.5,
        "sideways_choppy": 1.5,
        "crisis": 0.2,
    },
    "carry": {
        "bull_trending": 1.0,
        "bear_trending": 0.3,
        "sideways_choppy": 1.0,
        "crisis": 0.0,
    },
    "vol_short": {
        "bull_trending": 1.2,
        "bear_trending": 0.0,
        "sideways_choppy": 0.8,
        "crisis": 0.0,
    },
    "options_income": {
        "bull_trending": 0.8,
        "bear_trending": 0.4,
        "sideways_choppy": 1.2,
        "crisis": 0.0,
    },
}

STRATEGY_STYLE_MAP: dict[str, str] = {
    "cross_sectional_momentum": "momentum",
    "time_series_momentum": "momentum",
    "cross_asset_momentum": "momentum",
    "crypto_dual_momentum": "momentum",
    "rsi2_mean_reversion": "mean_reversion",
    "overnight_gap_fade": "mean_reversion",
    "vix_contango_roll": "vol_short",
    "earnings_vol_premium": "options_income",
    "quality_momentum_screen": "momentum",
    "cash_carry_basis": "carry",
    "liquidation_cascade": "momentum",
    "insider_cluster_buy": "momentum",
}

# DDL for optional persistence layer (SQLite / similar).
REGIME_STATE_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS regime_state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    regime TEXT NOT NULL,
    confidence REAL,
    signals_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Neutral / safe default inputs used when callers omit live data.
_NEUTRAL_VIX = 18.0
_NEUTRAL_T10Y2Y = 0.5
_NEUTRAL_UUP_ZSCORE = 0.0
_NEUTRAL_PCT_ABOVE_200DMA = 55.0
_NEUTRAL_HURST = 0.50


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_composite_regime(
    vix_state: str,
    credit_state: str,
    yield_state: str,
    hurst: float,
    breadth_state: str,
    dxy_state: str,
) -> tuple[str, float]:
    """
    Combine all six signal states into a single regime label and a
    confidence score.

    Decision logic (evaluated in priority order):

    1. **crisis** — triggered immediately if ``vix_state == "stress"`` OR
       ``credit_state == "red"``.  Confidence fixed at 0.95.

    2. **bull_trending** — requires ALL of:
       - ``vix_state`` in {``"calm"``, ``"normal"``}
       - ``credit_state == "green"``
       - ``hurst > 0.55``
       - ``breadth_state`` in {``"strong"``, ``"normal"``}

    3. **bear_trending** — requires ALL of:
       - ``yield_state == "inverted"``
       - ``hurst > 0.55``
       - ``breadth_state`` in {``"weak"``, ``"panic"``}

    4. **sideways_choppy** — catches all remaining cases, including when
       ``hurst < 0.45`` (low persistence) or breadth is normal while VIX
       is elevated.

    Confidence score:
        - Base: 0.50
        - +0.10 per confirming signal (maximum 0.95)

    Returns:
        Tuple of (``regime_label``, ``confidence``) where ``regime_label``
        is one of ``"crisis"``, ``"bull_trending"``, ``"bear_trending"``,
        ``"sideways_choppy"``.
    """
    hurst_safe = hurst if not math.isnan(hurst) else _NEUTRAL_HURST

    # --- Rule 1: Crisis (hard override) ---
    if vix_state == "stress" or credit_state == "red":
        return "crisis", 0.95

    # --- Rule 2: Bull trending ---
    bull_conditions = [
        vix_state in ("calm", "normal"),
        credit_state == "green",
        hurst_safe > 0.55,
        breadth_state in ("strong", "normal"),
    ]
    if all(bull_conditions):
        # Bonus confidence signal: steep curve and weak dollar are tailwinds.
        confirming = sum([
            yield_state == "steep",
            dxy_state == "weak",
        ])
        confidence = min(0.95, 0.50 + 0.10 * (len(bull_conditions) + confirming))
        return "bull_trending", round(confidence, 4)

    # --- Rule 3: Bear trending ---
    bear_conditions = [
        yield_state == "inverted",
        hurst_safe > 0.55,
        breadth_state in ("weak", "panic"),
    ]
    if all(bear_conditions):
        confirming = sum([
            credit_state in ("orange", "red"),
            dxy_state == "strong",
            vix_state in ("elevated", "stress"),
        ])
        confidence = min(0.95, 0.50 + 0.10 * (len(bear_conditions) + confirming))
        return "bear_trending", round(confidence, 4)

    # --- Rule 4: Sideways / choppy (default) ---
    # Build confidence from signals that support this label.
    confirming = sum([
        hurst_safe < 0.45,
        vix_state == "elevated" and breadth_state == "normal",
        yield_state == "flat",
        dxy_state == "neutral",
    ])
    confidence = min(0.95, 0.50 + 0.10 * confirming)
    return "sideways_choppy", round(confidence, 4)


# math is used inside _detect_composite_regime for isnan — import after
# the function definition so the module-level namespace is clean.
import math  # noqa: E402


# ---------------------------------------------------------------------------
# RegimeRouter
# ---------------------------------------------------------------------------


class RegimeRouter:
    """
    Orchestrates all six regime signals into a single composite regime and
    provides per-strategy allocation multipliers.

    All methods are pure analytics — no trading mutations.
    """

    def detect_regime(
        self,
        vix_level: Optional[float] = None,
        vx1: Optional[float] = None,
        vx2: Optional[float] = None,
        t10y2y: Optional[float] = None,
        uup_60d_zscore: Optional[float] = None,
        pct_above_200dma: Optional[float] = None,
        recent_returns: Optional[np.ndarray] = None,
        hurst_override: Optional[float] = None,
    ) -> dict:
        """
        Run all available regime signals and return a composite assessment.

        Any omitted input falls back to a neutral default so that the
        function never raises due to missing market data.

        Parameters
        ----------
        vix_level:
            VIX spot level (e.g. 18.5).
        vx1:
            First-month VIX futures price (for term-structure).
        vx2:
            Second-month VIX futures price (for term-structure).
        t10y2y:
            FRED T10Y2Y spread in percentage points.
        uup_60d_zscore:
            UUP 60-day price z-score.
        pct_above_200dma:
            Percentage of S&P 500 stocks above their 200-day MA (0–100).
        recent_returns:
            1-D array of recent daily returns used to compute a rolling
            Hurst estimate on-the-fly.
        hurst_override:
            Pre-computed Hurst value; skips ``rolling_hurst`` if provided.

        Returns
        -------
        dict with keys:
            ``regime`` (str), ``confidence`` (float),
            ``signals_breakdown`` (dict of per-signal dicts/values).
        """
        # ------------------------------------------------------------------
        # 1. Collect individual signal outputs
        # ------------------------------------------------------------------

        # VIX
        _vix_level = vix_level if vix_level is not None else _NEUTRAL_VIX
        vix_result = vix_regime(_vix_level, vx1=vx1, vx2=vx2)

        # Credit spread (always live; fails-open internally)
        credit_result = credit_spread_state()

        # Yield curve
        _t10y2y = t10y2y if t10y2y is not None else _NEUTRAL_T10Y2Y
        yield_result = yield_curve_state(_t10y2y)

        # Hurst exponent
        if hurst_override is not None:
            hurst_value = float(hurst_override)
        elif recent_returns is not None and len(recent_returns) >= 10:
            computed = rolling_hurst(np.asarray(recent_returns, dtype=float))
            # Use the most recent non-NaN value
            valid = computed[~np.isnan(computed)]
            hurst_value = float(valid[-1]) if len(valid) > 0 else _NEUTRAL_HURST
        else:
            hurst_value = _NEUTRAL_HURST

        # Market breadth
        _pct_above = (
            pct_above_200dma if pct_above_200dma is not None else _NEUTRAL_PCT_ABOVE_200DMA
        )
        breadth_result = market_breadth_state(_pct_above)

        # DXY momentum
        _uup_z = uup_60d_zscore if uup_60d_zscore is not None else _NEUTRAL_UUP_ZSCORE
        dxy_result = dxy_momentum_state(_uup_z)

        # ------------------------------------------------------------------
        # 2. Composite classification
        # ------------------------------------------------------------------
        regime_label, confidence = _detect_composite_regime(
            vix_state=vix_result["state"],
            credit_state=credit_result["state"],
            yield_state=yield_result["state"],
            hurst=hurst_value,
            breadth_state=breadth_result["state"],
            dxy_state=dxy_result["state"],
        )

        return {
            "regime": regime_label,
            "confidence": confidence,
            "signals_breakdown": {
                "vix": vix_result,
                "credit": credit_result,
                "yield_curve": yield_result,
                "hurst": hurst_value,
                "breadth": breadth_result,
                "dxy": dxy_result,
            },
        }

    def get_multiplier_for_strategy(
        self,
        strategy_name: str,
        regime: Optional[str] = None,
    ) -> float:
        """
        Return the allocation multiplier for ``strategy_name`` in the given
        ``regime``.

        If ``regime`` is ``None``, ``detect_regime()`` is called with all
        neutral defaults to obtain a current regime estimate.

        Returns ``1.0`` for any strategy not found in ``STRATEGY_STYLE_MAP``
        (unknown strategies are treated as unaffected by regime filtering).

        Parameters
        ----------
        strategy_name:
            Key into ``STRATEGY_STYLE_MAP`` (e.g. ``"cross_sectional_momentum"``).
        regime:
            One of ``"bull_trending"``, ``"bear_trending"``,
            ``"sideways_choppy"``, ``"crisis"``.  If ``None``, auto-detected.

        Returns
        -------
        float
            Allocation multiplier from ``REGIME_MULTIPLIERS``.
        """
        if regime is None:
            detection = self.detect_regime()
            regime = detection["regime"]

        style = STRATEGY_STYLE_MAP.get(strategy_name)
        if style is None:
            logger.debug(
                "strategy %r not in STRATEGY_STYLE_MAP; returning multiplier=1.0",
                strategy_name,
            )
            return 1.0

        style_multipliers = REGIME_MULTIPLIERS.get(style, {})
        multiplier = style_multipliers.get(regime, 1.0)
        return float(multiplier)


# ---------------------------------------------------------------------------
# RegimePersistenceFilter
# ---------------------------------------------------------------------------


class RegimePersistenceFilter:
    """
    Debounce rapid regime flips to prevent whipsawing.

    Normal regime transitions require **5 consecutive days** on the same
    label before the confirmed regime is updated.  Crisis transitions are
    faster, requiring only **2 consecutive days**.

    Attributes
    ----------
    current_regime:
        The most recently confirmed (stable) regime label.
    pending_regime:
        The candidate label that has not yet accumulated enough consecutive
        days for confirmation.
    consecutive_days:
        Count of how many consecutive days ``pending_regime`` has been seen.
    """

    CRISIS_THRESHOLD: int = 2
    NORMAL_THRESHOLD: int = 5

    def __init__(self) -> None:
        self.current_regime: str = "sideways_choppy"
        self.pending_regime: Optional[str] = None
        self.consecutive_days: int = 0

    def update(self, new_regime: str) -> str:
        """
        Feed a new daily regime observation and return the current
        *confirmed* regime.

        The confirmed regime only changes once the pending candidate has
        been seen for the required number of consecutive days (2 for
        ``"crisis"``, 5 for everything else).

        Parameters
        ----------
        new_regime:
            The raw regime label produced by ``RegimeRouter.detect_regime()``
            for today.

        Returns
        -------
        str
            The confirmed, debounced regime label.
        """
        if new_regime == self.current_regime:
            # Already confirmed — reset any pending counter.
            self.pending_regime = None
            self.consecutive_days = 0
            return self.current_regime

        if new_regime == self.pending_regime:
            self.consecutive_days += 1
        else:
            # New candidate — start fresh count.
            self.pending_regime = new_regime
            self.consecutive_days = 1

        threshold = (
            self.CRISIS_THRESHOLD
            if new_regime == "crisis"
            else self.NORMAL_THRESHOLD
        )

        if self.consecutive_days >= threshold:
            logger.info(
                "RegimePersistenceFilter: regime confirmed %r → %r "
                "after %d consecutive days",
                self.current_regime,
                new_regime,
                self.consecutive_days,
            )
            self.current_regime = new_regime
            self.pending_regime = None
            self.consecutive_days = 0

        return self.current_regime

    def force_set(self, regime: str) -> None:
        """
        Unconditionally set the confirmed regime, resetting all counters.

        Intended for testing and initialisation from persisted state.

        Parameters
        ----------
        regime:
            The regime label to force-confirm immediately.
        """
        self.current_regime = regime
        self.pending_regime = None
        self.consecutive_days = 0
        logger.debug("RegimePersistenceFilter: force-set regime to %r", regime)


# ---------------------------------------------------------------------------
# Advisory VIX scaling — opt-in per strategy, not a global loop modifier
# ---------------------------------------------------------------------------


def advisory_vix_scale(vix_level: float) -> float:
    """
    Return a size multiplier based on VIX level — advisory only.

    Strategies call this explicitly if they want VIX-aware sizing.
    It is never applied globally in the scan loop.

    Returns 0.0 when VIX > 40 (hard kill switch — never sell premium in crisis).
    Returns 0.5 when VIX > 25 (elevated vol, half-size).
    Returns 1.0 otherwise (normal conditions).

    Smoke-test: advisory_vix_scale(45.0) == 0.0; advisory_vix_scale(15.0) == 1.0

    Example
    -------
    Inside a strategy's ``generate_signals()``::

        from strategy_lab.core.regime.regime_router import advisory_vix_scale

        if advisory_vix_scale(current_vix) == 0.0:
            return []  # crisis — no new positions
    """
    if vix_level > 40:
        return 0.0
    if vix_level > 25:
        return 0.5
    return 1.0
