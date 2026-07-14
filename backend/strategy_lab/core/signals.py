"""Signal dataclass — the unit of communication between strategies and the broker."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Signal:
    """A trading signal produced by a strategy."""

    symbol: str
    side: str          # "buy" | "sell" | "hold"
    confidence: float  # 0.0 – 1.0
    size_hint: float   # fraction of position capital to deploy (0.0 – 1.0)
    reason: str
    strategy: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Time-boxed threshold experiment (2026-07-13): the discipline gate's
    # composite score at the moment this signal was admitted to execution.
    # Runner sets this from _gate_result.composite_score just before
    # _execute_signal writes the BotTrade row. Nullable — strategies
    # themselves never populate it.
    composite_score_at_execution: Optional[int] = None

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell", "hold"):
            raise ValueError(f"Invalid side '{self.side}'; must be buy|sell|hold")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if not 0.0 <= self.size_hint <= 1.0:
            raise ValueError(f"size_hint must be in [0, 1], got {self.size_hint}")

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "confidence": self.confidence,
            "size_hint": self.size_hint,
            "reason": self.reason,
            "strategy": self.strategy,
            "ts": self.ts.isoformat(),
        }
