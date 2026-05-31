from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.estate import BeneficiaryRecord, DigitalAssetRecord

router = APIRouter(prefix="/api/estate", tags=["estate"])

# ── serialisers ──────────────────────────────────────────────────────────────

def _ser_beneficiary(r: BeneficiaryRecord) -> dict:
    return {
        "id": r.id,
        "account_name": r.account_name,
        "account_type": r.account_type,
        "beneficiary_name": r.beneficiary_name,
        "beneficiary_relationship": r.beneficiary_relationship,
        "beneficiary_pct": r.beneficiary_pct,
        "has_tod": r.has_tod,
        "has_pod": r.has_pod,
        "last_reviewed": r.last_reviewed,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _ser_digital_asset(r: DigitalAssetRecord) -> dict:
    return {
        "id": r.id,
        "asset_type": r.asset_type,
        "description": r.description,
        "location_hint": r.location_hint,
        "recovery_contact": r.recovery_contact,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# ── schemas ───────────────────────────────────────────────────────────────────

class BeneficiaryBody(BaseModel):
    account_name: str
    account_type: Optional[str] = None
    beneficiary_name: Optional[str] = None
    beneficiary_relationship: Optional[str] = None
    beneficiary_pct: int = 100
    has_tod: bool = False
    has_pod: bool = False
    last_reviewed: Optional[str] = None
    notes: Optional[str] = None


class BeneficiaryUpdateBody(BaseModel):
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    beneficiary_name: Optional[str] = None
    beneficiary_relationship: Optional[str] = None
    beneficiary_pct: Optional[int] = None
    has_tod: Optional[bool] = None
    has_pod: Optional[bool] = None
    last_reviewed: Optional[str] = None
    notes: Optional[str] = None


class DigitalAssetBody(BaseModel):
    asset_type: Optional[str] = None
    description: Optional[str] = None
    location_hint: Optional[str] = None
    recovery_contact: Optional[str] = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_stale(last_reviewed: Optional[str]) -> bool:
    """Return True if last_reviewed is missing or more than 2 years ago."""
    if not last_reviewed:
        return True
    try:
        reviewed = date.fromisoformat(last_reviewed)
        delta = (date.today() - reviewed).days
        return delta > 730  # 2 years
    except ValueError:
        return True


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/beneficiaries")
def list_beneficiaries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = (
        db.query(BeneficiaryRecord)
        .filter_by(user_id=current_user.id)
        .order_by(BeneficiaryRecord.created_at)
        .all()
    )
    return {"beneficiaries": [_ser_beneficiary(r) for r in records]}


@router.post("/beneficiaries")
def create_beneficiary(
    body: BeneficiaryBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = BeneficiaryRecord(
        user_id=current_user.id,
        **body.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _ser_beneficiary(record)


@router.put("/beneficiaries/{record_id}")
def update_beneficiary(
    record_id: int,
    body: BeneficiaryUpdateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(BeneficiaryRecord).filter_by(
        id=record_id, user_id=current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(record, field, val)

    db.commit()
    db.refresh(record)
    return _ser_beneficiary(record)


@router.delete("/beneficiaries/{record_id}")
def delete_beneficiary(
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(BeneficiaryRecord).filter_by(
        id=record_id, user_id=current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    db.delete(record)
    db.commit()
    return {"ok": True}


@router.get("/health-check")
def estate_health_check(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a list of estate planning issues for the current user."""
    beneficiaries = (
        db.query(BeneficiaryRecord).filter_by(user_id=current_user.id).all()
    )
    digital_assets = (
        db.query(DigitalAssetRecord).filter_by(user_id=current_user.id).all()
    )

    issues: list[str] = []

    # Group by account to check pct totals
    accounts: dict[str, list[BeneficiaryRecord]] = {}
    for r in beneficiaries:
        accounts.setdefault(r.account_name, []).append(r)

    for acct_name, records in accounts.items():
        total_pct = sum(r.beneficiary_pct for r in records)
        if total_pct != 100:
            issues.append(
                f'"{acct_name}": beneficiary percentages sum to {total_pct}% (should be 100%)'
            )

        for r in records:
            if not r.has_tod and not r.has_pod:
                issues.append(
                    f'"{acct_name}": missing TOD/POD designation'
                )
            if _is_stale(r.last_reviewed):
                reviewed_str = r.last_reviewed or "never"
                issues.append(
                    f'"{acct_name}": beneficiary not reviewed in 2+ years (last reviewed: {reviewed_str})'
                )

    if not beneficiaries:
        issues.append("No beneficiary records found — add at least one account")

    if not digital_assets:
        issues.append("No digital assets documented — consider adding crypto, password managers, and email accounts")

    return {"issues": issues}


@router.get("/digital-assets")
def list_digital_assets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = (
        db.query(DigitalAssetRecord)
        .filter_by(user_id=current_user.id)
        .order_by(DigitalAssetRecord.created_at)
        .all()
    )
    return {"digital_assets": [_ser_digital_asset(r) for r in records]}


@router.post("/digital-assets")
def create_digital_asset(
    body: DigitalAssetBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = DigitalAssetRecord(
        user_id=current_user.id,
        **body.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _ser_digital_asset(record)


@router.delete("/digital-assets/{record_id}")
def delete_digital_asset(
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(DigitalAssetRecord).filter_by(
        id=record_id, user_id=current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    db.delete(record)
    db.commit()
    return {"ok": True}
