"""
Per-Bot Volatility Targeting — Barroso & Santa-Clara (2015) spec.

Fetches a bot's daily PnL equity curve from the bot_daily_pnl table and
computes a vol-target multiplier using a 126-day lookback.

Reference: Barroso & Santa-Clara (2015) "Momentum Has Its Moments",
           Journal of Financial Economics — Section 3.2 (vol targeting spec).

The VolTargetSizer uses a 60-day default tuned for high-frequency bots.
Equity/bond/commodity momentum strategies at weekly horizon should use
126 days (half-year) as in the original paper.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from strategy_lab.core.ops.vol_target_sizer import (
    compute_realized_vol,
    vol_adjusted_multiplier,
)

logger = logging.getLogger(__name__)

# Barroso & Santa-Clara (2015) use 126-day lookback for equity momentum
BSC_LOOKBACK_DAYS = 126

# Conservative caps: don't lever up more than 1.5× or cut below 25%
BSC_MAX_MULTIPLIER = 1.5
BSC_MIN_MULTIPLIER = 0.25

# Default target vol: 10% annualized (standard AQR risk parity target)
DEFAULT_TARGET_VOL = 0.10


def get_vol_target_multiplier(
    profile_name: str,
    db,
    target_vol: float = DEFAULT_TARGET_VOL,
) -> float:
    """Barroso & Santa-Clara vol targeting: target_vol / realized_vol_126d.

    Capped [BSC_MIN_MULTIPLIER, BSC_MAX_MULTIPLIER].
    Returns 1.0 if insufficient history (< 30 daily PnL rows).

    Fetches daily PnL equity from bot_daily_pnl via allocation lookup.

    Args:
        profile_name: Bot profile name (e.g. "tsmom_multi_asset").
        db:           SQLAlchemy Session — caller manages lifecycle.
        target_vol:   Target annualized vol, default 10%.

    Returns:
        Float multiplier to apply to position sizes.
    """
    try:
        from sqlalchemy import text as _text
        from app.db.models.bots import BotAllocation, BotProfile, BotDailyPnL

        # Resolve profile → first enabled paper allocation
        bp = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
        if not bp:
            logger.debug("[per_bot_vol] %s: profile not found → 1.0", profile_name)
            return 1.0

        alloc = (
            db.query(BotAllocation)
            .filter(
                BotAllocation.profile_id == bp.id,
                BotAllocation.enabled.is_(True),
                BotAllocation.paper_mode.is_(True),
            )
            .order_by(BotAllocation.id)
            .first()
        )
        if not alloc:
            logger.debug("[per_bot_vol] %s: no allocation found → 1.0", profile_name)
            return 1.0

        # Fetch last (BSC_LOOKBACK_DAYS + 10) daily PnL rows
        pnl_rows = (
            db.query(BotDailyPnL)
            .filter(BotDailyPnL.allocation_id == alloc.id)
            .order_by(BotDailyPnL.date.desc())
            .limit(BSC_LOOKBACK_DAYS + 10)
            .all()
        )

        if len(pnl_rows) < 30:
            logger.debug(
                "[per_bot_vol] %s: only %d daily PnL rows (need ≥30) → 1.0",
                profile_name, len(pnl_rows),
            )
            return 1.0

        # Reconstruct equity curve from cumulative pnl (realized + unrealized cents)
        # Rows are desc; reverse for chronological order
        pnl_rows_asc = list(reversed(pnl_rows))
        starting_capital = alloc.starting_capital_cents or 10_000_000

        equity_values: list[float] = [float(starting_capital)]
        for row in pnl_rows_asc:
            daily_net = (row.realized_cents or 0) + (row.unrealized_cents or 0)
            equity_values.append(equity_values[-1] + daily_net)

        # Compute daily returns from equity curve
        equity_arr = np.array(equity_values, dtype=float)
        # Avoid division by zero
        with np.errstate(divide="ignore", invalid="ignore"):
            daily_returns = np.where(
                equity_arr[:-1] > 0,
                np.diff(equity_arr) / equity_arr[:-1],
                0.0,
            )

        # Use only the last BSC_LOOKBACK_DAYS
        daily_returns = daily_returns[-BSC_LOOKBACK_DAYS:]

        realized_vol = compute_realized_vol(daily_returns, lookback=len(daily_returns))
        raw_mult = target_vol / realized_vol if realized_vol > 0.001 else BSC_MAX_MULTIPLIER
        multiplier = max(BSC_MIN_MULTIPLIER, min(BSC_MAX_MULTIPLIER, raw_mult))

        logger.info(
            "[per_bot_vol] %s: realized_vol_126d=%.2f%% target=%.2f%% multiplier=%.3f "
            "(rows=%d, alloc_id=%d)",
            profile_name,
            realized_vol * 100,
            target_vol * 100,
            multiplier,
            len(pnl_rows),
            alloc.id,
        )
        return multiplier

    except Exception as exc:
        logger.warning(
            "[per_bot_vol] %s: error computing multiplier (%s) → fallback 1.0",
            profile_name, exc,
        )
        return 1.0
