"""AlgorithmContext — the shared object every component receives each iteration.

Carries regime state, the broker adapter, and a price cache.
Designed to be cheap to construct and safe to pass between async methods.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .types import Symbol, Bar

logger = logging.getLogger(__name__)


# ── Broker Adapter protocol ────────────────────────────────────────────────────

class BrokerAdapter:
    """Minimal interface execution models and portfolio constructors use."""

    async def get_positions(self) -> dict[Symbol, float]:
        """Return {symbol: qty} for open positions."""
        raise NotImplementedError

    async def get_portfolio_value(self) -> float:
        """Return total portfolio value in USD."""
        raise NotImplementedError

    async def get_high_water_mark(self, bot_id: str) -> float:
        """Return peak portfolio value for drawdown calculation."""
        raise NotImplementedError

    async def submit_order(self, order) -> dict[str, Any]:
        """Submit an order. Returns broker response dict."""
        raise NotImplementedError


# ── Bar Cache ──────────────────────────────────────────────────────────────────

class BarCache:
    """Lightweight cache for OHLCV data and derived metrics.

    Backed by an in-memory dict; components call get_bars() and the cache
    fetches on demand.  Shared within one RunIteration so each symbol is
    fetched at most once per cycle.
    """

    def __init__(self) -> None:
        self._bars: dict[str, list[Bar]] = {}
        self._prices: dict[Symbol, float] = {}  # latest close per symbol

    def set_bars(self, symbol: Symbol, bars: list[Bar]) -> None:
        self._bars[symbol] = bars
        if bars:
            self._prices[symbol] = bars[-1].close

    def get_bars(self, symbol: Symbol) -> list[Bar]:
        return self._bars.get(symbol, [])

    def get_price(self, symbol: Symbol) -> Optional[float]:
        return self._prices.get(symbol)

    def set_price(self, symbol: Symbol, price: float) -> None:
        self._prices[symbol] = price


# ── Algorithm Context ──────────────────────────────────────────────────────────

@dataclass
class AlgorithmContext:
    """Passed to every component on each iteration."""
    bot_id: str
    portfolio_id: Optional[str]
    asset_class: str        # 'stocks' | 'crypto' | 'options'
    regime: dict[str, Any]
    catalysts: list[dict[str, Any]]
    broker: BrokerAdapter
    cache: BarCache = field(default_factory=BarCache)
    _events: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def log(self, level: str, msg: str) -> None:
        getattr(logger, level, logger.info)(f"[v2:{self.bot_id}] {msg}")

    def emit(self, event: str, payload: Any) -> None:
        self._events.append({"event": event, "payload": payload})
        self.log("debug", f"emit:{event} {payload}")

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)


# ── Paper broker (SQLAlchemy-backed, read-only in shadow mode) ─────────────────

class PaperBrokerAdapter(BrokerAdapter):
    """Reads positions/value from the paper_* tables via SQLAlchemy.

    In shadow_mode=True: submit_order() is a no-op (orders are only logged).
    In shadow_mode=False: would call POST /api/paper/orders (not yet wired).
    """

    def __init__(self, user_id: int, db, shadow_mode: bool = True) -> None:
        self._user_id = user_id
        self._db = db
        self._shadow_mode = shadow_mode

    async def get_positions(self) -> dict[Symbol, float]:
        from app.db.models.paper import PaperPosition
        rows = (
            self._db.query(PaperPosition)
            .filter_by(user_id=self._user_id)
            .all()
        )
        return {r.symbol: r.qty for r in rows}

    async def get_portfolio_value(self) -> float:
        from app.db.models.paper import PaperAccount
        acct = self._db.query(PaperAccount).filter_by(user_id=self._user_id).first()
        if not acct:
            return 100_000.0
        # equity = cash + positions market value (simple approximation)
        return float(acct.cash)

    async def get_high_water_mark(self, bot_id: str) -> float:
        """Return peak portfolio equity from daily snapshots, or current value."""
        from app.db.models.paper import PaperAccount
        acct = self._db.query(PaperAccount).filter_by(user_id=self._user_id).first()
        if not acct:
            return 100_000.0
        return float(acct.starting_balance or 100_000.0)

    async def submit_order(self, order) -> dict[str, Any]:
        if self._shadow_mode:
            logger.info(
                "[v2:paper:shadow] WOULD submit %s %s %s @ market",
                order.side, order.qty, order.symbol,
            )
            return {"shadow": True, "order": str(order)}
        # Live paper trading — not yet wired; log and skip
        logger.warning("[v2:paper] Live submission not yet wired; skipping %s", order)
        return {}
