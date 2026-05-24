from __future__ import annotations
from typing import Any
from app.db.models.tier import UserTier

ENTITLEMENTS: dict[str, dict[str, Any]] = {
    "free": {
        "pro_mode": False,
        "chart_history_years": 1,
        "chart_indicators_max": 5,
        "chart_tabs_max": 1,
        "watchlist_count": 1,
        "watchlist_symbols": 50,
        "alert_count_max": 10,
        "real_time_options": False,
        "extended_hours": False,
        "recurring_buys": False,
        "tax_loss_harvest": False,
        "strategy_lab_tier": "none",       # none|basic|advanced
        "strategy_backtest_years": 0,
        "learning_center_tier": "beginner", # beginner|intermediate|all
        "options_lab_tier": "none",         # none|basic|full
        "ai_tutor_unlimited": False,
        "ai_copilot_reasoning": False,
        "level_2_quotes": False,
        "opra_realtime": False,
        "options_flow": False,
        "reading_level_slider": False,
        "certified_exams": False,
        "instant_deposit_cap": 1000,
        "api_access": False,
        "support_tier": "community",        # community|email|live_chat
        "apy_rate": 1.5,
        "ira_match_rate": 0.0,
        "ira_match_cap": 0,
        "margin_enabled": False,
        "community_post": False,
        "crypto_limit": 50,
    },
    "plus": {
        "pro_mode": True,
        "chart_history_years": 5,
        "chart_indicators_max": 20,
        "chart_tabs_max": 4,
        "watchlist_count": 10,
        "watchlist_symbols": 100,
        "alert_count_max": 100,
        "real_time_options": True,
        "extended_hours": True,
        "recurring_buys": True,
        "tax_loss_harvest": True,
        "strategy_lab_tier": "basic",
        "strategy_backtest_years": 5,
        "learning_center_tier": "all",
        "options_lab_tier": "basic",
        "ai_tutor_unlimited": True,
        "ai_copilot_reasoning": False,
        "level_2_quotes": False,
        "opra_realtime": False,
        "options_flow": False,
        "reading_level_slider": False,
        "certified_exams": False,
        "instant_deposit_cap": 10000,
        "api_access": False,
        "support_tier": "email",
        "apy_rate": 3.5,
        "ira_match_rate": 0.01,
        "ira_match_cap": 70,
        "margin_enabled": False,
        "community_post": True,
        "crypto_limit": -1,
    },
    "premium": {
        "pro_mode": True,
        "chart_history_years": 20,
        "chart_indicators_max": 50,
        "chart_tabs_max": 16,
        "watchlist_count": -1,
        "watchlist_symbols": -1,
        "alert_count_max": -1,
        "real_time_options": True,
        "extended_hours": True,
        "recurring_buys": True,
        "tax_loss_harvest": True,
        "strategy_lab_tier": "advanced",
        "strategy_backtest_years": 20,
        "learning_center_tier": "all",
        "options_lab_tier": "full",
        "ai_tutor_unlimited": True,
        "ai_copilot_reasoning": True,
        "level_2_quotes": True,
        "opra_realtime": True,
        "options_flow": True,
        "reading_level_slider": True,
        "certified_exams": True,
        "instant_deposit_cap": 50000,
        "api_access": True,
        "support_tier": "live_chat",
        "apy_rate": 4.5,
        "ira_match_rate": 0.03,
        "ira_match_cap": 210,
        "margin_enabled": True,
        "community_post": True,
        "crypto_limit": -1,
    },
}

PRICING = {
    "plus":    {"monthly": 5.99,  "annual": 59.00,  "annual_monthly_equiv": 4.92},
    "premium": {"monthly": 19.99, "annual": 199.00, "annual_monthly_equiv": 16.58},
}

AUM_THRESHOLDS = {"plus": 10_000, "premium": 50_000}

STRIPE_PRICES = {
    # Fill in real Stripe Price IDs when available
    "plus_monthly":    "price_plus_monthly",
    "plus_annual":     "price_plus_annual",
    "premium_monthly": "price_premium_monthly",
    "premium_annual":  "price_premium_annual",
}


def effective_tier(row: UserTier | None) -> str:
    """Returns the highest applicable tier considering subscription + AUM override."""
    from datetime import datetime
    if row is None:
        return "free"

    tier_order = {"free": 0, "plus": 1, "premium": 2}
    base = row.tier if row.status in ("active", "trialing") else "free"

    # AUM override: if still valid, use whichever is higher
    aum = "free"
    if row.aum_override and row.aum_override_until and row.aum_override_until > datetime.utcnow():
        aum = row.aum_override

    return max(base, aum, key=lambda t: tier_order.get(t, 0))


def get_entitlements(row: UserTier | None) -> dict:
    tier = effective_tier(row)
    return {**ENTITLEMENTS[tier], "_tier": tier, "_status": row.status if row else "active"}


def can(entitlements: dict, feature_key: str, required_value: Any = True) -> bool:
    val = entitlements.get(feature_key)
    if isinstance(required_value, bool):
        return bool(val)
    return val == required_value or (isinstance(val, (int, float)) and val >= required_value)
