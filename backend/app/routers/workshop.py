from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.chart_analysis import ChartAnalysis
from app.dependencies import get_current_user, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workshop", tags=["workshop"])

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-5"


# ── Pydantic models ────────────────────────────────────────────────────────────

class AnalysisCreate(BaseModel):
    symbol: str
    timeframe: str
    name: str
    thesis: str = ""
    drawings: list = []


class AnalysisUpdate(BaseModel):
    name: Optional[str] = None
    thesis: Optional[str] = None
    drawings: Optional[list] = None


class AIAnalyzeRequest(BaseModel):
    symbol: str
    timeframe: str
    current_price: Optional[float] = None
    drawings: list = []
    indicators: list[str] = []
    thesis: str = ""


# ── CRUD endpoints ─────────────────────────────────────────────────────────────

@router.get("/analyses")
def list_analyses(
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(ChartAnalysis).filter_by(user_id=user.id)
    if symbol:
        q = q.filter(ChartAnalysis.symbol == symbol.upper())
    rows = q.order_by(ChartAnalysis.updated_at.desc()).all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "name": r.name,
            "thesis": r.thesis,
            "drawings": json.loads(r.drawings_json),
            "ai_analysis": json.loads(r.ai_analysis_json),
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/analyses")
def create_analysis(
    body: AnalysisCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = ChartAnalysis(
        user_id=user.id,
        symbol=body.symbol.upper(),
        timeframe=body.timeframe,
        name=body.name,
        thesis=body.thesis,
        drawings_json=json.dumps(body.drawings),
        ai_analysis_json="{}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "symbol": row.symbol, "timeframe": row.timeframe}


@router.put("/analyses/{analysis_id}")
def update_analysis(
    analysis_id: int,
    body: AnalysisUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.query(ChartAnalysis).filter_by(id=analysis_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if body.name is not None:
        row.name = body.name
    if body.thesis is not None:
        row.thesis = body.thesis
    if body.drawings is not None:
        row.drawings_json = json.dumps(body.drawings)
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.delete("/analyses/{analysis_id}")
def delete_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.query(ChartAnalysis).filter_by(id=analysis_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── AI Analyst ─────────────────────────────────────────────────────────────────

def _describe_drawings(drawings: list) -> str:
    if not drawings:
        return "No drawings on chart."
    lines = []
    for d in drawings:
        t = d.get("type", "unknown")
        if t == "hline":
            lines.append(f"- Horizontal line at ${d.get('price', '?'):.2f}")
        elif t == "trendline" and d.get("p1") and d.get("p2"):
            lines.append(
                f"- Trend line from ${d['p1']['price']:.2f} to ${d['p2']['price']:.2f}"
            )
        elif t == "rect" and d.get("p1") and d.get("p2"):
            lo = min(d["p1"]["price"], d["p2"]["price"])
            hi = max(d["p1"]["price"], d["p2"]["price"])
            lines.append(f"- Rectangle zone ${lo:.2f}–${hi:.2f}")
        elif t == "fib" and d.get("p1") and d.get("p2"):
            lines.append(
                f"- Fibonacci retracement ${d['p1']['price']:.2f}–${d['p2']['price']:.2f}"
            )
        elif t == "longpos" and d.get("p1") and d.get("p2") and d.get("p3"):
            lines.append(
                f"- Long position: entry ${d['p1']['price']:.2f}, stop ${d['p2']['price']:.2f}, target ${d['p3']['price']:.2f}"
            )
        elif t == "shortpos" and d.get("p1") and d.get("p2") and d.get("p3"):
            lines.append(
                f"- Short position: entry ${d['p1']['price']:.2f}, stop ${d['p2']['price']:.2f}, target ${d['p3']['price']:.2f}"
            )
        elif t == "channel" and d.get("p1") and d.get("p2"):
            lines.append(
                f"- Parallel channel from ${d['p1']['price']:.2f} to ${d['p2']['price']:.2f}"
            )
        elif t == "vline":
            lines.append("- Vertical line marking a time level")
        elif t in ("text", "arrow") and d.get("metadata", {}).get("label"):
            lines.append(f"- Annotation: \"{d['metadata']['label']}\"")
        else:
            lines.append(f"- {t} drawing")
    return "\n".join(lines)


def _build_prompt(req: AIAnalyzeRequest) -> str:
    drawing_desc = _describe_drawings(req.drawings)
    indicators_str = ", ".join(req.indicators) if req.indicators else "None"
    thesis = req.thesis.strip() or "No written thesis provided."

    return f"""You are an expert technical analyst reviewing a chart. Provide structured, objective analysis based ONLY on the technical evidence provided. Never give financial advice or say "you should buy/sell."

CHART CONTEXT:
- Asset: {req.symbol}
- Timeframe: {req.timeframe}
- Current Price: {"$" + str(req.current_price) if req.current_price else "Unknown"}
- Active Indicators: {indicators_str}

USER DRAWINGS ON CHART:
{drawing_desc}

USER'S WRITTEN THESIS:
{thesis}

Return your analysis in exactly this JSON structure — no markdown, no extra text, pure JSON:
{{
  "thesis_summary": "1-2 sentence interpretation of what the trader is setting up for",
  "supporting": ["evidence point 1", "evidence point 2", "evidence point 3"],
  "counterarguments": ["counter point 1", "counter point 2"],
  "invalidation": "Describe the specific price level or condition that invalidates the bullish/bearish thesis, and the approximate % distance",
  "suggested_additions": ["drawing or level to add 1", "drawing or level to add 2"],
  "setup_quality": "strong|moderate|weak",
  "setup_quality_reason": "One sentence explaining the rating"
}}"""


@router.post("/analyze")
async def analyze_chart(
    req: AIAnalyzeRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="AI analyst not configured")

    prompt = _build_prompt(req)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        resp.raise_for_status()
        data = resp.json()
        raw = data["content"][0]["text"].strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        analysis = json.loads(raw)
        return {"analysis": analysis}
    except json.JSONDecodeError as e:
        logger.warning(f"AI returned non-JSON: {e}")
        raise HTTPException(status_code=502, detail="AI returned unexpected format")
    except Exception as e:
        logger.error(f"Workshop AI analyst error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="AI analyst error")


@router.post("/analyses/{analysis_id}/analyze")
async def analyze_and_save(
    analysis_id: int,
    req: AIAnalyzeRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run AI analysis and cache the result on the named analysis."""
    result = await analyze_chart(req, user=user, db=db)
    row = db.query(ChartAnalysis).filter_by(id=analysis_id, user_id=user.id).first()
    if row:
        row.ai_analysis_json = json.dumps(result["analysis"])
        db.commit()
    return result
