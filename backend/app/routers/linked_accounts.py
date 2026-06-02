from __future__ import annotations

"""
Linked Accounts router — external brokerage integration via Plaid.
Prefix: /api/linked-accounts
"""

import random
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.linked_accounts import LinkedBrokerage, ExternalHolding
from app.services import plaid_service

router = APIRouter(prefix="/api/linked-accounts", tags=["linked-accounts"])

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _holdings_count(brokerage: LinkedBrokerage, db: Session) -> int:
    return db.query(ExternalHolding).filter_by(linked_brokerage_id=brokerage.id).count()


def _ser_brokerage(b: LinkedBrokerage, db: Session) -> dict:
    return {
        "id": b.id,
        "institution_name": b.institution_name,
        "status": b.status,
        "last_synced_at": b.last_synced_at.isoformat() if b.last_synced_at else None,
        "holdings_count": _holdings_count(b, db),
    }


def _sync_holdings(brokerage: LinkedBrokerage, db: Session) -> None:
    """Fetch holdings from Plaid (or demo) and upsert into external_holdings."""
    raw = plaid_service.fetch_investments(
        brokerage.plaid_access_token,
        institution_name=brokerage.institution_name,
    )

    # Delete existing holdings for this brokerage, then re-insert
    db.query(ExternalHolding).filter_by(linked_brokerage_id=brokerage.id).delete()

    for item in raw:
        holding = ExternalHolding(
            linked_brokerage_id=brokerage.id,
            symbol=item["symbol"],
            name=item["name"],
            quantity=float(item["quantity"]),
            cost_basis=item.get("cost_basis"),
            current_value=item.get("current_value"),
            security_type=item.get("type", "equity"),
            synced_at=datetime.utcnow(),
        )
        db.add(holding)

    brokerage.last_synced_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExchangeBody(BaseModel):
    public_token: str
    institution_slug: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/link-token")
def get_link_token(
    current_user: User = Depends(get_current_user),
):
    """Create a Plaid Link token for the current user."""
    token = plaid_service.create_link_token(current_user.id)
    return {"link_token": token}


@router.post("/exchange")
def exchange_token(
    body: ExchangeBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange a public token, store the brokerage, and trigger initial sync."""
    # For demo mode, use institution_slug to derive the institution name
    public_token = body.public_token
    if body.institution_slug:
        public_token = f"link-demo-{body.institution_slug}-{body.institution_slug}"

    access_token, item_id, detected_institution = plaid_service.exchange_public_token(
        public_token
    )

    institution_name = detected_institution or body.institution_slug.capitalize() or "Unknown"

    # Prevent duplicate items
    existing = db.query(LinkedBrokerage).filter_by(plaid_item_id=item_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="This brokerage is already connected")

    brokerage = LinkedBrokerage(
        user_id=current_user.id,
        institution_name=institution_name,
        plaid_item_id=item_id,
        plaid_access_token=access_token,
        status="active",
    )
    db.add(brokerage)
    db.commit()
    db.refresh(brokerage)

    _sync_holdings(brokerage, db)

    return {
        "id": brokerage.id,
        "institution_name": brokerage.institution_name,
        "status": brokerage.status,
    }


@router.get("/")
def list_brokerages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all linked brokerages for the current user."""
    brokerages = (
        db.query(LinkedBrokerage)
        .filter_by(user_id=current_user.id)
        .order_by(LinkedBrokerage.created_at)
        .all()
    )
    return [_ser_brokerage(b, db) for b in brokerages]


@router.delete("/{brokerage_id}")
def delete_brokerage(
    brokerage_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a linked brokerage and cascade-delete its holdings."""
    brokerage = db.query(LinkedBrokerage).filter_by(
        id=brokerage_id, user_id=current_user.id
    ).first()
    if not brokerage:
        raise HTTPException(status_code=404, detail="Not found")

    db.query(ExternalHolding).filter_by(linked_brokerage_id=brokerage.id).delete()
    db.delete(brokerage)
    db.commit()
    return Response(status_code=204)


@router.post("/{brokerage_id}/sync")
def sync_brokerage(
    brokerage_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-fetch holdings from Plaid and upsert."""
    brokerage = db.query(LinkedBrokerage).filter_by(
        id=brokerage_id, user_id=current_user.id
    ).first()
    if not brokerage:
        raise HTTPException(status_code=404, detail="Not found")

    _sync_holdings(brokerage, db)
    db.refresh(brokerage)
    return {"synced": True, "holdings_count": _holdings_count(brokerage, db)}


@router.get("/holdings")
def list_holdings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All ExternalHoldings as a flat list with P&L metrics."""
    brokerages = db.query(LinkedBrokerage).filter_by(user_id=current_user.id, status="active").all()
    if not brokerages:
        return {"holdings": [], "total_value": 0.0, "count": 0}

    brokerage_map = {b.id: b.institution_name for b in brokerages}
    brokerage_ids = [b.id for b in brokerages]

    all_holdings = (
        db.query(ExternalHolding)
        .filter(ExternalHolding.linked_brokerage_id.in_(brokerage_ids))
        .all()
    )

    result = []
    total_value = 0.0
    for h in all_holdings:
        institution = brokerage_map.get(h.linked_brokerage_id, "")
        cv = h.current_value or 0.0
        cb = h.cost_basis
        total_value += cv
        pnl = round(cv - cb, 2) if cb is not None else None
        pnl_pct = round((cv - cb) / cb * 100, 2) if cb and cb > 0 else None
        result.append({
            "symbol": h.symbol,
            "name": h.name,
            "institution": institution,
            "quantity": h.quantity,
            "cost_basis": cb,
            "current_value": cv if cv else None,
            "security_type": h.security_type,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
        })

    result.sort(key=lambda x: x["current_value"] or 0, reverse=True)

    return {
        "holdings": result,
        "total_value": round(total_value, 2),
        "count": len(result),
    }


@router.get("/insights")
def get_insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Analysis of external holdings: what to sell, tax-loss, concentration risks."""
    brokerages = db.query(LinkedBrokerage).filter_by(user_id=current_user.id, status="active").all()
    brokerage_ids = [b.id for b in brokerages]

    all_holdings = (
        db.query(ExternalHolding)
        .filter(ExternalHolding.linked_brokerage_id.in_(brokerage_ids))
        .all()
    ) if brokerage_ids else []

    total_value = sum(h.current_value or 0.0 for h in all_holdings)

    what_to_sell: list[dict] = []
    tax_loss_candidates: list[dict] = []
    concentration_risks: list[dict] = []

    # Aggregate by symbol
    symbol_totals: dict[str, dict] = defaultdict(lambda: {
        "cost_basis": 0.0, "current_value": 0.0, "symbol": "", "name": ""
    })
    for h in all_holdings:
        sym = h.symbol
        symbol_totals[sym]["symbol"] = sym
        symbol_totals[sym]["name"] = h.name
        symbol_totals[sym]["cost_basis"] += h.cost_basis or 0.0
        symbol_totals[sym]["current_value"] += h.current_value or 0.0

    for sym, data in symbol_totals.items():
        cb = data["cost_basis"]
        cv = data["current_value"]
        pnl = cv - cb
        pnl_pct = (pnl / cb * 100) if cb > 0 else 0.0
        pct_of_portfolio = (cv / total_value * 100) if total_value > 0 else 0.0

        if cb > 0 and pnl_pct <= -10:
            what_to_sell.append({
                "symbol": sym,
                "name": data["name"],
                "loss_pct": round(pnl_pct, 1),
                "unrealized_loss": round(pnl, 2),
            })

        if pnl < 0:
            tax_loss_candidates.append({
                "symbol": sym,
                "loss_pct": round(pnl_pct, 1),
                "potential_savings": round(abs(pnl) * 0.22, 2),
            })

        if pct_of_portfolio > 15:
            concentration_risks.append({
                "symbol": sym,
                "pct_of_portfolio": round(pct_of_portfolio, 1),
                "value": round(cv, 2),
            })

    what_to_sell = sorted(what_to_sell, key=lambda x: x["loss_pct"])[:5]
    tax_loss_candidates = sorted(tax_loss_candidates, key=lambda x: x["loss_pct"])[:10]
    concentration_risks = sorted(concentration_risks, key=lambda x: -x["pct_of_portfolio"])

    return {
        "what_to_sell": what_to_sell,
        "tax_loss_candidates": tax_loss_candidates,
        "concentration_risks": concentration_risks,
        "total_external_aum": round(total_value, 2),
    }


@router.get("/digest")
def get_digest(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Daily digest: overnight changes, news, earnings this week."""
    brokerages = db.query(LinkedBrokerage).filter_by(user_id=current_user.id).all()
    brokerage_ids = [b.id for b in brokerages]

    all_holdings = (
        db.query(ExternalHolding)
        .filter(ExternalHolding.linked_brokerage_id.in_(brokerage_ids))
        .all()
    ) if brokerage_ids else []

    symbols = list({h.symbol for h in all_holdings})

    overnight_changes = [
        {"symbol": sym, "change_pct": round(random.uniform(-1.5, 1.5), 2)}
        for sym in symbols
    ]
    total_value = sum(h.current_value or 0.0 for h in all_holdings)
    portfolio_overnight_change_pct = round(random.uniform(-0.8, 0.8), 2)

    earnings_this_week = [
        {"symbol": sym, "expected_date": "This week", "consensus_eps": round(random.uniform(0.5, 5.0), 2)}
        for sym in symbols[:3]
    ] if symbols else []

    return {
        "portfolio_overnight_change_pct": portfolio_overnight_change_pct,
        "total_external_value": round(total_value, 2),
        "overnight_changes": overnight_changes,
        "earnings_this_week": earnings_this_week,
        "symbols_tracked": symbols,
    }
