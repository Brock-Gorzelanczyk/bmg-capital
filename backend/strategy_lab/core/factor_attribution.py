"""Fama-French 3-factor attribution + HRP allocation."""
from __future__ import annotations

import io
import logging
import math
import os
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

FAMA_FRENCH_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/"
    "ftp/F-F_Research_Data_Factors_daily_CSV.zip"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

_ZEROS_DICT: Dict[str, object] = {
    "alpha": 0.0,
    "alpha_annualized": 0.0,
    "alpha_tstat": 0.0,
    "b_mkt": 0.0,
    "b_smb": 0.0,
    "b_hml": 0.0,
    "r_squared": 0.0,
    "alpha_significant": False,
}


# ── Public API ────────────────────────────────────────────────────────────────


def fetch_ff_factors(cache_dir: str = "~/.bmg_cache") -> pd.DataFrame:
    """Download (or load from cache) the Fama-French 3-factor daily data.

    Returns a DataFrame with a DatetimeIndex and columns:
        mkt_rf, smb, hml, rf  (all in decimal, not percent).

    An empty DataFrame is returned on any network/parse error so callers can
    degrade gracefully.
    """
    expanded = Path(cache_dir).expanduser()
    expanded.mkdir(parents=True, exist_ok=True)
    cache_file = expanded / "ff3_daily.parquet"

    # ── Cache hit ─────────────────────────────────────────────────────────────
    if cache_file.exists():
        age_seconds = (
            pd.Timestamp.now() - pd.Timestamp(cache_file.stat().st_mtime, unit="s")
        ).total_seconds()
        if age_seconds < 86_400:  # 24 h
            try:
                return pd.read_parquet(cache_file)
            except Exception as exc:  # noqa: BLE001
                logger.warning("FF cache read failed (%s); re-fetching.", exc)

    # ── Download ──────────────────────────────────────────────────────────────
    try:
        response = requests.get(FAMA_FRENCH_URL, timeout=30)
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            # The zip contains at least one CSV; pick the daily (non-annual) file.
            names = [n for n in zf.namelist() if n.endswith(".CSV") or n.endswith(".csv")]
            # The main daily file is the largest (annual summary is a tiny suffix).
            csv_name = max(names, key=lambda n: zf.getinfo(n).file_size)
            raw_text = zf.read(csv_name).decode("utf-8", errors="replace")

        # ── Parse: skip preamble lines until we hit a data row ────────────────
        lines: List[str] = raw_text.splitlines()
        data_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Data rows start with an 8-digit date like 19260701
            if stripped and stripped[:4].isdigit() and len(stripped.split(",")[0].strip()) == 8:
                data_start = i
                break

        data_lines = lines[data_start:]

        # Find where data ends (annual rows at the bottom have 6-digit dates or blanks)
        data_end = len(data_lines)
        for j, line in enumerate(data_lines):
            stripped = line.strip()
            if not stripped:
                continue
            first_token = stripped.split(",")[0].strip()
            # Annual rows have a 4- or 6-digit "date" like "192607" or blank
            if first_token and not (first_token.isdigit() and len(first_token) == 8):
                data_end = j
                break

        csv_block = "\n".join(data_lines[:data_end])
        df = pd.read_csv(
            io.StringIO(csv_block),
            header=None,
            names=["date", "Mkt-RF", "SMB", "HML", "RF"],
            skipinitialspace=True,
        )

        # ── Coerce types ──────────────────────────────────────────────────────
        df["date"] = pd.to_datetime(df["date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"])

        today = pd.Timestamp(date.today())
        df = df[df["date"] <= today]

        for col in ["Mkt-RF", "SMB", "HML", "RF"]:
            df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

        df = df.dropna()
        df = df.rename(columns={"Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RF": "rf"})
        df = df.set_index("date").sort_index()

        # ── Cache result ──────────────────────────────────────────────────────
        try:
            df.to_parquet(cache_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write FF cache: %s", exc)

        return df

    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_ff_factors failed: %s", exc)
        return pd.DataFrame()


def fama_french_decomposition(
    strategy_returns: pd.Series,
    ff_factors: pd.DataFrame,
) -> dict:
    """Run an OLS regression of strategy excess returns on FF3 factors.

    Args:
        strategy_returns: Daily total returns (not excess) as a Series with a
            DatetimeIndex.
        ff_factors: DataFrame from :func:`fetch_ff_factors`.

    Returns:
        dict with keys: alpha, alpha_annualized, alpha_tstat, b_mkt, b_smb,
        b_hml, r_squared, alpha_significant.  All zeros on insufficient data.
    """
    try:
        import statsmodels.api as sm  # lazy import — optional heavy dep

        # ── Align ─────────────────────────────────────────────────────────────
        common_idx = strategy_returns.index.intersection(ff_factors.index)
        if len(common_idx) < 30:
            return dict(_ZEROS_DICT)

        ret = strategy_returns.loc[common_idx]
        factors = ff_factors.loc[common_idx]
        rf = factors["rf"]
        excess = ret - rf
        X = factors[["mkt_rf", "smb", "hml"]]

        # ── OLS ───────────────────────────────────────────────────────────────
        X_const = sm.add_constant(X)
        model = sm.OLS(excess, X_const).fit()

        alpha: float = float(model.params["const"])
        alpha_annualized: float = alpha * 252
        alpha_tstat: float = float(model.tvalues["const"])

        return {
            "alpha": alpha,
            "alpha_annualized": alpha_annualized,
            "alpha_tstat": alpha_tstat,
            "b_mkt": float(model.params["mkt_rf"]),
            "b_smb": float(model.params["smb"]),
            "b_hml": float(model.params["hml"]),
            "r_squared": float(model.rsquared),
            "alpha_significant": bool(abs(alpha_tstat) >= 2.0),
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("fama_french_decomposition failed: %s", exc)
        return dict(_ZEROS_DICT)


def hierarchical_risk_parity(returns_df: pd.DataFrame) -> dict:
    """Compute Hierarchical Risk Parity (HRP) weights via recursive bisection.

    Args:
        returns_df: DataFrame where each column is a strategy/bot and each row
            is a daily return observation.

    Returns:
        dict mapping column name -> allocation weight (sums to 1.0).
        Falls back to equal weights on insufficient data or errors.
    """
    cols = list(returns_df.columns)
    equal: dict = {c: 1.0 / len(cols) for c in cols}

    if len(cols) < 2:
        return equal

    try:
        from scipy.cluster.hierarchy import leaves_list, linkage  # noqa: PLC0415
        from scipy.spatial.distance import squareform  # noqa: PLC0415

        clean = returns_df.dropna()
        if len(clean) < 10:
            return equal

        corr_matrix = clean.corr().values
        dist_matrix = np.sqrt(np.clip(0.5 * (1.0 - corr_matrix), 0.0, None))

        # scipy linkage expects condensed distance vector
        condensed = squareform(dist_matrix, checks=False)
        link = linkage(condensed, method="single")
        sort_order: List[int] = list(leaves_list(link))
        ordered_cols: List[str] = [cols[i] for i in sort_order]

        def _cluster_var(cluster_cols: List[str]) -> float:
            """Inverse-variance weighted variance of a cluster."""
            sub = clean[cluster_cols]
            variances = sub.var()
            # Guard against zero variance
            variances = variances.replace(0.0, np.nan).dropna()
            if variances.empty:
                return 1e-10
            w_inv = 1.0 / variances
            w = w_inv / w_inv.sum()
            cov = sub[variances.index.tolist()].cov().values
            return float(np.dot(w.values, np.dot(cov, w.values)))

        def _bisect(items: List[str]) -> dict:
            """Recursively bisect the ordered cluster list."""
            if len(items) == 1:
                return {items[0]: 1.0}
            split = len(items) // 2
            left, right = items[:split], items[split:]
            cv_left = _cluster_var(left)
            cv_right = _cluster_var(right)
            denom = cv_left + cv_right
            alpha_left = 1.0 - cv_left / denom if denom > 0 else 0.5
            l_weights = _bisect(left)
            r_weights = _bisect(right)
            return (
                {k: v * alpha_left for k, v in l_weights.items()}
                | {k: v * (1.0 - alpha_left) for k, v in r_weights.items()}
            )

        raw_weights = _bisect(ordered_cols)

        # Normalize to sum = 1.0
        total = sum(raw_weights.values())
        if total <= 0:
            return equal
        weights = {k: v / total for k, v in raw_weights.items()}
        return weights

    except Exception as exc:  # noqa: BLE001
        logger.warning("hierarchical_risk_parity failed: %s", exc)
        return equal


def neutralize_factor_exposure(
    current_weights: dict,
    factor_loadings: dict,
    preserve_total: bool = True,
) -> dict:
    """Partially neutralize market-beta exposure across a set of bots.

    Uses a simple one-step proportional adjustment (not full quadratic
    programming) to reduce net market-beta toward zero.

    Args:
        current_weights:  {bot_id: weight}
        factor_loadings:  {bot_id: {"beta_market": float, "beta_smb": float, "beta_hml": float}}
        preserve_total:   If True, renormalize so weights sum to 1.0.

    Returns:
        {bot_id: adjusted_weight}
    """
    if not current_weights:
        return current_weights

    # ── Compute portfolio-level factor exposures ──────────────────────────────
    port_beta_mkt = sum(
        current_weights.get(k, 0.0) * v.get("beta_market", 0.0)
        for k, v in factor_loadings.items()
    )
    port_beta_smb = sum(
        current_weights.get(k, 0.0) * v.get("beta_smb", 0.0)
        for k, v in factor_loadings.items()
    )
    port_beta_hml = sum(
        current_weights.get(k, 0.0) * v.get("beta_hml", 0.0)
        for k, v in factor_loadings.items()
    )

    # If all loadings are zero there is nothing to neutralize.
    if port_beta_mkt == 0.0 and port_beta_smb == 0.0 and port_beta_hml == 0.0:
        return dict(current_weights)

    # ── Simple proportional adjustment on market beta ─────────────────────────
    adjusted: dict = {}
    for bot_id, w in current_weights.items():
        loadings = factor_loadings.get(bot_id, {})
        beta_mkt = loadings.get("beta_market", 0.0)
        adj_w = max(0.0, w - 0.5 * (beta_mkt - port_beta_mkt) * w)
        adjusted[bot_id] = adj_w

    if preserve_total:
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}

    return adjusted
