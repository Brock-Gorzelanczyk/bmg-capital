"""Chart layout save/load for TradingView Advanced Charts save_load_adapter."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal
from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users/me/chart-layouts", tags=["chart-layouts"])


class ChartLayout(Base):
    __tablename__ = "chart_layouts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False, default="My Chart")
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class SaveLayoutRequest(BaseModel):
    name: Optional[str] = "My Chart"
    content: Optional[Any] = None


@router.get("")
async def list_chart_layouts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(ChartLayout).filter(
        ChartLayout.user_id == current_user.id
    ).order_by(ChartLayout.updated_at.desc()).all()
    return {
        "charts": [
            {"id": r.id, "name": r.name, "timestamp": int(r.updated_at.timestamp() * 1000)}
            for r in rows
        ]
    }


@router.post("")
async def save_chart_layout(
    body: SaveLayoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json
    content_str = json.dumps(body.content) if body.content is not None else None
    layout = ChartLayout(
        user_id=current_user.id,
        name=body.name or "My Chart",
        content=content_str,
    )
    db.add(layout)
    db.commit()
    db.refresh(layout)
    return {"id": layout.id}


@router.get("/{layout_id}")
async def get_chart_layout(
    layout_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ChartLayout).filter(
        ChartLayout.id == layout_id,
        ChartLayout.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Layout not found")
    import json
    content = json.loads(row.content) if row.content else {}
    return {"id": row.id, "name": row.name, "content": content}


@router.delete("/{layout_id}")
async def delete_chart_layout(
    layout_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ChartLayout).filter(
        ChartLayout.id == layout_id,
        ChartLayout.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Layout not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
