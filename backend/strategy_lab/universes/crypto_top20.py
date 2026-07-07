"""Top 20 crypto pairs by market cap, quoted vs USD.

These are yfinance ticker symbols (BTC-USD, ETH-USD, etc). Static list
snapshot; refresh via yfinance nightly if capacity grows.
"""
from __future__ import annotations


_CRYPTO_TOP20: list[str] = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "AVAX-USD", "DOGE-USD", "DOT-USD", "MATIC-USD",
    "LINK-USD", "UNI-USD", "LTC-USD", "ATOM-USD", "ETC-USD",
    "XLM-USD", "NEAR-USD", "ALGO-USD", "AAVE-USD", "SUI-USD",
]


def crypto_top20() -> list[str]:
    return list(_CRYPTO_TOP20)
