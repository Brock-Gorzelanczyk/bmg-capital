"""
Options chain data: tries Alpaca live data, falls back to Black-Scholes synthetic.
"""
from __future__ import annotations

import math
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Black-Scholes helpers ────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    if T <= 0 or sigma <= 0:
        if opt == "call":
            return max(0.0, S - K)
        return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _bs_delta(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    if T <= 0 or sigma <= 0:
        return (1.0 if S > K else 0.0) if opt == "call" else (-1.0 if S < K else 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1) if opt == "call" else _norm_cdf(d1) - 1


def _bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return math.exp(-0.5 * d1 ** 2) / (S * sigma * math.sqrt(2 * math.pi * T))


def _bs_theta(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
    if opt == "call":
        theta = (-S * pdf_d1 * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2))
    else:
        theta = (-S * pdf_d1 * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2))
    return round(theta / 365, 4)  # per calendar day


def _bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return round(S * math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi) * math.sqrt(T) / 100, 4)


def _synthetic_chain(
    underlying: str,
    underlying_price: float,
    expiration: date,
    base_iv: float = 0.30,
    r: float = 0.05,
) -> dict:
    today = date.today()
    T = max((expiration - today).days, 1) / 365.0

    # Generate strikes around current price
    step = max(1.0, round(underlying_price * 0.025, 0))  # 2.5% of price
    atm = round(underlying_price / step) * step
    strikes = [atm + i * step for i in range(-10, 11)]

    calls, puts = [], []
    for K in strikes:
        # IV skew: OTM puts have higher IV
        moneyness = K / underlying_price
        iv_call = base_iv * (1 + 0.05 * max(0, moneyness - 1))
        iv_put = base_iv * (1 + 0.15 * max(0, 1 - moneyness))

        for opt_type, iv in [("call", iv_call), ("put", iv_put)]:
            mid = _bs_price(underlying_price, K, T, r, iv, opt_type)
            spread = max(0.01, mid * 0.04)
            bid = round(max(0.01, mid - spread / 2), 2)
            ask = round(mid + spread / 2, 2)
            delta = _bs_delta(underlying_price, K, T, r, iv, opt_type)
            contract = {
                "symbol": f"{underlying}{expiration.strftime('%y%m%d')}{opt_type[0].upper()}{int(K*1000):08d}",
                "strike": K,
                "expiration": expiration.isoformat(),
                "optionType": opt_type,
                "bid": bid,
                "ask": ask,
                "last": round((bid + ask) / 2, 2),
                "volume": int(abs(delta) * 1000),
                "openInterest": int(abs(delta) * 5000),
                "impliedVolatility": round(iv, 4),
                "delta": round(delta, 4),
                "gamma": round(_bs_gamma(underlying_price, K, T, r, iv), 4),
                "theta": _bs_theta(underlying_price, K, T, r, iv, opt_type),
                "vega": _bs_vega(underlying_price, K, T, r, iv),
                "inTheMoney": (opt_type == "call" and K < underlying_price) or (opt_type == "put" and K > underlying_price),
            }
            if opt_type == "call":
                calls.append(contract)
            else:
                puts.append(contract)

    return {
        "underlying": underlying,
        "underlyingPrice": underlying_price,
        "expiration": expiration.isoformat(),
        "calls": calls,
        "puts": puts,
        "source": "synthetic",
    }


async def get_chain(
    symbol: str,
    underlying_price: float,
    expiration: Optional[date] = None,
    api_key: str = "",
    secret_key: str = "",
) -> dict:
    if expiration is None:
        # Default to next monthly expiration (3rd Friday)
        today = date.today()
        candidate = today + timedelta(days=30)
        # Find the 3rd Friday of candidate's month
        first = candidate.replace(day=1)
        first_friday_offset = (4 - first.weekday()) % 7
        third_friday = first.replace(day=1 + first_friday_offset + 14)
        if third_friday < today:
            candidate = candidate + timedelta(days=32)
            first = candidate.replace(day=1)
            first_friday_offset = (4 - first.weekday()) % 7
            third_friday = first.replace(day=1 + first_friday_offset + 14)
        expiration = third_friday

    if api_key and secret_key:
        try:
            from alpaca.data.historical.option import OptionHistoricalDataClient
            from alpaca.data.requests import OptionChainRequest
            client = OptionHistoricalDataClient(api_key=api_key, secret_key=secret_key)
            req = OptionChainRequest(
                underlying_symbol=symbol,
                expiration_date=expiration,
            )
            chain_data = client.get_option_chain(req)
            if chain_data:
                calls, puts = [], []
                for contract_symbol, snap in chain_data.items():
                    details = snap.latest_quote if snap.latest_quote else None
                    greeks = snap.greeks if hasattr(snap, "greeks") else None
                    opt_type = "call" if "C" in contract_symbol.upper().split(symbol.upper())[-1][:1] or \
                               (len(contract_symbol) > len(symbol) + 6 and contract_symbol[len(symbol) + 6] == "C") \
                               else "put"
                    contract = {
                        "symbol": contract_symbol,
                        "strike": float(snap.strike_price) if hasattr(snap, "strike_price") else 0,
                        "expiration": expiration.isoformat(),
                        "optionType": opt_type,
                        "bid": float(details.bid_price) if details else 0,
                        "ask": float(details.ask_price) if details else 0,
                        "last": float(snap.latest_trade.price) if snap.latest_trade else 0,
                        "volume": int(snap.daily_bar.volume) if snap.daily_bar else 0,
                        "openInterest": 0,
                        "impliedVolatility": float(snap.implied_volatility) if hasattr(snap, "implied_volatility") and snap.implied_volatility else 0.30,
                        "delta": float(greeks.delta) if greeks and greeks.delta else 0,
                        "gamma": float(greeks.gamma) if greeks and greeks.gamma else 0,
                        "theta": float(greeks.theta) if greeks and greeks.theta else 0,
                        "vega": float(greeks.vega) if greeks and greeks.vega else 0,
                        "inTheMoney": False,
                    }
                    (calls if opt_type == "call" else puts).append(contract)
                return {
                    "underlying": symbol,
                    "underlyingPrice": underlying_price,
                    "expiration": expiration.isoformat(),
                    "calls": sorted(calls, key=lambda c: c["strike"]),
                    "puts": sorted(puts, key=lambda c: c["strike"]),
                    "source": "live",
                }
        except Exception as e:
            logger.info(f"Alpaca options unavailable for {symbol}: {e} — using synthetic")

    return _synthetic_chain(symbol, underlying_price, expiration)


def get_expirations(days_out: int = 120) -> list[str]:
    """Return upcoming monthly option expiration dates (3rd Friday of each month)."""
    expirations = []
    today = date.today()
    check = today
    while (check - today).days < days_out:
        first = check.replace(day=1)
        first_friday_offset = (4 - first.weekday()) % 7
        third_friday = first.replace(day=1 + first_friday_offset + 14)
        if third_friday > today:
            expirations.append(third_friday.isoformat())
        # Advance to next month
        if check.month == 12:
            check = check.replace(year=check.year + 1, month=1, day=1)
        else:
            check = check.replace(month=check.month + 1, day=1)
    return expirations[:6]  # Up to 6 expirations out
