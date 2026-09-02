"""Options flow helpers — Unusual Options Activity (UOA), Lee-Ready direction
inference, block detection. Free-tier DIY replacement for Unusual Whales.

Uses Alpaca's options snapshots + trades endpoints (free with paper account).
Doesn't try to be Unusual Whales — captures ~70% of the signal at $0/mo per
research note research/25-options-flow-services-DIY-alternatives.md.

Load-bearing insight from research/22: raw flow-following is NEGATIVE alpha
at retail latency (Blocher 2020). Every signal produced here is a CONFLUENCE
input, not a standalone entry. Score threshold, then act.

References:
- Lee, C. &  Ready, M. (1991). "Inferring Trade Direction from Intraday Data."
  Journal of Finance 46(2): 733-746.
- Roll, Schwartz, Subrahmanyam (2010). "O/S: The Relative Trading Activity in
  Options and Stock." JFE 96(1): 1-17.
- Cremers &  Weinbaum (2010). "Deviations from Put-Call Parity and Stock
  Return Predictability." JFQA 45(2): 335-367.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", "backend", ".env"))

DATA_BASE = "https://data.alpaca.markets"


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


# ────────────────────────────────────────────────────────────────────────────
# Chain + snapshot pulls
# ────────────────────────────────────────────────────────────────────────────

def fetch_chain_snapshots(underlying: str, expiration: str,
                          strike_gte: Optional[float] = None,
                          strike_lte: Optional[float] = None,
                          option_type: Optional[str] = None) -> dict:
    """Fetch full chain snapshots for one underlying + expiration.

    Returns dict {occ_symbol: snapshot}. Snapshot includes latestQuote (bp/ap),
    latestTrade (p/s), impliedVolatility (often None on indicative feed).
    """
    params = {"feed": "indicative", "expiration_date": expiration}
    if option_type:
        params["type"] = option_type
    if strike_gte is not None:
        params["strike_price_gte"] = strike_gte
    if strike_lte is not None:
        params["strike_price_lte"] = strike_lte
    r = requests.get(f"{DATA_BASE}/v1beta1/options/snapshots/{underlying}",
                     headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("snapshots", {})


def fetch_option_bars(occ_symbol: str, timeframe: str = "1Day", limit: int = 30) -> list[dict]:
    """Fetch OHLCV bars for a specific option contract."""
    params = {"timeframe": timeframe, "limit": limit}
    r = requests.get(f"{DATA_BASE}/v1beta1/options/bars/{occ_symbol}",
                     headers=_headers(), params=params, timeout=15)
    if r.status_code != 200:
        return []
    return r.json().get("bars", [])


def fetch_stock_trades(symbol: str, hours: int = 1, limit: int = 10000) -> list[dict]:
    """Fetch recent stock trades for block detection.
    Returns list of trades with {t: timestamp, p: price, s: size, ...}.
    """
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    params = {"start": start, "limit": limit}
    r = requests.get(f"{DATA_BASE}/v2/stocks/{symbol}/trades",
                     headers=_headers(), params=params, timeout=15)
    if r.status_code != 200:
        return []
    return r.json().get("trades", [])


def fetch_stock_quotes(symbol: str, hours: int = 1, limit: int = 10000) -> list[dict]:
    """Fetch recent quotes for Lee-Ready direction inference against trades."""
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    params = {"start": start, "limit": limit}
    r = requests.get(f"{DATA_BASE}/v2/stocks/{symbol}/quotes",
                     headers=_headers(), params=params, timeout=15)
    if r.status_code != 200:
        return []
    return r.json().get("quotes", [])


# ────────────────────────────────────────────────────────────────────────────
# Lee-Ready 1991 tick direction inference
# ────────────────────────────────────────────────────────────────────────────

def lee_ready_direction(trade_price: float, bid: float, ask: float,
                        prev_trade_price: Optional[float] = None) -> str:
    """Classify a trade as buyer- or seller-initiated per Lee-Ready 1991.

    Rules (in order):
      1. If trade > mid → BUY (buyer-initiated, hit the ask side)
      2. If trade < mid → SELL (seller-initiated, hit the bid side)
      3. If trade == mid → tick rule vs prev trade:
           trade > prev → BUY
           trade < prev → SELL
           trade == prev → UNKNOWN

    Returns "BUY" | "SELL" | "UNKNOWN"
    """
    if bid <= 0 or ask <= 0 or trade_price <= 0:
        return "UNKNOWN"
    mid = (bid + ask) / 2.0
    if trade_price > mid:
        return "BUY"
    if trade_price < mid:
        return "SELL"
    # At mid — apply tick rule
    if prev_trade_price is None:
        return "UNKNOWN"
    if trade_price > prev_trade_price:
        return "BUY"
    if trade_price < prev_trade_price:
        return "SELL"
    return "UNKNOWN"


def bucket_direction_via_bidask(fill_price: float, bid: float, ask: float,
                                tolerance: float = 0.05) -> str:
    """Simpler than Lee-Ready — just bid/ask proximity. Used when we only
    have snapshot data (no tick tape).

    tolerance = fraction of spread. Default 0.05 = fill within 5% of ask → BUY.
    """
    if bid <= 0 or ask <= 0 or fill_price <= 0:
        return "UNKNOWN"
    spread = ask - bid
    if spread <= 0:
        return "UNKNOWN"
    ask_gap = (ask - fill_price) / spread  # 0 = at ask, 1 = at bid
    if ask_gap <= tolerance:
        return "BUY"
    if ask_gap >= 1 - tolerance:
        return "SELL"
    return "MID"


# ────────────────────────────────────────────────────────────────────────────
# Unusual Options Activity scoring
# ────────────────────────────────────────────────────────────────────────────

def compute_uoa_score(current_volume: int, trailing_avg_volume: float,
                     open_interest: int, direction: str) -> dict:
    """Score a contract's UOA level.

    A "hot" contract has:
      - Volume >> average (vol_ratio high)
      - Volume > open interest (new positioning, not closing)
      - Directional agreement (all buys or all sells, not mixed)

    Returns dict with vol_ratio, oi_ratio, composite_score, tier (A/B/C/none).
    """
    import math

    vol_ratio = current_volume / max(trailing_avg_volume, 1.0)
    oi_ratio = current_volume / max(open_interest, 1)

    # Composite: rewards high volume, high vol_ratio, new positioning (vol > OI),
    # penalizes mixed direction
    direction_multiplier = {
        "BUY": 1.0, "SELL": 1.0, "MID": 0.3, "UNKNOWN": 0.3
    }.get(direction, 0.5)

    score = vol_ratio * math.log10(max(current_volume, 10)) * direction_multiplier
    if oi_ratio > 1.0:
        score *= 1.5  # New positioning bonus

    # Tier assignment (per research/22)
    tier = "none"
    if score >= 30 and vol_ratio >= 5 and current_volume >= 1000:
        tier = "A"  # HIGH conviction UOA
    elif score >= 15 and vol_ratio >= 3 and current_volume >= 500:
        tier = "B"  # MEDIUM conviction
    elif score >= 5 and vol_ratio >= 2 and current_volume >= 200:
        tier = "C"  # LOW conviction

    return {
        "vol_ratio": round(vol_ratio, 2),
        "oi_ratio": round(oi_ratio, 2),
        "direction": direction,
        "direction_multiplier": direction_multiplier,
        "composite_score": round(score, 2),
        "tier": tier,
    }


def compute_trailing_avg_volume(occ_symbol: str, days: int = 30) -> float:
    """Fetch trailing-N-day average volume for a contract via Alpaca bars.

    Returns float. Zero if no bars available.
    """
    bars = fetch_option_bars(occ_symbol, timeframe="1Day", limit=days)
    if not bars:
        return 0.0
    volumes = [b.get("v", 0) for b in bars]
    if not volumes:
        return 0.0
    return sum(volumes) / len(volumes)


# ────────────────────────────────────────────────────────────────────────────
# Block trade detection
# ────────────────────────────────────────────────────────────────────────────

def detect_blocks(trades: list[dict], quotes: list[dict],
                  min_size_shares: int = 10000,
                  min_notional_usd: float = 250000.0) -> list[dict]:
    """Detect block trades from a trades feed + quotes feed for Lee-Ready.

    A block = single print >= min_size_shares OR notional >= min_notional_usd.
    Returns list of enriched trade dicts with direction (via Lee-Ready).
    """
    if not trades:
        return []

    # Build quote timeline for fast lookup
    quotes_sorted = sorted(quotes, key=lambda q: q.get("t", ""))

    def _quote_at(ts: str) -> tuple[float, float]:
        """Binary-search for quote at or before ts. Returns (bid, ask)."""
        if not quotes_sorted:
            return 0.0, 0.0
        lo, hi = 0, len(quotes_sorted) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if quotes_sorted[mid].get("t", "") <= ts:
                best = quotes_sorted[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            return 0.0, 0.0
        return float(best.get("bp", 0)), float(best.get("ap", 0))

    blocks = []
    prev_price = None
    for t in trades:
        size = int(t.get("s", 0))
        price = float(t.get("p", 0))
        notional = size * price
        if size < min_size_shares and notional < min_notional_usd:
            prev_price = price
            continue
        bid, ask = _quote_at(t.get("t", ""))
        direction = lee_ready_direction(price, bid, ask, prev_price)
        blocks.append({
            "ts": t.get("t"),
            "price": price,
            "size": size,
            "notional": round(notional, 2),
            "bid": bid,
            "ask": ask,
            "direction": direction,
        })
        prev_price = price
    return blocks


def signed_block_flow(blocks: list[dict]) -> dict:
    """Aggregate block trades to a signed flow measure.
    signed_notional = sum(notional × +1 if BUY, -1 if SELL, 0 if MID/UNKNOWN)
    """
    if not blocks:
        return {"n_blocks": 0, "signed_notional": 0.0, "gross_notional": 0.0,
                "buy_notional": 0.0, "sell_notional": 0.0}
    signed = 0.0
    gross = 0.0
    buy_n = 0.0
    sell_n = 0.0
    for b in blocks:
        n = b["notional"]
        gross += n
        if b["direction"] == "BUY":
            signed += n
            buy_n += n
        elif b["direction"] == "SELL":
            signed -= n
            sell_n += n
    return {
        "n_blocks": len(blocks),
        "signed_notional": round(signed, 2),
        "gross_notional": round(gross, 2),
        "buy_notional": round(buy_n, 2),
        "sell_notional": round(sell_n, 2),
        "flow_ratio": round(signed / gross if gross > 0 else 0.0, 3),
    }


# ────────────────────────────────────────────────────────────────────────────
# OCC symbol parsing
# ────────────────────────────────────────────────────────────────────────────

def parse_occ_symbol(occ: str) -> Optional[dict]:
    """Parse an OCC-format option symbol into {underlying, expiration, right, strike}.
    Format: SYMBOL[6chars] YYMMDD C/P NNNNNNNN(8-digit strike in 1/1000)
    Ex: SPY261002C00781000 → SPY, 2026-10-02, CALL, $781.00
    """
    if len(occ) < 15:
        return None
    try:
        # Underlying is variable length; last 15 chars = date(6) + right(1) + strike(8)
        tail = occ[-15:]
        underlying = occ[:-15]
        date_str = tail[0:6]  # YYMMDD
        right_c = tail[6]  # C or P
        strike_str = tail[7:15]  # NNNNNNNN
        year = 2000 + int(date_str[0:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        strike = int(strike_str) / 1000.0
        right = "call" if right_c == "C" else "put"
        return {
            "underlying": underlying,
            "expiration": f"{year:04d}-{month:02d}-{day:02d}",
            "right": right,
            "strike": strike,
        }
    except Exception:
        return None


if __name__ == "__main__":
    # Smoke test
    print("Testing OCC parse: SPY261002C00781000")
    print(parse_occ_symbol("SPY261002C00781000"))

    print("\nTesting Lee-Ready:")
    print(f"  trade $10.05, bid $10.00, ask $10.10 → {lee_ready_direction(10.05, 10.00, 10.10)}")
    print(f"  trade $10.09, bid $10.00, ask $10.10 → {lee_ready_direction(10.09, 10.00, 10.10)}")
    print(f"  trade $10.01, bid $10.00, ask $10.10 → {lee_ready_direction(10.01, 10.00, 10.10)}")

    print("\nTesting UOA scoring:")
    print(compute_uoa_score(current_volume=5000, trailing_avg_volume=500,
                            open_interest=2000, direction="BUY"))
