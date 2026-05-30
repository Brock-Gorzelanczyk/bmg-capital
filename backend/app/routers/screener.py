from __future__ import annotations

import json
import logging
from typing import Any, List, Union

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.screener.filters import PRESET_SCREENS
from app.screener.runner import run_screen

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/screener", tags=["screener"])


class FilterConfig(BaseModel):
    field: str
    operator: str = "eq"
    value: Any


class ScreenRequest(BaseModel):
    filters: List[FilterConfig]


# ── Natural-language filter chip ─────────────────────────────────────────────

class FilterChip(BaseModel):
    field: str
    operator: str
    value: Union[str, float, int]
    label: str


class NLParseRequest(BaseModel):
    query: str
    existing_filters: List[FilterChip] | None = None


class NLParseResponse(BaseModel):
    filters: List[FilterChip]
    explanation: str
    merge: bool = False


_NL_SYSTEM_BASE = """You are a stock screener assistant. Parse the user's natural language query into structured filter chips.

Available fields: rsi, price, volume, rel_volume, change_1d, change_5d, market_cap, pe_ratio, ma50_cross, ma200_cross, above_ma50, above_ma200, macd_positive, breakout_30d

Available operators: gt (greater than), lt (less than), gte, lte, eq, cross_above, cross_below, is_true

Return JSON only:
{
  "filters": [
    {"field": "rsi", "operator": "lt", "value": 35, "label": "RSI < 35"},
    ...
  ],
  "explanation": "Looking for oversold stocks..."
}

Keep it to 3-6 filters max. Return valid JSON only, no preamble."""

_NL_SYSTEM_FOLLOWUP = """You are a stock screener assistant helping the user refine an existing screen. The user already has active filters and is making a follow-up request.

Existing filters: {existing_filters_summary}

Parse their follow-up query and return ONLY the new/modified filters to MERGE with the existing ones. Do not re-return filters that are not being changed. Only include filters for fields that are new or being modified.

Available fields: rsi, price, volume, rel_volume, change_1d, change_5d, market_cap, pe_ratio, ma50_cross, ma200_cross, above_ma50, above_ma200, macd_positive, breakout_30d

Available operators: gt (greater than), lt (less than), gte, lte, eq, cross_above, cross_below, is_true

Return JSON only:
{{
  "filters": [
    {{"field": "market_cap", "operator": "gt", "value": 10000000000, "label": "Market Cap > 10B"}},
    ...
  ],
  "explanation": "Narrowing to large-cap stocks..."
}}

Return valid JSON only, no preamble."""


def _build_existing_filters_summary(existing_filters: List[FilterChip]) -> str:
    parts = []
    for f in existing_filters:
        op_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "eq": "=", "cross_above": "cross above", "cross_below": "cross below", "is_true": "is true"}
        op_str = op_map.get(f.operator, f.operator)
        parts.append(f"{f.field}{op_str}{f.value}")
    return ", ".join(parts)


@router.post("/parse-natural-language", response_model=NLParseResponse)
async def parse_natural_language(req: NLParseRequest):
    """Parse a natural language query into structured filter chips using Claude."""
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    is_followup = bool(req.existing_filters)

    if is_followup:
        summary = _build_existing_filters_summary(req.existing_filters)  # type: ignore[arg-type]
        system_prompt = _NL_SYSTEM_FOLLOWUP.format(existing_filters_summary=summary)
    else:
        system_prompt = _NL_SYSTEM_BASE

    hdrs = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers=hdrs,
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": req.query}],
                },
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {e}")

    raw_text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    )

    try:
        parsed = json.loads(raw_text)
        return NLParseResponse(
            filters=[FilterChip(**f) for f in parsed.get("filters", [])],
            explanation=parsed.get("explanation", ""),
            merge=is_followup,
        )
    except Exception as e:
        logger.warning(f"NL parse failed to decode JSON: {e} — raw: {raw_text[:300]}")
        raise HTTPException(status_code=422, detail="Could not parse Claude response as JSON")


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
