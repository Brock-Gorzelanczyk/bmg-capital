"""
Midpoint Peg Iceberg — Weekend 6, Module 13.

Hidden order pegged to NBBO midpoint.
Display tip is randomized (20-80% of slice) — never a round number.
Refreshed on partial fill with randomized delay to avoid pattern detection.

Use for: large orders where price impact and information leakage matter.
Anti-detection: randomized tip size + refresh delay + occasional skip.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class IcebergOrder:
    """State for a single iceberg order."""
    symbol: str
    side: str
    total_shares: float
    filled_shares: float = 0.0
    current_tip_shares: float = 0.0
    nbbo_mid: float = 0.0
    refresh_count: int = 0
    last_refresh_ts: float = 0.0
    completed: bool = False


@dataclass
class IcebergSlice:
    """Instruction produced by each refresh."""
    tip_shares: float           # visible display quantity
    hidden_shares: float        # hidden portion of order
    limit_price: float          # peg to current mid
    min_refresh_delay_ms: int   # wait at least this long before next refresh
    skip_refresh: bool          # occasionally skip to avoid pattern detection


class MidpointPegIceberg:
    """
    Manages a midpoint-pegged iceberg order with anti-detection randomization.

    Tip size: uniformly random in [20%, 80%] of slice_size
    Refresh delay: uniformly random in [min_delay_ms, max_delay_ms]
    Skip probability: randomly skip ~8% of refreshes to avoid HFT pattern matching
    """

    def __init__(
        self,
        symbol: str,
        side: str,
        total_shares: float,
        slice_size: float,
        min_refresh_delay_ms: int = 200,
        max_refresh_delay_ms: int = 2000,
        skip_probability: float = 0.08,
    ) -> None:
        self._order = IcebergOrder(
            symbol=symbol,
            side=side,
            total_shares=total_shares,
        )
        self._slice_size = slice_size
        self._min_delay_ms = min_refresh_delay_ms
        self._max_delay_ms = max_refresh_delay_ms
        self._skip_probability = skip_probability
        self._rng = random.Random()  # instance-level RNG (seedable for tests)

    def refresh(self, current_nbbo_mid: float, last_fill: float = 0.0) -> Optional[IcebergSlice]:
        """
        Generate a refresh instruction.

        Parameters
        ----------
        current_nbbo_mid : current midpoint of NBBO
        last_fill : shares filled since last refresh

        Returns
        -------
        IcebergSlice or None if order complete / skip
        """
        o = self._order
        o.filled_shares += last_fill

        if o.filled_shares >= o.total_shares:
            o.completed = True
            logger.info("[iceberg] %s %s complete — %.0f shares", o.side, o.symbol, o.filled_shares)
            return None

        # Occasional skip to disrupt predictable refresh pattern
        if self._rng.random() < self._skip_probability:
            logger.debug("[iceberg] skip refresh %s (anti-detection)", o.symbol)
            return IcebergSlice(
                tip_shares=0.0,
                hidden_shares=0.0,
                limit_price=current_nbbo_mid,
                min_refresh_delay_ms=self._random_delay(),
                skip_refresh=True,
            )

        remaining = o.total_shares - o.filled_shares
        slice_qty = min(self._slice_size, remaining)

        # Randomize tip: 20-80% of slice
        tip_fraction = self._rng.uniform(0.20, 0.80)
        tip_shares = max(1.0, round(slice_qty * tip_fraction, 0))
        hidden_shares = max(0.0, slice_qty - tip_shares)

        # Peg to current mid — add tiny random offset to avoid exact-mid clustering
        # For buy: peg to mid (not bid) for passive fill
        offset = self._rng.uniform(-0.001, 0.001) * current_nbbo_mid
        limit_price = round(current_nbbo_mid + offset, 4)

        o.nbbo_mid = current_nbbo_mid
        o.current_tip_shares = tip_shares
        o.refresh_count += 1
        o.last_refresh_ts = time.time()

        logger.debug(
            "[iceberg] refresh #%d %s %s tip=%.0f hidden=%.0f px=%.4f remaining=%.0f",
            o.refresh_count, o.side, o.symbol,
            tip_shares, hidden_shares, limit_price, remaining,
        )

        return IcebergSlice(
            tip_shares=tip_shares,
            hidden_shares=hidden_shares,
            limit_price=limit_price,
            min_refresh_delay_ms=self._random_delay(),
            skip_refresh=False,
        )

    def cancel(self) -> None:
        self._order.completed = True
        logger.info("[iceberg] %s %s cancelled at %.0f/%.0f filled",
                    self._order.side, self._order.symbol,
                    self._order.filled_shares, self._order.total_shares)

    @property
    def pct_complete(self) -> float:
        if self._order.total_shares <= 0:
            return 100.0
        return round((self._order.filled_shares / self._order.total_shares) * 100, 1)

    @property
    def is_complete(self) -> bool:
        return self._order.completed

    def _random_delay(self) -> int:
        return self._rng.randint(self._min_delay_ms, self._max_delay_ms)

    def seed(self, seed: int) -> None:
        """Seed RNG for reproducible testing."""
        self._rng.seed(seed)
