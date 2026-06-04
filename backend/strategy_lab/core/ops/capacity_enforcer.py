"""
Capacity Enforcer — Weekend 4, Module 8.

Each strategy declares max_notional_usd (its AUM capacity).
When total allocated capital across all users for that strategy
approaches the cap, refuse new signups.

Renaissance's Medallion Fund is the canonical example: capped at ~$10B
because larger size would erode alpha. BMG mirrors this at the strategy level.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Default capacity per strategy class (USD)
DEFAULT_CAPACITY = {
    "intraday": 5_000_000,      # $5M — limited by market impact
    "swing": 20_000_000,        # $20M
    "position": 50_000_000,     # $50M
    "long_term": 100_000_000,   # $100M — liquid ETFs handle more
    "options": 10_000_000,      # $10M — options liquidity constraint
    "crypto": 2_000_000,        # $2M — crypto is less liquid
}

WARNING_THRESHOLD = 0.80    # warn at 80% capacity
HARD_CAP_THRESHOLD = 0.95   # reject new users at 95% capacity


@dataclass
class CapacityStatus:
    strategy_id: str
    max_notional_usd: float
    current_notional_usd: float
    utilization_pct: float
    accepts_new_users: bool
    warning: bool
    message: str


def evaluate_capacity(
    strategy_id: str,
    max_notional_usd: float,
    current_notional_usd: float,
    proposed_addition_usd: float = 0.0,
) -> CapacityStatus:
    """
    Check if a strategy can accept additional capital.

    Parameters
    ----------
    strategy_id : strategy identifier
    max_notional_usd : declared capacity ceiling
    current_notional_usd : total USD currently allocated by all users
    proposed_addition_usd : size of the proposed new allocation to check

    Returns
    -------
    CapacityStatus with accepts_new_users=False if over cap
    """
    projected = current_notional_usd + proposed_addition_usd
    utilization = projected / max(max_notional_usd, 1.0)

    if utilization >= HARD_CAP_THRESHOLD:
        return CapacityStatus(
            strategy_id=strategy_id,
            max_notional_usd=max_notional_usd,
            current_notional_usd=current_notional_usd,
            utilization_pct=round(utilization * 100, 1),
            accepts_new_users=False,
            warning=True,
            message=(
                f"Strategy is at {utilization*100:.0f}% capacity "
                f"(${current_notional_usd:,.0f} / ${max_notional_usd:,.0f}). "
                "No new allocations accepted."
            ),
        )

    if utilization >= WARNING_THRESHOLD:
        logger.warning(
            "[capacity] %s at %.0f%% capacity — approaching limit",
            strategy_id, utilization * 100,
        )
        return CapacityStatus(
            strategy_id=strategy_id,
            max_notional_usd=max_notional_usd,
            current_notional_usd=current_notional_usd,
            utilization_pct=round(utilization * 100, 1),
            accepts_new_users=True,
            warning=True,
            message=(
                f"Strategy is at {utilization*100:.0f}% capacity — "
                "accepting users but approaching the limit."
            ),
        )

    return CapacityStatus(
        strategy_id=strategy_id,
        max_notional_usd=max_notional_usd,
        current_notional_usd=current_notional_usd,
        utilization_pct=round(utilization * 100, 1),
        accepts_new_users=True,
        warning=False,
        message=f"Strategy has capacity ({utilization*100:.0f}% utilized).",
    )


def default_capacity(time_horizon: str) -> float:
    """Return default capacity for a strategy based on its time horizon."""
    return DEFAULT_CAPACITY.get(time_horizon, DEFAULT_CAPACITY["swing"])
