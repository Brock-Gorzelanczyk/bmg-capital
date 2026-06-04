"""
Percentage of Volume (POV) Adaptive Execution — Weekend 6, Module 12.

Each minute: observe tape volume V_t.
Submit (V_t × target_pct) − already_filled, clipped by max_clip.

Use when: liquidity is uncertain, order size < 1% ADV.
POV auto-adapts to actual market flow without needing a volume forecast.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TARGET_PCT = 0.10    # participate at 10% of market volume
DEFAULT_MAX_CLIP = 500       # max shares per minute submission


@dataclass
class POVState:
    """Mutable state tracked across a single POV execution."""
    symbol: str
    side: str
    total_shares: float
    target_pct: float
    max_clip: float
    shares_filled: float = 0.0
    shares_submitted: float = 0.0
    minutes_elapsed: int = 0
    completed: bool = False
    slippage_bps: float = 0.0


@dataclass
class POVSlice:
    """Output of each POV tick."""
    minute: int
    observed_volume: float
    shares_to_submit: float
    cumulative_filled: float
    pct_complete: float
    is_last: bool


class POVExecutor:
    """
    Stateful POV executor for one parent order.

    Call tick() each minute with the observed tape volume for that minute.
    """

    def __init__(
        self,
        symbol: str,
        side: str,
        total_shares: float,
        target_pct: float = DEFAULT_TARGET_PCT,
        max_clip: float = DEFAULT_MAX_CLIP,
        min_pct: float = 0.05,
        max_pct: float = 0.20,
    ) -> None:
        if not (0 < target_pct <= 1):
            raise ValueError(f"target_pct must be in (0,1], got {target_pct}")
        self._state = POVState(
            symbol=symbol,
            side=side,
            total_shares=total_shares,
            target_pct=target_pct,
            max_clip=max_clip,
        )
        self._min_pct = min_pct
        self._max_pct = max_pct

    def tick(self, observed_volume: float, fill_this_minute: float = 0.0) -> POVSlice:
        """
        Process one minute of tape data.

        Parameters
        ----------
        observed_volume : total shares traded in market this minute
        fill_this_minute : shares that actually got filled from our prior submission

        Returns
        -------
        POVSlice describing what to submit now
        """
        s = self._state
        s.shares_filled += fill_this_minute
        s.minutes_elapsed += 1

        if s.completed or s.shares_filled >= s.total_shares:
            s.completed = True
            return POVSlice(
                minute=s.minutes_elapsed,
                observed_volume=observed_volume,
                shares_to_submit=0.0,
                cumulative_filled=s.shares_filled,
                pct_complete=100.0,
                is_last=True,
            )

        remaining = s.total_shares - s.shares_filled
        target_qty = observed_volume * s.target_pct
        # Clip to avoid single-minute outsized participation
        clipped = min(target_qty, s.max_clip, remaining)
        clipped = max(0.0, clipped)

        s.shares_submitted += clipped
        pct_complete = (s.shares_filled / s.total_shares) * 100

        return POVSlice(
            minute=s.minutes_elapsed,
            observed_volume=observed_volume,
            shares_to_submit=round(clipped, 4),
            cumulative_filled=round(s.shares_filled, 4),
            pct_complete=round(pct_complete, 1),
            is_last=False,
        )

    def adapt_rate(self, urgency: float) -> None:
        """
        Adjust participation rate based on urgency signal (0=relaxed, 1=urgent).
        Maps urgency to [min_pct, max_pct] range.
        """
        new_rate = self._min_pct + (self._max_pct - self._min_pct) * urgency
        old_rate = self._state.target_pct
        self._state.target_pct = round(new_rate, 4)
        logger.debug(
            "[pov] %s rate adapted %.1f%% → %.1f%% (urgency=%.2f)",
            self._state.symbol, old_rate * 100, new_rate * 100, urgency,
        )

    @property
    def state(self) -> POVState:
        return self._state

    @property
    def pct_complete(self) -> float:
        if self._state.total_shares <= 0:
            return 100.0
        return (self._state.shares_filled / self._state.total_shares) * 100
