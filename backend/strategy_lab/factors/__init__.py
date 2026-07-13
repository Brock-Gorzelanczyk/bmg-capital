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


def _return_lookback(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .return_lookback import compute
    return compute(symbols, db, params)


def _novy_marx_gp_a(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .novy_marx_gp_a import compute
    return compute(symbols, db, params)


def _low_volatility(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .low_volatility import compute
    return compute(symbols, db, params)


def _value_hml(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .value_hml import compute
    return compute(symbols, db, params)


def _net_stock_issuance(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .net_stock_issuance import compute
    return compute(symbols, db, params)


def _tsm_12m(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .tsm_12m import compute
    return compute(symbols, db, params)


def _idio_volatility(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .idio_volatility import compute
    return compute(symbols, db, params)


def _residual_momentum(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .residual_momentum import compute
    return compute(symbols, db, params)


def _bab(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .bab import compute
    return compute(symbols, db, params)


def _pead(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .pead import compute
    return compute(symbols, db, params)


def _insider_cluster_buys(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .insider_cluster_buys import compute
    return compute(symbols, db, params)


def _crypto_xs_momentum(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .crypto_xs_momentum import compute
    return compute(symbols, db, params)


def _accruals(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .accruals import compute
    return compute(symbols, db, params)


def _short_term_momentum(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .short_term_momentum import compute
    return compute(symbols, db, params)


def _cw_vol_spread(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .cw_vol_spread import compute
    return compute(symbols, db, params)


def _os_ratio(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .os_ratio import compute
    return compute(symbols, db, params)


def _overnight_momentum(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .overnight_momentum import compute
    return compute(symbols, db, params)


def _smart_money_13f(symbols: list[str], db: Session, params: dict) -> dict[str, float]:
    from .smart_money_13f import compute
    return compute(symbols, db, params)


_REGISTRY: dict[str, Callable[[list[str], Session, dict], dict[str, float]]] = {
    "alphabetical": alphabetical,
    # 2026-07-05 Phase 2 factors — both hit yfinance for data.
    "return_lookback": _return_lookback,
    "novy_marx_gp_a": _novy_marx_gp_a,
    # 2026-07-06 SSRN batch: 3 vault Tier A/B factors. All yfinance-backed.
    "low_volatility": _low_volatility,
    "value_hml": _value_hml,
    "net_stock_issuance": _net_stock_issuance,
    # 2026-07-06 fleet gap fillers:
    #   tsm_12m: time-series momentum on ETFs — trend-following gap
    #   idio_volatility: distinct from low_volatility, market-residual vol
    "tsm_12m": _tsm_12m,
    "idio_volatility": _idio_volatility,
    # 2026-07-07 SSRN batch (top-of-catalog picks):
    #   residual_momentum: Blitz-Huij-Martens — 2x Sharpe of raw 12-1 momentum
    #   bab: Frazzini-Pedersen Betting Against Beta — long-only low-beta variant
    "residual_momentum": _residual_momentum,
    "bab": _bab,
    # 2026-07-07 SSRN batch 3:
    #   pead: Post-Earnings-Announcement Drift (Bernard-Thomas)
    #   insider_cluster_buys: Cohen-Malloy-Pomorski opportunistic insider signal
    #   crypto_xs_momentum: Liu-Tsyvinski-Wu crypto cross-section
    "pead": _pead,
    "insider_cluster_buys": _insider_cluster_buys,
    "crypto_xs_momentum": _crypto_xs_momentum,
    # 2026-07-08 SSRN batch 4:
    #   accruals: Sloan 1996 — one of the most-replicated cross-sectional
    #             anomalies. Long low-accrual (quality earnings) names.
    "accruals": _accruals,
    # 2026-07-09 SSRN batch 5:
    #   short_term_momentum: Medhat-Schmeling 2022 RFS — 1-month momentum
    #                        conditioned on turnover. Fills the month t-1
    #                        gap the 12-1 UMD explicitly skips.
    #   cw_vol_spread:       Cremers-Weinbaum 2010 JFQA — OI-weighted IV
    #                        spread (call - put) as informed-flow signal.
    "short_term_momentum": _short_term_momentum,
    "cw_vol_spread": _cw_vol_spread,
    # 2026-07-12 SSRN batch 6:
    #   os_ratio:            Roll-Schwartz-Subrahmanyam 2010, Johnson-So 2012 —
    #                        option volume / stock volume as informed-flow
    #                        signal. Long low O/S. Complements cw_vol_spread.
    #   overnight_momentum:  Lou-Polk-Skouras 2019 JFE — sum of overnight
    #                        (close→open) returns. Daily rebal, uncorrelated
    #                        with 12-1 UMD.
    #   smart_money_13f:     Frazzini-Lamont 2008 — track Δ shares held by
    #                        top-100 hedge funds via SEC 13F filings.
    #                        Quarterly rebal. Reads from smart_money_13f_holdings
    #                        cache; degrades to empty scores until the EDGAR
    #                        ingest job ships.
    "os_ratio": _os_ratio,
    "overnight_momentum": _overnight_momentum,
    "smart_money_13f": _smart_money_13f,
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
