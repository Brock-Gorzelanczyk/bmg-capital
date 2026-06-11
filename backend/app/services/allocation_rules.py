"""Allocation tier rule engine — pure functions, no DB calls.

Tiers
-----
T0 CANDIDATE   — 0 % of capital (paper only, watching)
T1 PROBATION   — up to 3 % of capital
T2 PRODUCTION  — up to 12 % of capital
T3 CORE        — up to 20 % of capital
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Tier definitions ─────────────────────────────────────────────────────────

TIERS: dict[str, dict[str, Any]] = {
    "T0": {"label": "CANDIDATE",   "max_capital_pct": 0.00, "color": "gray"},
    "T1": {"label": "PROBATION",   "max_capital_pct": 0.03, "color": "yellow"},
    "T2": {"label": "PRODUCTION",  "max_capital_pct": 0.12, "color": "blue"},
    "T3": {"label": "CORE",        "max_capital_pct": 0.20, "color": "green"},
}

# ── Promotion rules ───────────────────────────────────────────────────────────
# Each rule is a dict of metric thresholds that must ALL be satisfied.

PROMOTION_RULES: dict[str, dict[str, Any]] = {
    # T0 → T1: survive 30-day candidate window with positive returns
    "T0_to_T1": {
        "from_tier": "T0",
        "to_tier": "T1",
        "min_trades": 10,
        "min_win_rate": 0.45,
        "min_return_30d_pct": 0.0,
        "max_drawdown_pct": 0.15,
        "description": "30-day candidate with positive return and ≥45 % win rate",
    },
    # T1 → T2: 60-day track record in live capital
    "T1_to_T2": {
        "from_tier": "T1",
        "to_tier": "T2",
        "min_trades": 25,
        "min_win_rate": 0.50,
        "min_return_30d_pct": 2.0,
        "min_profit_factor": 1.30,
        "max_drawdown_pct": 0.10,
        "description": "60-day probation: ≥50 % win rate, 2 % 30d return, PF ≥ 1.3",
    },
    # T2 → T3: proven production performer
    "T2_to_T3": {
        "from_tier": "T2",
        "to_tier": "T3",
        "min_trades": 60,
        "min_win_rate": 0.55,
        "min_return_30d_pct": 4.0,
        "min_profit_factor": 1.50,
        "max_drawdown_pct": 0.08,
        "min_sharpe": 1.0,
        "description": "Production to Core: ≥55 % win, 4 % 30d return, PF ≥ 1.5, Sharpe ≥ 1",
    },
}

# ── Demotion rules ────────────────────────────────────────────────────────────

DEMOTION_RULES: dict[str, dict[str, Any]] = {
    # T3 → T2: core slipping
    "T3_to_T2": {
        "from_tier": "T3",
        "to_tier": "T2",
        "trigger_drawdown_pct": 0.12,
        "trigger_win_rate_below": 0.45,
        "trigger_return_30d_pct_below": -3.0,
        "description": "Core demoted: DD > 12 % or win rate < 45 % or 30d return < -3 %",
    },
    # T2 → T1: production stumble
    "T2_to_T1": {
        "from_tier": "T2",
        "to_tier": "T1",
        "trigger_drawdown_pct": 0.15,
        "trigger_win_rate_below": 0.40,
        "trigger_return_30d_pct_below": -5.0,
        "description": "Production demoted: DD > 15 % or win rate < 40 % or 30d return < -5 %",
    },
    # T1 → T0: back to observation
    "T1_to_T0": {
        "from_tier": "T1",
        "to_tier": "T0",
        "trigger_drawdown_pct": 0.20,
        "trigger_win_rate_below": 0.35,
        "trigger_return_30d_pct_below": -8.0,
        "description": "Probation returned to candidate: unacceptable risk metrics",
    },
}


# ── Metrics dataclass ─────────────────────────────────────────────────────────

@dataclass
class BotMetrics:
    allocation_id: int
    current_tier: str
    total_trades: int
    win_rate: float
    return_30d_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float


# ── Evaluation logic ──────────────────────────────────────────────────────────

def evaluate_bot(metrics: BotMetrics) -> tuple[str, str | None]:
    """Return (new_tier, reason) for a bot given its current metrics.

    Demotion takes priority over promotion.  Returns the unchanged tier
    with reason=None if no change applies.
    """
    tier = metrics.current_tier

    # Check demotion first
    for rule in DEMOTION_RULES.values():
        if rule["from_tier"] != tier:
            continue
        triggered = (
            metrics.max_drawdown_pct >= rule["trigger_drawdown_pct"]
            or metrics.win_rate < rule["trigger_win_rate_below"]
            or metrics.return_30d_pct < rule["trigger_return_30d_pct_below"]
        )
        if triggered:
            return rule["to_tier"], rule["description"]

    # Check promotion
    for rule in PROMOTION_RULES.values():
        if rule["from_tier"] != tier:
            continue
        passes = (
            metrics.total_trades >= rule["min_trades"]
            and metrics.win_rate >= rule["min_win_rate"]
            and metrics.return_30d_pct >= rule["min_return_30d_pct"]
            and metrics.max_drawdown_pct <= rule["max_drawdown_pct"]
        )
        if "min_profit_factor" in rule:
            passes = passes and metrics.profit_factor >= rule["min_profit_factor"]
        if "min_sharpe" in rule:
            passes = passes and metrics.sharpe_ratio >= rule["min_sharpe"]
        if passes:
            return rule["to_tier"], rule["description"]

    return tier, None


def max_capital_pct(tier: str) -> float:
    """Return the max capital fraction allowed for a given tier."""
    return TIERS.get(tier, TIERS["T0"])["max_capital_pct"]
