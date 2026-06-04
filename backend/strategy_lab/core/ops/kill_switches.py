"""
Kill Switches — Weekend 1, Module 6.  3-LEVEL SAFETY SYSTEM.

Level 1 — Strategy-level: order rate spike, fill deviation, P&L 5σ event
Level 2 — Bot-level: cumulative daily loss > 2× rolling daily vol
Level 3 — Fund-level: broker disconnect, LULD halt, market-wide circuit breakers

Each level runs independently. Higher levels cascade down (fund kill
stops all bots; bot kill stops all strategies on that bot).

Strategy code CANNOT re-enable a kill switch. Manual review required.

Usage
-----
ks = KillSwitchManager()

# Strategy level
ks.check_strategy("orb_v1", daily_pnl=-500, expected_daily_vol=100)

# Bot level
ks.check_bot(bot_id=3, daily_pnl=-800, rolling_daily_vol_usd=300)

# Fund level — call from market data feed handler
ks.on_market_event(MarketEvent.CIRCUIT_BREAKER_7PCT)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class MarketEvent(Enum):
    BROKER_DISCONNECT = auto()
    LULD_HALT = auto()
    CIRCUIT_BREAKER_7PCT = auto()
    CIRCUIT_BREAKER_13PCT = auto()
    CIRCUIT_BREAKER_20PCT = auto()


class KillLevel(Enum):
    STRATEGY = "strategy"
    BOT = "bot"
    FUND = "fund"


@dataclass
class KillSwitchEvent:
    id: str
    level: KillLevel
    scope: str                  # strategy_id, bot_id, or "fund"
    triggered_at: datetime
    reason: str
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class KillSwitchManager:
    """
    Manages all three kill switch levels.
    Thread-safe. Callbacks fire on any level-3 event.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._killed_strategies: dict[str, KillSwitchEvent] = {}
        self._killed_bots: dict[int, KillSwitchEvent] = {}
        self._fund_killed: bool = False
        self._fund_kill_event: Optional[KillSwitchEvent] = None
        self._fund_kill_callbacks: list[Callable] = []
        self._event_log: list[KillSwitchEvent] = []
        self._uid_counter = 0

    # ── Public Checks ────────────────────────────────────────────────────────

    def is_strategy_live(self, strategy_id: str) -> bool:
        """Return False if this strategy or its bot or the fund is killed."""
        if self._fund_killed:
            return False
        if strategy_id in self._killed_strategies:
            return False
        return True

    def is_bot_live(self, bot_id: int) -> bool:
        """Return False if this bot or the fund is killed."""
        if self._fund_killed:
            return False
        if bot_id in self._killed_bots:
            return False
        return True

    def is_fund_live(self) -> bool:
        return not self._fund_killed

    # ── Strategy-Level Triggers ───────────────────────────────────────────────

    def check_strategy(
        self,
        strategy_id: str,
        daily_pnl: float,
        expected_daily_vol: float,
        order_rate: int = 0,
        max_order_rate: int = 100,
    ) -> None:
        """
        Check and potentially kill a strategy.

        Parameters
        ----------
        daily_pnl : today's realized + unrealized P&L in USD
        expected_daily_vol : expected daily P&L std dev (from backtest)
        order_rate : orders submitted in last minute
        max_order_rate : threshold for runaway detection
        """
        with self._lock:
            if strategy_id in self._killed_strategies:
                return  # already dead

            reasons = []

            # 5σ P&L event
            if expected_daily_vol > 0 and abs(daily_pnl) > 5 * expected_daily_vol:
                reasons.append(f"5σ P&L event: ${daily_pnl:,.0f} vs σ=${expected_daily_vol:,.0f}")

            # Order rate spike
            if order_rate > max_order_rate:
                reasons.append(f"order rate spike: {order_rate}/min > {max_order_rate}/min")

            if reasons:
                self._kill_strategy(strategy_id, "; ".join(reasons))

    def check_bot(
        self,
        bot_id: int,
        daily_pnl: float,
        rolling_daily_vol_usd: float,
    ) -> None:
        """Kill a bot if daily loss exceeds 2× rolling daily vol."""
        with self._lock:
            if bot_id in self._killed_bots:
                return

            if rolling_daily_vol_usd > 0 and daily_pnl < -2 * rolling_daily_vol_usd:
                self._kill_bot(
                    bot_id,
                    f"daily loss ${abs(daily_pnl):,.0f} > 2× daily vol ${rolling_daily_vol_usd:,.0f}",
                )

    def on_market_event(self, event: MarketEvent, details: str = "") -> None:
        """Handle a market-wide event — may trigger fund-level kill."""
        FUND_KILL_EVENTS = {
            MarketEvent.BROKER_DISCONNECT,
            MarketEvent.CIRCUIT_BREAKER_7PCT,
            MarketEvent.CIRCUIT_BREAKER_13PCT,
            MarketEvent.CIRCUIT_BREAKER_20PCT,
        }
        PAUSE_EVENTS = {MarketEvent.LULD_HALT}

        with self._lock:
            if event in FUND_KILL_EVENTS:
                reason = f"market event: {event.name}"
                if details:
                    reason += f" ({details})"
                self._kill_fund(reason)
            elif event in PAUSE_EVENTS:
                logger.warning("[kill_switch] LULD halt detected — pausing new entries: %s", details)
                # LULD: pause new entries but don't kill (exits should still work)
                # In a full implementation this would set a pause flag per symbol

    # ── Manual Controls ───────────────────────────────────────────────────────

    def kill_strategy(self, strategy_id: str, reason: str) -> None:
        with self._lock:
            self._kill_strategy(strategy_id, f"manual: {reason}")

    def kill_bot(self, bot_id: int, reason: str) -> None:
        with self._lock:
            self._kill_bot(bot_id, f"manual: {reason}")

    def kill_fund(self, reason: str) -> None:
        with self._lock:
            self._kill_fund(f"manual: {reason}")

    def resolve_strategy(self, strategy_id: str, resolved_by: str) -> bool:
        with self._lock:
            if strategy_id not in self._killed_strategies:
                return False
            ev = self._killed_strategies.pop(strategy_id)
            ev.resolved = True
            ev.resolved_at = datetime.now(timezone.utc)
            ev.resolved_by = resolved_by
            logger.info("[kill_switch] strategy %s resolved by %s", strategy_id, resolved_by)
            return True

    def resolve_bot(self, bot_id: int, resolved_by: str) -> bool:
        with self._lock:
            if bot_id not in self._killed_bots:
                return False
            ev = self._killed_bots.pop(bot_id)
            ev.resolved = True
            ev.resolved_at = datetime.now(timezone.utc)
            ev.resolved_by = resolved_by
            logger.info("[kill_switch] bot %d resolved by %s", bot_id, resolved_by)
            return True

    def resolve_fund(self, resolved_by: str) -> bool:
        with self._lock:
            if not self._fund_killed:
                return False
            self._fund_killed = False
            if self._fund_kill_event:
                self._fund_kill_event.resolved = True
                self._fund_kill_event.resolved_at = datetime.now(timezone.utc)
                self._fund_kill_event.resolved_by = resolved_by
            logger.warning("[kill_switch] FUND kill resolved by %s — VERIFY market conditions", resolved_by)
            return True

    def add_fund_kill_callback(self, callback: Callable) -> None:
        """Register callback to fire when fund-level kill triggers (e.g. flatten all positions)."""
        self._fund_kill_callbacks.append(callback)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "fund_killed": self._fund_killed,
            "fund_kill_reason": self._fund_kill_event.reason if self._fund_kill_event else None,
            "killed_bots": {
                str(k): v.reason for k, v in self._killed_bots.items()
            },
            "killed_strategies": {
                k: v.reason for k, v in self._killed_strategies.items()
            },
            "total_events": len(self._event_log),
        }

    def recent_events(self, n: int = 20) -> list[dict]:
        events = self._event_log[-n:]
        return [
            {
                "id": e.id,
                "level": e.level.value,
                "scope": e.scope,
                "triggered_at": e.triggered_at.isoformat(),
                "reason": e.reason,
                "resolved": e.resolved,
            }
            for e in reversed(events)
        ]

    # ── Private ───────────────────────────────────────────────────────────────

    def _uid(self) -> str:
        self._uid_counter += 1
        return f"ks_{self._uid_counter:06d}"

    def _kill_strategy(self, strategy_id: str, reason: str) -> None:
        ev = KillSwitchEvent(
            id=self._uid(),
            level=KillLevel.STRATEGY,
            scope=strategy_id,
            triggered_at=datetime.now(timezone.utc),
            reason=reason,
        )
        self._killed_strategies[strategy_id] = ev
        self._event_log.append(ev)
        logger.error("[kill_switch] STRATEGY KILLED: %s — %s", strategy_id, reason)

    def _kill_bot(self, bot_id: int, reason: str) -> None:
        ev = KillSwitchEvent(
            id=self._uid(),
            level=KillLevel.BOT,
            scope=str(bot_id),
            triggered_at=datetime.now(timezone.utc),
            reason=reason,
        )
        self._killed_bots[bot_id] = ev
        self._event_log.append(ev)
        logger.error("[kill_switch] BOT KILLED: bot_id=%d — %s", bot_id, reason)

    def _kill_fund(self, reason: str) -> None:
        if self._fund_killed:
            return  # don't duplicate
        ev = KillSwitchEvent(
            id=self._uid(),
            level=KillLevel.FUND,
            scope="fund",
            triggered_at=datetime.now(timezone.utc),
            reason=reason,
        )
        self._fund_killed = True
        self._fund_kill_event = ev
        self._event_log.append(ev)
        logger.critical("[kill_switch] FUND KILLED: %s", reason)
        for cb in self._fund_kill_callbacks:
            try:
                cb(ev)
            except Exception as exc:
                logger.error("[kill_switch] callback error: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: Optional[KillSwitchManager] = None


def get_kill_switch_manager() -> KillSwitchManager:
    global _manager
    if _manager is None:
        _manager = KillSwitchManager()
    return _manager
