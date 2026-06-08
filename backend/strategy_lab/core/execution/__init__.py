# strategy_lab/core/execution was a single module (execution.py) that was later
# converted to a package directory. execution.py still exists but is shadowed by
# this package. Re-export the public API here so existing imports keep working.
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionConfig:
    order_type: str = "limit"
    limit_offset_bps: int = 5
    reprice_after_seconds: int = 30
    reprice_attempts: int = 3
    fallback_to_market: bool = True
    use_brackets: bool = True

    @classmethod
    def from_profile(cls, profile_config: dict) -> "ExecutionConfig":
        exec_section = profile_config.get("execution", {}) or {}
        return cls(
            order_type=exec_section.get("order_type", "limit"),
            limit_offset_bps=int(exec_section.get("limit_offset_bps", 5)),
            reprice_after_seconds=int(exec_section.get("reprice_after_seconds", 30)),
            reprice_attempts=int(exec_section.get("reprice_attempts", 3)),
            fallback_to_market=bool(exec_section.get("fallback_to_market", True)),
            use_brackets=bool(exec_section.get("use_brackets", True)),
        )


class BrokerAdapter(ABC):
    @abstractmethod
    def submit_order(self, symbol: str, qty: float, side: str) -> dict: ...

    @abstractmethod
    def get_positions(self) -> list[dict]: ...

    @abstractmethod
    def get_account(self) -> dict: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        target_price: float,
        limit_price: Optional[float] = None,
    ) -> dict: ...


def compute_limit_price(current_price: float, side: str, offset_bps: int) -> float:
    offset = current_price * (offset_bps / 10_000)
    return round(current_price + offset if side == "buy" else current_price - offset, 4)


def compute_bracket_prices(entry: float, profile_config: dict) -> tuple[float, float]:
    stop_pct = abs(profile_config.get("stop_loss_pct", 5.0)) / 100
    target_pct = abs(profile_config.get("take_profit_pct", 10.0)) / 100
    return round(entry * (1 - stop_pct), 4), round(entry * (1 + target_pct), 4)


def track_slippage(expected_cents: int, actual_cents: int) -> float:
    if expected_cents == 0:
        return 0.0
    return abs(actual_cents - expected_cents) / expected_cents * 10_000


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
    if force_live:
        if os.getenv("RIA_REGISTERED", "false").lower() != "true":
            raise PermissionError("Live trading not available; RIA registration pending")
        if asset_class not in LIVE_BROKERS:
            raise ValueError(f"Unknown asset_class '{asset_class}'")
        return LIVE_BROKERS[asset_class]()()
    if asset_class not in PAPER_BROKERS:
        raise ValueError(f"Unknown asset_class '{asset_class}'")
    return PAPER_BROKERS[asset_class]()()
