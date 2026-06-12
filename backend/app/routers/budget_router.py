"""
/api/budget — Daily API spend tracking and cap enforcement.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("/status")
def get_budget_status(db: Session = Depends(get_db)):
    from agents.budget import get_status
    return get_status(db)


@router.post("/reset")
def reset_budget_cap(db: Session = Depends(get_db)):
    """Clear today's cap-hit flag to resume LLM work."""
    from agents.budget import reset_cap, get_status
    reset_cap(db)
    return {"ok": True, "message": "Budget cap cleared. LLM features resumed for today.", "status": get_status(db)}


@router.post("/simulate-cap")
def simulate_cap_hit(db: Session = Depends(get_db)):
    """Debug: force cap_hit=true for testing. Revert with POST /api/budget/reset."""
    try:
        from agents.budget import _ensure_tables
        from sqlalchemy import text
        from datetime import date, datetime, timezone
        _ensure_tables(db)
        today = date.today().isoformat()
        now = datetime.now(timezone.utc).isoformat()
        db.execute(text("""
            INSERT INTO daily_budget_state (date, total_spent_usd, cap_hit, cap_hit_at, warn_sent)
            VALUES (:d, 3.00, true, :ts, true)
            ON CONFLICT (date) DO UPDATE SET
              total_spent_usd = 3.00, cap_hit = true, cap_hit_at = :ts, warn_sent = true
        """), {"d": today, "ts": now})
        db.commit()
        return {"ok": True, "message": "Cap-hit state forced. Use POST /api/budget/reset to clear."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
