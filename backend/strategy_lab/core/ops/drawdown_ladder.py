"""
Drawdown Ladder — Weekend 2, Module 1.  MILLENNIUM POD MODEL.

Three-tier drawdown discipline per bot:
  -5% from HWM  → cut allocation_multiplier to 0.5 (half-size)
  -7.5% from HWM → halt bot, require user review to resume
  -10% lifetime  → retire permanently, no appeal

Runs as daily cron (called after session close).
Writes allocation_multiplier back to BotAllocation.

Reference: Millennium Management pod rules (Navnoor Bawa, 2024).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class DrawdownState(Enum):
    NORMAL = "normal"
    HALF_SIZE = "half_size"        # -5% from HWM
    HALTED = "halted"              # -7.5% from HWM
    RETIRED = "retired"            # -10% lifetime


@dataclass
class BotDrawdownStatus:
    bot_id: int
    allocation_id: int
    current_equity_usd: float
    hwm_usd: float
    initial_capital_usd: float
    state: DrawdownState
    allocation_multiplier: float   # 1.0, 0.5, or 0.0
    dd_from_hwm_pct: float
    dd_from_initial_pct: float
    evaluated_at: datetime
    halt_reason: Optional[str] = None


TIER_HALF_SIZE = -5.0    # % from HWM
TIER_HALT = -7.5         # % from HWM
TIER_RETIRE = -10.0      # % from initial capital


def evaluate_bot(
    bot_id: int,
    allocation_id: int,
    current_equity_usd: float,
    hwm_usd: float,
    initial_capital_usd: float,
    current_state: DrawdownState = DrawdownState.NORMAL,
) -> BotDrawdownStatus:
    """
    Evaluate drawdown state for a single bot allocation.

    Parameters
    ----------
    bot_id : bot identifier
    allocation_id : BotAllocation.id from DB
    current_equity_usd : current mark-to-market equity
    hwm_usd : high-water mark equity
    initial_capital_usd : original funded capital
    current_state : existing state (HALTED/RETIRED cannot self-resolve)

    Returns
    -------
    BotDrawdownStatus with updated state + allocation_multiplier
    """
    # Never un-retire automatically
    if current_state == DrawdownState.RETIRED:
        return BotDrawdownStatus(
            bot_id=bot_id,
            allocation_id=allocation_id,
            current_equity_usd=current_equity_usd,
            hwm_usd=hwm_usd,
            initial_capital_usd=initial_capital_usd,
            state=DrawdownState.RETIRED,
            allocation_multiplier=0.0,
            dd_from_hwm_pct=_dd_pct(current_equity_usd, hwm_usd),
            dd_from_initial_pct=_dd_pct(current_equity_usd, initial_capital_usd),
            evaluated_at=datetime.now(timezone.utc),
            halt_reason="permanent retirement — -10% lifetime drawdown",
        )

    dd_from_hwm = _dd_pct(current_equity_usd, hwm_usd)
    dd_from_initial = _dd_pct(current_equity_usd, initial_capital_usd)

    # Tier 3: permanent retirement
    if dd_from_initial <= TIER_RETIRE:
        logger.critical(
            "[drawdown_ladder] bot_id=%d RETIRED — lifetime DD=%.2f%%",
            bot_id, dd_from_initial,
        )
        return BotDrawdownStatus(
            bot_id=bot_id,
            allocation_id=allocation_id,
            current_equity_usd=current_equity_usd,
            hwm_usd=hwm_usd,
            initial_capital_usd=initial_capital_usd,
            state=DrawdownState.RETIRED,
            allocation_multiplier=0.0,
            dd_from_hwm_pct=dd_from_hwm,
            dd_from_initial_pct=dd_from_initial,
            evaluated_at=datetime.now(timezone.utc),
            halt_reason=f"lifetime drawdown {dd_from_initial:.2f}% breached -10% threshold",
        )

    # Tier 2: halt (sticky — only manual review can lift)
    if dd_from_hwm <= TIER_HALT or current_state == DrawdownState.HALTED:
        reason = (
            f"drawdown from HWM {dd_from_hwm:.2f}% breached -7.5% threshold"
            if dd_from_hwm <= TIER_HALT
            else "still in halt state (manual review required)"
        )
        if current_state != DrawdownState.HALTED:
            logger.error(
                "[drawdown_ladder] bot_id=%d HALTED — DD from HWM=%.2f%%",
                bot_id, dd_from_hwm,
            )
        return BotDrawdownStatus(
            bot_id=bot_id,
            allocation_id=allocation_id,
            current_equity_usd=current_equity_usd,
            hwm_usd=hwm_usd,
            initial_capital_usd=initial_capital_usd,
            state=DrawdownState.HALTED,
            allocation_multiplier=0.0,
            dd_from_hwm_pct=dd_from_hwm,
            dd_from_initial_pct=dd_from_initial,
            evaluated_at=datetime.now(timezone.utc),
            halt_reason=reason,
        )

    # Tier 1: half-size
    if dd_from_hwm <= TIER_HALF_SIZE:
        logger.warning(
            "[drawdown_ladder] bot_id=%d HALF-SIZE — DD from HWM=%.2f%%",
            bot_id, dd_from_hwm,
        )
        return BotDrawdownStatus(
            bot_id=bot_id,
            allocation_id=allocation_id,
            current_equity_usd=current_equity_usd,
            hwm_usd=hwm_usd,
            initial_capital_usd=initial_capital_usd,
            state=DrawdownState.HALF_SIZE,
            allocation_multiplier=0.5,
            dd_from_hwm_pct=dd_from_hwm,
            dd_from_initial_pct=dd_from_initial,
            evaluated_at=datetime.now(timezone.utc),
        )

    # Normal — update HWM if new high
    new_hwm = max(hwm_usd, current_equity_usd)
    return BotDrawdownStatus(
        bot_id=bot_id,
        allocation_id=allocation_id,
        current_equity_usd=current_equity_usd,
        hwm_usd=new_hwm,
        initial_capital_usd=initial_capital_usd,
        state=DrawdownState.NORMAL,
        allocation_multiplier=1.0,
        dd_from_hwm_pct=dd_from_hwm,
        dd_from_initial_pct=dd_from_initial,
        evaluated_at=datetime.now(timezone.utc),
    )


def evaluate_all_bots(bot_data: list[dict]) -> list[BotDrawdownStatus]:
    """
    Evaluate drawdown state for a list of bots.

    Parameters
    ----------
    bot_data : list of dicts with keys:
        bot_id, allocation_id, current_equity_usd, hwm_usd,
        initial_capital_usd, current_state (optional str)

    Returns
    -------
    list of BotDrawdownStatus, one per bot
    """
    results = []
    for bd in bot_data:
        state_str = bd.get("current_state", "normal")
        try:
            current_state = DrawdownState(state_str)
        except ValueError:
            current_state = DrawdownState.NORMAL

        status = evaluate_bot(
            bot_id=bd["bot_id"],
            allocation_id=bd["allocation_id"],
            current_equity_usd=float(bd["current_equity_usd"]),
            hwm_usd=float(bd["hwm_usd"]),
            initial_capital_usd=float(bd["initial_capital_usd"]),
            current_state=current_state,
        )
        results.append(status)
    return results


def _dd_pct(current: float, reference: float) -> float:
    """Compute drawdown percentage (negative = drawdown)."""
    if reference <= 0:
        return 0.0
    return round(((current - reference) / reference) * 100, 4)
