"""
Pre-Trade Risk Gate — Weekend 1, Module 2.  CRITICAL SAFETY MODULE.

Separate from all strategy code. Every order MUST pass through this gate
before submission. This module CANNOT be disabled by strategy code.

Mirrors SEC 15c3-5 Market Access Rule requirements.
Inspired by Knight Capital post-mortem: $440M loss in 45 minutes
due to missing pre-trade controls on order rate and position limits.

The gate runs synchronously and raises RiskGateError on any violation.
Strategy code must catch this and treat it as "order rejected".

Usage
-----
gate = PreTradeRiskGate.from_env()

try:
    gate.check(order)
except RiskGateError as e:
    logger.error("Order rejected: %s", e)
    return  # do not submit
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class RiskGateError(Exception):
    """Raised when an order fails a pre-trade risk check."""

    def __init__(self, reason: str, check_name: str) -> None:
        super().__init__(f"[{check_name}] {reason}")
        self.reason = reason
        self.check_name = check_name


@dataclass
class OrderIntent:
    """Standardized order representation consumed by the gate."""
    symbol: str
    side: str                           # "buy" | "sell" | "sell_short"
    qty: float                          # shares / units
    order_type: str                     # "market" | "limit" | "stop"
    limit_price: Optional[float]        # required for limit orders
    arrival_mid: Optional[float]        # NBBO midpoint at decision time
    notional_usd: float                 # abs(qty * price)
    strategy_id: str
    bot_id: int
    account_equity_usd: float           # current account equity
    gross_exposure_usd: float           # current total gross exposure
    symbol_position_usd: float          # current position in this symbol


@dataclass
class GateConfig:
    """Configurable limits — loaded from env or DB."""
    max_order_notional_usd: float = 50_000.0
    max_position_per_symbol_pct: float = 5.0        # % of account equity
    max_gross_exposure_pct: float = 100.0            # % of account equity
    max_orders_per_second_per_symbol: int = 10
    fat_finger_band_pct: float = 5.0                 # reject if limit > X% from mid
    max_daily_loss_usd: float = 5_000.0              # halt if exceeded
    blocked_symbols: set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "GateConfig":
        return cls(
            max_order_notional_usd=float(os.getenv("GATE_MAX_NOTIONAL_USD", "50000")),
            max_position_per_symbol_pct=float(os.getenv("GATE_MAX_POS_PCT", "5.0")),
            max_gross_exposure_pct=float(os.getenv("GATE_MAX_GROSS_EXP_PCT", "100.0")),
            max_orders_per_second_per_symbol=int(os.getenv("GATE_MAX_OPS", "10")),
            fat_finger_band_pct=float(os.getenv("GATE_FAT_FINGER_PCT", "5.0")),
            max_daily_loss_usd=float(os.getenv("GATE_MAX_DAILY_LOSS_USD", "5000")),
        )


class PreTradeRiskGate:
    """
    Hard pre-trade risk gate.  All checks run in O(1).
    Thread-safe.  Cannot be bypassed by strategy code.
    """

    def __init__(self, config: Optional[GateConfig] = None) -> None:
        self._config = config or GateConfig()
        self._lock = threading.Lock()
        # {symbol: [timestamps of recent orders]}
        self._order_timestamps: dict[str, list[float]] = {}
        self._daily_loss_usd: float = 0.0
        self._gate_killed: bool = False
        self._kill_reason: str = ""
        logger.info("[risk_gate] initialized with config: %s", self._config)

    @classmethod
    def from_env(cls) -> "PreTradeRiskGate":
        return cls(config=GateConfig.from_env())

    # ── Public API ──────────────────────────────────────────────────────────

    def check(self, order: OrderIntent) -> None:
        """
        Run all pre-trade checks. Raises RiskGateError on any violation.
        Silent on pass.

        This is the single choke-point — ALL orders must call this.
        """
        if self._gate_killed:
            raise RiskGateError(
                f"Gate is killed: {self._kill_reason}", "kill_switch"
            )

        with self._lock:
            self._check_blocked_symbol(order)
            self._check_notional_cap(order)
            self._check_position_concentration(order)
            self._check_gross_exposure(order)
            self._check_fat_finger(order)
            self._check_order_rate(order)
            self._check_daily_loss(order)
            self._record_order(order)

    def record_fill(self, pnl_usd: float) -> None:
        """Call after each fill with realized P&L. Used for daily loss tracking."""
        with self._lock:
            if pnl_usd < 0:
                self._daily_loss_usd += abs(pnl_usd)

    def reset_daily_counters(self) -> None:
        """Call at market open each day."""
        with self._lock:
            self._daily_loss_usd = 0.0
            self._order_timestamps.clear()

    def kill(self, reason: str) -> None:
        """Emergency kill — blocks all subsequent orders from this gate instance."""
        with self._lock:
            self._gate_killed = True
            self._kill_reason = reason
        logger.critical("[risk_gate] GATE KILLED: %s", reason)

    def is_killed(self) -> bool:
        return self._gate_killed

    def status(self) -> dict:
        return {
            "killed": self._gate_killed,
            "kill_reason": self._kill_reason,
            "daily_loss_usd": self._daily_loss_usd,
            "config": {
                "max_order_notional_usd": self._config.max_order_notional_usd,
                "max_position_per_symbol_pct": self._config.max_position_per_symbol_pct,
                "max_gross_exposure_pct": self._config.max_gross_exposure_pct,
            },
        }

    # ── Individual Checks ────────────────────────────────────────────────────

    def _check_blocked_symbol(self, order: OrderIntent) -> None:
        if order.symbol in self._config.blocked_symbols:
            raise RiskGateError(
                f"{order.symbol} is on the blocked list", "blocked_symbol"
            )

    def _check_notional_cap(self, order: OrderIntent) -> None:
        if order.notional_usd > self._config.max_order_notional_usd:
            raise RiskGateError(
                f"Order notional ${order.notional_usd:,.0f} exceeds cap "
                f"${self._config.max_order_notional_usd:,.0f}",
                "notional_cap",
            )

    def _check_position_concentration(self, order: OrderIntent) -> None:
        if order.account_equity_usd <= 0:
            return
        new_position_usd = order.symbol_position_usd + order.notional_usd
        pct = (new_position_usd / order.account_equity_usd) * 100
        if pct > self._config.max_position_per_symbol_pct:
            raise RiskGateError(
                f"Position in {order.symbol} would be {pct:.1f}% of equity, "
                f"limit is {self._config.max_position_per_symbol_pct}%",
                "position_concentration",
            )

    def _check_gross_exposure(self, order: OrderIntent) -> None:
        if order.account_equity_usd <= 0:
            return
        new_gross = order.gross_exposure_usd + order.notional_usd
        pct = (new_gross / order.account_equity_usd) * 100
        if pct > self._config.max_gross_exposure_pct:
            raise RiskGateError(
                f"Gross exposure would be {pct:.1f}% of equity, "
                f"limit is {self._config.max_gross_exposure_pct}%",
                "gross_exposure",
            )

    def _check_fat_finger(self, order: OrderIntent) -> None:
        if order.order_type != "limit":
            return
        if order.limit_price is None or order.arrival_mid is None:
            return
        if order.arrival_mid <= 0:
            return
        deviation_pct = abs(order.limit_price - order.arrival_mid) / order.arrival_mid * 100
        if deviation_pct > self._config.fat_finger_band_pct:
            raise RiskGateError(
                f"Limit price ${order.limit_price:.2f} is {deviation_pct:.1f}% from mid "
                f"${order.arrival_mid:.2f}, exceeds fat-finger band "
                f"{self._config.fat_finger_band_pct}%",
                "fat_finger",
            )

    def _check_order_rate(self, order: OrderIntent) -> None:
        now = time.monotonic()
        sym = order.symbol
        if sym not in self._order_timestamps:
            self._order_timestamps[sym] = []
        # Purge timestamps older than 1 second
        self._order_timestamps[sym] = [
            t for t in self._order_timestamps[sym] if now - t < 1.0
        ]
        rate = len(self._order_timestamps[sym])
        if rate >= self._config.max_orders_per_second_per_symbol:
            raise RiskGateError(
                f"Order rate for {sym} is {rate}/s, limit is "
                f"{self._config.max_orders_per_second_per_symbol}/s — "
                "possible runaway strategy",
                "order_rate",
            )

    def _check_daily_loss(self, order: OrderIntent) -> None:
        if self._daily_loss_usd >= self._config.max_daily_loss_usd:
            raise RiskGateError(
                f"Daily loss ${self._daily_loss_usd:,.0f} has reached the "
                f"${self._config.max_daily_loss_usd:,.0f} limit — "
                "trading halted until next session",
                "daily_loss_limit",
            )

    def _record_order(self, order: OrderIntent) -> None:
        sym = order.symbol
        if sym not in self._order_timestamps:
            self._order_timestamps[sym] = []
        self._order_timestamps[sym].append(time.monotonic())


# ── Singleton (one gate per process) ─────────────────────────────────────────

_gate: Optional[PreTradeRiskGate] = None


def get_gate() -> PreTradeRiskGate:
    global _gate
    if _gate is None:
        _gate = PreTradeRiskGate.from_env()
    return _gate
