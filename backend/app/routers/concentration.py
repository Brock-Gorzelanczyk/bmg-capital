"""
/api/admin/concentration — top fleet exposures by symbol.

Shows the highest single-name exposures across all bots and flags any
name that's already over the per-name cap (3% of fleet NAV). The cap
itself is enforced at signal-execution time in runner._execute_signal —
this endpoint is the observability view for what's already on the books.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/concentration")
def concentration(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Top N names by % of fleet NAV. Flags entries over the 3% cap."""
    from app.services.concentration import (
        top_concentrations,
        _fleet_nav_cents,
        PER_NAME_CAP,
    )
    fleet_nav = _fleet_nav_cents(db) or 0
    rows = top_concentrations(db, limit=limit)
    over_cap = [r for r in rows if r.get("exceeds_cap")]
    return {
        "fleet_nav_cents": fleet_nav,
        "per_name_cap_pct": PER_NAME_CAP * 100,
        "per_name_cap_cents": int(fleet_nav * PER_NAME_CAP),
        "top_concentrations": rows,
        "over_cap_count": len(over_cap),
        "over_cap": over_cap,
    }
