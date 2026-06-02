from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.session import SessionLocal
from app.db.models.autopilot import AutopilotAction

logger = logging.getLogger(__name__)


def log_autopilot_action(
    user_id: int,
    category: str,
    action_type: str,
    params: dict,
    ai_rationale: str = "",
    result: str = "success",
    outcome_value: Optional[float] = None,
    asset: Optional[str] = None,
) -> None:
    """Fire-and-forget. Never raises. Appends one row to autopilot_actions."""
    try:
        db = SessionLocal()
        try:
            action = AutopilotAction(
                user_id=user_id,
                category=category,
                action_type=action_type,
                asset=asset or None,
                params=params or {},
                ai_rationale=ai_rationale,
                result=result,
                outcome_value=outcome_value,
                created_at=datetime.now(timezone.utc),
            )
            db.add(action)
            db.commit()
            db.refresh(action)

            # Best-effort WebSocket broadcast
            try:
                from app.ws.manager import connection_manager
                import asyncio

                action_dict = {
                    "id": action.id,
                    "category": action.category,
                    "action_type": action.action_type,
                    "asset": action.asset,
                    "ai_rationale": action.ai_rationale,
                    "result": action.result,
                    "created_at": action.created_at.isoformat(),
                }
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        connection_manager.broadcast_autonomous_action(action_dict)
                    )
            except Exception:
                pass  # WS broadcast is best-effort
        finally:
            db.close()
    except Exception as e:
        logger.error(f"autopilot_logger failed: {e}")
