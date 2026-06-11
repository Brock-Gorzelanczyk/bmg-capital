"""BrokerAdapter interface and factory.

get_broker() always returns a paper adapter unless force_live=True AND
the RIA_REGISTERED environment variable is set to 'true'.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from strategy_lab.core.signals import Signal


# ── Execution config ──────────────────────────────────────────────────────────

@dataclass
class ExecutionConfig:
    """Parsed from the profile YAML execution section."""

    order_type: str = "limit"
    limit_offset_bps: int = 5
    reprice_after_seconds: int = 30
    reprice_attempts: int = 3
    fallback_to_market: bool = True
    use_brackets: bool = True

    @classmethod
    def from_profile(cls, profile_config: dict) -> "ExecutionConfig":
        """Build an ExecutionConfig from a profile YAML dict."""
        exec_section = profile_config.get("execution", {}) or {}
        return cls(
            order_type=exec_section.get("order_type", "limit"),
            limit_offset_bps=int(exec_section.get("limit_offset_bps", 5)),
            reprice_after_seconds=int(exec_section.get("reprice_after_seconds", 30)),
            reprice_attempts=int(exec_section.get("reprice_attempts", 3)),
            fallback_to_market=bool(exec_section.get("fallback_to_market", True)),
            use_brackets=bool(exec_section.get("use_brackets", True)),
        )


# ── Execution quality helpers ─────────────────────────────────────────────────

def compute_limit_price(current_price: float, side: str, offset_bps: int) -> float:
    """Compute a limit price slightly above (buy) or below (sell) current price.

    For buy orders we go slightly higher to increase fill probability.
    For sell orders we go slightly lower.

    Args:
        current_price: Current market price.
        side: "buy" or "sell".
        offset_bps: Basis-point offset (e.g. 10 bps = 0.10%).

    Returns:
        Limit price rounded to 4 decimal places.
    """
    offset = current_price * (offset_bps / 10_000)
    if side == "buy":
        return round(current_price + offset, 4)
    return round(current_price - offset, 4)


def compute_bracket_prices(entry: float, profile_config: dict) -> tuple[float, float]:
    """Compute stop-loss and take-profit prices for a long bracket order.

    Args:
        entry: Expected entry price.
        profile_config: Profile YAML dict with stop_loss_pct / take_profit_pct.

    Returns:
        (stop_price, target_price) tuple, both rounded to 4 decimal places.
    """
    stop_pct = abs(profile_config.get("stop_loss_pct", 5.0)) / 100
    target_pct = abs(profile_config.get("take_profit_pct", 10.0)) / 100
    stop_price = round(entry * (1 - stop_pct), 4)
    target_price = round(entry * (1 + target_pct), 4)
    return stop_price, target_price


def track_slippage(expected_cents: int, actual_cents: int) -> float:
    """Compute execution slippage in basis points.

    Args:
        expected_cents: Expected fill price in cents.
        actual_cents: Actual fill price in cents.

    Returns:
        Absolute slippage in basis points (always positive).
    """
    if expected_cents == 0:
        return 0.0
    return abs(actual_cents - expected_cents) / expected_cents * 10_000


# ── Broker adapter ABC ────────────────────────────────────────────────────────

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

    @abstractmethod
    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        target_price: float,
        limit_price: Optional[float] = None,
    ) -> dict:
        """Submit entry + stop-loss + take-profit as an OCO bracket order.

        Uses Alpaca's order_class='bracket' with take_profit.limit_price
        and stop_loss.stop_price legs.

        Args:
            symbol: Asset symbol.
            qty: Quantity to trade.
            side: "buy" or "sell".
            stop_price: Stop-loss trigger price.
            target_price: Take-profit limit price.
            limit_price: Entry limit price; if None, submits a market entry.

        Returns:
            Order dict with at least 'order_id'.
        """
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
    "stock":   _get_paper_stocks_cls,
    "crypto":  _get_paper_crypto_cls,
    "quant":   _get_paper_crypto_cls,  # quant bots trade crypto via Alpaca paper
}

LIVE_BROKERS = {
    "stock":   _get_live_stocks_cls,
    "crypto":  _get_live_crypto_cls,
    "quant":   _get_live_crypto_cls,
}


def get_broker(asset_class: str, force_live: bool = False) -> BrokerAdapter:
    """Factory: return the appropriate broker adapter.

    Paper is always the default.  Live requires RIA_REGISTERED=true.
    The returned adapter is always wrapped with SafeBrokerWrapper so that
    the trading gate and blackout checks apply to every order submission.
    Wrapping is fail-open — if SafeBrokerWrapper can't be imported the raw
    adapter is returned instead, ensuring nothing blocks legitimate trades.
    """
    if force_live:
        if os.getenv("RIA_REGISTERED", "false").lower() != "true":
            raise PermissionError("Live trading not available; RIA registration pending")
        if asset_class not in LIVE_BROKERS:
            raise ValueError(f"Unknown asset_class '{asset_class}'")
        inner = LIVE_BROKERS[asset_class]()()
    else:
        if asset_class not in PAPER_BROKERS:
            raise ValueError(f"Unknown asset_class '{asset_class}'")
        inner = PAPER_BROKERS[asset_class]()()
    try:
        from app.services.safe_broker import SafeBrokerWrapper
        return SafeBrokerWrapper(inner)  # type: ignore[return-value]
    except Exception:
        return inner
