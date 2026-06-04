"""
Hierarchical Risk Parity Allocator — Weekend 3, Module 4.

HRP clusters strategies by return correlation (scipy linkage),
then allocates capital within and across clusters so each contributes
equal risk — without inverting a potentially ill-conditioned covariance matrix.

Runs weekly (cron). Writes new capital_pct to BotAllocation.

Reference: López de Prado, "Building Diversified Portfolios That Outperform
Out-of-Sample", Journal of Portfolio Management 2016 (SSRN 2708678).
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    """Convert covariance matrix to correlation matrix."""
    std = np.sqrt(np.diag(cov))
    std[std == 0] = 1.0  # avoid division by zero
    corr = cov / np.outer(std, std)
    corr = np.clip(corr, -1, 1)
    np.fill_diagonal(corr, 1.0)
    return corr


def _quasi_diag(link: np.ndarray, n: int) -> list[int]:
    """Sort clustered items so similar items are adjacent (quasi-diagonalization)."""
    link = link.astype(int)
    sort_ix = [0]
    while True:
        new_sort_ix: list[int] = []
        for item in sort_ix:
            if item < n:
                new_sort_ix.append(item)
            else:
                left = int(link[item - n, 0])
                right = int(link[item - n, 1])
                new_sort_ix.extend([left, right])
        sort_ix = new_sort_ix
        if max(sort_ix) < n:
            break
    return sort_ix


def _recursive_bisect(cov: np.ndarray, sort_ix: list[int]) -> np.ndarray:
    """Recursively bisect and allocate weights via inverse-variance within each cluster."""
    w = np.ones(len(sort_ix))
    cluster_items = [sort_ix]

    while cluster_items:
        cluster_items = [
            sub for item in cluster_items for sub in [item[:len(item) // 2], item[len(item) // 2:]]
            if len(item) > 1
        ]
        for subcluster in cluster_items:
            c_slice = np.ix_(subcluster, subcluster)
            sub_cov = cov[c_slice]
            # Inverse variance weights within subcluster
            var = np.diag(sub_cov).copy()
            var[var <= 0] = 1e-10
            inv_var = 1.0 / var
            sub_w = inv_var / inv_var.sum()

            # Cluster variance
            c_var = float(sub_w @ sub_cov @ sub_w)
            alpha = c_var / (c_var + 1e-10)

            w[subcluster] *= sub_w * (1 - alpha)

    return w / w.sum()


def hrp_weights(
    returns_matrix: np.ndarray,
    labels: Optional[list[str]] = None,
) -> dict[str, float]:
    """
    Compute HRP weights from a return matrix.

    Parameters
    ----------
    returns_matrix : (T, N) array — T time periods, N assets/strategies
    labels : list of N strategy/asset names

    Returns
    -------
    dict mapping label → weight (sums to 1.0)
    """
    try:
        from scipy.cluster.hierarchy import linkage
        from scipy.spatial.distance import squareform
    except ImportError:
        logger.warning("scipy not installed — falling back to equal-weight HRP")
        n = returns_matrix.shape[1]
        if labels:
            return {l: round(1.0 / n, 4) for l in labels}
        return {str(i): round(1.0 / n, 4) for i in range(n)}

    n = returns_matrix.shape[1]
    if labels is None:
        labels = [str(i) for i in range(n)]

    # Handle degenerate cases
    if n == 1:
        return {labels[0]: 1.0}
    if n == 2:
        return {labels[0]: 0.5, labels[1]: 0.5}

    # Covariance + correlation
    cov = np.cov(returns_matrix.T)
    corr = _cov_to_corr(cov)

    # Distance matrix for clustering
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, 1))
    np.fill_diagonal(dist, 0)

    # Hierarchical clustering (Ward's linkage)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="ward")

    # Quasi-diagonalization
    sort_ix = _quasi_diag(link, n)

    # Recursive bisection
    w = _recursive_bisect(cov, sort_ix)

    # Reorder weights back to original label order
    w_final = np.zeros(n)
    for new_pos, orig_pos in enumerate(sort_ix):
        w_final[orig_pos] = w[new_pos]

    return {labels[i]: round(float(w_final[i]), 4) for i in range(n)}


class HRPAllocator:
    """
    Stateful HRP allocator that maintains return history per bot/strategy.
    """

    def __init__(self, min_history_days: int = 60) -> None:
        self.min_history_days = min_history_days
        self._returns: dict[str, list[float]] = {}

    def update(self, label: str, daily_return: float) -> None:
        """Feed a daily return observation."""
        if label not in self._returns:
            self._returns[label] = []
        self._returns[label].append(daily_return)

    def allocate(self) -> dict[str, float]:
        """
        Compute HRP weights. Falls back to equal-weight if insufficient history.
        """
        # Filter to labels with sufficient history
        qualified = {
            k: v for k, v in self._returns.items()
            if len(v) >= self.min_history_days
        }

        if len(qualified) < 2:
            n = len(self._returns) or 1
            return {k: round(1.0 / n, 4) for k in self._returns}

        labels = list(qualified.keys())
        min_len = min(len(v) for v in qualified.values())
        # Align all series to same length
        matrix = np.array([qualified[l][-min_len:] for l in labels]).T

        return hrp_weights(matrix, labels)

    def n_assets(self) -> int:
        return len(self._returns)


_allocator: Optional[HRPAllocator] = None


def get_hrp_allocator() -> HRPAllocator:
    global _allocator
    if _allocator is None:
        _allocator = HRPAllocator()
    return _allocator
