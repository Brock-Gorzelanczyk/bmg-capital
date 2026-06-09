"""Deployment-target position sizer.

Activated via env var: ENABLE_DEPLOYMENT_TARGET_SIZING=true

Formula:
    per_trade_notional = (bot_capital * deployment_target_pct) / target_position_count

Hard caps (both must pass):
    max_position_pct       — no single trade exceeds this fraction of bot capital
    max_total_deployed_pct — do not open a new position if it would push total
                             deployed notional over this fraction of bot capital
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.db.models.bots import BotAllocation

logger = logging.getLogger(__name__)


def compute_per_trade_notional(
    alloc: "BotAllocation",
    profile: dict,
    db: "Session",
    capital_usd: float,
    profile_name: str = "",
) -> float:
    """Return dollar notional to deploy for the next trade, or 0.0 if capped."""
    risk_cfg = profile.get("risk", {})
    deployment_target_pct = float(risk_cfg.get("deployment_target_pct", 0.50))
    target_position_count = max(1, int(risk_cfg.get("target_position_count", 20)))
    max_position_pct = float(risk_cfg.get("max_position_pct", 0.05))
    max_total_deployed_pct = float(risk_cfg.get("max_total_deployed_pct", 0.80))

    target_notional = (capital_usd * deployment_target_pct) / target_position_count
    max_position_notional = capital_usd * max_position_pct
    capped_notional = min(target_notional, max_position_notional)

    current_deployed = _sum_open_notional(alloc.id, db)
    max_total = capital_usd * max_total_deployed_pct

    if current_deployed + capped_notional > max_total:
        logger.warning(
            "[sizing] %s deployment cap — deployed=%.0f + new=%.0f > max=%.0f, skipping",
            profile_name or alloc.id,
            current_deployed,
            capped_notional,
            max_total,
        )
        return 0.0

    logger.info(
        "[sizing] %s notional=%.2f (target=%.2f cap_per_pos=%.2f "
        "deployed=%.0f/%.0f)",
        profile_name or alloc.id,
        capped_notional,
        target_notional,
        max_position_notional,
        current_deployed,
        max_total,
    )
    return capped_notional


def get_risk_status(alloc: "BotAllocation", profile: dict, capital_usd: float, db: "Session") -> dict:
    """Return the risk-status payload for the /risk-status endpoint."""
    risk_cfg = profile.get("risk", {})
    deployment_target_pct = float(risk_cfg.get("deployment_target_pct", 0.50))
    target_position_count = max(1, int(risk_cfg.get("target_position_count", 20)))
    max_position_pct = float(risk_cfg.get("max_position_pct", 0.05))
    max_total_deployed_pct = float(risk_cfg.get("max_total_deployed_pct", 0.80))

    target_notional = (capital_usd * deployment_target_pct) / target_position_count
    max_position_notional = capital_usd * max_position_pct
    per_trade_target = min(target_notional, max_position_notional)

    current_deployed = _sum_open_notional(alloc.id, db)
    deployment_cap = capital_usd * max_total_deployed_pct
    open_count = _count_open_positions(alloc.id, db)

    would_size_to = per_trade_target if (current_deployed + per_trade_target <= deployment_cap) else 0.0

    return {
        "bot_id": profile.get("name", ""),
        "bot_capital": round(capital_usd, 2),
        "current_deployed": round(current_deployed, 2),
        "deployment_pct": round(current_deployed / capital_usd, 4) if capital_usd > 0 else 0.0,
        "open_positions": open_count,
        "per_trade_target": round(per_trade_target, 2),
        "next_trade_would_size_to": round(would_size_to, 2),
        "deployment_cap": round(deployment_cap, 2),
        "deployment_target_pct": deployment_target_pct,
        "max_total_deployed_pct": max_total_deployed_pct,
        "flag_enabled": True,
    }


def _sum_open_notional(allocation_id: int, db: "Session") -> float:
    from app.db.models.bots import BotPosition
    rows = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == allocation_id,
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .all()
    )
    return sum(
        abs(p.qty or 0) * ((p.avg_cost_cents or 0) / 100.0)
        for p in rows
    )


def _count_open_positions(allocation_id: int, db: "Session") -> int:
    from app.db.models.bots import BotPosition
    return (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == allocation_id,
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .count()
    )
