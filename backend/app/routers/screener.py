from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.screener.filters import PRESET_SCREENS
from app.screener.runner import run_screen

router = APIRouter(prefix="/api/screener", tags=["screener"])


class FilterConfig(BaseModel):
    field: str
    operator: str = "eq"
    value: Any


class ScreenRequest(BaseModel):
    filters: List[FilterConfig]


@router.post("/run")
async def run_screener(req: ScreenRequest):
    """Run a custom screener with the provided filter configs."""
    try:
        filter_dicts = [f.dict() for f in req.filters]
        results = await run_screen(filter_dicts)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/presets")
async def get_presets():
    """Return the list of available preset screen names."""
    return {"presets": list(PRESET_SCREENS.keys())}


@router.post("/presets/{name}")
async def run_preset(name: str):
    """Run one of the pre-built preset screens."""
    if name not in PRESET_SCREENS:
        raise HTTPException(status_code=404, detail="Preset not found")
    results = await run_screen(PRESET_SCREENS[name])
    return {"results": results, "count": len(results), "preset": name}
