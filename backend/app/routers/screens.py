from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.screen import SavedScreen

router = APIRouter(prefix="/api/screens", tags=["screens"])


class SaveScreenRequest(BaseModel):
    name: str
    filters: list


@router.get("")
def list_screens(db: Session = Depends(get_db), user=Depends(get_current_user)):
    screens = (
        db.query(SavedScreen)
        .filter((SavedScreen.user_id == user.id) | (SavedScreen.user_id.is_(None)))
        .order_by(SavedScreen.created_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "filters": json.loads(s.filters_json),
            "created_at": s.created_at.isoformat(),
        }
        for s in screens
    ]


@router.post("")
def save_screen(req: SaveScreenRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    screen = SavedScreen(
        name=req.name.strip(),
        filters_json=json.dumps(req.filters),
        user_id=user.id,
    )
    db.add(screen)
    db.commit()
    db.refresh(screen)
    return {
        "id": screen.id,
        "name": screen.name,
        "filters": req.filters,
        "created_at": screen.created_at.isoformat(),
    }


@router.delete("/{screen_id}")
def delete_screen(screen_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    screen = db.query(SavedScreen).filter_by(id=screen_id, user_id=user.id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    db.delete(screen)
    db.commit()
    return {"status": "deleted"}
