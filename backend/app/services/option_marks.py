"""
Live option-quote fetcher for mark-to-market on open option positions.

Used by app/core/canonical.py to compute unrealized P&L for options bots.
Without this, options positions stayed frozen at entry premium → today P&L = $0.

Endpoint: https://data.alpaca.markets/v1beta1/options/quotes/latest?symbols=...
Auth: same ALPACA_API_KEY / ALPACA_SECRET_KEY used by the equities adapter.

Notes:
  - Composite types (call/put spread, iron condor, calendar) cannot be expressed
    as a single OCC contract — we skip them and log "options:mtm:composite".
  - bid=0 AND ask=0 means no live quote — we skip and log "options:mtm:no_quote"
    rather than silently falling back to entry price.
  - Cached for 60s per symbol so dashboard refreshes don't hammer Alpaca.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_QUOTE_CACHE: dict[str, tuple[Optional[float], float]] = {}
# symbol → (mid_price_dollars_or_None, monotonic_ts)
_QUOTE_CACHE_TTL = 60.0  # seconds

_ALPACA_OPTIONS_URL = "https://data.alpaca.markets/v1beta1/options/quotes/latest"

# OCC composite types we cannot price as a single contract (multi-leg).
_COMPOSITE_TYPES = {"spread", "call/put spread", "iron condor", "condor", "calendar"}

# Regex for symbols already in OCC format (e.g. "SPY260717C00800000").
import re as _re
_OCC_RE = _re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def _is_occ_symbol(symbol: str) -> bool:
    return bool(_OCC_RE.match((symbol or "").upper().strip()))


def build_occ_symbol(underlying: str, expiration_date: str, option_type: str, strike_price: float) -> Optional[str]:
    """Build an OCC option symbol, e.g. AMD270617C00540000.

    Args:
        underlying:      Root ticker (e.g. "SPY"). Required.
        expiration_date: ISO date "YYYY-MM-DD". Required.
        option_type:     "call" | "put" (composite types return None).
        strike_price:    Strike in dollars (e.g. 540.0).

    Returns None if any input is missing/invalid or the type is composite.
    """
    if not underlying or not expiration_date or not option_type or strike_price is None:
        return None
    ot = option_type.lower().strip()
    if ot in _COMPOSITE_TYPES:
        return None
    if ot.startswith("c"):
        cp = "C"
    elif ot.startswith("p"):
        cp = "P"
    else:
        return None
    try:
        yy = expiration_date[2:4]
        mm = expiration_date[5:7]
        dd = expiration_date[8:10]
        strike_int = int(round(float(strike_price) * 1000))
        if strike_int <= 0:
            return None
        return f"{underlying.upper()}{yy}{mm}{dd}{cp}{strike_int:08d}"
    except (ValueError, IndexError, TypeError):
        return None


def occ_for_position(pos) -> Optional[str]:
    """Resolve the OCC contract symbol for a BotPosition.

    Prefers `pos.symbol` if it's already an OCC string (live Alpaca fills store
    it there). Otherwise constructs from `(underlying_symbol or symbol,
    expiration_date, option_type, strike_price)`.
    """
    if _is_occ_symbol(pos.symbol or ""):
        return pos.symbol.upper().strip()
    root = pos.underlying_symbol or pos.symbol
    return build_occ_symbol(root, pos.expiration_date, pos.option_type, pos.strike_price)


def _fetch_alpaca_quotes(symbols: list[str], timeout: int = 8) -> dict[str, Optional[float]]:
    """Hit Alpaca's options quotes endpoint. Returns {symbol: mid_dollars_or_None}.

    A symbol present in the response with bid=ask=0 maps to None (no quote).
    A symbol missing from the response is also None.
    Never raises — logs and returns empty on any error.
    """
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_PAPER_KEY") or ""
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_PAPER_SECRET") or ""
    if not api_key or not secret:
        logger.warning("[option_marks] ALPACA_API_KEY/SECRET_KEY not set — cannot fetch option marks")
        return {s: None for s in symbols}
    if not symbols:
        return {}

    out: dict[str, Optional[float]] = {s: None for s in symbols}
    # Alpaca accepts comma-separated lists; batch to be safe.
    BATCH = 100
    for i in range(0, len(symbols), BATCH):
        batch = symbols[i:i + BATCH]
        qs = urllib.parse.urlencode({"symbols": ",".join(batch)})
        url = f"{_ALPACA_OPTIONS_URL}?{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            logger.warning("[option_marks] Alpaca options/quotes/latest failed: %s", exc)
            continue

        quotes = data.get("quotes") or {}
        for sym in batch:
            q = quotes.get(sym)
            if not q:
                logger.info("options:mtm:no_quote symbol=%s (not in response)", sym)
                continue
            bid = float(q.get("bp") or 0)
            ask = float(q.get("ap") or 0)
            if bid <= 0 and ask <= 0:
                logger.info("options:mtm:no_quote symbol=%s (bid=ask=0)", sym)
                continue
            # Use mid; if one side is 0, use the other.
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
            else:
                mid = max(bid, ask)
            out[sym] = mid
    return out


def fetch_option_marks_cents(occ_symbols: list[str]) -> dict[str, Optional[int]]:
    """Fetch current option mark (mid price) in cents for OCC symbols.

    60-second in-memory cache per symbol. Returns a dict where values are:
      - int cents if a live quote is available
      - None if no quote / fetch failed (caller should leave unrealized=0)

    Always returns one entry per input symbol.
    """
    if not occ_symbols:
        return {}
    now = time.monotonic()
    out: dict[str, Optional[int]] = {}
    stale: list[str] = []
    for sym in occ_symbols:
        cached = _QUOTE_CACHE.get(sym)
        if cached and (now - cached[1]) < _QUOTE_CACHE_TTL:
            mid = cached[0]
            out[sym] = int(round(mid * 100)) if mid is not None else None
        else:
            stale.append(sym)

    if stale:
        fresh = _fetch_alpaca_quotes(stale)
        for sym, mid in fresh.items():
            _QUOTE_CACHE[sym] = (mid, now)
            out[sym] = int(round(mid * 100)) if mid is not None else None
        # Symbols requested but missing from fresh (shouldn't happen — _fetch
        # returns one entry per input) — fill with None.
        for sym in stale:
            if sym not in out:
                _QUOTE_CACHE[sym] = (None, now)
                out[sym] = None
    return out
