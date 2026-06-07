"""Live price fetcher — exchange-native, no yfinance.

Use this for any code that needs a CURRENT price for trade decisions:
  - Position monitor exit prices
  - Fill simulation
  - Risk calculations
  - Migration cleanup closes

Crypto  → Kraken public ticker API (proven working; no auth required)
Stocks  → Alpaca StockLatestTradeRequest (IEX feed)

yfinance is acceptable ONLY for historical bars used as chart backdrops.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ── Kraken symbol mapping ─────────────────────────────────────────────────────
# Maps our internal "BASE/USD" format to the Kraken pair query string.
# Kraken returns results under normalized keys (sometimes different from the pair
# we sent), so we also maintain a reverse lookup.

_TO_KRAKEN_PAIR: dict[str, str] = {
    "BTC/USD":   "XBTUSD",
    "ETH/USD":   "ETHUSD",
    "SOL/USD":   "SOLUSD",
    "AVAX/USD":  "AVAXUSD",
    "DOGE/USD":  "XDGUSD",
    "ADA/USD":   "ADAUSD",
    "LINK/USD":  "LINKUSD",
    "MATIC/USD": "MATICUSD",
    "ARB/USD":   "ARBUSD",
    "OP/USD":    "OPUSD",
    "BNB/USD":   "BNBUSD",
    "DOT/USD":   "DOTUSD",
    "LTC/USD":   "LTCUSD",
    "XRP/USD":   "XXRPZUSD",
    "UNI/USD":   "UNIUSD",
    "ATOM/USD":  "ATOMUSD",
    "NEAR/USD":  "NEARUSD",
    "APT/USD":   "APTUSD",
    "SUI/USD":   "SUIUSD",
}

# Some Kraken response keys differ from the pair we requested.
# Map pair → expected response key (only needed for legacy pairs).
_KRAKEN_RESPONSE_KEY: dict[str, str] = {
    "XBTUSD":  "XXBTZUSD",
    "ETHUSD":  "XETHZUSD",
    "XDGUSD":  "XDGZUSD",
    "XXRPZUSD": "XXRPZUSD",
}


def _kraken_pair(symbol: str) -> Optional[str]:
    """Return the Kraken pair string for a crypto symbol, or None if unknown."""
    if symbol in _TO_KRAKEN_PAIR:
        return _TO_KRAKEN_PAIR[symbol]
    # Generic fallback: BASE/USD → BASEUSD
    if "/" in symbol:
        base = symbol.split("/")[0]
        if base == "BTC":
            base = "XBT"
        return f"{base}USD"
    return None


def fetch_crypto_prices_kraken(symbols: list[str], timeout: int = 8) -> dict[str, float]:
    """Fetch live crypto prices from Kraken public ticker API.

    Args:
        symbols: List of internal symbols in "BASE/USD" format.
        timeout: HTTP timeout in seconds.

    Returns:
        Dict mapping original symbol → USD price. Missing symbols are omitted.
    """
    if not symbols:
        return {}

    pair_to_sym: dict[str, str] = {}  # kraken_pair → original symbol
    for sym in symbols:
        pair = _kraken_pair(sym)
        if pair:
            pair_to_sym[pair] = sym

    if not pair_to_sym:
        return {}

    pairs_str = ",".join(pair_to_sym.keys())
    url = f"https://api.kraken.com/0/public/Ticker?pair={pairs_str}"
    prices: dict[str, float] = {}

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bmg-capital/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        if data.get("error"):
            logger.warning("[live_prices] Kraken API error: %s", data["error"])

        result = data.get("result", {})

        for pair, sym in pair_to_sym.items():
            # Try the exact pair key first, then the normalized response key
            response_key = _KRAKEN_RESPONSE_KEY.get(pair, pair)
            entry = result.get(response_key) or result.get(pair)

            if entry and entry.get("c"):
                try:
                    price = float(entry["c"][0])
                    if price > 0:
                        prices[sym] = price
                except (ValueError, IndexError):
                    pass

        logger.debug("[live_prices] Kraken: %d/%d symbols fetched", len(prices), len(symbols))

    except Exception as exc:
        logger.warning("[live_prices] Kraken fetch failed: %s", exc)

    return prices


def fetch_stock_prices_alpaca(symbols: list[str]) -> dict[str, float]:
    """Fetch live stock prices via Alpaca StockLatestTradeRequest (IEX feed).

    Args:
        symbols: List of stock ticker symbols (no slashes).

    Returns:
        Dict mapping symbol → price. Missing symbols are omitted.
    """
    if not symbols:
        return {}

    prices: dict[str, float] = {}
    try:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestTradeRequest
        from app.alpaca.client import get_historical_client

        client = get_historical_client()
        trades = client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        )
        for sym, trade in trades.items():
            if trade and trade.price and float(trade.price) > 0:
                prices[sym] = float(trade.price)

    except Exception as exc:
        logger.warning("[live_prices] Alpaca stock latest-trade failed: %s", exc)

    return prices


def fetch_live_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch live prices, routing crypto to Kraken and stocks to Alpaca.

    Args:
        symbols: Mix of "BASE/USD" crypto and plain stock tickers.

    Returns:
        Dict mapping symbol → price. Symbols with no price are omitted.
    """
    crypto_syms = [s for s in symbols if "/" in s]
    stock_syms  = [s for s in symbols if "/" not in s]

    prices: dict[str, float] = {}

    if crypto_syms:
        kraken_prices = fetch_crypto_prices_kraken(crypto_syms)
        prices.update(kraken_prices)

        # For any crypto symbols Kraken didn't cover, try Alpaca crypto feed
        missing_crypto = [s for s in crypto_syms if s not in prices]
        if missing_crypto:
            try:
                from alpaca.data.historical.crypto import CryptoHistoricalDataClient
                from alpaca.data.requests import CryptoLatestTradeRequest

                # Alpaca crypto uses BASE/USD format natively
                alpaca_syms = [s if s.endswith("/USD") else f"{s.split('/')[0]}/USD"
                               for s in missing_crypto]
                client = CryptoHistoricalDataClient()
                trades = client.get_crypto_latest_trade(
                    CryptoLatestTradeRequest(symbol_or_symbols=list(set(alpaca_syms)))
                )
                for sym, trade in trades.items():
                    if trade and trade.price and float(trade.price) > 0:
                        # Map back to original symbol
                        if sym in missing_crypto:
                            prices[sym] = float(trade.price)
            except Exception as exc:
                logger.warning("[live_prices] Alpaca crypto fallback failed: %s", exc)

    if stock_syms:
        alpaca_prices = fetch_stock_prices_alpaca(stock_syms)
        prices.update(alpaca_prices)

    return prices


def fetch_single_crypto_price(symbol: str, fallback: float = 0.0) -> float:
    """Convenience wrapper for a single crypto symbol. Returns fallback on failure."""
    result = fetch_crypto_prices_kraken([symbol])
    return result.get(symbol, fallback)
