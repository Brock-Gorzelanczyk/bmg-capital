from __future__ import annotations

from datetime import timezone, date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.net_worth import NetWorthAccount, NetWorthSnapshot

router = APIRouter(prefix="/api/net-worth", tags=["net-worth"])

# ── serialisers ─────────────────────────────────────────────────────────────

def _ser_account(a: NetWorthAccount) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "account_type": a.account_type,
        "institution": a.institution,
        "balance": a.balance,
        "is_liability": a.is_liability,
        "currency": a.currency,
        "notes": a.notes,
        "last_updated": a.last_updated.isoformat() if a.last_updated else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _ser_snapshot(s: NetWorthSnapshot) -> dict:
    return {
        "id": s.id,
        "snapshot_date": str(s.snapshot_date),
        "total_assets": s.total_assets,
        "total_liabilities": s.total_liabilities,
        "net_worth": s.net_worth,
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def _compute_summary(accounts: list[NetWorthAccount]) -> dict:
    total_assets = sum(a.balance for a in accounts if not a.is_liability)
    total_liabilities = sum(a.balance for a in accounts if a.is_liability)
    net_worth = total_assets - total_liabilities

    by_category: dict[str, dict] = {}
    for a in accounts:
        cat = a.account_type
        if cat not in by_category:
            by_category[cat] = {"assets": 0.0, "liabilities": 0.0}
        if a.is_liability:
            by_category[cat]["liabilities"] += a.balance
        else:
            by_category[cat]["assets"] += a.balance

    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        "by_category": by_category,
    }


def _take_snapshot(user_id: int, db: Session) -> NetWorthSnapshot:
    """Upsert a snapshot for today with current account state."""
    accounts = db.query(NetWorthAccount).filter_by(user_id=user_id).all()
    summary = _compute_summary(accounts)
    today = date.today()

    existing = db.query(NetWorthSnapshot).filter_by(
        user_id=user_id, snapshot_date=today
    ).first()

    if existing:
        existing.total_assets = summary["total_assets"]
        existing.total_liabilities = summary["total_liabilities"]
        existing.net_worth = summary["net_worth"]
        db.commit()
        db.refresh(existing)
        return existing

    snap = NetWorthSnapshot(
        user_id=user_id,
        snapshot_date=today,
        total_assets=summary["total_assets"],
        total_liabilities=summary["total_liabilities"],
        net_worth=summary["net_worth"],
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


# ── schemas ──────────────────────────────────────────────────────────────────

class AccountBody(BaseModel):
    name: str
    account_type: str
    institution: Optional[str] = None
    balance: float = 0.0
    is_liability: bool = False
    currency: str = "USD"
    notes: Optional[str] = None


class AccountUpdateBody(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
    institution: Optional[str] = None
    balance: Optional[float] = None
    is_liability: Optional[bool] = None
    currency: Optional[str] = None
    notes: Optional[str] = None


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/accounts")
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = (
        db.query(NetWorthAccount)
        .filter_by(user_id=current_user.id)
        .order_by(NetWorthAccount.created_at)
        .all()
    )
    return {"accounts": [_ser_account(a) for a in accounts]}


@router.post("/accounts")
def create_account(
    body: AccountBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = NetWorthAccount(
        user_id=current_user.id,
        name=body.name,
        account_type=body.account_type,
        institution=body.institution,
        balance=body.balance,
        is_liability=body.is_liability,
        currency=body.currency,
        notes=body.notes,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    _take_snapshot(current_user.id, db)
    return _ser_account(account)


@router.put("/accounts/{account_id}")
def update_account(
    account_id: int,
    body: AccountUpdateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(NetWorthAccount).filter_by(
        id=account_id, user_id=current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(account, field, val)

    # Manually bump last_updated since SQLAlchemy onupdate only fires on flush
    account.last_updated = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)
    _take_snapshot(current_user.id, db)
    return _ser_account(account)


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(NetWorthAccount).filter_by(
        id=account_id, user_id=current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    db.delete(account)
    db.commit()
    _take_snapshot(current_user.id, db)
    return {"ok": True}


@router.get("/summary")
def get_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = db.query(NetWorthAccount).filter_by(user_id=current_user.id).all()
    summary = _compute_summary(accounts)

    # 30-day change: find the nearest snapshot at or before 30 days ago
    thirty_ago = date.today() - timedelta(days=30)
    old_snap = (
        db.query(NetWorthSnapshot)
        .filter(
            NetWorthSnapshot.user_id == current_user.id,
            NetWorthSnapshot.snapshot_date <= thirty_ago,
        )
        .order_by(desc(NetWorthSnapshot.snapshot_date))
        .first()
    )

    change_30d: Optional[float] = None
    if old_snap is not None:
        change_30d = round(summary["net_worth"] - old_snap.net_worth, 2)

    return {**summary, "change_30d": change_30d}


@router.post("/snapshot")
def take_snapshot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    snap = _take_snapshot(current_user.id, db)
    return _ser_snapshot(snap)


@router.get("/history")
def get_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cutoff = date.today() - timedelta(days=365)
    snaps = (
        db.query(NetWorthSnapshot)
        .filter(
            NetWorthSnapshot.user_id == current_user.id,
            NetWorthSnapshot.snapshot_date >= cutoff,
        )
        .order_by(NetWorthSnapshot.snapshot_date)
        .all()
    )
    return {"history": [_ser_snapshot(s) for s in snaps]}
