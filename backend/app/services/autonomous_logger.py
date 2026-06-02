from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.session import SessionLocal
from app.db.models.autonomous import AutonomousAction

logger = logging.getLogger(__name__)


def log_action(
    user_id: int,
    lab: str,
    action_type: str,
    rationale: str,
    asset: str = "",
    strategy_id: str = "",
    params: dict | None = None,
    result: str = "success",
    outcome_value: float | None = None,
) -> None:
    """Fire-and-forget action logger. Never raises — autonomous jobs must not fail due to logging."""
    try:
        db = SessionLocal()
        try:
            action = AutonomousAction(
                user_id=user_id,
                lab=lab,
                strategy_id=strategy_id or None,
                action_type=action_type,
                asset=asset or None,
                params=json.dumps(params or {}),
                rationale=rationale,
                result=result,
                outcome_value=outcome_value,
                created_at=datetime.now(timezone.utc),
            )
            db.add(action)
            db.commit()
            db.refresh(action)
            try:
                from app.ws.manager import connection_manager
                import asyncio
                action_dict = {
                    "id": action.id,
                    "lab": action.lab,
                    "action_type": action.action_type,
                    "asset": action.asset,
                    "rationale": action.rationale,
                    "created_at": action.created_at.isoformat(),
                }
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(connection_manager.broadcast_autonomous_action(action_dict))
            except Exception:
                pass  # WS broadcast is best-effort
        finally:
            db.close()
    except Exception as e:
        logger.error(f"autonomous_logger failed: {e}")


def get_recent_actions(user_id: int, limit: int = 50, lab: str | None = None) -> list[dict]:
    """Return recent actions for a user as dicts."""
    try:
        db = SessionLocal()
        try:
            q = db.query(AutonomousAction).filter(AutonomousAction.user_id == user_id)
            if lab:
                q = q.filter(AutonomousAction.lab == lab)
            actions = q.order_by(AutonomousAction.created_at.desc()).limit(limit).all()
            return [
                {
                    "id": a.id,
                    "lab": a.lab,
                    "strategy_id": a.strategy_id,
                    "action_type": a.action_type,
                    "asset": a.asset,
                    "params": json.loads(a.params) if a.params else {},
                    "rationale": a.rationale,
                    "result": a.result,
                    "outcome_value": a.outcome_value,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in actions
            ]
        finally:
            db.close()
    except Exception:
        return []
