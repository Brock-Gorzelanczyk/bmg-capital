from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.tier import UserTier
from app.services.entitlements import ENTITLEMENTS, PRICING, get_entitlements, effective_tier

router = APIRouter(prefix="/api/tiers", tags=["tiers"])


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_or_create_tier(db: Session, user_id: int) -> UserTier:
    row = db.query(UserTier).filter_by(user_id=user_id).first()
    if not row:
        row = UserTier(user_id=user_id, tier="free", status="active")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _stripe():
    """Return configured stripe module or raise 503."""
    try:
        import stripe as _s
    except ImportError:
        raise HTTPException(500, "Stripe library not installed")
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured — add STRIPE_SECRET_KEY env var")
    _s.api_key = settings.stripe_secret_key
    return _s


def _price_id(plan: str, interval: str) -> str:
    mapping = {
        "plus_monthly":    settings.stripe_price_plus_monthly,
        "plus_annual":     settings.stripe_price_plus_annual,
        "premium_monthly": settings.stripe_price_premium_monthly,
        "premium_annual":  settings.stripe_price_premium_annual,
    }
    pid = mapping.get(f"{plan}_{interval}", "")
    if not pid:
        raise HTTPException(503, f"Stripe price ID not configured for {plan}/{interval}")
    return pid


def _tier_from_price(price_id: str) -> tuple[str, str]:
    """Return (tier, interval) from a Stripe price ID."""
    for key, pid in {
        "plus_monthly":    settings.stripe_price_plus_monthly,
        "plus_annual":     settings.stripe_price_plus_annual,
        "premium_monthly": settings.stripe_price_premium_monthly,
        "premium_annual":  settings.stripe_price_premium_annual,
    }.items():
        if pid and pid == price_id:
            parts = key.split("_")
            return parts[0], parts[1]
    return "plus", "monthly"


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/me")
def get_my_tier(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = _get_or_create_tier(db, current_user.id)
        ents = get_entitlements(row)
    except Exception:
        from app.services.entitlements import ENTITLEMENTS
        ents = {**ENTITLEMENTS["free"], "_tier": "free", "_status": "active"}
        return {
            "tier": "free", "status": "active", "entitlements": ents,
            "billing_interval": None, "trial_ends_at": None,
            "current_period_end": None, "cancel_at_period_end": False,
            "aum_override": None, "has_stripe": False,
        }
    return {
        "tier": ents["_tier"],
        "status": ents["_status"],
        "entitlements": ents,
        "billing_interval": row.billing_interval,
        "trial_ends_at": row.trial_ends_at.isoformat() if row.trial_ends_at else None,
        "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "cancel_at_period_end": row.cancel_at_period_end,
        "aum_override": row.aum_override,
        "has_stripe": bool(row.stripe_customer_id),
    }


@router.get("/plans")
def get_plans():
    return {
        "plans": [
            {
                "id": "free",
                "name": "Free",
                "pricing": {"monthly": 0, "annual": 0, "annual_monthly_equiv": 0},
                "entitlements": ENTITLEMENTS["free"],
            },
            {
                "id": "plus",
                "name": "Plus",
                "pricing": PRICING["plus"],
                "entitlements": ENTITLEMENTS["plus"],
            },
            {
                "id": "premium",
                "name": "Premium",
                "pricing": PRICING["premium"],
                "entitlements": ENTITLEMENTS["premium"],
            },
        ]
    }


class TrialBody(BaseModel):
    pass


@router.post("/start-trial")
def start_trial(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start 7-day free Plus trial (no card required)."""
    from datetime import timedelta
    row = _get_or_create_tier(db, current_user.id)
    if row.tier != "free":
        raise HTTPException(400, "Already on a paid tier")
    if row.trial_ends_at:
        raise HTTPException(400, "Free trial already used")

    now = datetime.utcnow()
    row.tier = "plus"
    row.status = "trialing"
    row.trial_ends_at = now + timedelta(days=7)
    row.current_period_end = row.trial_ends_at
    db.commit()
    return {"ok": True, "trial_ends_at": row.trial_ends_at.isoformat()}


class CheckoutBody(BaseModel):
    plan: str           # plus | premium
    interval: str = "monthly"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@router.post("/checkout")
def create_checkout(
    body: CheckoutBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Checkout session for a subscription."""
    s = _stripe()
    price_id = _price_id(body.plan, body.interval)

    success_url = body.success_url or f"{settings.app_url}/settings?sub=success"
    cancel_url = body.cancel_url or f"{settings.app_url}/upgrade"

    row = _get_or_create_tier(db, current_user.id)

    if not row.stripe_customer_id:
        customer = s.Customer.create(
            email=current_user.email,
            metadata={"user_id": str(current_user.id)},
        )
        row.stripe_customer_id = customer.id
        db.commit()

    from datetime import timedelta
    trial_days = None
    if row.tier == "free" and not row.trial_ends_at:
        trial_days = 7

    session = s.checkout.Session.create(
        customer=row.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        subscription_data={"trial_period_days": trial_days} if trial_days else {},
    )
    return {"url": session.url}


class PortalBody(BaseModel):
    return_url: Optional[str] = None


@router.post("/portal")
def create_portal(
    body: PortalBody = PortalBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Customer Portal session for managing subscriptions."""
    s = _stripe()
    row = _get_or_create_tier(db, current_user.id)
    if not row.stripe_customer_id:
        raise HTTPException(400, "No billing account found — subscribe first")

    return_url = body.return_url or f"{settings.app_url}/settings"
    session = s.billing_portal.Session.create(
        customer=row.stripe_customer_id,
        return_url=return_url,
    )
    return {"url": session.url}


_STATUS_MAP = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "canceled": "cancelled",
    "incomplete": "past_due",
    "incomplete_expired": "cancelled",
    "unpaid": "past_due",
}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    """Handle Stripe webhook events."""
    try:
        import stripe as s
        s.api_key = settings.stripe_secret_key
    except ImportError:
        raise HTTPException(500, "Stripe not installed")

    payload = await request.body()

    try:
        if settings.stripe_webhook_secret and stripe_signature:
            event = s.Webhook.construct_event(
                payload, stripe_signature, settings.stripe_webhook_secret
            )
        else:
            import json
            event = json.loads(payload)
    except Exception:
        raise HTTPException(400, "Invalid webhook")

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        _upsert_subscription(db, obj)
    elif event_type == "customer.subscription.deleted":
        _cancel_subscription(db, obj)
    elif event_type == "invoice.payment_failed":
        _mark_past_due(db, obj.get("customer"))
    elif event_type == "invoice.payment_succeeded":
        _clear_past_due(db, obj.get("customer"))

    return {"received": True}


# ── webhook helpers ────────────────────────────────────────────────────────────

def _upsert_subscription(db: Session, sub: dict):
    customer_id = sub.get("customer")
    row = db.query(UserTier).filter_by(stripe_customer_id=customer_id).first()
    if not row:
        return

    items = sub.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else ""
    tier, interval = _tier_from_price(price_id)

    row.tier = tier
    row.status = _STATUS_MAP.get(sub.get("status", "active"), "active")
    row.billing_interval = interval
    row.stripe_subscription_id = sub.get("id")
    row.cancel_at_period_end = sub.get("cancel_at_period_end", False)

    if sub.get("current_period_end"):
        row.current_period_end = datetime.fromtimestamp(sub["current_period_end"])
    if sub.get("trial_end"):
        row.trial_ends_at = datetime.fromtimestamp(sub["trial_end"])

    db.commit()


def _cancel_subscription(db: Session, sub: dict):
    customer_id = sub.get("customer")
    row = db.query(UserTier).filter_by(stripe_customer_id=customer_id).first()
    if not row:
        return
    row.tier = "free"
    row.status = "active"
    row.billing_interval = None
    row.stripe_subscription_id = None
    row.cancel_at_period_end = False
    db.commit()


def _mark_past_due(db: Session, customer_id: Optional[str]):
    if not customer_id:
        return
    row = db.query(UserTier).filter_by(stripe_customer_id=customer_id).first()
    if row:
        row.status = "past_due"
        db.commit()


def _clear_past_due(db: Session, customer_id: Optional[str]):
    if not customer_id:
        return
    row = db.query(UserTier).filter_by(stripe_customer_id=customer_id).first()
    if row and row.status == "past_due":
        row.status = "active"
        db.commit()
