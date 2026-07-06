"""Universe registry for portfolio-rank bots.

Each universe is a callable that returns a list of tickers. The
runtime looks up the callable by name via `get_universe`.

Phase 1 ships one canned universe (`sp500_partial`) — a 60-name
subset of S&P 500 mega/large caps used for framework verification.
Real anomaly bots in Phase 2 need full 500/1000/2000-name universes;
those get pulled from a provider (or a nightly refresh table) rather
than hard-coded here.
"""
from __future__ import annotations

from typing import Callable


# 60 recognizable S&P 500 names spanning sectors. Alphabetized on write
# so the dummy alphabetical-rank bot has a deterministic top decile.
_SP500_PARTIAL: list[str] = [
    "AAPL", "ABBV", "ACN", "ADBE", "AMD", "AMGN", "AMZN", "AVGO",
    "AXP", "BA", "BAC", "BLK", "BMY", "C", "CAT", "CMCSA",
    "COST", "CRM", "CSCO", "CVS", "CVX", "DE", "DIS", "DUK",
    "F", "FDX", "GE", "GILD", "GM", "GOOG", "GOOGL", "GS",
    "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "LIN",
    "LLY", "LMT", "LOW", "MA", "MCD", "META", "MRK", "MS",
    "MSFT", "NEE", "NFLX", "NKE", "NOW", "NVDA", "ORCL", "PEP",
    "PFE", "PG", "PM", "PYPL",
]


def sp500_partial() -> list[str]:
    return list(_SP500_PARTIAL)


_REGISTRY: dict[str, Callable[[], list[str]]] = {
    "sp500_partial": sp500_partial,
}


def get_universe(name: str) -> list[str]:
    fn = _REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"unknown universe: {name}")
    return fn()


def list_universes() -> list[str]:
    return sorted(_REGISTRY.keys())
