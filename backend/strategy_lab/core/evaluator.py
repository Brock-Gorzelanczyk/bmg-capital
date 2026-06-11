"""
strategy_lab/core/evaluator.py

Deflated Sharpe Ratio (Bailey & López de Prado, 2014) + Benjamini-Hochberg FDR
correction for strategy promotion filtering.

Pure analytics module — no trading mutations, no order placement.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import scipy.stats
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL — callers may execute this against their SQLite / Postgres engine
# ---------------------------------------------------------------------------

STRATEGY_EVALUATION_TRIALS_DDL = """
CREATE TABLE IF NOT EXISTS strategy_evaluation_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    n_param_combos INTEGER DEFAULT 1,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sr_hat REAL,
    dsr_score REAL,
    bh_adjusted_pvalue REAL,
    wfe_score REAL,
    promotion_eligible INTEGER DEFAULT 0
);
"""


# ---------------------------------------------------------------------------
# Core analytical functions
# ---------------------------------------------------------------------------


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int,
    benchmark_sr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute the Deflated Sharpe Ratio (DSR) per Bailey & López de Prado (2014).

    Parameters
    ----------
    returns : np.ndarray
        1-D array of per-observation (e.g. daily) returns.
    n_trials : int
        Total number of independent strategy trials / parameter combinations
        tested.  Must be >= 1 (clamped internally).
    benchmark_sr : float, optional
        If provided, used directly as SR* (the expected maximum Sharpe under
        the null).  If None, SR* is estimated from n_trials via the inverse
        normal CDF.

    Returns
    -------
    dict with keys:
        dsr              – float in [0, 1]: probability the observed Sharpe is
                           genuine (not data-mined noise)
        sr_hat           – annualized observed Sharpe ratio (sqrt(252) scaling)
        sr_benchmark     – SR* value used in the calculation
        z_stat           – standardised z-statistic before CDF transform
        passes_90        – dsr >= 0.90
        passes_95        – dsr >= 0.95
        n_observations   – number of return observations
        skewness         – sample skewness of returns
        kurtosis         – sample excess kurtosis of returns
    """
    safe_defaults: Dict[str, Any] = {
        "dsr": 0.0,
        "sr_hat": 0.0,
        "sr_benchmark": 0.0,
        "z_stat": 0.0,
        "passes_90": False,
        "passes_95": False,
        "n_observations": 0,
        "skewness": 0.0,
        "kurtosis": 0.0,
    }

    # --- guard: empty / trivial input ------------------------------------------
    returns = np.asarray(returns, dtype=float).ravel()
    if returns.size < 4:
        logger.warning(
            "deflated_sharpe_ratio: fewer than 4 observations (%d); "
            "returning safe defaults.",
            returns.size,
        )
        return safe_defaults

    n_trials = max(1, int(n_trials))
    T: int = len(returns)

    # --- per-observation Sharpe (ddof=1) ----------------------------------------
    mu = np.mean(returns)
    sigma = np.std(returns, ddof=1)

    if sigma == 0.0:
        logger.warning(
            "deflated_sharpe_ratio: zero variance in returns; "
            "returning safe defaults."
        )
        return safe_defaults

    sr_hat_per_obs: float = mu / sigma                        # per-observation
    sr_hat_annualized: float = sr_hat_per_obs * math.sqrt(252)

    # --- higher moments ---------------------------------------------------------
    gamma3: float = float(scipy.stats.skew(returns, bias=False))
    gamma4: float = float(scipy.stats.kurtosis(returns, fisher=True, bias=False))  # excess

    # --- expected maximum SR under IID null (SR*) --------------------------------
    if benchmark_sr is not None:
        sr_star: float = float(benchmark_sr)
    else:
        # Approximation: z-score of (1 - 1/N) quantile → per-observation units
        # (same scale as sr_hat_per_obs, so no further scaling needed here)
        sr_star = float(scipy.stats.norm.ppf(1.0 - 1.0 / n_trials))

    # --- DSR z-statistic (Bailey & López de Prado eq. 8) -----------------------
    numerator: float = (sr_hat_per_obs - sr_star) * math.sqrt(T - 1)

    denom_sq: float = (
        1.0
        - gamma3 * sr_hat_per_obs
        + (gamma4 - 1.0) / 4.0 * sr_hat_per_obs ** 2
    )

    if denom_sq <= 0.0:
        # Pathological distribution; fall back to raw numerator sign
        logger.debug(
            "deflated_sharpe_ratio: non-positive denominator squared (%.4f); "
            "clamping z_stat to 0.",
            denom_sq,
        )
        z_stat = 0.0
    else:
        z_stat = numerator / math.sqrt(denom_sq)

    dsr: float = float(scipy.stats.norm.cdf(z_stat))

    return {
        "dsr": dsr,
        "sr_hat": sr_hat_annualized,
        "sr_benchmark": sr_star,
        "z_stat": z_stat,
        "passes_90": dsr >= 0.90,
        "passes_95": dsr >= 0.95,
        "n_observations": T,
        "skewness": gamma3,
        "kurtosis": gamma4,
    }


# ---------------------------------------------------------------------------


def benjamini_hochberg(
    p_values: List[float],
    fdr_q: float = 0.10,
) -> List[bool]:
    """
    Benjamini-Hochberg (1995) FDR correction.

    Parameters
    ----------
    p_values : list[float]
        Uncorrected p-values, one per strategy/hypothesis.
    fdr_q : float
        Desired false discovery rate (default 0.10 = 10 %).

    Returns
    -------
    list[bool]
        Boolean mask aligned with ``p_values``.
        True  → reject null (strategy is statistically significant signal).
        False → fail to reject (likely noise).
    """
    if not p_values:
        return []

    m: int = len(p_values)
    # Build sorted index: ascending p-value
    indexed: List[Tuple[float, int]] = sorted(
        enumerate(p_values), key=lambda x: x[1]
    )

    # BH threshold: p[i] <= (rank / m) * q   (rank is 1-based)
    reject_flags: List[bool] = [False] * m
    last_reject: int = -1

    for rank_0based, (original_idx, pval) in enumerate(indexed):
        rank = rank_0based + 1  # 1-based
        threshold = (rank / m) * fdr_q
        if pval <= threshold:
            last_reject = rank_0based

    # All hypotheses up to and including the last rejection are rejected
    # (standard step-up procedure)
    if last_reject >= 0:
        for rank_0based, (original_idx, _) in enumerate(indexed):
            if rank_0based <= last_reject:
                reject_flags[original_idx] = True

    return reject_flags


# ---------------------------------------------------------------------------


def min_btl_satisfied(
    sr_daily: float,
    t_days: int,
    alpha: float = 0.05,
    beta: float = 0.05,
) -> bool:
    """
    Check the minimum backtest length (MinBTL) condition.

    T* = ((z_alpha + z_beta) / SR_daily)^2 * (1 + SR_daily^2 / 2)

    Parameters
    ----------
    sr_daily : float
        Daily Sharpe ratio (annualized_sr / sqrt(252)).
    t_days : int
        Number of days of backtest data available.
    alpha : float
        Type-I error probability (default 0.05).
    beta : float
        Type-II error probability / desired power = 1 - beta (default 0.05).

    Returns
    -------
    bool
        True if t_days >= T* (backtest is long enough to be meaningful).
    """
    if sr_daily == 0.0:
        # Infinite length required for zero-Sharpe strategy — never satisfied
        return False

    z_alpha: float = float(scipy.stats.norm.ppf(1.0 - alpha))
    z_beta: float = float(scipy.stats.norm.ppf(1.0 - beta))

    t_star: float = (
        ((z_alpha + z_beta) / sr_daily) ** 2
        * (1.0 + sr_daily ** 2 / 2.0)
    )

    return t_days >= t_star


# ---------------------------------------------------------------------------
# Evaluator class
# ---------------------------------------------------------------------------


@dataclass
class _CandidateRecord:
    """Internal container for a single strategy under evaluation."""

    name: str
    returns: np.ndarray
    wfe_score: float = 0.0
    n_param_combos: int = 1


class BMGStrategyEvaluator:
    """
    Orchestrates DSR computation + Benjamini-Hochberg FDR correction across
    a pool of strategy candidates and (optionally) persists results to DB.

    Parameters
    ----------
    db_session : sqlalchemy.orm.Session, optional
        If provided, ``save_to_db()`` and ``_load_n_effective()`` will
        read/write ``strategy_evaluation_trials``.
    fdr_q : float
        False discovery rate budget for the BH procedure (default 0.10).
    """

    def __init__(
        self,
        db_session: Optional[Session] = None,
        fdr_q: float = 0.10,
    ) -> None:
        self.fdr_q: float = fdr_q
        self.db: Optional[Session] = db_session
        self._candidates: Dict[str, _CandidateRecord] = {}
        self.n_effective: int = self._load_n_effective()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_n_effective(self) -> int:
        """
        Sum ``n_param_combos`` from ``strategy_evaluation_trials`` in the DB.
        Returns 0 if the DB session is absent or the table does not exist.
        """
        if self.db is None:
            return 0
        try:
            result = self.db.execute(
                text(
                    "SELECT COALESCE(SUM(n_param_combos), 0) "
                    "FROM strategy_evaluation_trials"
                )
            )
            row = result.fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:  # table missing or any DB error
            logger.debug(
                "_load_n_effective: could not query DB (%s); defaulting to 0.",
                exc,
            )
            return 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_candidate(
        self,
        name: str,
        returns: np.ndarray,
        wfe_score: float = 0.0,
        n_param_combos: int = 1,
    ) -> None:
        """
        Register a strategy candidate for batch evaluation.

        If a candidate with the same ``name`` already exists it is replaced
        and ``n_effective`` is adjusted accordingly.

        Parameters
        ----------
        name : str
            Unique strategy identifier.
        returns : np.ndarray
            Per-observation (daily) return series.
        wfe_score : float
            Walk-forward efficiency score (0–1).  Used in promotion gate.
        n_param_combos : int
            Number of parameter combinations tried during optimisation.
            Contributes to the multiple-testing adjustment via ``n_effective``.
        """
        n_param_combos = max(1, int(n_param_combos))

        if name in self._candidates:
            # Adjust n_effective for the replaced record
            self.n_effective -= self._candidates[name].n_param_combos

        self._candidates[name] = _CandidateRecord(
            name=name,
            returns=np.asarray(returns, dtype=float).ravel(),
            wfe_score=float(wfe_score),
            n_param_combos=n_param_combos,
        )
        self.n_effective = max(1, self.n_effective + n_param_combos)
        logger.debug(
            "add_candidate: '%s' registered.  n_effective=%d",
            name,
            self.n_effective,
        )

    def evaluate_all(self) -> pd.DataFrame:
        """
        Run DSR + BH FDR correction on every registered candidate.

        Returns
        -------
        pd.DataFrame
            One row per candidate with columns:
            name, sr_hat, sr_benchmark, dsr_score, z_stat,
            bh_pvalue, bh_adjusted_pvalue, bh_reject,
            wfe_score, minbtl_satisfied, promotion_eligible
        """
        if not self._candidates:
            logger.warning("evaluate_all: no candidates registered; returning empty DataFrame.")
            return pd.DataFrame(
                columns=[
                    "name", "sr_hat", "sr_benchmark", "dsr_score", "z_stat",
                    "bh_pvalue", "bh_adjusted_pvalue", "bh_reject",
                    "wfe_score", "minbtl_satisfied", "promotion_eligible",
                ]
            )

        n_total_trials: int = max(1, self.n_effective)
        rows: List[Dict[str, Any]] = []

        for rec in self._candidates.values():
            dsr_result = deflated_sharpe_ratio(
                returns=rec.returns,
                n_trials=n_total_trials,
            )

            # p-value for BH: p = 1 - DSR  (DSR is prob. Sharpe is real)
            bh_pvalue: float = 1.0 - dsr_result["dsr"]

            # MinBTL check — convert annualised SR to daily
            sr_daily: float = (
                dsr_result["sr_hat"] / math.sqrt(252)
                if dsr_result["sr_hat"] != 0.0
                else 0.0
            )
            minbtl: bool = min_btl_satisfied(
                sr_daily=sr_daily,
                t_days=dsr_result["n_observations"],
            )

            rows.append(
                {
                    "name": rec.name,
                    "sr_hat": dsr_result["sr_hat"],
                    "sr_benchmark": dsr_result["sr_benchmark"],
                    "dsr_score": dsr_result["dsr"],
                    "z_stat": dsr_result["z_stat"],
                    "bh_pvalue": bh_pvalue,
                    "bh_adjusted_pvalue": float("nan"),  # filled below
                    "bh_reject": False,                  # filled below
                    "wfe_score": rec.wfe_score,
                    "minbtl_satisfied": minbtl,
                    "promotion_eligible": False,         # filled below
                }
            )

        df = pd.DataFrame(rows)

        # --- BH correction ------------------------------------------------------
        p_vals: List[float] = df["bh_pvalue"].tolist()
        m: int = len(p_vals)
        bh_rejects: List[bool] = benjamini_hochberg(p_vals, fdr_q=self.fdr_q)
        df["bh_reject"] = bh_rejects

        # Compute BH-adjusted p-values (Benjamini-Hochberg step-up adjusted)
        # adjusted_p[i] = min over j>=i of (m/j * p[sorted_j])
        sorted_idx = np.argsort(p_vals)
        adjusted = np.empty(m, dtype=float)
        for rank_0, orig_idx in enumerate(sorted_idx):
            adjusted[orig_idx] = min(
                (m / (rank_0 + 1)) * p_vals[orig_idx], 1.0
            )
        # Enforce monotonicity (step-up)
        # Traverse sorted order in reverse and carry forward the minimum
        running_min = 1.0
        for rank_0 in reversed(range(m)):
            orig_idx = sorted_idx[rank_0]
            running_min = min(running_min, adjusted[orig_idx])
            adjusted[orig_idx] = running_min

        df["bh_adjusted_pvalue"] = adjusted

        # --- promotion gate -----------------------------------------------------
        df["promotion_eligible"] = (
            (df["dsr_score"] >= 0.90)
            & (df["wfe_score"] >= 0.5)
            & df["minbtl_satisfied"]
        )

        logger.info(
            "evaluate_all: %d candidates evaluated.  %d promotion-eligible.",
            len(df),
            df["promotion_eligible"].sum(),
        )
        return df

    def get_promotion_candidates(self) -> pd.DataFrame:
        """
        Return only strategies that pass the full promotion gate.

        Returns
        -------
        pd.DataFrame
            Subset of ``evaluate_all()`` where ``promotion_eligible == True``,
            sorted by ``dsr_score`` descending.
        """
        all_results = self.evaluate_all()
        eligible = all_results[all_results["promotion_eligible"]].sort_values(
            "dsr_score", ascending=False
        )
        return eligible.reset_index(drop=True)

    def save_to_db(self) -> None:
        """
        Upsert every registered candidate into ``strategy_evaluation_trials``.

        Skipped silently if ``db_session`` was not provided.
        If the table does not exist, logs a warning and returns.
        """
        if self.db is None:
            logger.debug("save_to_db: no DB session; skipping.")
            return

        results_df = self.evaluate_all()
        if results_df.empty:
            logger.debug("save_to_db: no results to persist.")
            return

        evaluated_at = datetime.utcnow().isoformat(timespec="seconds")

        for _, row in results_df.iterrows():
            rec = self._candidates[row["name"]]
            try:
                # Try UPDATE first
                updated = self.db.execute(
                    text(
                        """
                        UPDATE strategy_evaluation_trials
                        SET n_param_combos        = :n_param_combos,
                            evaluated_at          = :evaluated_at,
                            sr_hat                = :sr_hat,
                            dsr_score             = :dsr_score,
                            bh_adjusted_pvalue    = :bh_adjusted_pvalue,
                            wfe_score             = :wfe_score,
                            promotion_eligible    = :promotion_eligible
                        WHERE strategy_name = :strategy_name
                        """
                    ),
                    {
                        "strategy_name": row["name"],
                        "n_param_combos": rec.n_param_combos,
                        "evaluated_at": evaluated_at,
                        "sr_hat": float(row["sr_hat"]),
                        "dsr_score": float(row["dsr_score"]),
                        "bh_adjusted_pvalue": float(row["bh_adjusted_pvalue"]),
                        "wfe_score": float(row["wfe_score"]),
                        "promotion_eligible": int(bool(row["promotion_eligible"])),
                    },
                )
                if updated.rowcount == 0:
                    # Row does not exist yet — INSERT
                    self.db.execute(
                        text(
                            """
                            INSERT INTO strategy_evaluation_trials
                                (strategy_name, n_param_combos, evaluated_at,
                                 sr_hat, dsr_score, bh_adjusted_pvalue,
                                 wfe_score, promotion_eligible)
                            VALUES
                                (:strategy_name, :n_param_combos, :evaluated_at,
                                 :sr_hat, :dsr_score, :bh_adjusted_pvalue,
                                 :wfe_score, :promotion_eligible)
                            """
                        ),
                        {
                            "strategy_name": row["name"],
                            "n_param_combos": rec.n_param_combos,
                            "evaluated_at": evaluated_at,
                            "sr_hat": float(row["sr_hat"]),
                            "dsr_score": float(row["dsr_score"]),
                            "bh_adjusted_pvalue": float(row["bh_adjusted_pvalue"]),
                            "wfe_score": float(row["wfe_score"]),
                            "promotion_eligible": int(bool(row["promotion_eligible"])),
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "save_to_db: failed to upsert '%s': %s", row["name"], exc
                )
                continue

        try:
            self.db.commit()
            logger.info("save_to_db: committed %d rows.", len(results_df))
        except Exception as exc:
            logger.error("save_to_db: commit failed: %s", exc)
            self.db.rollback()
