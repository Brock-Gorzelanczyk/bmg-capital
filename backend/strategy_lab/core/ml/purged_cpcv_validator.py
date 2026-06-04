"""
Purged Combinatorial Cross-Validation (CPCV) — Priority 2.

Replaces the walk-forward backtester's simple train/test split with a
combinatorially purged CV that prevents lookahead leakage from overlapping
label horizons.

Reference: López de Prado (2018) — Advances in Financial Machine Learning,
           Chapter 12.

Usage
-----
from strategy_lab.core.ml.purged_cpcv_validator import CPCV

cv = CPCV(n_splits=6, n_test_splits=2, embargo_pct=0.01)
for train_idx, test_idx in cv.split(X, t1_series):
    # train_idx, test_idx = row indices into X
    model.fit(X.iloc[train_idx], y.iloc[train_idx])
    score = model.score(X.iloc[test_idx], y.iloc[test_idx])
"""
from __future__ import annotations

import itertools
import logging
from typing import Generator, Optional

import numpy as np

logger = logging.getLogger(__name__)


class CPCV:
    """
    Combinatorial Purged Cross-Validation.

    Parameters
    ----------
    n_splits : int
        Total number of folds (N in CPCV(N, k)).
    n_test_splits : int
        Number of folds held out per combination (k).
    embargo_pct : float
        Fraction of observations to embargo after each test window to
        prevent leakage from overlapping returns.
    """

    def __init__(
        self,
        n_splits: int = 6,
        n_test_splits: int = 2,
        embargo_pct: float = 0.01,
    ) -> None:
        if n_test_splits >= n_splits:
            raise ValueError("n_test_splits must be less than n_splits")
        self.n_splits = n_splits
        self.n_test_splits = n_test_splits
        self.embargo_pct = embargo_pct

    def split(
        self,
        X: "np.ndarray",
        t1: Optional["np.ndarray"] = None,
    ) -> Generator[tuple[np.ndarray, np.ndarray], None, None]:
        """
        Yield (train_indices, test_indices) for each combinatorial fold.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
        t1 : array-like of shape (n_samples,), optional
            End time of each observation's label horizon (pandas DatetimeIndex
            or array of floats representing timestamps).  Used for purging.
        """
        n = len(X)
        fold_size = n // self.n_splits
        # Build fold boundary indices
        bounds = [(i * fold_size, min((i + 1) * fold_size, n)) for i in range(self.n_splits)]

        embargo_n = int(n * self.embargo_pct)

        for test_combo in itertools.combinations(range(self.n_splits), self.n_test_splits):
            test_mask = np.zeros(n, dtype=bool)
            for fi in test_combo:
                start, end = bounds[fi]
                test_mask[start:end] = True

            train_mask = ~test_mask

            # Purge: remove train observations whose label horizon overlaps a test window
            if t1 is not None:
                test_start = min(bounds[fi][0] for fi in test_combo)
                train_indices = np.where(train_mask)[0]
                for i in train_indices:
                    if t1[i] >= test_start:
                        train_mask[i] = False

            # Embargo: remove observations just before each test window start
            for fi in test_combo:
                start = bounds[fi][0]
                embargo_start = max(0, start - embargo_n)
                train_mask[embargo_start:start] = False

            train_idx = np.where(train_mask)[0]
            test_idx = np.where(test_mask)[0]

            if len(train_idx) == 0 or len(test_idx) == 0:
                logger.debug("[cpcv] skipping empty fold (combo=%s)", test_combo)
                continue

            yield train_idx, test_idx

    def n_combinations(self) -> int:
        """Total number of CV folds this will produce."""
        from math import comb
        return comb(self.n_splits, self.n_test_splits)


def backtest_with_cpcv(
    model_factory,
    X: "np.ndarray",
    y: "np.ndarray",
    t1: Optional["np.ndarray"] = None,
    n_splits: int = 6,
    n_test_splits: int = 2,
) -> dict:
    """
    Run CPCV and return aggregated performance metrics.

    Returns
    -------
    dict with keys: mean_score, std_score, n_folds, scores
    """
    cv = CPCV(n_splits=n_splits, n_test_splits=n_test_splits)
    scores: list[float] = []

    for train_idx, test_idx in cv.split(X, t1):
        model = model_factory()
        try:
            model.fit(X[train_idx], y[train_idx])
            score = float(model.score(X[test_idx], y[test_idx]))
            scores.append(score)
        except Exception as exc:
            logger.warning("[cpcv] fold failed: %s", exc)

    if not scores:
        return {"mean_score": None, "std_score": None, "n_folds": 0, "scores": []}

    return {
        "mean_score": float(np.mean(scores)),
        "std_score": float(np.std(scores)),
        "n_folds": len(scores),
        "scores": scores,
    }
