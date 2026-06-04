"""
Meta-label classifier — Priority 1.

XGBoost binary classifier that wraps every rules-based signal and outputs
a confidence probability.  The probability is returned as `ml_confidence`
and used as a `size_hint` multiplier in RiskManager.position_size().

Usage
-----
clf = MetaLabelClassifier(model_id="stock_day_orb")
clf.fit(feature_df, label_series)           # label = 1 if trade was profitable
prob = clf.predict_proba(live_features)     # float in [0, 1]
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Model artefacts live here so they survive container restarts on Railway
_MODEL_DIR = Path(__file__).parent.parent.parent / "ml_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)

_FEATURE_COLS = [
    "rvol",           # relative volume vs 20-day avg
    "gap_pct",        # overnight gap %
    "atr_pct",        # ATR as % of price
    "rsi_14",         # 14-period RSI
    "vix",            # CBOE VIX at signal time
    "adv_decline",    # advancers / decliners ratio (0-2)
    "trend_score",    # regime_detector trend_regime encoded: bull=1, chop=0, bear=-1
    "hour_of_day",    # 9-16 float
    "day_of_week",    # 0=Mon…4=Fri
    "spread_bps",     # bid-ask spread in basis points
]


class MetaLabelClassifier:
    """XGBoost meta-label classifier, lazy-loads xgboost at call time."""

    def __init__(self, model_id: str, threshold: float = 0.52) -> None:
        self.model_id = model_id
        self.threshold = threshold
        self._model_path = _MODEL_DIR / f"meta_label_{model_id}.pkl"
        self._model: Optional[object] = None

    # ── Training ────────────────────────────────────────────────────────────

    def fit(self, X: "np.ndarray", y: "np.ndarray") -> None:
        """Train XGBoost on historical signal outcomes and persist to disk."""
        try:
            import xgboost as xgb
        except ImportError:
            logger.warning("xgboost not installed — meta_label_classifier disabled")
            return

        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
        )
        model.fit(X, y)
        self._model = model
        with open(self._model_path, "wb") as f:
            pickle.dump(model, f)
        logger.info("[meta_label] trained model_id=%s on %d samples", self.model_id, len(y))

    # ── Inference ────────────────────────────────────────────────────────────

    def predict_proba(self, features: dict) -> float:
        """Return probability in [0,1] that the current signal will be profitable."""
        model = self._load()
        if model is None:
            return 1.0  # passthrough when no model trained yet

        try:
            row = np.array([[features.get(c, 0.0) for c in _FEATURE_COLS]], dtype=np.float32)
            prob = float(model.predict_proba(row)[0][1])
            return prob
        except Exception as exc:
            logger.warning("[meta_label] inference error: %s", exc)
            return 1.0

    def is_trained(self) -> bool:
        return self._model_path.exists()

    # ── Private ──────────────────────────────────────────────────────────────

    def _load(self) -> Optional[object]:
        if self._model is not None:
            return self._model
        if not self._model_path.exists():
            return None
        try:
            with open(self._model_path, "rb") as f:
                self._model = pickle.load(f)
            return self._model
        except Exception as exc:
            logger.warning("[meta_label] could not load model: %s", exc)
            return None


# ── Convenience singleton registry ───────────────────────────────────────────

_registry: dict[str, MetaLabelClassifier] = {}


def get_classifier(model_id: str) -> MetaLabelClassifier:
    if model_id not in _registry:
        _registry[model_id] = MetaLabelClassifier(model_id)
    return _registry[model_id]


def apply_ml_size_hint(model_id: str, features: dict) -> float:
    """
    Return a size_hint multiplier in [0.25, 1.0] based on ML confidence.

    Called from runner.py before RiskManager.position_size().
    Falls back to 1.0 when no model exists.
    """
    clf = get_classifier(model_id)
    if not clf.is_trained():
        return 1.0
    prob = clf.predict_proba(features)
    # Scale: prob < threshold → 0.25x, prob > 0.75 → 1.0x, linear between
    if prob < clf.threshold:
        return 0.25
    return max(0.25, min(1.0, (prob - clf.threshold) / (0.75 - clf.threshold) * 0.75 + 0.25))
