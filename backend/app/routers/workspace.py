from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.workspace import UserWorkspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceBody(BaseModel):
    name: str
    icon: Optional[str] = "📊"
    layout_json: Optional[str] = "[]"
    widgets_json: Optional[str] = "[]"
    is_default: Optional[bool] = False
    sort_order: Optional[int] = 0


def _serialize(w: UserWorkspace) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "icon": w.icon,
        "layout_json": w.layout_json,
        "widgets_json": w.widgets_json,
        "is_default": w.is_default,
        "sort_order": w.sort_order,
    }


@router.get("")
def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(UserWorkspace)
        .filter_by(user_id=current_user.id)
        .order_by(UserWorkspace.sort_order, UserWorkspace.id)
        .all()
    )
    return [_serialize(w) for w in rows]


@router.post("")
def create_workspace(
    body: WorkspaceBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.is_default:
        db.query(UserWorkspace).filter_by(user_id=current_user.id, is_default=True).update(
            {"is_default": False}
        )

    w = UserWorkspace(
        user_id=current_user.id,
        name=body.name,
        icon=body.icon or "📊",
        layout_json=body.layout_json or "[]",
        widgets_json=body.widgets_json or "[]",
        is_default=body.is_default or False,
        sort_order=body.sort_order or 0,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return _serialize(w)


@router.put("/{workspace_id}")
def update_workspace(
    workspace_id: int,
    body: WorkspaceBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    w = db.query(UserWorkspace).filter_by(id=workspace_id, user_id=current_user.id).first()
    if not w:
        raise HTTPException(404, "Workspace not found")

    if body.is_default:
        db.query(UserWorkspace).filter_by(user_id=current_user.id, is_default=True).update(
            {"is_default": False}
        )

    w.name = body.name
    if body.icon is not None:
        w.icon = body.icon
    if body.layout_json is not None:
        w.layout_json = body.layout_json
    if body.widgets_json is not None:
        w.widgets_json = body.widgets_json
    if body.is_default is not None:
        w.is_default = body.is_default
    if body.sort_order is not None:
        w.sort_order = body.sort_order
    w.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(w)
    return _serialize(w)


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    w = db.query(UserWorkspace).filter_by(id=workspace_id, user_id=current_user.id).first()
    if not w:
        raise HTTPException(404)
    db.delete(w)
    db.commit()
    return {"ok": True}
