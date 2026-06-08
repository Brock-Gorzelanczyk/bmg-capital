"""Static sector lookup for Russell 1000 / strategy universe symbols.

Used by sector concentration cap in runner.py.
Returns None for unknown symbols (treated as uncapped).
"""
from __future__ import annotations

_SECTOR: dict[str, str] = {
    # Technology
    "AAPL": "technology", "MSFT": "technology", "NVDA": "technology",
    "AMD": "technology", "GOOGL": "technology", "GOOG": "technology",
    "META": "technology", "ADBE": "technology", "CRM": "technology",
    "ORCL": "technology", "TSM": "technology", "AVGO": "technology",
    "INTC": "technology", "QCOM": "technology", "TXN": "technology",
    "MU": "technology", "AMAT": "technology", "LRCX": "technology",
    "KLAC": "technology", "MRVL": "technology", "SNPS": "technology",
    "CDNS": "technology", "NOW": "technology", "PANW": "technology",
    "CRWD": "technology", "FTNT": "technology", "ZS": "technology",
    "SNOW": "technology", "PLTR": "technology", "DDOG": "technology",
    # Communication Services
    "NFLX": "communication", "DIS": "communication", "CMCSA": "communication",
    "T": "communication", "VZ": "communication", "TMUS": "communication",
    "CHTR": "communication", "PARA": "communication", "WBD": "communication",
    # Consumer Discretionary
    "AMZN": "consumer_disc", "TSLA": "consumer_disc", "HD": "consumer_disc",
    "MCD": "consumer_disc", "NKE": "consumer_disc", "SBUX": "consumer_disc",
    "TGT": "consumer_disc", "LOW": "consumer_disc", "BKNG": "consumer_disc",
    "ABNB": "consumer_disc", "UBER": "consumer_disc", "LYFT": "consumer_disc",
    "RIVN": "consumer_disc", "F": "consumer_disc", "GM": "consumer_disc",
    # Consumer Staples
    "PG": "consumer_staples", "KO": "consumer_staples", "PEP": "consumer_staples",
    "COST": "consumer_staples", "WMT": "consumer_staples", "MO": "consumer_staples",
    "PM": "consumer_staples", "CL": "consumer_staples", "GIS": "consumer_staples",
    # Financials
    "JPM": "financials", "BAC": "financials", "WFC": "financials",
    "GS": "financials", "MS": "financials", "BLK": "financials",
    "C": "financials", "USB": "financials", "AXP": "financials",
    "V": "financials", "MA": "financials", "PYPL": "financials",
    "SQ": "financials", "COIN": "financials",
    # Healthcare
    "JNJ": "healthcare", "UNH": "healthcare", "PFE": "healthcare",
    "ABBV": "healthcare", "MRK": "healthcare", "LLY": "healthcare",
    "TMO": "healthcare", "ABT": "healthcare", "DHR": "healthcare",
    "ISRG": "healthcare", "AMGN": "healthcare", "GILD": "healthcare",
    "MRNA": "healthcare", "BNTX": "healthcare", "REGN": "healthcare",
    "VRTX": "healthcare", "BIIB": "healthcare",
    # Industrials
    "BA": "industrials", "CAT": "industrials", "HON": "industrials",
    "GE": "industrials", "LMT": "industrials", "RTX": "industrials",
    "NOC": "industrials", "GD": "industrials", "UPS": "industrials",
    "FDX": "industrials", "DE": "industrials", "MMM": "industrials",
    # Energy
    "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
    "EOG": "energy", "MPC": "energy", "PSX": "energy", "VLO": "energy",
    # Materials
    "LIN": "materials", "APD": "materials", "FCX": "materials",
    "NEM": "materials", "GOLD": "materials", "ALB": "materials",
    # Real Estate
    "AMT": "real_estate", "PLD": "real_estate", "EQIX": "real_estate",
    "CCI": "real_estate", "PSA": "real_estate", "O": "real_estate",
    # Utilities
    "NEE": "utilities", "DUK": "utilities", "SO": "utilities",
    "D": "utilities", "AEP": "utilities", "EXC": "utilities",
    # ETFs (treat as their own pseudo-sector — no concentration limit)
    "SPY": "etf", "QQQ": "etf", "IWM": "etf", "DIA": "etf",
    "VTI": "etf", "VNQ": "etf", "XLF": "etf", "XLK": "etf",
}


def get_sector(symbol: str) -> str | None:
    """Return the sector string for symbol, or None if unknown."""
    return _SECTOR.get(symbol.upper())
