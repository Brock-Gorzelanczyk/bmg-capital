"""Factor registry for portfolio-rank bots.

A factor function takes a list of tickers and a SQLAlchemy Session
(so factor code can pull whatever price / fundamentals data it needs)
and returns a dict[ticker, float]. Higher score means "more of the
factor" — the runtime sorts descending and takes the top decile long.

Phase 1 ships only `alphabetical`. Phase 2 adds `momentum_umd` and
`quality_gross_profitability`.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session


def alphabetical(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    """Score = negative alphabetical index.

    Higher score means earlier in the alphabet, so the runtime's
    "top decile" is the first N tickers by name. Zero economic content;
    used only for framework verification.
    """
    scores: dict[str, float] = {}
    for i, s in enumerate(sorted(symbols)):
        # 1000.0 for first, 999.0 for second, ... so top decile = A-... tickers
        scores[s] = float(1000.0 - i)
    return scores


_REGISTRY: dict[str, Callable[[list[str], Session, dict], dict[str, float]]] = {
    "alphabetical": alphabetical,
}


def compute_factor(
    factor_type: str,
    symbols: list[str],
    db: Session,
    params: dict | None = None,
) -> dict[str, float]:
    fn = _REGISTRY.get(factor_type)
    if fn is None:
        raise KeyError(f"unknown factor: {factor_type}")
    return fn(symbols, db, params or {})


def list_factors() -> list[str]:
    return sorted(_REGISTRY.keys())
