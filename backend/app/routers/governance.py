from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.db.models.users import User

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/proposals")
async def get_proposals(
    state: str = Query("active", regex="^(active|pending|closed)$"),
    limit: int = Query(20, le=50),
    spaces: str = Query("", description="Comma-separated space IDs; empty = default list"),
    current_user: User = Depends(get_current_user),
):
    from app.services.governance import get_active_proposals, get_closed_proposals
    space_list = [s.strip() for s in spaces.split(",") if s.strip()] or None
    if state in ("active", "pending"):
        proposals = await get_active_proposals(spaces=space_list, limit=limit)
    else:
        proposals = await get_closed_proposals(spaces=space_list, limit=limit)
    return {"proposals": proposals}


@router.get("/proposals/{space_id}")
async def get_space_proposals(
    space_id: str,
    state: str = Query("active"),
    limit: int = Query(5, le=20),
    current_user: User = Depends(get_current_user),
):
    from app.services.governance import get_space_proposals
    proposals = await get_space_proposals(space_id, state=state, limit=limit)
    return {"proposals": proposals, "space_id": space_id}
