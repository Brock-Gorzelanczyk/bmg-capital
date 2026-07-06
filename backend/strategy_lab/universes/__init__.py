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


def _load_sp500() -> list[str]:
    """Lazy import; prefer the auto-refreshed dynamic file when present.

    `sp500_dynamic.py` is written nightly at 02:15 America/Chicago by
    `app.services.sp500_refresh.refresh_and_write()` from the iShares IVV
    holdings CSV. Falls back to the hardcoded snapshot in `sp500.py`
    when the dynamic file is missing or fails to import (fresh deploy,
    first-boot before the cron has run, iShares outage).
    """
    try:
        from .sp500_dynamic import sp500_dynamic  # type: ignore
        return sp500_dynamic()
    except Exception:
        from .sp500 import sp500
        return sp500()


def _load_etf_liquid() -> list[str]:
    from .etf_liquid import etf_liquid
    return etf_liquid()


_REGISTRY: dict[str, Callable[[], list[str]]] = {
    "sp500_partial": sp500_partial,
    "sp500": _load_sp500,
    "etf_liquid": _load_etf_liquid,
}


def get_universe(name: str) -> list[str]:
    fn = _REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"unknown universe: {name}")
    return fn()


def list_universes() -> list[str]:
    return sorted(_REGISTRY.keys())
