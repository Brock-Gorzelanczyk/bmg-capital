"""
Lee-Ready Aggressor Classification — Weekend 7, Module 16.

Classifies each tape print as buyer-initiated or seller-initiated
using the Lee-Ready (1991) algorithm:
  - If price > prior midpoint: buyer-initiated (buy aggressor)
  - If price < prior midpoint: seller-initiated (sell aggressor)
  - If price == midpoint: use tick test (up-tick = buy, down-tick = sell)

Rolling 5-minute aggressor imbalance used as a signal feature.
High buy imbalance → supports long entries. High sell imbalance → gate longs.

Reference: Lee & Ready (1991), "Inferring Trade Direction from Intraday Data"
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradePrint:
    price: float
    size: float
    timestamp: float        # unix seconds
    aggressor: Optional[str] = None  # "buy" | "sell" | None (unknown)


class LeeReadyClassifier:
    """
    Classifies tape prints and maintains rolling aggressor imbalance.

    Imbalance = (buy_volume - sell_volume) / total_volume
    ∈ [-1, 1]. Positive = net buying pressure.
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        self._window_s = window_seconds
        self._prior_mid: Optional[float] = None
        self._prior_price: Optional[float] = None
        self._prints: Deque[TradePrint] = deque()

    def classify(
        self,
        price: float,
        size: float,
        timestamp: float,
        current_mid: Optional[float] = None,
    ) -> TradePrint:
        """
        Classify a single tape print.

        Parameters
        ----------
        price : trade price
        size : shares traded
        timestamp : unix seconds
        current_mid : NBBO midpoint at time of print (improves accuracy)
        """
        mid = current_mid if current_mid is not None else self._prior_mid

        if mid is not None and abs(price - mid) > 1e-6:
            # Mid-point rule
            aggressor = "buy" if price > mid else "sell"
        elif self._prior_price is not None:
            # Tick test fallback
            aggressor = "buy" if price > self._prior_price else "sell"
        else:
            aggressor = None  # first print — unknown

        print_ = TradePrint(
            price=price,
            size=size,
            timestamp=timestamp,
            aggressor=aggressor,
        )

        self._prior_price = price
        if current_mid is not None:
            self._prior_mid = current_mid

        # Maintain rolling window
        self._prints.append(print_)
        cutoff = timestamp - self._window_s
        while self._prints and self._prints[0].timestamp < cutoff:
            self._prints.popleft()

        return print_

    def rolling_imbalance(self) -> float:
        """
        Compute aggressor imbalance over the rolling window.

        Returns float in [-1, 1]. 0.0 if no data.
        """
        buy_vol = 0.0
        sell_vol = 0.0
        for p in self._prints:
            if p.aggressor == "buy":
                buy_vol += p.size
            elif p.aggressor == "sell":
                sell_vol += p.size

        total = buy_vol + sell_vol
        if total < 1e-10:
            return 0.0
        return round((buy_vol - sell_vol) / total, 4)

    def buy_volume(self) -> float:
        return sum(p.size for p in self._prints if p.aggressor == "buy")

    def sell_volume(self) -> float:
        return sum(p.size for p in self._prints if p.aggressor == "sell")

    def n_prints(self) -> int:
        return len(self._prints)

    def reset(self) -> None:
        self._prints.clear()
        self._prior_mid = None
        self._prior_price = None


# Per-symbol classifiers
_classifiers: dict[str, LeeReadyClassifier] = {}


def get_classifier(symbol: str, window_seconds: float = 300.0) -> LeeReadyClassifier:
    if symbol not in _classifiers:
        _classifiers[symbol] = LeeReadyClassifier(window_seconds)
    return _classifiers[symbol]


def imbalance_gate(symbol: str, signal_side: str, threshold: float = 0.3) -> bool:
    """
    Gate a signal based on rolling aggressor imbalance.

    Parameters
    ----------
    symbol : ticker
    signal_side : "buy" | "sell"
    threshold : min imbalance required in signal direction

    Returns True if gate passes, False if blocked.
    """
    clf = get_classifier(symbol)
    imbalance = clf.rolling_imbalance()

    if signal_side == "buy" and imbalance < -threshold:
        logger.info("[lee_ready] blocking long %s — sell pressure %.2f", symbol, imbalance)
        return False
    if signal_side == "sell" and imbalance > threshold:
        logger.info("[lee_ready] blocking short %s — buy pressure %.2f", symbol, imbalance)
        return False
    return True
