"""
Order Book Imbalance (Top-5 Levels) — Weekend 7, Module 15.

OBI = (bid_qty - ask_qty) / (bid_qty + ask_qty) across top 5 levels.
Weighted by exponential decay (closer to best = higher weight).

Gate: refuse long entry when OBI < -0.4 (heavily ask-stacked).
Gate: refuse short entry when OBI > 0.4 (heavily bid-stacked).

Data: IEX DEEP (free, IEX-listed), Polygon L2 (paid), or synthetic.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

LONG_GATE_THRESHOLD = -0.40
SHORT_GATE_THRESHOLD = 0.40
N_LEVELS = 5
DECAY = 0.7


def compute_obi(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    n_levels: int = N_LEVELS,
    decay: float = DECAY,
) -> float:
    """Compute exponentially-weighted OBI from top-N bid/ask levels."""
    weights = np.array([decay ** i for i in range(n_levels)])
    bid_qty = np.zeros(n_levels)
    ask_qty = np.zeros(n_levels)

    for i, (_, qty) in enumerate(bids[:n_levels]):
        bid_qty[i] = qty
    for i, (_, qty) in enumerate(asks[:n_levels]):
        ask_qty[i] = qty

    total_bid = float(np.dot(bid_qty, weights))
    total_ask = float(np.dot(ask_qty, weights))
    total = total_bid + total_ask
    if total < 1e-10:
        return 0.0
    return round((total_bid - total_ask) / total, 4)


def gate_long(obi: float) -> bool:
    """Return True if OBI permits a long entry."""
    return obi >= LONG_GATE_THRESHOLD


def gate_short(obi: float) -> bool:
    """Return True if OBI permits a short entry."""
    return obi <= SHORT_GATE_THRESHOLD


def fetch_iex_obi(symbol: str) -> Optional[float]:
    """Fetch OBI from IEX TOPS (free tier)."""
    try:
        import requests
        token = os.getenv("IEX_TOKEN", "")
        if not token:
            return None
        url = f"https://api.iex.cloud/v1/data/core/tops/{symbol}"
        resp = requests.get(url, params={"token": token}, timeout=3)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        entry = data[0] if isinstance(data, list) else data
        bid = float(entry.get("bidSize", 0))
        ask = float(entry.get("askSize", 0))
        total = bid + ask
        return round((bid - ask) / total, 4) if total > 0 else None
    except Exception as exc:
        logger.debug("[obi_top5] IEX error for %s: %s", symbol, exc)
        return None


def get_obi(symbol: str) -> float:
    """Fetch OBI from best available source. Returns 0.0 (neutral) on failure."""
    obi = fetch_iex_obi(symbol)
    return obi if obi is not None else 0.0
