from __future__ import annotations

import json
import logging
from datetime import timezone, datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.workspace import UserWorkspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# ── AI workspace generation ────────────────────────────────────────────────────

class GenerateWorkspaceRequest(BaseModel):
    prompt: str
    lab_id: str  # "strategy" | "options" | "crypto" | "ta-workshop"

class GeneratedWidget(BaseModel):
    type: str
    title: str
    grid_x: int
    grid_y: int
    w: int
    h: int
    config: dict = {}

class GenerateWorkspaceResponse(BaseModel):
    workspace_name: str
    reasoning: str
    widgets: List[GeneratedWidget]


_SYSTEM_PROMPT = """You are a workspace composer for BMG Capital, a trading platform.
Build a workspace layout for the {lab_id} lab.
Respond ONLY with valid JSON matching this schema exactly:
{{
  "workspace_name": "string (3-5 words, descriptive)",
  "reasoning": "string (1 sentence explaining the layout choice)",
  "widgets": [
    {{"type": "string", "title": "string", "grid_x": int, "grid_y": int, "w": int, "h": int, "config": {{}}}}
  ]
}}
Available widget types for strategy lab: ["position-blotter", "equity-curve", "pnl-calendar", "watchlist", "daily-recap"]
Available widget types for options lab: ["position-blotter", "watchlist", "equity-curve", "daily-recap", "pnl-calendar"]
Available widget types for crypto lab: ["watchlist", "equity-curve", "position-blotter", "pnl-calendar", "daily-recap"]
Available widget types for ta-workshop lab: ["equity-curve", "watchlist", "position-blotter", "daily-recap", "pnl-calendar"]
Grid is 12 columns wide, 8 rows tall. Include 4-6 widgets. Chart widgets are typically w:6 h:4. Narrow widgets w:3 h:4."""

_DEFAULTS: dict[str, dict] = {
    "strategy": {
        "workspace_name": "Strategy Overview",
        "reasoning": "Balanced layout showing performance curve, open positions, watchlist, P&L history, and daily AI brief.",
        "widgets": [
            {"type": "equity-curve", "title": "Equity Curve", "grid_x": 0, "grid_y": 0, "w": 6, "h": 4, "config": {}},
            {"type": "position-blotter", "title": "Positions", "grid_x": 6, "grid_y": 0, "w": 6, "h": 4, "config": {}},
            {"type": "watchlist", "title": "Watchlist", "grid_x": 0, "grid_y": 4, "w": 4, "h": 4, "config": {}},
            {"type": "pnl-calendar", "title": "P&L Calendar", "grid_x": 4, "grid_y": 4, "w": 4, "h": 4, "config": {}},
            {"type": "daily-recap", "title": "AI Brief", "grid_x": 8, "grid_y": 4, "w": 4, "h": 4, "config": {}},
        ],
    },
    "options": {
        "workspace_name": "Options Flow Desk",
        "reasoning": "Options-focused layout with positions, watchlist, performance tracking, and AI recap.",
        "widgets": [
            {"type": "position-blotter", "title": "Options Positions", "grid_x": 0, "grid_y": 0, "w": 6, "h": 4, "config": {}},
            {"type": "watchlist", "title": "Watchlist", "grid_x": 6, "grid_y": 0, "w": 6, "h": 4, "config": {}},
            {"type": "equity-curve", "title": "Equity Curve", "grid_x": 0, "grid_y": 4, "w": 4, "h": 4, "config": {}},
            {"type": "daily-recap", "title": "AI Brief", "grid_x": 4, "grid_y": 4, "w": 4, "h": 4, "config": {}},
            {"type": "pnl-calendar", "title": "P&L Calendar", "grid_x": 8, "grid_y": 4, "w": 4, "h": 4, "config": {}},
        ],
    },
    "crypto": {
        "workspace_name": "Crypto Market Watch",
        "reasoning": "Crypto-optimized view with live watchlist front and center, backed by portfolio tracking.",
        "widgets": [
            {"type": "watchlist", "title": "Crypto Watchlist", "grid_x": 0, "grid_y": 0, "w": 6, "h": 4, "config": {}},
            {"type": "equity-curve", "title": "Portfolio Curve", "grid_x": 6, "grid_y": 0, "w": 6, "h": 4, "config": {}},
            {"type": "position-blotter", "title": "Positions", "grid_x": 0, "grid_y": 4, "w": 4, "h": 4, "config": {}},
            {"type": "pnl-calendar", "title": "P&L Calendar", "grid_x": 4, "grid_y": 4, "w": 4, "h": 4, "config": {}},
            {"type": "daily-recap", "title": "AI Brief", "grid_x": 8, "grid_y": 4, "w": 4, "h": 4, "config": {}},
        ],
    },
    "ta-workshop": {
        "workspace_name": "Technical Analysis Suite",
        "reasoning": "TA-focused layout emphasizing chart performance, watchlist for scanning, and position tracking.",
        "widgets": [
            {"type": "equity-curve", "title": "Equity Curve", "grid_x": 0, "grid_y": 0, "w": 8, "h": 4, "config": {}},
            {"type": "watchlist", "title": "Scan List", "grid_x": 8, "grid_y": 0, "w": 4, "h": 4, "config": {}},
            {"type": "position-blotter", "title": "Positions", "grid_x": 0, "grid_y": 4, "w": 6, "h": 4, "config": {}},
            {"type": "daily-recap", "title": "AI Brief", "grid_x": 6, "grid_y": 4, "w": 3, "h": 4, "config": {}},
            {"type": "pnl-calendar", "title": "P&L Calendar", "grid_x": 9, "grid_y": 4, "w": 3, "h": 4, "config": {}},
        ],
    },
}


def _get_default(lab_id: str) -> GenerateWorkspaceResponse:
    d = _DEFAULTS.get(lab_id, _DEFAULTS["strategy"])
    return GenerateWorkspaceResponse(
        workspace_name=d["workspace_name"],
        reasoning=d["reasoning"],
        widgets=[GeneratedWidget(**w) for w in d["widgets"]],
    )


@router.post("/generate", response_model=GenerateWorkspaceResponse)
async def generate_workspace(
    body: GenerateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
):
    if not settings.anthropic_api_key:
        return _get_default(body.lab_id)

    system = _SYSTEM_PROMPT.format(lab_id=body.lab_id)
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": f"Build a workspace for: {body.prompt}"}],
    }
    hdrs = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=hdrs)
            r.raise_for_status()
            data = r.json()
            raw_text = data["content"][0]["text"]
            # Strip possible markdown code fences
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            parsed = json.loads(raw_text)
            return GenerateWorkspaceResponse(
                workspace_name=parsed["workspace_name"],
                reasoning=parsed["reasoning"],
                widgets=[GeneratedWidget(**w) for w in parsed["widgets"]],
            )
    except Exception as exc:
        logger.warning("Workspace generation failed, returning default: %s", exc)
        return _get_default(body.lab_id)


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
    w.updated_at = datetime.now(timezone.utc)
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
