"""Static beta-by-symbol map for portfolio factor attribution (Phase 6).

Beta = sensitivity of symbol's daily returns to SPY (broad market).
Hand-calibrated approximate values across the top of our trading universe;
default 1.0 for unknown symbols.

Used by ``GET /api/performance/factor-attribution`` to decompose total P&L
into market (beta) vs alpha (skill) components.

NOTE: These are intentionally coarse — refit periodically against rolling
60-day OLS regressions if accuracy becomes a constraint.
"""
from __future__ import annotations

from typing import Dict

DEFAULT_BETA = 1.0

STATIC_BETA: Dict[str, float] = {
    # Index ETFs
    "SPY": 1.00,
    "QQQ": 1.15,
    "IWM": 1.20,
    "DIA": 0.95,
    "VTI": 1.00,
    "VOO": 1.00,
    "VNQ": 0.85,
    "GLD": 0.00,
    "TLT": -0.30,
    "BIL": 0.00,
    "SHY": -0.05,
    "XLF": 1.10,
    "XLK": 1.20,
    "XLE": 1.05,
    "XLV": 0.75,
    "XLU": 0.55,
    "XLY": 1.15,
    "XLP": 0.55,
    "XLI": 1.05,
    "XLB": 1.10,
    # Crypto (loose correlation to SPY but directionally correct)
    "BTC": 0.50,
    "BTC/USD": 0.50,
    "ETH": 0.60,
    "ETH/USD": 0.60,
    "SOL/USD": 0.85,
    "AVAX/USD": 0.90,
    "DOGE/USD": 0.70,
    "ADA/USD": 0.80,
    "LINK/USD": 0.80,
    "MATIC/USD": 0.85,
    "POL/USD": 0.85,
    "OP/USD": 0.90,
    "ARB/USD": 0.90,
    "DOT/USD": 0.80,
    "LTC/USD": 0.55,
    "XRP/USD": 0.55,
    "BNB/USD": 0.60,
    "UNI/USD": 0.85,
    "ATOM/USD": 0.80,
    "NEAR/USD": 0.90,
    "APT/USD": 0.90,
    "SUI/USD": 0.95,
    "TIA/USD": 0.90,
    "INJ/USD": 0.95,
    "SHIB/USD": 0.80,
    "XLM/USD": 0.55,
    # Top single-name stocks (by open notional in our universe)
    "AAPL": 1.10,
    "MSFT": 1.05,
    "NVDA": 1.65,
    "AMD":  1.75,
    "META": 1.30,
    "GOOGL": 1.10,
    "GOOG": 1.10,
    "AMZN": 1.20,
    "TSLA": 1.90,
    "NFLX": 1.25,
    "AVGO": 1.30,
    "ORCL": 0.95,
    "ADBE": 1.15,
    "CRM":  1.20,
    "INTC": 0.95,
    "QCOM": 1.20,
    "TXN":  1.05,
    "MU":   1.45,
    "AMAT": 1.40,
    "TSM":  1.25,
    "PLTR": 1.50,
    "SNOW": 1.40,
    "CRWD": 1.35,
    "PANW": 1.20,
    "COIN": 2.10,
    "SQ":   1.55,
    "PYPL": 1.30,
    "V":    0.95,
    "MA":   1.00,
    "JPM":  1.10,
    "BAC":  1.15,
    "WFC":  1.10,
    "GS":   1.20,
    "MS":   1.20,
    "JNJ":  0.60,
    "UNH":  0.70,
    "LLY":  0.75,
    "PFE":  0.65,
    "ABBV": 0.65,
    "MRK":  0.65,
    "XOM":  0.95,
    "CVX":  0.90,
    "BA":   1.30,
    "DIS":  1.10,
    "UBER": 1.35,
    "ABNB": 1.35,
}


def get_beta(symbol: str) -> float:
    """Return the static beta for ``symbol``.

    Falls back to ``DEFAULT_BETA`` (1.0) for any symbol not in the table.
    Lookup is case-insensitive but preserves slash-form for crypto pairs.
    """
    if not symbol:
        return DEFAULT_BETA
    key = symbol.strip().upper()
    if key in STATIC_BETA:
        return STATIC_BETA[key]
    if "/" in key:
        base = key.split("/", 1)[0]
        if base in STATIC_BETA:
            return STATIC_BETA[base]
    return DEFAULT_BETA
