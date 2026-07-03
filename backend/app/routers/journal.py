from __future__ import annotations

from datetime import timezone, datetime, date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, require_admin
from app.db.models.users import User
from app.db.models.journal import JournalEntry
from app.core.tz import iso_utc

router = APIRouter(prefix="/api/journal", tags=["journal"])


def _ser(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "paper_order_id": e.paper_order_id,
        "symbol": e.symbol,
        "trade_date": str(e.trade_date),
        "side": e.side,
        "qty": e.qty,
        "entry_price": e.entry_price,
        "exit_price": e.exit_price,
        "pnl": e.pnl,
        "setup": e.setup,
        "mood": e.mood,
        "confidence": e.confidence,
        "notes": e.notes,
        "lessons": e.lessons,
        "rating": e.rating,
        "entry_type": getattr(e, "entry_type", None),
        "created_at": iso_utc(e.created_at),
    }


@router.get("")
def list_entries(
    limit: int = 50,
    symbol: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(JournalEntry).filter_by(user_id=current_user.id)
    if symbol:
        q = q.filter(JournalEntry.symbol == symbol.upper())
    rows = q.order_by(desc(JournalEntry.trade_date), desc(JournalEntry.created_at)).limit(limit).all()
    return [_ser(e) for e in rows]


@router.get("/stats")
def journal_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entries = db.query(JournalEntry).filter_by(user_id=current_user.id).all()
    total = len(entries)
    with_notes = sum(1 for e in entries if e.notes)
    pnls = [e.pnl for e in entries if e.pnl is not None]
    wins = sum(1 for p in pnls if p > 0)
    avg_mood = round(sum(e.mood for e in entries if e.mood) / max(1, sum(1 for e in entries if e.mood)), 1)
    return {
        "total_entries": total,
        "entries_with_notes": with_notes,
        "total_pnl": round(sum(pnls), 2),
        "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
        "avg_mood": avg_mood,
    }


class EntryBody(BaseModel):
    symbol: str
    trade_date: str
    side: str
    qty: float = 0
    entry_price: float = 0
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    paper_order_id: Optional[int] = None
    setup: Optional[str] = None
    mood: Optional[int] = None
    confidence: Optional[int] = None
    notes: Optional[str] = None
    lessons: Optional[str] = None
    rating: Optional[int] = None


@router.post("")
def create_entry(
    body: EntryBody,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import date
    entry = JournalEntry(
        user_id=current_user.id,
        symbol=body.symbol.upper(),
        trade_date=date.fromisoformat(body.trade_date),
        side=body.side,
        qty=body.qty,
        entry_price=body.entry_price,
        exit_price=body.exit_price,
        pnl=body.pnl,
        paper_order_id=body.paper_order_id,
        setup=body.setup,
        mood=body.mood,
        confidence=body.confidence,
        notes=body.notes,
        lessons=body.lessons,
        rating=body.rating,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _ser(entry)


# ── Pre-Mortem endpoints ──────────────────────────────────────────────────────

class PreMortemCreate(BaseModel):
    symbol: str
    direction: str          # "long" or "short"
    thesis: str             # user's pre-mortem text (failure scenario)
    position_size: Optional[float] = None
    entry_price: Optional[float] = None


@router.post("/pre-mortem")
def create_pre_mortem(
    body: PreMortemCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Save a pre-mortem entry before placing a trade."""
    entry = JournalEntry(
        user_id=current_user.id,
        symbol=body.symbol.upper(),
        trade_date=date_type.today(),
        side=body.direction,
        qty=body.position_size or 0,
        entry_price=body.entry_price or 0,
        notes=body.thesis,
        setup="pre_mortem",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": entry.id, **_ser(entry)}


@router.get("/pre-mortems")
def list_pre_mortems(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all pre-mortem entries with their setup='pre_mortem' marker."""
    rows = (
        db.query(JournalEntry)
        .filter_by(user_id=current_user.id, setup="pre_mortem")
        .order_by(desc(JournalEntry.created_at))
        .all()
    )
    return [_ser(e) for e in rows]


@router.patch("/{entry_id}")
def update_entry(
    entry_id: int,
    body: EntryBody,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = db.query(JournalEntry).filter_by(id=entry_id, user_id=current_user.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, val)
    entry.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _ser(entry)


@router.delete("/{entry_id}")
def delete_entry(
    entry_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = db.query(JournalEntry).filter_by(id=entry_id, user_id=current_user.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}
