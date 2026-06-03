"""
Custom Bot Builder — lets users assemble a bot from strategy modules,
save a draft, validate it, and deploy it as a new BotProfile + BotAllocation.

GET  /api/custom-bot/templates  — list / seed the 6 starter templates
GET  /api/custom-bot/draft      — fetch user's current undeployed draft
POST /api/custom-bot/draft      — upsert user's draft
POST /api/custom-bot/validate   — validate draft fields before deploy
POST /api/custom-bot/deploy     — deploy draft as a live (paper) bot
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.custom_bot import BotTemplate, UserCustomBotDraft
from app.db.models.bots import BotProfile, BotAllocation
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/custom-bot", tags=["custom-bot"])

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

TEMPLATE_SEED = [
    {
        "name": "income",
        "emoji": "💰",
        "tagline": "Sell premium, collect theta. Wheel strategy + covered calls.",
        "strategies": ["wheel_strategy", "covered_call_30d", "cash_secured_put", "bull_put_credit_spread", "iron_condor_45dte"],
        "default_config": {"capital_dollars": 25000, "risk_profile": "conservative", "schedule": "auto"},
    },
    {
        "name": "growth",
        "emoji": "📈",
        "tagline": "Momentum + quality breakouts. Built for bull markets.",
        "strategies": ["time_series_momentum_etf", "dual_momentum_gem", "canslim_pivot_breakout", "minervini_vcp", "cup_and_handle", "relative_strength_leaders"],
        "default_config": {"capital_dollars": 10000, "risk_profile": "standard", "schedule": "auto"},
    },
    {
        "name": "safety",
        "emoji": "🛡️",
        "tagline": "Low volatility, dividend growth, monthly rebalance.",
        "strategies": ["factor_blend", "low_vol_anomaly", "dividend_growth", "monthly_rebalance"],
        "default_config": {"capital_dollars": 50000, "risk_profile": "conservative", "schedule": "auto"},
    },
    {
        "name": "day_trader",
        "emoji": "🌊",
        "tagline": "Intraday momentum + ORB + VWAP reversion.",
        "strategies": ["orb_stocks_in_play", "intraday_momentum_noise_band", "gap_and_go_momentum", "raschke_holy_grail", "crabel_nr7_breakout", "pead_intraday_drift", "vwap_reversion_chop"],
        "default_config": {"capital_dollars": 10000, "risk_profile": "aggressive", "schedule": "auto"},
    },
    {
        "name": "crypto_pro",
        "emoji": "🪙",
        "tagline": "Crypto intraday + swing + DCA overlay.",
        "strategies": ["crypto_intraday_momentum", "crypto_weekend_momentum", "crypto_rsi_mean_reversion", "crypto_momentum_breakout", "crypto_btc_dominance_regime", "crypto_volatility_breakout", "crypto_news_sentiment", "dca_btc_eth", "monthly_rebalance_majors"],
        "default_config": {"capital_dollars": 5000, "risk_profile": "aggressive", "schedule": "auto"},
    },
    {
        "name": "build_from_scratch",
        "emoji": "✨",
        "tagline": "Start with an empty basket. Pick any strategies from the full library.",
        "strategies": [],
        "default_config": {"capital_dollars": 10000, "risk_profile": "standard", "schedule": "auto"},
    },
]

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class DraftBody(BaseModel):
    name: Optional[str] = None
    template_id: Optional[int] = None
    strategies: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None


class ValidateBody(BaseModel):
    strategies: List[str]
    name: str
    capital_dollars: float
    risk_profile: str


class DeployConfigBody(BaseModel):
    capital_dollars: float
    risk_profile: str
    schedule: str = "auto"


class DeployBody(BaseModel):
    draft_id: int
    name: str
    strategies: List[str]
    config: DeployConfigBody


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STOCK_KEYWORDS = {"orb", "canslim", "minervini", "vcp", "cup_and_handle", "wheel", "covered_call", "cash_secured_put", "iron_condor", "bull_put", "momentum_etf", "dual_momentum", "relative_strength", "low_vol", "dividend", "gap_and_go", "raschke", "crabel", "pead", "vwap", "intraday_momentum_noise", "factor_blend"}
_CRYPTO_KEYWORDS = {"crypto", "btc", "eth", "dca_btc"}


def _has_stock_strategies(strategies: List[str]) -> bool:
    joined = " ".join(strategies).lower()
    return any(kw in joined for kw in _STOCK_KEYWORDS)


def _has_crypto_strategies(strategies: List[str]) -> bool:
    joined = " ".join(strategies).lower()
    return any(kw in joined for kw in _CRYPTO_KEYWORDS)


def _compute_first_run_ts(schedule: str) -> datetime:
    """Compute the next scheduled run timestamp based on the schedule type."""
    now_et = datetime.now(timezone.utc)  # approximation; server uses UTC

    if schedule in ("auto", "daily_4pm"):
        # Today at 4:05 PM ET (UTC-4 / UTC-5 — use UTC+4h offset as rough ET proxy)
        # We compute in UTC: 4:05 PM ET = 20:05 UTC (EDT) or 21:05 UTC (EST)
        today_run = now_et.replace(hour=20, minute=5, second=0, microsecond=0)
        if now_et >= today_run:
            today_run += timedelta(days=1)
        return today_run

    if schedule == "every_4h":
        # Next 4-hour boundary (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
        hour = now_et.hour
        next_boundary_hour = ((hour // 4) + 1) * 4
        if next_boundary_hour >= 24:
            next_run = now_et.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            next_run = now_et.replace(hour=next_boundary_hour, minute=0, second=0, microsecond=0)
        return next_run

    if schedule == "monthly":
        # First Tuesday of next month
        first_of_next = (now_et.replace(day=1) + timedelta(days=32)).replace(day=1)
        # Find first Tuesday (weekday 1)
        day_offset = (1 - first_of_next.weekday()) % 7
        first_tuesday = first_of_next + timedelta(days=day_offset)
        return first_tuesday.replace(hour=20, minute=5, second=0, microsecond=0)

    # Fallback: tomorrow at 4:05 PM UTC
    return (now_et + timedelta(days=1)).replace(hour=20, minute=5, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/templates")
def get_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return all bot templates, seeding the table on first call if empty."""
    count = db.execute(select(BotTemplate)).scalars().first()
    if count is None:
        for seed in TEMPLATE_SEED:
            template = BotTemplate(
                name=seed["name"],
                emoji=seed["emoji"],
                tagline=seed["tagline"],
                strategies=seed["strategies"],
                default_config=seed["default_config"],
                popularity_count=0,
            )
            db.add(template)
        db.commit()

    templates = db.execute(select(BotTemplate)).scalars().all()
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "emoji": t.emoji,
                "tagline": t.tagline,
                "strategies": t.strategies,
                "default_config": t.default_config,
                "popularity_count": t.popularity_count,
            }
            for t in templates
        ]
    }


@router.get("/draft")
def get_draft(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the user's latest undeployed draft, or null if none exists."""
    draft = db.execute(
        select(UserCustomBotDraft)
        .where(
            UserCustomBotDraft.user_id == current_user.id,
            UserCustomBotDraft.deployed_at.is_(None),
        )
        .order_by(UserCustomBotDraft.updated_at.desc())
        .limit(1)
    ).scalars().first()

    if draft is None:
        return {"draft": None}

    return {
        "draft": {
            "id": draft.id,
            "name": draft.name,
            "template_id": draft.template_id,
            "strategies": draft.strategies,
            "config": draft.config,
            "created_at": draft.created_at.isoformat(),
            "updated_at": draft.updated_at.isoformat(),
        }
    }


@router.post("/draft")
def upsert_draft(
    body: DraftBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upsert the user's undeployed draft. Updates existing or creates new."""
    draft = db.execute(
        select(UserCustomBotDraft)
        .where(
            UserCustomBotDraft.user_id == current_user.id,
            UserCustomBotDraft.deployed_at.is_(None),
        )
        .order_by(UserCustomBotDraft.updated_at.desc())
        .limit(1)
    ).scalars().first()

    if draft is None:
        draft = UserCustomBotDraft(user_id=current_user.id)
        db.add(draft)

    if body.name is not None:
        draft.name = body.name
    if body.template_id is not None:
        draft.template_id = body.template_id
    if body.strategies is not None:
        draft.strategies = body.strategies
    if body.config is not None:
        draft.config = body.config

    draft.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(draft)

    return {"draft_id": draft.id}


@router.post("/validate")
def validate_draft(
    body: ValidateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Validate a draft's fields before deployment."""
    errors: List[str] = []
    warnings: List[str] = []

    if len(body.strategies) < 1:
        errors.append("Add at least 1 strategy")

    if len(body.strategies) > 10:
        errors.append("Max 10 strategies")

    if not (1000 <= body.capital_dollars <= 100000):
        errors.append("Capital must be $1K–$100K")

    if not body.name or not body.name.strip():
        errors.append("Name is required")

    # Check for duplicate bot name for this user
    if body.name and body.name.strip():
        existing = db.execute(
            select(BotProfile)
            .join(BotAllocation, BotAllocation.profile_id == BotProfile.id)
            .where(
                BotAllocation.user_id == current_user.id,
                BotProfile.name == body.name.strip(),
            )
        ).scalars().first()
        if existing:
            errors.append(f"You already have a bot named '{body.name.strip()}'")

    # Mixed asset class warning
    if _has_stock_strategies(body.strategies) and _has_crypto_strategies(body.strategies):
        warnings.append("Mixed asset classes detected. Consider creating 2 separate bots.")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    return {"valid": True, "warnings": warnings}


@router.post("/deploy")
def deploy_draft(
    body: DeployBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Deploy a draft as a new paper-mode BotProfile + BotAllocation."""
    # Verify draft belongs to current user
    draft = db.execute(
        select(UserCustomBotDraft).where(
            UserCustomBotDraft.id == body.draft_id,
            UserCustomBotDraft.user_id == current_user.id,
        )
    ).scalars().first()

    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.deployed_at is not None:
        raise HTTPException(status_code=400, detail="Draft has already been deployed")

    # 1. Create BotProfile
    profile = BotProfile(
        name=body.name,
        asset_class="custom",
        config_json={
            "strategies": body.strategies,
            "schedule": body.config.schedule,
            "risk_profile": body.config.risk_profile,
            "paper_only": True,
        },
        enabled=True,
    )
    db.add(profile)
    db.flush()  # get profile.id without committing

    # 2. Create BotAllocation
    alloc = BotAllocation(
        user_id=current_user.id,
        profile_id=profile.id,
        capital_pct=10,
        risk_profile=body.config.risk_profile,
        paper_mode=True,
        enabled=True,
    )
    db.add(alloc)
    db.flush()  # get alloc.id

    # 3. Mark draft as deployed
    now = datetime.now(timezone.utc)
    draft.deployed_at = now
    draft.deployed_bot_id = profile.id
    draft.updated_at = now

    db.commit()
    db.refresh(profile)
    db.refresh(alloc)

    # 4. Compute first_run_ts
    first_run_ts = _compute_first_run_ts(body.config.schedule)

    return {
        "bot_id": profile.id,
        "bot_name": profile.name,
        "allocation_id": alloc.id,
        "first_run_ts": first_run_ts.isoformat(),
    }
