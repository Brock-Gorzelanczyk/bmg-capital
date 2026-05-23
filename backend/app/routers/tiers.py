from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.tier import UserTier

router = APIRouter(prefix="/api/tiers", tags=["tiers"])

TIER_FEATURES = {
    "free": {
        "paper_trading": True,
        "basic_screener": True,
        "learn": True,
        "watchlist_limit": 10,
        "alerts_limit": 3,
        "strategy_backtest": False,
        "options_lab": False,
        "social": True,
        "ai_explain": False,
        "advanced_charts": False,
    },
    "pro": {
        "paper_trading": True,
        "basic_screener": True,
        "learn": True,
        "watchlist_limit": 100,
        "alerts_limit": 50,
        "strategy_backtest": True,
        "options_lab": True,
        "social": True,
        "ai_explain": True,
        "advanced_charts": True,
    },
    "premium": {
        "paper_trading": True,
        "basic_screener": True,
        "learn": True,
        "watchlist_limit": -1,   # unlimited
        "alerts_limit": -1,
        "strategy_backtest": True,
        "options_lab": True,
        "social": True,
        "ai_explain": True,
        "advanced_charts": True,
    },
}

TIER_PRICING = {
    "free": {"monthly": 0, "annual": 0},
    "pro": {"monthly": 19, "annual": 179},
    "premium": {"monthly": 49, "annual": 469},
}


@router.get("/me")
def get_my_tier(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    tier = row.tier if row else "free"
    return {
        "tier": tier,
        "features": TIER_FEATURES.get(tier, TIER_FEATURES["free"]),
        "expires_at": row.expires_at.isoformat() if row and row.expires_at else None,
    }


@router.get("/plans")
def get_plans():
    return {
        "plans": [
            {
                "id": tier,
                "name": tier.capitalize(),
                "pricing": TIER_PRICING[tier],
                "features": TIER_FEATURES[tier],
            }
            for tier in ["free", "pro", "premium"]
        ]
    }
