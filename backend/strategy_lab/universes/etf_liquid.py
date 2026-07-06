"""Liquid ETF universe for time-series momentum bots.

30-name curated list spanning equity (US + international), fixed income,
commodities, real estate, and sectors. Chosen for daily volume > $50M
so the momentum bot has clean price signals and low fill risk.

Update cadence: quarterly, by hand. Constituent turnover in liquid
ETFs is near-zero.
"""
from __future__ import annotations


_ETF_LIQUID: list[str] = [
    # US equity broad
    "SPY", "QQQ", "IWM", "DIA", "MDY",
    # International equity
    "VGK", "VWO", "EFA", "EEM",
    # Fixed income
    "TLT", "IEF", "LQD", "HYG", "MUB", "TIP", "SHY",
    # Commodities
    "GLD", "SLV", "DBC", "USO", "UNG",
    # Real estate
    "VNQ", "IYR",
    # Sectors
    "XLE", "XLF", "XLK", "XLV", "XLY", "XLI",
]


def etf_liquid() -> list[str]:
    return list(_ETF_LIQUID)
