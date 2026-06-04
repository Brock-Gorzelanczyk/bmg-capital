"""
Order Book Imbalance (OBI) Short-Horizon Filter — Priority 10.

Computes OBI from top-N bid/ask levels of the order book.
Used as a pre-entry gate: refuse signals when the book is stacked
heavily against the trade direction.

OBI = (bid_qty - ask_qty) / (bid_qty + ask_qty)
    ∈ [-1, 1]
    > 0 → buying pressure (bullish)
    < 0 → selling pressure (bearish)

For entries:
  Long signal: require OBI > -0.3 (book not heavily stacked against us)
  Short signal: require OBI < 0.3

Data source:
  - IEX DEEP (free, IEX-only securities)
  - Polygon L2 advanced (paid)
  - Falls back to neutral (0.0) when no L2 available

Usage
-----
obi = OBIFilter()
imbalance = obi.compute(bids=[(price, qty), ...], asks=[(price, qty), ...], levels=5)
if not obi.allows_long(imbalance):
    skip_trade()
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class OBIFilter:
    """
    Order book imbalance filter for pre-entry gating.

    Computes weighted OBI across the top N levels.
    Weights decay exponentially with distance from best.
    """

    def __init__(
        self,
        long_threshold: float = -0.35,   # reject long if OBI < this
        short_threshold: float = 0.35,   # reject short if OBI > this
        n_levels: int = 5,
        decay_factor: float = 0.7,       # weight decay per level
    ) -> None:
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold
        self.n_levels = n_levels
        self.decay_factor = decay_factor

    # ── OBI Computation ──────────────────────────────────────────────────────

    def compute(
        self,
        bids: list[tuple[float, float]],  # (price, qty) sorted best first
        asks: list[tuple[float, float]],  # (price, qty) sorted best first
        levels: Optional[int] = None,
    ) -> float:
        """
        Compute exponentially-weighted OBI across top-N levels.

        Returns float in [-1, 1]. Returns 0.0 if book is empty.
        """
        n = levels or self.n_levels
        bids = bids[:n]
        asks = asks[:n]

        if not bids and not asks:
            return 0.0

        weights = np.array([self.decay_factor ** i for i in range(n)])

        bid_qty = np.zeros(n)
        ask_qty = np.zeros(n)

        for i, (_, qty) in enumerate(bids):
            if i < n:
                bid_qty[i] = qty

        for i, (_, qty) in enumerate(asks):
            if i < n:
                ask_qty[i] = qty

        total_bid = float(np.dot(bid_qty, weights[:len(bid_qty)]))
        total_ask = float(np.dot(ask_qty, weights[:len(ask_qty)]))
        total = total_bid + total_ask

        if total < 1e-10:
            return 0.0

        return round((total_bid - total_ask) / total, 4)

    # ── Signal Gates ─────────────────────────────────────────────────────────

    def allows_long(self, obi: float) -> bool:
        """Return True if OBI is not heavily stacked against a long entry."""
        return obi >= self.long_threshold

    def allows_short(self, obi: float) -> bool:
        """Return True if OBI is not heavily stacked against a short entry."""
        return obi <= self.short_threshold

    def gate_signal(self, signal_side: str, obi: float) -> bool:
        """
        Gate a signal based on OBI.

        Parameters
        ----------
        signal_side : "long" | "short" | "hold"
        obi : OBI value in [-1, 1]

        Returns
        -------
        True = allow the signal, False = block it
        """
        if signal_side == "long":
            return self.allows_long(obi)
        if signal_side == "short":
            return self.allows_short(obi)
        return True  # hold signals pass through

    # ── Live Data Fetch ───────────────────────────────────────────────────────

    def fetch_iex_obi(self, symbol: str) -> Optional[float]:
        """
        Fetch OBI from IEX DEEP endpoint (free, IEX-listed stocks only).

        Returns None if unavailable or network error.
        """
        try:
            import requests
            base = os.getenv("IEX_BASE_URL", "https://api.iex.cloud/v1")
            token = os.getenv("IEX_TOKEN", "")
            if not token:
                return None

            url = f"{base}/data/core/tops/{symbol}"
            resp = requests.get(url, params={"token": token}, timeout=3)
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data:
                return None

            entry = data[0] if isinstance(data, list) else data
            bid_qty = float(entry.get("bidSize", 0))
            ask_qty = float(entry.get("askSize", 0))
            total = bid_qty + ask_qty
            if total < 1:
                return None
            return round((bid_qty - ask_qty) / total, 4)
        except Exception as exc:
            logger.debug("[obi] IEX fetch error for %s: %s", symbol, exc)
            return None

    def fetch_polygon_obi(self, symbol: str) -> Optional[float]:
        """
        Fetch OBI from Polygon L2 snapshot (requires advanced subscription).
        """
        try:
            import requests
            api_key = os.getenv("POLYGON_API_KEY", "")
            if not api_key:
                return None

            url = f"https://api.polygon.io/v3/snapshot/options/{symbol}"
            # Note: Polygon L2 requires a specific endpoint — this is a stub
            # that shows the pattern; replace with actual L2 endpoint when subscribed
            resp = requests.get(
                f"https://api.polygon.io/v2/last/nbbo/{symbol}",
                params={"apiKey": api_key},
                timeout=3,
            )
            if resp.status_code != 200:
                return None

            data = resp.json().get("results", {})
            bid_size = float(data.get("bs", 0))
            ask_size = float(data.get("as", 0))
            total = bid_size + ask_size
            if total < 1:
                return None
            return round((bid_size - ask_size) / total, 4)
        except Exception as exc:
            logger.debug("[obi] Polygon L2 error for %s: %s", symbol, exc)
            return None

    def get_obi(self, symbol: str) -> float:
        """
        Try IEX first, fall back to Polygon, fall back to 0.0 (neutral).
        """
        obi = self.fetch_iex_obi(symbol)
        if obi is not None:
            return obi
        obi = self.fetch_polygon_obi(symbol)
        if obi is not None:
            return obi
        logger.debug("[obi] no L2 data for %s — returning neutral 0.0", symbol)
        return 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────

_filter = OBIFilter()


def get_obi_filter() -> OBIFilter:
    return _filter


def gate_entry(signal_side: str, symbol: str) -> tuple[bool, float]:
    """
    Convenience: fetch OBI for symbol and gate the signal.

    Returns (allowed, obi_value).
    """
    f = get_obi_filter()
    obi = f.get_obi(symbol)
    allowed = f.gate_signal(signal_side, obi)
    if not allowed:
        logger.info("[obi] blocked %s signal on %s (OBI=%.3f)", signal_side, symbol, obi)
    return allowed, obi
