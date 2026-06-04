"""
HMM Regime Gate — Priority 3.

Gaussian HMM with 3 hidden states (bull / chop / crisis) trained on
SPY daily returns + realized volatility.  The posterior state probabilities
are merged into the existing regime_detector.py output dict as
`hmm_state` and `hmm_probs`.

Strategies can gate entries on regime:
    if features["hmm_state"] == "bull": allow_long = True

Usage
-----
gate = HMMRegimeGate()
gate.fit(returns_array, rv_array)           # train once per week
state, probs = gate.predict(latest_return, latest_rv)
# state: "bull" | "chop" | "crisis"
# probs: {"bull": 0.8, "chop": 0.15, "crisis": 0.05}
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
_MODEL_PATH = _MODEL_DIR / "hmm_regime_gate.pkl"

# Label mapping: HMM states are assigned after fitting by sorting on mean return
_STATE_LABELS = ["crisis", "chop", "bull"]  # low → high return order


class HMMRegimeGate:
    """3-state Gaussian HMM for market regime detection."""

    def __init__(self, n_components: int = 3) -> None:
        self.n_components = n_components
        self._model: Optional[object] = None
        self._state_map: dict[int, str] = {}

    # ── Training ────────────────────────────────────────────────────────────

    def fit(self, returns: np.ndarray, realized_vol: np.ndarray) -> None:
        """
        Train HMM on 2-feature sequence: [daily_return, realized_vol].

        Parameters
        ----------
        returns : 1-D array of daily log returns (252+ days recommended)
        realized_vol : 1-D array of 5-day realized volatility (annualized)
        """
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            logger.warning("hmmlearn not installed — HMM regime gate disabled")
            return

        X = np.column_stack([returns, realized_vol])
        model = GaussianHMM(
            n_components=self.n_components,
            covariance_type="full",
            n_iter=200,
            random_state=42,
        )
        model.fit(X)

        # Map state indices to labels by sorting on mean return per state
        means = model.means_[:, 0]  # first feature = return
        order = np.argsort(means)   # ascending: crisis < chop < bull
        self._state_map = {int(order[i]): _STATE_LABELS[i] for i in range(self.n_components)}

        self._model = model
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump({"model": model, "state_map": self._state_map}, f)
        logger.info("[hmm_gate] trained on %d observations", len(returns))

    # ── Inference ────────────────────────────────────────────────────────────

    def predict(
        self,
        recent_returns: np.ndarray,
        recent_rv: np.ndarray,
    ) -> tuple[str, dict[str, float]]:
        """
        Decode the most likely current state and return posterior probs.

        Parameters
        ----------
        recent_returns : 1-D array of recent daily returns (at least 5 days)
        recent_rv : 1-D array of recent realized vol values

        Returns
        -------
        (state_label, prob_dict)  e.g. ("bull", {"bull": 0.8, "chop": 0.15, "crisis": 0.05})
        """
        model = self._load()
        if model is None:
            return "chop", {"bull": 0.33, "chop": 0.34, "crisis": 0.33}

        try:
            X = np.column_stack([recent_returns, recent_rv])
            log_prob, state_seq = model.decode(X, algorithm="viterbi")
            posteriors = model.predict_proba(X)

            current_state_idx = int(state_seq[-1])
            current_label = self._state_map.get(current_state_idx, "chop")

            current_posteriors = posteriors[-1]
            prob_dict = {
                self._state_map.get(i, str(i)): round(float(current_posteriors[i]), 4)
                for i in range(self.n_components)
            }
            return current_label, prob_dict
        except Exception as exc:
            logger.warning("[hmm_gate] predict error: %s", exc)
            return "chop", {"bull": 0.33, "chop": 0.34, "crisis": 0.33}

    def is_trained(self) -> bool:
        return _MODEL_PATH.exists()

    # ── Private ──────────────────────────────────────────────────────────────

    def _load(self) -> Optional[object]:
        if self._model is not None:
            return self._model
        if not _MODEL_PATH.exists():
            return None
        try:
            with open(_MODEL_PATH, "rb") as f:
                saved = pickle.load(f)
            self._model = saved["model"]
            self._state_map = saved["state_map"]
            return self._model
        except Exception as exc:
            logger.warning("[hmm_gate] could not load model: %s", exc)
            return None


# ── Singleton ────────────────────────────────────────────────────────────────

_gate = HMMRegimeGate()


def get_hmm_gate() -> HMMRegimeGate:
    return _gate


def enrich_regime_dict(regime: dict, recent_returns: np.ndarray, recent_rv: np.ndarray) -> dict:
    """
    Merge HMM state into an existing regime_detector output dict.
    Safe to call even if hmmlearn is missing (returns unchanged dict).
    """
    gate = get_hmm_gate()
    if not gate.is_trained():
        regime.setdefault("hmm_state", "chop")
        regime.setdefault("hmm_probs", {"bull": 0.33, "chop": 0.34, "crisis": 0.33})
        return regime

    state, probs = gate.predict(recent_returns, recent_rv)
    regime["hmm_state"] = state
    regime["hmm_probs"] = probs
    return regime
