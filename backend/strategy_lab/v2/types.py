"""Core data types that flow between the 5 LEAN-style components.

These are the contracts between Universe → Alpha → Portfolio → Risk → Execution.
Keeping them in one file makes the pipeline instantly readable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


Symbol = str   # "NVDA", "BTC/USD", etc.


@dataclass
class Bar:
    symbol: Symbol
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Insight:
    """Output of an AlphaModel — a directional prediction for one symbol."""
    symbol: Symbol
    direction: str          # 'up' | 'down' | 'flat'
    confidence: float       # 0.0 – 1.0
    period: str             # '1h' | '1d' | '5d' | '30d'
    source: str             # which alpha generated this
    reason: str             # human-readable explanation
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    magnitude: Optional[float] = None  # expected price move, e.g. 0.025 = 2.5%

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down", "flat"):
            raise ValueError(f"direction must be up|down|flat, got '{self.direction}'")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")


@dataclass
class PortfolioTarget:
    """Output of a PortfolioConstructionModel — desired position for one symbol."""
    symbol: Symbol
    target_qty: float       # shares/units (positive=long, negative=short, 0=close)
    reason: str
    target_value_usd: float = 0.0   # dollar value of the target (informational)
    source_insight: Optional[Insight] = None


@dataclass
class Order:
    """Output of an ExecutionModel — an actual order to send to the broker."""
    symbol: Symbol
    side: str               # 'buy' | 'sell'
    qty: float
    order_type: str         # 'market' | 'limit' | 'stop' | 'stop_limit'
    time_in_force: str      # 'day' | 'gtc' | 'ioc' | 'fok'
    tag: str                # traceback to insight/target
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    estimated_fill_usd: Optional[float] = None


@dataclass
class RunResult:
    """Summary returned by AlgorithmRunner.run_iteration()."""
    bot_id: str
    ts: datetime
    universe_size: int
    insights: list[Insight]
    targets: list[PortfolioTarget]
    orders: list[Order]
    shadow_mode: bool
    duration_ms: int = 0
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None
