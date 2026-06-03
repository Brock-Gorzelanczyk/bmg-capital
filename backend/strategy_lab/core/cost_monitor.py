"""
Track API costs for Polygon and Anthropic.
Alert at 80% of monthly budget.
Stores counts in memory (upgrade to Redis/DB later).
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

# ── In-memory call counters keyed by "YYYY-MM:service:call_type" ─────────────
_api_calls: dict[str, int] = defaultdict(int)


def _month_key() -> str:
    """Return the current month key, e.g. '2026-06'."""
    return datetime.now().strftime("%Y-%m")


MONTHLY_BUDGETS: dict[str, int] = {
    "polygon": int(os.getenv("POLYGON_MONTHLY_BUDGET_USD", "200")),
    "anthropic": int(os.getenv("ANTHROPIC_MONTHLY_BUDGET_USD", "50")),
}

# Cost-per-call estimates in USD
COST_PER_CALL: dict[str, float] = {
    "polygon_bars": 0.0001,
    "polygon_news": 0.0002,
    "anthropic_haiku": 0.0003,   # ~$0.25/M tokens, ~1k tokens avg
    "anthropic_sonnet": 0.003,   # ~$3/M tokens, ~1k tokens avg
}


def record_api_call(service: str, call_type: str, count: int = 1) -> None:
    """Record one or more API calls of a given type for cost tracking."""
    key = f"{_month_key()}:{service}:{call_type}"
    _api_calls[key] += count


def get_monthly_cost(service: str) -> float:
    """Return the estimated USD cost for a service in the current month."""
    month = _month_key()
    total = 0.0
    for call_type, cost_per in COST_PER_CALL.items():
        if not call_type.startswith(service):
            continue
        key = f"{month}:{service}:{call_type}"
        total += _api_calls[key] * cost_per
    return total


def get_call_counts(service: str) -> dict[str, int]:
    """Return raw call counts for all call_types of a service this month."""
    month = _month_key()
    counts: dict[str, int] = {}
    for call_type in COST_PER_CALL:
        if not call_type.startswith(service):
            continue
        key = f"{month}:{service}:{call_type}"
        counts[call_type] = _api_calls[key]
    return counts


def check_budget_alert(service: str) -> bool:
    """
    Check if the service has consumed >= 80% of its monthly budget.
    Returns True if over threshold (alert condition), False otherwise.
    """
    budget = MONTHLY_BUDGETS.get(service, 0)
    if budget == 0:
        return False

    cost = get_monthly_cost(service)
    pct = (cost / budget) * 100

    if pct >= 80:
        logger.warning(
            "[cost] %s at $%.2f / $%d (%.0f%% of monthly budget)",
            service,
            cost,
            budget,
            pct,
        )
        return True

    logger.debug("[cost] %s: $%.4f / $%d (%.1f%%)", service, cost, budget, pct)
    return False


def check_all_budgets() -> dict[str, bool]:
    """Run budget checks for all tracked services. Returns {service: alert_tripped}."""
    return {service: check_budget_alert(service) for service in MONTHLY_BUDGETS}


def get_cost_summary() -> dict:
    """Return a summary dict for monitoring / admin endpoints."""
    month = _month_key()
    summary: dict[str, dict] = {}
    for service, budget in MONTHLY_BUDGETS.items():
        cost = get_monthly_cost(service)
        summary[service] = {
            "month": month,
            "estimated_cost_usd": round(cost, 4),
            "budget_usd": budget,
            "pct_used": round((cost / budget * 100) if budget else 0, 1),
            "alert": cost >= budget * 0.8,
            "call_counts": get_call_counts(service),
        }
    return summary
