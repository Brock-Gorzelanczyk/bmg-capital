"""Alpaca-tradeable crypto pairs, USD-quoted.

Verified against Alpaca /v2/assets on 2026-07-07. Symbols use the
Alpaca convention (BTC/USD) — the yfinance factor code translates
to BTC-USD internally via the Ticker() lookup.

Initial list: top-20 by market cap, restricted to Alpaca-supported
pairs. BNB / MATIC / ATOM / NEAR / ETC / XLM / ALGO / SUI dropped
per Alpaca asset list (they'd 422 with 'asset not found').
"""
from __future__ import annotations


_CRYPTO_TOP20: list[str] = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "DOGE/USD", "DOT/USD", "LINK/USD", "UNI/USD",
    "LTC/USD", "AAVE/USD", "BCH/USD", "CRV/USD", "SHIB/USD",
    "PEPE/USD", "BONK/USD", "GRT/USD", "SUSHI/USD", "YFI/USD",
]


def crypto_top20() -> list[str]:
    return list(_CRYPTO_TOP20)
