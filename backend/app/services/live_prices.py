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

# ── Symbol aliases ────────────────────────────────────────────────────────────
# Translate our watchlist symbols to the name the exchange actually knows.
# Applied in fetch_live_prices() before any exchange query; results are
# mapped back to the caller's original symbol name.
SYMBOL_ALIASES: dict[str, str] = {
    "MATIC/USD": "POL/USD",  # Kraken renamed MATIC → POL in late 2024
}

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
    "POL/USD":   "POLUSD",   # was MATIC — use SYMBOL_ALIASES to route MATIC/USD here
    "OP/USD":    "OPUSD",
    "BNB/USD":   "BNBUSD",
    "DOT/USD":   "DOTUSD",
    "LTC/USD":   "LTCUSD",
    "XLM/USD":   "XXLMZUSD",   # Stellar — Kraken legacy key
    "XRP/USD":   "XXRPZUSD",
    "UNI/USD":   "UNIUSD",
    "ATOM/USD":  "ATOMUSD",
    "NEAR/USD":  "NEARUSD",
    "APT/USD":   "APTUSD",
    "SUI/USD":   "SUIUSD",
    "TIA/USD":   "TIAUSD",   # Celestia
    "INJ/USD":   "INJUSD",   # Injective
    "BNB/USD":   "BNBUSD",
}

# Symbols that should NOT go to Kraken — price is wrong or pair doesn't exist.
# They fall through to the Alpaca crypto fallback automatically.
_SKIP_KRAKEN: set[str] = {
    "ARB/USD",   # Kraken ARBUSD returns ~$0.0008 (decimal bug); Alpaca is correct
    "SHIB/USD",  # Kraken has SHIB2/USDT, not SHIBUSD; Alpaca handles it correctly
}

# ── CoinGecko fallback mapping ────────────────────────────────────────────────
# Third-tier fallback for symbols Kraken + Alpaca crypto both miss.
# Maps our internal "BASE/USD" format → CoinGecko coin ID.
_TO_COINGECKO_ID: dict[str, str] = {
    "BTC/USD":   "bitcoin",
    "ETH/USD":   "ethereum",
    "SOL/USD":   "solana",
    "AVAX/USD":  "avalanche-2",
    "DOGE/USD":  "dogecoin",
    "ADA/USD":   "cardano",
    "LINK/USD":  "chainlink",
    "POL/USD":   "matic-network",
    "MATIC/USD": "matic-network",
    "OP/USD":    "optimism",
    "ARB/USD":   "arbitrum",
    "BNB/USD":   "binancecoin",
    "DOT/USD":   "polkadot",
    "LTC/USD":   "litecoin",
    "XLM/USD":   "stellar",
    "XRP/USD":   "ripple",
    "UNI/USD":   "uniswap",
    "ATOM/USD":  "cosmos",
    "NEAR/USD":  "near",
    "APT/USD":   "aptos",
    "SUI/USD":   "sui",
    "TIA/USD":   "celestia",
    "INJ/USD":   "injective-protocol",
    "SHIB/USD":  "shiba-inu",
}

# Some Kraken response keys differ from the pair we requested.
# Map pair → expected response key (only needed for legacy pairs).
_KRAKEN_RESPONSE_KEY: dict[str, str] = {
    "XBTUSD":  "XXBTZUSD",
    "ETHUSD":  "XETHZUSD",
    "XDGUSD":  "XDGZUSD",
    "XXRPZUSD": "XXRPZUSD",
    "XXLMZUSD": "XXLMZUSD",
}


def _kraken_pair(symbol: str) -> Optional[str]:
    """Return the Kraken pair string for a crypto symbol, or None if unknown."""
    if symbol in _SKIP_KRAKEN:
        return None
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


def fetch_crypto_prices_coingecko(symbols: list[str], timeout: int = 8) -> dict[str, float]:
    """Fetch crypto prices from CoinGecko free API (no auth required).

    Third-tier fallback — only called when Kraken + Alpaca both return no price.

    Args:
        symbols: Internal "BASE/USD" symbols to look up.

    Returns:
        Dict mapping original symbol → USD price. Missing symbols are omitted.
    """
    if not symbols:
        return {}

    sym_to_id: dict[str, str] = {}
    for sym in symbols:
        cg_id = _TO_COINGECKO_ID.get(sym)
        if cg_id:
            sym_to_id[sym] = cg_id

    if not sym_to_id:
        return {}

    ids_str = ",".join(set(sym_to_id.values()))
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=usd"
    prices: dict[str, float] = {}

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "bmg-capital/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        id_to_price: dict[str, float] = {}
        for cg_id, vals in data.items():
            usd = vals.get("usd")
            if usd and float(usd) > 0:
                id_to_price[cg_id] = float(usd)

        for sym, cg_id in sym_to_id.items():
            if cg_id in id_to_price:
                prices[sym] = id_to_price[cg_id]

        logger.debug("[live_prices] CoinGecko: %d/%d symbols fetched", len(prices), len(symbols))

    except Exception as exc:
        logger.warning("[live_prices] CoinGecko fallback failed: %s", exc)

    return prices


def fetch_live_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch live prices, routing crypto to Kraken and stocks to Alpaca.

    Args:
        symbols: Mix of "BASE/USD" crypto and plain stock tickers.

    Returns:
        Dict mapping symbol → price (using the caller's original symbol names).
        Symbols with no price are omitted.
    """
    # Apply aliases: translate before querying, reverse-map before returning.
    # e.g. MATIC/USD → POL/USD for Kraken, then result keyed back as MATIC/USD.
    orig_to_resolved: dict[str, str] = {s: SYMBOL_ALIASES.get(s, s) for s in symbols}
    resolved_symbols = list(orig_to_resolved.values())

    crypto_syms = [s for s in resolved_symbols if "/" in s]
    stock_syms  = [s for s in resolved_symbols if "/" not in s]

    resolved_prices: dict[str, float] = {}

    if crypto_syms:
        kraken_prices = fetch_crypto_prices_kraken(crypto_syms)
        resolved_prices.update(kraken_prices)

        # For any crypto symbols Kraken didn't cover, try Alpaca crypto feed
        missing_crypto = [s for s in crypto_syms if s not in resolved_prices]
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
                        if sym in missing_crypto:
                            resolved_prices[sym] = float(trade.price)
            except Exception as exc:
                logger.warning("[live_prices] Alpaca crypto fallback failed: %s", exc)

        # Third tier: CoinGecko free API for anything still missing
        still_missing = [s for s in crypto_syms if s not in resolved_prices]
        if still_missing:
            cg_prices = fetch_crypto_prices_coingecko(still_missing)
            resolved_prices.update(cg_prices)

    if stock_syms:
        alpaca_prices = fetch_stock_prices_alpaca(stock_syms)
        resolved_prices.update(alpaca_prices)

    # Reverse-map: return prices under the caller's original symbol names
    return {
        orig: resolved_prices[resolved]
        for orig, resolved in orig_to_resolved.items()
        if resolved in resolved_prices
    }


def fetch_single_crypto_price(symbol: str, fallback: float = 0.0) -> float:
    """Convenience wrapper for a single crypto symbol. Returns fallback on failure."""
    result = fetch_crypto_prices_kraken([symbol])
    return result.get(symbol, fallback)
