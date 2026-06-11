"""
strategy_lab/core/walk_forward/engine.py

Walk-forward analysis engine with CPCV PBO calculation.

Pure analytics module — no trading mutations, no order placement.
"""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import scipy.stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DSR integration (optional — graceful fallback if evaluator not present)
# ---------------------------------------------------------------------------

try:
    from strategy_lab.core.evaluator import deflated_sharpe_ratio as _dsr_fn  # type: ignore

    _HAS_EVALUATOR = True
except ImportError:
    _HAS_EVALUATOR = False


def _compute_dsr(returns: np.ndarray, n_trials: int) -> float:
    """Compute Deflated Sharpe Ratio via evaluator module, or 0.0 if unavailable."""
    if not _HAS_EVALUATOR or len(returns) < 10:
        return 0.0
    result = _dsr_fn(returns, n_trials)
    return result.get("dsr", 0.0)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WalkResult:
    """Results for a single IS/OOS walk window."""

    walk_id: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    is_sharpe: float
    oos_sharpe: float
    wfe: float  # oos_sharpe / is_sharpe, clamped to [-2, 2]
    best_params: dict
    is_returns: np.ndarray
    oos_returns: np.ndarray
    n_is_trades: int
    n_oos_trades: int


@dataclass
class WFAResult:
    """Aggregate result from a full walk-forward analysis run."""

    strategy_name: str
    walks: List[WalkResult]
    aggregate_oos_sharpe: float
    aggregate_is_sharpe: float
    wfe: float  # aggregate_oos_sharpe / aggregate_is_sharpe
    pbo: float  # Probability of Backtest Overfitting from CPCV
    dsr: float  # Deflated Sharpe from evaluator module
    n_trials: int  # total param combos tried across all walks
    all_trial_is_sharpes: List[float]
    oos_returns: np.ndarray  # concatenated OOS returns across all walks


# ---------------------------------------------------------------------------
# Helper: Sharpe ratio
# ---------------------------------------------------------------------------


def _sharpe(returns: np.ndarray) -> float:
    """
    Annualised Sharpe ratio from a daily returns array.

    sharpe = mean(returns) / std(returns, ddof=1) * sqrt(252)

    Returns 0.0 when the array has fewer than 2 elements or zero variance.
    """
    arr = np.asarray(returns, dtype=float).ravel()
    if len(arr) < 2:
        return 0.0
    std = np.std(arr, ddof=1)
    if std == 0.0:
        return 0.0
    return float(np.mean(arr) / std * math.sqrt(252))


# ---------------------------------------------------------------------------
# Helper: resolve close column
# ---------------------------------------------------------------------------


def _close_col(bars: pd.DataFrame) -> str:
    """Return the name of the close column, accepting 'close' or 'c'."""
    if "close" in bars.columns:
        return "close"
    if "c" in bars.columns:
        return "c"
    raise KeyError(
        f"bars DataFrame must contain a 'close' or 'c' column. "
        f"Found: {list(bars.columns)}"
    )


# ---------------------------------------------------------------------------
# Helper: trading-day offset (approximate)
# ---------------------------------------------------------------------------


def _trading_days(years: float) -> int:
    """Convert years to approximate trading days (252 days/year)."""
    return int(round(years * 252))


# ---------------------------------------------------------------------------
# Purged K-Fold Cross-Validation
# ---------------------------------------------------------------------------


def purged_kfold_splits(
    timestamps: pd.DatetimeIndex,
    n_splits: int,
    label_horizon_days: int = 1,
    embargo_days: int = 21,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Generate purged and embargoed train/test index splits.

    Parameters
    ----------
    timestamps : pd.DatetimeIndex
        Ordered timestamps of the dataset (must be monotonic).
    n_splits : int
        Number of folds to divide the data into.
    label_horizon_days : int
        Lookahead horizon of labels in calendar days.  Train samples whose
        label window [t, t + horizon] overlaps the test-fold start are purged.
    embargo_days : int
        Calendar days of embargo applied around test-fold boundaries to prevent
        leakage due to autocorrelation.

    Returns
    -------
    List of (train_indices, test_indices) as integer arrays.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")

    n = len(timestamps)
    if n < n_splits:
        raise ValueError(
            f"timestamps length ({n}) must be >= n_splits ({n_splits})"
        )

    horizon = timedelta(days=label_horizon_days)
    embargo = timedelta(days=embargo_days)

    # Divide into roughly equal folds
    fold_sizes = np.full(n_splits, n // n_splits, dtype=int)
    fold_sizes[: n % n_splits] += 1
    fold_boundaries: List[Tuple[int, int]] = []
    start = 0
    for size in fold_sizes:
        fold_boundaries.append((start, start + size))
        start += size

    result: List[Tuple[np.ndarray, np.ndarray]] = []

    for k, (test_lo, test_hi) in enumerate(fold_boundaries):
        test_idx = np.arange(test_lo, test_hi)
        test_start_ts = timestamps[test_lo]
        test_end_ts = timestamps[test_hi - 1]

        train_mask = np.ones(n, dtype=bool)
        # Exclude test fold
        train_mask[test_lo:test_hi] = False

        for i in range(n):
            if not train_mask[i]:
                continue
            t = timestamps[i]

            if i < test_lo:
                # Pre-test samples: purge those whose label window overlaps test start
                label_end = t + horizon
                if label_end >= test_start_ts:
                    train_mask[i] = False
                    continue
                # Embargo: within embargo_days before the test start
                if (test_start_ts - t).days <= embargo_days:
                    train_mask[i] = False
                    continue
            else:
                # Post-test samples: embargo those within embargo_days after test end
                if (t - test_end_ts).days <= embargo_days:
                    train_mask[i] = False
                    continue

        train_idx = np.where(train_mask)[0]

        if len(train_idx) == 0 or len(test_idx) == 0:
            logger.warning(
                "purged_kfold_splits: fold %d produced empty train (%d) or "
                "test (%d) split; skipping.",
                k,
                len(train_idx),
                len(test_idx),
            )
            continue

        result.append((train_idx, test_idx))

    return result


# ---------------------------------------------------------------------------
# CPCV — Combinatorial Purged Cross-Validation / PBO
# ---------------------------------------------------------------------------


def cpcv_pbo(
    strategy_fn: Callable[[pd.DataFrame, dict], List[float]],
    bars: pd.DataFrame,
    param_grid: List[dict],
    n_paths: int = 10,
    n_splits: int = 6,
    embargo_days: int = 21,
) -> float:
    """
    Combinatorial Purged Cross-Validation for Probability of Backtest
    Overfitting (Bailey & López de Prado).

    For each combination of IS/OOS splits:
      1. Find the param combo with the highest IS Sharpe.
      2. Evaluate that combo on OOS.
      3. Check whether the OOS Sharpe of the best-IS combo falls below the
         median OOS Sharpe across **all** combos on that same OOS set.

    PBO = fraction of paths (split combinations) where the selected strategy
    underperforms the median.

    Parameters
    ----------
    strategy_fn : callable
        ``strategy_fn(bars, params) -> list[float]`` — returns daily returns.
    bars : pd.DataFrame
        OHLCV data with DatetimeIndex.
    param_grid : list[dict]
        Parameter combinations to evaluate.
    n_paths : int
        Maximum number of split combinations to evaluate (capped at C(n,n//2)).
    n_splits : int
        Number of folds; must be even so that IS and OOS are the same size.
    embargo_days : int
        Embargo gap to prevent lookahead leakage.

    Returns
    -------
    float
        PBO in [0, 1].  PBO < 0.10 is good; PBO > 0.50 suggests overfit.
    """
    if len(param_grid) == 0:
        logger.warning("cpcv_pbo: empty param_grid; returning PBO=1.0.")
        return 1.0

    if n_splits < 2:
        logger.warning("cpcv_pbo: n_splits < 2; returning PBO=1.0.")
        return 1.0

    # Ensure even number of splits for balanced IS/OOS
    if n_splits % 2 != 0:
        n_splits += 1

    try:
        splits = purged_kfold_splits(
            timestamps=bars.index,
            n_splits=n_splits,
            label_horizon_days=1,
            embargo_days=embargo_days,
        )
    except Exception as exc:
        logger.error("cpcv_pbo: purged_kfold_splits failed: %s", exc)
        return 1.0

    if len(splits) < 2:
        logger.warning(
            "cpcv_pbo: fewer than 2 valid splits (%d); returning PBO=1.0.",
            len(splits),
        )
        return 1.0

    n_valid = len(splits)
    half = n_valid // 2

    # Generate all C(n_valid, half) IS-fold-index combinations
    all_combos = list(itertools.combinations(range(n_valid), half))

    # Cap at n_paths for efficiency
    max_paths = min(n_paths, len(all_combos))
    # Sample deterministically (first max_paths) to keep reproducibility
    selected_combos = all_combos[:max_paths]

    overfit_count = 0
    evaluated_count = 0

    for combo in selected_combos:
        oos_fold_indices = [i for i in range(n_valid) if i not in combo]

        # Collect IS bar indices
        is_idx_sets = [splits[i][0] for i in combo]  # train indices per IS fold
        is_indices_flat: np.ndarray = np.unique(np.concatenate(is_idx_sets))

        # Collect OOS bar indices
        oos_idx_sets = [splits[i][1] for i in oos_fold_indices]
        oos_indices_flat: np.ndarray = np.unique(np.concatenate(oos_idx_sets))

        if len(is_indices_flat) < 10 or len(oos_indices_flat) < 10:
            logger.debug("cpcv_pbo: combo %s has insufficient data; skipping.", combo)
            continue

        is_bars = bars.iloc[is_indices_flat]
        oos_bars = bars.iloc[oos_indices_flat]

        # Evaluate all param combos on IS
        combo_is_sharpes: List[float] = []
        combo_oos_sharpes: List[float] = []

        for params in param_grid:
            try:
                is_rets = np.asarray(strategy_fn(is_bars, params), dtype=float)
                is_sr = _sharpe(is_rets)
            except Exception as exc:
                logger.debug(
                    "cpcv_pbo: strategy_fn failed on IS for params %s: %s",
                    params,
                    exc,
                )
                is_sr = 0.0

            try:
                oos_rets = np.asarray(strategy_fn(oos_bars, params), dtype=float)
                oos_sr = _sharpe(oos_rets)
            except Exception as exc:
                logger.debug(
                    "cpcv_pbo: strategy_fn failed on OOS for params %s: %s",
                    params,
                    exc,
                )
                oos_sr = 0.0

            combo_is_sharpes.append(is_sr)
            combo_oos_sharpes.append(oos_sr)

        if not combo_is_sharpes:
            continue

        # Best IS combo
        best_is_idx = int(np.argmax(combo_is_sharpes))
        best_oos_sharpe = combo_oos_sharpes[best_is_idx]
        median_oos_sharpe = float(np.median(combo_oos_sharpes))

        evaluated_count += 1
        if best_oos_sharpe < median_oos_sharpe:
            overfit_count += 1

    if evaluated_count == 0:
        logger.warning("cpcv_pbo: no paths evaluated; returning PBO=1.0.")
        return 1.0

    pbo = overfit_count / evaluated_count
    return float(np.clip(pbo, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Minimum Backtest Length
# ---------------------------------------------------------------------------


def min_btl_satisfied(
    sr_daily: float,
    t_days: int,
    alpha: float = 0.05,
    beta: float = 0.05,
) -> bool:
    """
    Minimum Backtest Length check (Bailey & López de Prado).

    T* = ((z_alpha + z_beta) / SR_daily)^2 * (1 + SR_daily^2 / 2)

    Returns True if t_days >= T*.  Returns False when sr_daily == 0.

    Parameters
    ----------
    sr_daily : float
        Daily (per-observation) Sharpe ratio.
    t_days : int
        Number of trading days in the backtest.
    alpha : float
        Type I error rate (significance level), default 0.05.
    beta : float
        Type II error rate (1 - power), default 0.05.
    """
    if sr_daily == 0.0:
        return False

    z_alpha = scipy.stats.norm.ppf(1.0 - alpha)
    z_beta = scipy.stats.norm.ppf(1.0 - beta)

    t_star = ((z_alpha + z_beta) / sr_daily) ** 2 * (1.0 + sr_daily**2 / 2.0)
    return bool(t_days >= t_star)


# ---------------------------------------------------------------------------
# Promotion Gate
# ---------------------------------------------------------------------------


def check_promotion_gate(
    result: WFAResult,
    gross_sharpe: Optional[float] = None,
    net_sharpe: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluate a strategy against all promotion criteria.

    Checks
    ------
    wfe_ok          wfe >= 0.5
    oos_sharpe_ok   aggregate_oos_sharpe >= 1.0
    pbo_ok          pbo < 0.10
    dsr_ok          dsr >= 0.90
    minbtl_ok       min_btl_satisfied for concatenated OOS returns
    net_sharpe_ok   net_sharpe >= 0.7 (only when net_sharpe is provided)

    Parameters
    ----------
    result : WFAResult
        Output of ``run_walk_forward``.
    gross_sharpe : float, optional
        Override for the OOS Sharpe check.  Uses result.aggregate_oos_sharpe
        when None.
    net_sharpe : float, optional
        After-cost Sharpe.  When provided, adds a net_sharpe_ok check.

    Returns
    -------
    dict with keys: ``eligible`` (bool), ``checks`` (dict), ``values`` (dict).
    """
    oos_sharpe = gross_sharpe if gross_sharpe is not None else result.aggregate_oos_sharpe

    # Min BTL uses daily (per-obs) Sharpe: annualised / sqrt(252)
    sr_daily = oos_sharpe / math.sqrt(252) if oos_sharpe != 0.0 else 0.0
    t_days = len(result.oos_returns) if result.oos_returns is not None else 0

    wfe_ok = result.wfe >= 0.5
    oos_sharpe_ok = oos_sharpe >= 1.0
    pbo_ok = result.pbo < 0.10
    dsr_ok = result.dsr >= 0.90
    minbtl_ok = min_btl_satisfied(sr_daily=sr_daily, t_days=t_days)

    checks: Dict[str, bool] = {
        "wfe_ok": wfe_ok,
        "oos_sharpe_ok": oos_sharpe_ok,
        "pbo_ok": pbo_ok,
        "dsr_ok": dsr_ok,
        "minbtl_ok": minbtl_ok,
    }

    if net_sharpe is not None:
        checks["net_sharpe_ok"] = net_sharpe >= 0.7
    else:
        checks["net_sharpe_ok"] = True  # skip check when not provided

    eligible = all(checks.values())

    return {
        "eligible": eligible,
        "checks": checks,
        "values": {
            "wfe": result.wfe,
            "oos_sharpe": oos_sharpe,
            "pbo": result.pbo,
            "dsr": result.dsr,
        },
    }


# ---------------------------------------------------------------------------
# Main Walk-Forward Engine
# ---------------------------------------------------------------------------


def run_walk_forward(
    strategy_fn: Callable[[pd.DataFrame, dict], List[float]],
    bars: pd.DataFrame,
    param_grid: List[dict],
    strategy_name: str = "unknown",
    is_years: float = 5.0,
    oos_years: float = 1.0,
    embargo_days: int = 21,
) -> WFAResult:
    """
    Run a full anchored/rolling walk-forward analysis.

    Walk construction
    -----------------
    * First window: IS starts at bar 0, IS ends at bar is_bars-1.
    * Each subsequent window rolls forward by oos_bars trading days.
    * OOS window starts embargo_days after IS end.
    * Stops when there are insufficient bars for a full OOS window.

    Sharpe computation
    ------------------
    sharpe = mean(returns) / std(returns, ddof=1) * sqrt(252)
    0-std returns → 0.0.

    Parameters
    ----------
    strategy_fn : callable
        ``strategy_fn(bars: pd.DataFrame, params: dict) -> list[float]``
        Returns a list/array of **daily returns** (floats).
    bars : pd.DataFrame
        Historical OHLCV data.  Must have a DatetimeIndex.
        Accepted column names: open/high/low/close/volume or o/h/l/c/v.
    param_grid : list[dict]
        Parameter combinations to grid-search on each IS window.
    strategy_name : str
        Identifier used in the returned WFAResult.
    is_years : float
        Length of the In-Sample window in years (trading days = years × 252).
    oos_years : float
        Length of each Out-of-Sample window in years.
    embargo_days : int
        Number of trading bars to skip between IS end and OOS start.

    Returns
    -------
    WFAResult
        ``walks`` is empty if there are insufficient bars for even one walk.
    """
    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------
    if bars.empty:
        logger.warning("run_walk_forward: bars is empty; returning empty result.")
        return WFAResult(
            strategy_name=strategy_name,
            walks=[],
            aggregate_oos_sharpe=0.0,
            aggregate_is_sharpe=0.0,
            wfe=0.0,
            pbo=1.0,
            dsr=0.0,
            n_trials=0,
            all_trial_is_sharpes=[],
            oos_returns=np.array([]),
        )

    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must have a DatetimeIndex.")

    # Ensure sorted index
    bars = bars.sort_index()

    # Verify close column exists (raises KeyError if not)
    _close_col(bars)

    n_bars = len(bars)
    is_bars_count = _trading_days(is_years)
    oos_bars_count = _trading_days(oos_years)
    min_bars_needed = is_bars_count + embargo_days + oos_bars_count

    if n_bars < min_bars_needed:
        logger.warning(
            "run_walk_forward: insufficient bars (%d) for even one walk "
            "(need %d = IS:%d + embargo:%d + OOS:%d).  Returning empty result.",
            n_bars,
            min_bars_needed,
            is_bars_count,
            embargo_days,
            oos_bars_count,
        )
        return WFAResult(
            strategy_name=strategy_name,
            walks=[],
            aggregate_oos_sharpe=0.0,
            aggregate_is_sharpe=0.0,
            wfe=0.0,
            pbo=1.0,
            dsr=0.0,
            n_trials=0,
            all_trial_is_sharpes=[],
            oos_returns=np.array([]),
        )

    if not param_grid:
        logger.warning("run_walk_forward: param_grid is empty; defaulting to [{}].")
        param_grid = [{}]

    # ------------------------------------------------------------------
    # Build walk windows
    # ------------------------------------------------------------------
    walks: List[WalkResult] = []
    all_oos_returns: List[np.ndarray] = []
    all_trial_is_sharpes: List[float] = []
    n_trials_total = 0
    walk_id = 0

    is_start_idx = 0

    while True:
        is_end_idx = is_start_idx + is_bars_count - 1
        oos_start_idx = is_end_idx + 1 + embargo_days
        oos_end_idx = oos_start_idx + oos_bars_count - 1

        # Stop if we run out of bars
        if oos_end_idx >= n_bars:
            break

        is_slice = bars.iloc[is_start_idx : is_end_idx + 1]
        oos_slice = bars.iloc[oos_start_idx : oos_end_idx + 1]

        try:
            # ---- IS grid search ----------------------------------------
            best_is_sharpe = -np.inf
            best_params: dict = param_grid[0]
            best_is_returns: np.ndarray = np.array([])

            for params in param_grid:
                try:
                    is_rets = np.asarray(
                        strategy_fn(is_slice, params), dtype=float
                    ).ravel()
                    sr = _sharpe(is_rets)
                    all_trial_is_sharpes.append(sr)
                    n_trials_total += 1

                    if sr > best_is_sharpe:
                        best_is_sharpe = sr
                        best_params = params
                        best_is_returns = is_rets
                except Exception as exc:
                    logger.debug(
                        "walk %d: strategy_fn failed on IS for params %s: %s",
                        walk_id,
                        params,
                        exc,
                    )
                    all_trial_is_sharpes.append(0.0)
                    n_trials_total += 1

            if best_is_sharpe == -np.inf:
                best_is_sharpe = 0.0

            # ---- OOS evaluation ----------------------------------------
            try:
                oos_rets = np.asarray(
                    strategy_fn(oos_slice, best_params), dtype=float
                ).ravel()
                oos_sharpe = _sharpe(oos_rets)
            except Exception as exc:
                logger.warning(
                    "walk %d: strategy_fn failed on OOS for params %s: %s",
                    walk_id,
                    best_params,
                    exc,
                )
                oos_rets = np.array([])
                oos_sharpe = 0.0

            # ---- WFE ---------------------------------------------------
            if best_is_sharpe == 0.0:
                wfe = 0.0
            else:
                wfe = float(np.clip(oos_sharpe / best_is_sharpe, -2.0, 2.0))

            walk = WalkResult(
                walk_id=walk_id,
                is_start=bars.index[is_start_idx],
                is_end=bars.index[is_end_idx],
                oos_start=bars.index[oos_start_idx],
                oos_end=bars.index[oos_end_idx],
                is_sharpe=float(best_is_sharpe),
                oos_sharpe=float(oos_sharpe),
                wfe=wfe,
                best_params=best_params,
                is_returns=best_is_returns,
                oos_returns=oos_rets,
                n_is_trades=len(best_is_returns),
                n_oos_trades=len(oos_rets),
            )
            walks.append(walk)

            if len(oos_rets) > 0:
                all_oos_returns.append(oos_rets)

        except Exception as exc:
            logger.error(
                "run_walk_forward: unhandled error in walk %d; skipping. %s",
                walk_id,
                exc,
                exc_info=True,
            )

        # Roll forward by one OOS window (rolling walk-forward)
        is_start_idx += oos_bars_count
        walk_id += 1

    # ------------------------------------------------------------------
    # Aggregate statistics
    # ------------------------------------------------------------------
    if not walks:
        logger.warning(
            "run_walk_forward: no valid walks completed for strategy '%s'.",
            strategy_name,
        )
        return WFAResult(
            strategy_name=strategy_name,
            walks=[],
            aggregate_oos_sharpe=0.0,
            aggregate_is_sharpe=0.0,
            wfe=0.0,
            pbo=1.0,
            dsr=0.0,
            n_trials=n_trials_total,
            all_trial_is_sharpes=all_trial_is_sharpes,
            oos_returns=np.array([]),
        )

    concat_oos = (
        np.concatenate(all_oos_returns) if all_oos_returns else np.array([])
    )
    agg_oos_sharpe = _sharpe(concat_oos)

    all_is_returns_list = [w.is_returns for w in walks if len(w.is_returns) > 0]
    concat_is = (
        np.concatenate(all_is_returns_list) if all_is_returns_list else np.array([])
    )
    agg_is_sharpe = _sharpe(concat_is)

    agg_wfe = (
        0.0
        if agg_is_sharpe == 0.0
        else float(np.clip(agg_oos_sharpe / agg_is_sharpe, -2.0, 2.0))
    )

    # CPCV PBO
    try:
        pbo = cpcv_pbo(
            strategy_fn=strategy_fn,
            bars=bars,
            param_grid=param_grid,
            n_paths=10,
            n_splits=6,
            embargo_days=embargo_days,
        )
    except Exception as exc:
        logger.error(
            "run_walk_forward: cpcv_pbo failed for '%s': %s",
            strategy_name,
            exc,
            exc_info=True,
        )
        pbo = 1.0

    # DSR
    dsr = _compute_dsr(concat_oos, n_trials=max(n_trials_total, 1))

    return WFAResult(
        strategy_name=strategy_name,
        walks=walks,
        aggregate_oos_sharpe=float(agg_oos_sharpe),
        aggregate_is_sharpe=float(agg_is_sharpe),
        wfe=agg_wfe,
        pbo=float(pbo),
        dsr=float(dsr),
        n_trials=n_trials_total,
        all_trial_is_sharpes=all_trial_is_sharpes,
        oos_returns=concat_oos,
    )
