"""BrokerAdapter interface and factory.

get_broker() always returns a paper adapter unless force_live=True AND
the RIA_REGISTERED environment variable is set to 'true'.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional

from strategy_lab.core.signals import Signal


class BrokerAdapter(ABC):
    """Abstract broker interface.  All implementations must be paper-safe."""

    @abstractmethod
    def submit_order(self, symbol: str, qty: float, side: str) -> dict:
        """Submit a market order.  Returns order dict with at least 'order_id'."""
        ...

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Return list of open positions as dicts."""
        ...

    @abstractmethod
    def get_account(self) -> dict:
        """Return account summary (equity, cash, buying_power)."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by ID.  Returns True on success."""
        ...


# ── Late imports to avoid circular deps ──────────────────────────────────────

def _get_paper_stocks_cls():
    from strategy_lab.brokers.alpaca_paper_stocks import PaperStocksAdapter
    return PaperStocksAdapter


def _get_paper_crypto_cls():
    from strategy_lab.brokers.alpaca_paper_crypto import PaperCryptoAdapter
    return PaperCryptoAdapter


def _get_live_stocks_cls():
    from strategy_lab.brokers.alpaca_live_stocks import LiveStocksAdapter
    return LiveStocksAdapter


def _get_live_crypto_cls():
    from strategy_lab.brokers.alpaca_live_crypto import LiveCryptoAdapter
    return LiveCryptoAdapter


PAPER_BROKERS = {
    "stock": _get_paper_stocks_cls,
    "crypto": _get_paper_crypto_cls,
}

LIVE_BROKERS = {
    "stock": _get_live_stocks_cls,
    "crypto": _get_live_crypto_cls,
}


def get_broker(asset_class: str, force_live: bool = False) -> BrokerAdapter:
    """Factory: return the appropriate broker adapter.

    Paper is always the default.  Live requires RIA_REGISTERED=true.
    """
    if force_live:
        if os.getenv("RIA_REGISTERED", "false").lower() != "true":
            raise PermissionError("Live trading not available; RIA registration pending")
        if asset_class not in LIVE_BROKERS:
            raise ValueError(f"Unknown asset_class '{asset_class}'")
        return LIVE_BROKERS[asset_class]()()
    if asset_class not in PAPER_BROKERS:
        raise ValueError(f"Unknown asset_class '{asset_class}'")
    return PAPER_BROKERS[asset_class]()()
