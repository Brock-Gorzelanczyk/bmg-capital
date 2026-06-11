"""Symbol universe lists for the Scout screener."""

from __future__ import annotations

# Top 100 S&P 500 components by market cap (hardcoded)
SP500_SYMBOLS: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B",
    "UNH", "XOM", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "ABBV",
    "MRK", "LLY", "PEP", "COST", "AVGO", "TMO", "MCD", "ACN", "CSCO",
    "ABT", "DHR", "WMT", "NKE", "NEE", "PM", "TXN", "CRM", "BMY",
    "UPS", "QCOM", "RTX", "HON", "T", "AMGN", "SBUX", "INTU", "LOW",
    "MDT", "BLK", "GOOG", "IBM", "GS", "CAT", "AXP", "DE", "AMAT",
    "SPGI", "NOW", "ELV", "ADP", "ISRG", "MMC", "BKNG", "VRTX", "ADI",
    "LMT", "CI", "SYK", "REGN", "ZTS", "MO", "PLD", "CB", "C",
    "TGT", "AMT", "DUK", "SO", "ETN", "APD", "MDLZ", "ITW", "ICE",
    "NOC", "CL", "ATVI", "EMR", "PNC", "WM", "F", "GM", "USB",
    "NSC", "ECL", "AON", "FDX", "TFC", "FISV", "VLO", "PSA", "MSI",
    "HPQ", "BA", "GE",
]

# Top 30 crypto pairs (yfinance format)
CRYPTO_SYMBOLS: list[str] = [
    "BTC-USD", "ETH-USD", "BNB-USD", "XRP-USD", "SOL-USD",
    "ADA-USD", "AVAX-USD", "DOGE-USD", "DOT-USD", "MATIC-USD",
    "SHIB-USD", "LTC-USD", "UNI-USD", "LINK-USD", "ATOM-USD",
    "XLM-USD", "NEAR-USD", "ALGO-USD", "ICP-USD", "FIL-USD",
    "VET-USD", "SAND-USD", "MANA-USD", "AXS-USD", "CRO-USD",
    "HBAR-USD", "FTM-USD", "EOS-USD", "THETA-USD", "AAVE-USD",
]

# Additional mid-caps (Russell 1000 additions beyond S&P 100)
RUSSELL_EXTRA_SYMBOLS: list[str] = [
    "SNAP", "SPOT", "LYFT", "UBER", "DASH", "ABNB", "RBLX", "RIVN",
    "LCID", "PLTR", "HOOD", "COIN", "SOFI", "OPEN", "CLOV", "WISH",
    "ZM", "PTON", "NKLA", "SPCE", "NET", "DDOG", "SNOW", "U",
    "PATH", "S", "GTLB", "BILL", "MNDY", "DOCN", "MDB", "CFLT",
    "ESTC", "ZI", "BRZE", "PCOR", "SAMSF", "CELH", "DUOL", "IONQ",
]

UNIVERSE_PRESETS: dict[str, list[str]] = {
    "sp500": SP500_SYMBOLS,
    "russell1000": SP500_SYMBOLS + RUSSELL_EXTRA_SYMBOLS,
    "crypto_top50": CRYPTO_SYMBOLS,
    "sp500_plus_top_crypto": SP500_SYMBOLS + CRYPTO_SYMBOLS,
    "watchlist": [],  # populated at runtime from user's watchlist
}


def get_universe_symbols(
    universe: str,
    watchlist_symbols: list[str] | None = None,
) -> list[str]:
    """Return deduplicated symbol list for a universe preset.

    Args:
        universe: One of the keys in UNIVERSE_PRESETS.  Unknown keys fall back
                  to "sp500_plus_top_crypto".
        watchlist_symbols: Only used when universe == "watchlist".

    Returns:
        Deduplicated list of ticker strings, order-preserving for preset
        universes and set-deduplicated (no order guarantee) for watchlists.
    """
    if universe == "watchlist":
        return list(set(watchlist_symbols or []))
    symbols = UNIVERSE_PRESETS.get(universe, UNIVERSE_PRESETS["sp500_plus_top_crypto"])
    return list(dict.fromkeys(symbols))  # deduplicate preserving order


def get_asset_class(symbol: str) -> str:
    """Detect equity vs crypto from symbol format.

    Args:
        symbol: Ticker string, e.g. "AAPL", "BTC-USD", "ETHUSDT".

    Returns:
        "crypto" or "equity".
    """
    if (
        symbol.endswith("-USD")
        or symbol.endswith("/USD")
        or symbol.endswith("USDT")
    ):
        return "crypto"
    return "equity"
