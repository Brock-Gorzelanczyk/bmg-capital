"""
XGBoost / LightGBM Factor Ranker — Priority 4.

Trains a gradient-boosted ranker on a cross-section of factor scores
(momentum, value, quality, low-vol) and outputs a composite rank score
for each symbol.  Used by the strategy runner to rank candidate entries
and pick the top-N.

Usage
-----
ranker = FactorRanker()
ranker.fit(panel_df)     # columns = factor scores + forward_return (label)
scores = ranker.rank(live_factor_df)   # returns Series indexed by symbol
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).parent.parent.parent / "ml_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)
_MODEL_PATH = _MODEL_DIR / "xgb_factor_ranker.pkl"

FACTOR_COLS = [
    "mom_12_1",       # 12-month minus 1-month return
    "mom_1",          # 1-month return (short-term reversal)
    "pb_rank",        # price-to-book rank (0=cheap, 1=expensive)
    "roe",            # return on equity (trailing 12m)
    "debt_eq",        # debt / equity ratio
    "vol_6m",         # 6-month realized annualized volatility
    "beta_1y",        # 1-year beta vs SPY
    "gp_assets",      # gross profit / total assets (Novy-Marx)
    "accruals",       # accounting accruals / avg assets
    "iv_rank",        # implied volatility rank 0-100
]


class FactorRanker:
    """LightGBM ranker that blends factor scores into a single composite rank."""

    def __init__(self) -> None:
        self._model: Optional[object] = None

    # ── Training ────────────────────────────────────────────────────────────

    def fit(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> None:
        """
        Train LightGBM LambdaRank on historical panel data.

        Parameters
        ----------
        X : (n_obs, n_features) — factor scores
        y : (n_obs,) — forward 21-day return rank within each cross-section (0=worst)
        groups : (n_obs,) — number of stocks in each rebalance date group
        """
        try:
            import lightgbm as lgb
        except ImportError:
            logger.warning("lightgbm not installed — factor ranker disabled")
            return

        train_data = lgb.Dataset(X, label=y, group=groups)
        params = {
            "objective": "lambdarank",
            "metric": "ndcg",
            "ndcg_eval_at": [5, 10],
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 20,
            "n_estimators": 300,
            "verbose": -1,
        }
        model = lgb.train(params, train_data, num_boost_round=300)
        self._model = model
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(model, f)
        logger.info("[factor_ranker] trained on %d observations", len(y))

    # ── Inference ────────────────────────────────────────────────────────────

    def rank(self, X: np.ndarray) -> np.ndarray:
        """
        Return composite score for each row (higher = more attractive).

        Falls back to equal scores if model not trained.
        """
        model = self._load()
        if model is None:
            return np.ones(len(X))
        try:
            return model.predict(X)
        except Exception as exc:
            logger.warning("[factor_ranker] predict error: %s", exc)
            return np.ones(len(X))

    def top_n_indices(self, X: np.ndarray, n: int = 10) -> np.ndarray:
        """Return row indices of the top-N ranked stocks."""
        scores = self.rank(X)
        return np.argsort(scores)[::-1][:n]

    def is_trained(self) -> bool:
        return _MODEL_PATH.exists()

    def _load(self) -> Optional[object]:
        if self._model is not None:
            return self._model
        if not _MODEL_PATH.exists():
            return None
        try:
            with open(_MODEL_PATH, "rb") as f:
                self._model = pickle.load(f)
            return self._model
        except Exception as exc:
            logger.warning("[factor_ranker] load error: %s", exc)
            return None


_ranker = FactorRanker()


def get_ranker() -> FactorRanker:
    return _ranker
