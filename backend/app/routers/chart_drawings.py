from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.chart_drawings import ChartDrawing

router = APIRouter(prefix="/api/chart-drawings", tags=["chart-drawings"])

class DrawingsBody(BaseModel):
    symbol: str
    timeframe: str
    drawings: list  # JSON array of drawing objects

@router.get("")
def get_drawings(symbol: str, timeframe: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(ChartDrawing).filter_by(user_id=user.id, symbol=symbol.upper(), timeframe=timeframe).first()
    if not row:
        return {"drawings": []}
    import json
    return {"drawings": json.loads(row.drawings_json)}

@router.put("")
def save_drawings(body: DrawingsBody, db: Session = Depends(get_db), user=Depends(get_current_user)):
    import json
    row = db.query(ChartDrawing).filter_by(user_id=user.id, symbol=body.symbol.upper(), timeframe=body.timeframe).first()
    if row:
        row.drawings_json = json.dumps(body.drawings)
    else:
        row = ChartDrawing(user_id=user.id, symbol=body.symbol.upper(), timeframe=body.timeframe, drawings_json=json.dumps(body.drawings))
        db.add(row)
    db.commit()
    return {"ok": True}
