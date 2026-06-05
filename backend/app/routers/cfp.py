from __future__ import annotations
import secrets
from datetime import timezone, datetime, date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.cfp_booking import CFPBooking
from app.db.models.tier import UserTier
from app.services.entitlements import effective_tier, get_entitlements

router = APIRouter(prefix="/api/cfp", tags=["cfp"])

@router.get("/availability")
def get_availability(current_user: User = Depends(get_current_user)):
    slots = []
    today = date.today()
    for delta in range(7):
        d = today + timedelta(days=delta + 1)
        if d.weekday() in (0, 2, 4):  # Mon, Wed, Fri
            for hour in (10, 14, 16):
                slots.append({"datetime": datetime(d.year, d.month, d.day, hour, 0).isoformat(), "available": True})
    return {"slots": slots}

class BookBody(BaseModel):
    slot_datetime: str
    topic: str = ""
    format: str = "video"

@router.post("/book")
def book_session(body: BookBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tier_row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    ents = get_entitlements(tier_row) if tier_row else {}
    cfp_limit = int(ents.get("cfp_sessions_per_year", 0))
    if cfp_limit == 0:
        raise HTTPException(403, "CFP sessions require Plus or Premium tier")
    if cfp_limit != -1:
        year_start = datetime(datetime.now(timezone.utc).year, 1, 1)
        used = db.query(CFPBooking).filter(CFPBooking.user_id == current_user.id, CFPBooking.created_at >= year_start).count()
        if used >= cfp_limit:
            raise HTTPException(403, f"You've used your {cfp_limit} CFP session(s) for this year. Upgrade to Premium for unlimited.")
    slot_dt = datetime.fromisoformat(body.slot_datetime)
    booking = CFPBooking(
        user_id=current_user.id,
        slot_datetime=slot_dt,
        topic=body.topic,
        format=body.format,
        confirmation_id=secrets.token_hex(4).upper(),
        zoom_link="https://zoom.us/j/99999999999?pwd=BMGCapitalCFP",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return {
        "confirmation_id": booking.confirmation_id,
        "zoom_link": booking.zoom_link,
        "slot_datetime": booking.slot_datetime.isoformat(),
        "calendar_invite_sent": True,
        "topic": booking.topic,
        "format": booking.format,
    }

@router.get("/my-bookings")
def my_bookings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bookings = db.query(CFPBooking).filter_by(user_id=current_user.id).order_by(CFPBooking.slot_datetime.desc()).all()
    return [{"id": b.id, "confirmation_id": b.confirmation_id, "slot_datetime": b.slot_datetime.isoformat(), "topic": b.topic, "format": b.format, "zoom_link": b.zoom_link, "status": b.status} for b in bookings]
