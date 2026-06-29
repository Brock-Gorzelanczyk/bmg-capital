from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.paper import PaperAccount
from app.db.models.robo import (
    CorePortfolio,
    DirectIndexPortfolio,
    RebalanceLog,
    RiskProfile,
    RoboGoal,
    WashSaleGuard,
)
from app.services.robo_scoring import (
    compute_glide_path,
    compute_risk_score,
    monte_carlo_percentiles,
    monte_carlo_probability,
    score_to_allocation,
    score_to_portfolio_type,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/robo", tags=["robo"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class QuizBody(BaseModel):
    time_horizon: str
    goal_type: str
    income_bracket: str
    savings_rate: float
    loss_tolerance: str
    experience: str
    has_emergency_fund: bool


class GoalCreateBody(BaseModel):
    name: str
    goal_type: str
    target_amount: float
    target_date: Optional[date] = None
    monthly_contribution: Optional[float] = 0.0


class GoalUpdateBody(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    target_date: Optional[date] = None
    monthly_contribution: Optional[float] = None


class RebalanceSimulateBody(BaseModel):
    deposit_amount: Optional[float] = None


class DirectIndexCustomizeBody(BaseModel):
    sector_exclusions: Optional[List[str]] = None
    ticker_exclusions: Optional[List[str]] = None
    tilts: Optional[Dict[str, Any]] = None
    nl_prompt: Optional[str] = None


class AiExplainBody(BaseModel):
    context: str  # "rebalance"|"volatility"|"goal"|"tax"
    data: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _months_between(d1: date, d2: date) -> int:
    """Return number of months from d1 to d2 (always >= 1)."""
    return max(1, (d2.year - d1.year) * 12 + (d2.month - d1.month))


def _equity_fraction_from_allocation(allocation: dict) -> float:
    """Estimate equity fraction from a ticker-based allocation dict."""
    equity_tickers = {"VTI", "VXUS", "VBR", "VWO", "ITOT", "SCHB"}
    eq = sum(v for k, v in allocation.items() if k.upper() in equity_tickers)
    return min(max(eq, 0.0), 1.0)


def _parse_nl_prompt_regex(nl_prompt: str) -> dict:
    """Fallback regex parser for direct-index NL customization."""
    result: dict = {"exclude_sectors": [], "exclude_tickers": [], "tilts": {}}

    sector_keywords = [
        "energy", "fossil", "oil", "gas", "tobacco", "gambling", "weapons",
        "defense", "alcohol", "cannabis", "utilities", "financials", "healthcare",
        "technology", "consumer", "industrials", "materials", "real estate",
    ]
    prompt_lower = nl_prompt.lower()
    for kw in sector_keywords:
        if kw in prompt_lower:
            result["exclude_sectors"].append(kw)

    if "esg" in prompt_lower or "sustainable" in prompt_lower or "green" in prompt_lower:
        result["tilts"]["esg"] = True
    if "value" in prompt_lower:
        result["tilts"]["value"] = 0.2
    if "momentum" in prompt_lower:
        result["tilts"]["momentum"] = 0.1
    if "small" in prompt_lower or "small cap" in prompt_lower:
        result["tilts"]["small_cap"] = 0.1

    # Extract ticker exclusions: uppercase 1-5 char words
    tickers = re.findall(r'\b([A-Z]{1,5})\b', nl_prompt)
    result["exclude_tickers"] = list(set(tickers)) if tickers else []

    return result


def _call_anthropic_parse(nl_prompt: str) -> dict:
    """Parse NL prompt using deterministic classifier; LLM-cached fallback if low confidence.

    SHIP 3 R4: primary path is now robo_prompt_parser (no LLM).
    If confidence < 0.6, falls back to call_llm_cached.
    """
    from app.services.robo_prompt_parser import parse_robo_prompt
    parsed = parse_robo_prompt(nl_prompt)
    if parsed.get("confidence", 0) >= 0.6:
        # High-confidence deterministic result — no LLM
        return _parse_nl_prompt_regex(nl_prompt)  # keep existing shape for consumer
    # Low-confidence: use cached LLM
    try:
        from app.services.llm_client import call_llm_cached
        raw = call_llm_cached(
            model="claude-haiku-4-5-20251001",
            prompt=nl_prompt,
            system_prompt=(
                "You are a financial portfolio configuration assistant. "
                "Extract portfolio customization preferences from the user's message and respond ONLY with valid JSON "
                "in this exact format: "
                "{\"exclude_sectors\": [], \"exclude_tickers\": [], \"tilts\": {}} "
                "tilts keys can be: esg (bool), value (float 0-1), momentum (float 0-1), small_cap (float 0-1). "
                "Do not include any explanation — only the JSON object."
            ),
            max_tokens=300,
            ttl_seconds=86400,
            agent_name="robo_parse",
        )
        return json.loads(raw)
    except Exception as e:
        logger.warning("robo_parse LLM fallback failed, using regex: %s", e)
        return _parse_nl_prompt_regex(nl_prompt)


# ---------------------------------------------------------------------------
# POST /api/robo/quiz
# ---------------------------------------------------------------------------

@router.post("/quiz")
def submit_quiz(
    body: QuizBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Compute risk score, upsert RiskProfile, get-or-create CorePortfolio."""
    risk_score = compute_risk_score(
        time_horizon=body.time_horizon,
        loss_tolerance=body.loss_tolerance,
        has_emergency_fund=body.has_emergency_fund,
        savings_rate=body.savings_rate,
        experience=body.experience,
    )
    allocation = score_to_allocation(risk_score)
    allocation_json = json.dumps(allocation)
    portfolio_type = score_to_portfolio_type(risk_score)

    # Upsert RiskProfile
    profile = db.query(RiskProfile).filter(RiskProfile.user_id == current_user.id).first()
    if profile:
        profile.time_horizon = body.time_horizon
        profile.goal_type = body.goal_type
        profile.income_bracket = body.income_bracket
        profile.savings_rate = body.savings_rate
        profile.loss_tolerance = body.loss_tolerance
        profile.experience = body.experience
        profile.has_emergency_fund = body.has_emergency_fund
        profile.risk_score = risk_score
        profile.target_allocation = allocation_json
        profile.updated_at = datetime.now(timezone.utc)
    else:
        profile = RiskProfile(
            user_id=current_user.id,
            time_horizon=body.time_horizon,
            goal_type=body.goal_type,
            income_bracket=body.income_bracket,
            savings_rate=body.savings_rate,
            loss_tolerance=body.loss_tolerance,
            experience=body.experience,
            has_emergency_fund=body.has_emergency_fund,
            risk_score=risk_score,
            target_allocation=allocation_json,
        )
        db.add(profile)

    # Get or create CorePortfolio
    core = db.query(CorePortfolio).filter(CorePortfolio.user_id == current_user.id).first()
    if not core:
        core = CorePortfolio(
            user_id=current_user.id,
            total_value=0.0,
            target_allocation=allocation_json,
            current_allocation=allocation_json,
        )
        db.add(core)
    else:
        core.target_allocation = allocation_json
        core.updated_at = datetime.now(timezone.utc)

    db.commit()

    message_map = {
        "Conservative": "Your portfolio is optimized for capital preservation with minimal volatility.",
        "Moderate": "Your portfolio balances safety and growth with a modest equity tilt.",
        "Balanced": "Your portfolio is evenly split between growth and stability.",
        "Growth": "Your portfolio leans toward equities for long-term wealth building.",
        "Aggressive Growth": "Your portfolio maximizes equity exposure for maximum long-run growth.",
    }

    return {
        "risk_score": risk_score,
        "target_allocation": allocation,
        "portfolio_type": portfolio_type,
        "message": message_map.get(portfolio_type, "Portfolio configured."),
    }


# ---------------------------------------------------------------------------
# GET /api/robo/profile
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return current RiskProfile + CorePortfolio, or null if not set up."""
    profile = db.query(RiskProfile).filter(RiskProfile.user_id == current_user.id).first()
    core = db.query(CorePortfolio).filter(CorePortfolio.user_id == current_user.id).first()

    if not profile:
        return {"profile": None, "core_portfolio": None}

    return {
        "profile": {
            "id": profile.id,
            "time_horizon": profile.time_horizon,
            "goal_type": profile.goal_type,
            "income_bracket": profile.income_bracket,
            "savings_rate": profile.savings_rate,
            "loss_tolerance": profile.loss_tolerance,
            "experience": profile.experience,
            "has_emergency_fund": profile.has_emergency_fund,
            "risk_score": profile.risk_score,
            "target_allocation": json.loads(profile.target_allocation),
            "portfolio_type": score_to_portfolio_type(profile.risk_score),
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        },
        "core_portfolio": _serialize_core(core) if core else None,
    }


# ---------------------------------------------------------------------------
# GET /api/robo/dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Aggregate robo dashboard — never 500s, returns zeros for missing data."""
    try:
        profile = db.query(RiskProfile).filter(RiskProfile.user_id == current_user.id).first()
        core = db.query(CorePortfolio).filter(CorePortfolio.user_id == current_user.id).first()
        goals = db.query(RoboGoal).filter(RoboGoal.user_id == current_user.id).all()
        paper_account = db.query(PaperAccount).filter(PaperAccount.user_id == current_user.id).first()

        core_value = core.total_value if core else 0.0
        paper_value = 0.0
        if paper_account:
            paper_value = paper_account.cash  # cash balance as proxy for paper account value

        # Active: everything not in core robo (paper + other)
        active_value = paper_value  # extend later for crypto/real holdings
        total_value = core_value + active_value

        core_pct = round(core_value / total_value * 100, 1) if total_value > 0 else 0.0
        active_pct = round(active_value / total_value * 100, 1) if total_value > 0 else 0.0

        goals_summary = []
        for g in goals:
            goals_summary.append({
                "name": g.name,
                "value": g.current_balance,
                "target": g.target_amount,
                "probability_pct": g.probability_pct,
            })

        direct_index = db.query(DirectIndexPortfolio).filter(
            DirectIndexPortfolio.user_id == current_user.id
        ).first()

        risk_profile_data = None
        if profile:
            risk_profile_data = {
                "risk_score": profile.risk_score,
                "portfolio_type": score_to_portfolio_type(profile.risk_score),
                "time_horizon": profile.time_horizon,
                "target_allocation": json.loads(profile.target_allocation),
            }

        # Suggested split: core / active as 10s-rounded pct
        if total_value > 0:
            core_10 = round(core_pct / 10) * 10
            active_10 = 100 - core_10
            suggested_split = f"{core_10}/{active_10}"
        else:
            suggested_split = "70/30"

        return {
            "total_value": round(total_value, 2),
            "core": {
                "value": round(core_value, 2),
                "allocation_pct": core_pct,
                "ytd_return_pct": core.ytd_return_pct if core else 0.0,
                "rebalance_needed": core.rebalance_needed if core else False,
                "goals": goals_summary,
                "direct_index_enabled": core.direct_index_enabled if core else False,
                "direct_index": {
                    "total_value": direct_index.total_value,
                    "tracking_error_pct": direct_index.tracking_error_pct,
                    "ytd_harvested_losses": direct_index.ytd_harvested_losses,
                    "estimated_tax_savings": direct_index.estimated_tax_savings,
                } if direct_index else None,
            },
            "active": {
                "value": round(active_value, 2),
                "allocation_pct": active_pct,
                "ytd_return_pct": 0.0,
                "paper_value": round(paper_value, 2),
                "holdings_value": 0.0,
                "crypto_value": 0.0,
            },
            "suggested_split": suggested_split,
            "risk_profile": risk_profile_data,
        }
    except Exception as e:
        logger.error("Robo dashboard error for user %s: %s", current_user.id, e, exc_info=True)
        return {
            "total_value": 0.0,
            "core": {
                "value": 0.0,
                "allocation_pct": 0.0,
                "ytd_return_pct": 0.0,
                "rebalance_needed": False,
                "goals": [],
                "direct_index_enabled": False,
                "direct_index": None,
            },
            "active": {
                "value": 0.0,
                "allocation_pct": 0.0,
                "ytd_return_pct": 0.0,
                "paper_value": 0.0,
                "holdings_value": 0.0,
                "crypto_value": 0.0,
            },
            "suggested_split": "70/30",
            "risk_profile": None,
        }


# ---------------------------------------------------------------------------
# POST /api/robo/goals
# ---------------------------------------------------------------------------

@router.post("/goals")
def create_goal(
    body: GoalCreateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new robo goal with glide path and Monte Carlo probability."""
    glide_path_data: list = []
    probability_pct = 0.0
    monthly_contribution = body.monthly_contribution or 0.0

    if body.target_date:
        glide_path_data = compute_glide_path(body.target_date)
        months_to_goal = _months_between(date.today(), body.target_date)
        # Use first entry equity fraction for Monte Carlo
        eq_frac = glide_path_data[0]["equity"] if glide_path_data else 0.6
        seed = current_user.id + months_to_goal
        random_seed = seed
        probability_pct = monte_carlo_probability(
            target_amount=body.target_amount,
            current_balance=0.0,
            monthly_contribution=monthly_contribution,
            months_to_goal=months_to_goal,
            equity_fraction=eq_frac,
            n_simulations=1000,
            seed=random_seed,
        )

    goal = RoboGoal(
        user_id=current_user.id,
        name=body.name,
        goal_type=body.goal_type,
        target_amount=body.target_amount,
        target_date=body.target_date,
        current_balance=0.0,
        monthly_contribution=monthly_contribution,
        status="on_track",
        glide_path=json.dumps(glide_path_data) if glide_path_data else None,
        probability_pct=probability_pct,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

    return _serialize_goal(goal)


# ---------------------------------------------------------------------------
# GET /api/robo/goals
# ---------------------------------------------------------------------------

@router.get("/goals")
def list_goals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List all goals for the current user with computed extra fields."""
    goals = db.query(RoboGoal).filter(RoboGoal.user_id == current_user.id).all()
    return [_serialize_goal(g) for g in goals]


# ---------------------------------------------------------------------------
# PUT /api/robo/goals/{goal_id}
# ---------------------------------------------------------------------------

@router.put("/goals/{goal_id}")
def update_goal(
    goal_id: int,
    body: GoalUpdateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update goal fields, recompute glide path and probability."""
    goal = db.query(RoboGoal).filter(
        RoboGoal.id == goal_id,
        RoboGoal.user_id == current_user.id,
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if body.name is not None:
        goal.name = body.name
    if body.target_amount is not None:
        goal.target_amount = body.target_amount
    if body.target_date is not None:
        goal.target_date = body.target_date
    if body.monthly_contribution is not None:
        goal.monthly_contribution = body.monthly_contribution

    # Recompute if target_date is set
    if goal.target_date:
        glide_path_data = compute_glide_path(goal.target_date)
        months_to_goal = _months_between(date.today(), goal.target_date)
        eq_frac = glide_path_data[0]["equity"] if glide_path_data else 0.6
        seed = current_user.id + months_to_goal
        probability_pct = monte_carlo_probability(
            target_amount=goal.target_amount,
            current_balance=goal.current_balance,
            monthly_contribution=goal.monthly_contribution,
            months_to_goal=months_to_goal,
            equity_fraction=eq_frac,
            n_simulations=1000,
            seed=seed,
        )
        goal.glide_path = json.dumps(glide_path_data)
        goal.probability_pct = probability_pct

    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(goal)
    return _serialize_goal(goal)


# ---------------------------------------------------------------------------
# DELETE /api/robo/goals/{goal_id}
# ---------------------------------------------------------------------------

@router.delete("/goals/{goal_id}")
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete a goal (must belong to current user)."""
    goal = db.query(RoboGoal).filter(
        RoboGoal.id == goal_id,
        RoboGoal.user_id == current_user.id,
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(goal)
    db.commit()
    return {"deleted": True, "goal_id": goal_id}


# ---------------------------------------------------------------------------
# GET /api/robo/goals/{goal_id}/projection
# ---------------------------------------------------------------------------

@router.get("/goals/{goal_id}/projection")
def goal_projection(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """High-precision Monte Carlo projection for a specific goal (n=2000)."""
    goal = db.query(RoboGoal).filter(
        RoboGoal.id == goal_id,
        RoboGoal.user_id == current_user.id,
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if not goal.target_date:
        return {
            "probability_pct": 0.0,
            "expected_value": goal.current_balance,
            "percentile_10": goal.current_balance,
            "percentile_50": goal.current_balance,
            "percentile_90": goal.current_balance,
            "monthly_needed_for_90pct": None,
            "note": "No target date set — projection unavailable",
        }

    months_to_goal = _months_between(date.today(), goal.target_date)
    glide_path_data = goal.glide_path_list()
    eq_frac = glide_path_data[0]["equity"] if glide_path_data else 0.6
    seed = current_user.id + months_to_goal

    stats = monte_carlo_percentiles(
        target_amount=goal.target_amount,
        current_balance=goal.current_balance,
        monthly_contribution=goal.monthly_contribution,
        months_to_goal=months_to_goal,
        equity_fraction=eq_frac,
        n_simulations=2000,
        seed=seed,
    )

    # Calculate monthly contribution needed to achieve 90% probability
    monthly_needed = _find_monthly_for_90pct(
        target_amount=goal.target_amount,
        current_balance=goal.current_balance,
        months_to_goal=months_to_goal,
        equity_fraction=eq_frac,
        seed=seed,
    )

    return {**stats, "monthly_needed_for_90pct": monthly_needed}


def _find_monthly_for_90pct(
    target_amount: float,
    current_balance: float,
    months_to_goal: int,
    equity_fraction: float,
    seed: int,
    max_iter: int = 20,
) -> Optional[float]:
    """Binary search for monthly contribution that yields ~90% probability."""
    try:
        lo, hi = 0.0, target_amount / max(months_to_goal, 1) * 3
        for _ in range(max_iter):
            mid = (lo + hi) / 2
            prob = monte_carlo_probability(
                target_amount=target_amount,
                current_balance=current_balance,
                monthly_contribution=mid,
                months_to_goal=months_to_goal,
                equity_fraction=equity_fraction,
                n_simulations=500,
                seed=seed,
            )
            if prob >= 90.0:
                hi = mid
            else:
                lo = mid
        return round(hi, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GET /api/robo/rebalance/history
# ---------------------------------------------------------------------------

@router.get("/rebalance/history")
def rebalance_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Last 20 rebalance log entries for the current user."""
    logs = (
        db.query(RebalanceLog)
        .filter(RebalanceLog.user_id == current_user.id)
        .order_by(RebalanceLog.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": log.id,
            "trigger": log.trigger,
            "summary": log.summary,
            "trades": json.loads(log.trades) if log.trades else [],
            "total_value_before": log.total_value_before,
            "total_value_after": log.total_value_after,
            "taxes_triggered": log.taxes_triggered,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ---------------------------------------------------------------------------
# POST /api/robo/rebalance/simulate
# ---------------------------------------------------------------------------

@router.post("/rebalance/simulate")
def rebalance_simulate(
    body: RebalanceSimulateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Simulate a rebalance — does NOT execute trades."""
    core = db.query(CorePortfolio).filter(CorePortfolio.user_id == current_user.id).first()
    if not core:
        raise HTTPException(status_code=404, detail="No core portfolio found. Complete the quiz first.")

    target = json.loads(core.target_allocation)
    current = json.loads(core.current_allocation) if core.current_allocation else target
    total_value = core.total_value

    # Compute drift per position
    drifts: list[dict] = []
    for symbol, target_pct in target.items():
        current_pct = current.get(symbol, 0.0)
        drift = current_pct - target_pct
        drifts.append({"symbol": symbol, "target_pct": target_pct, "current_pct": current_pct, "drift": drift})

    drifts.sort(key=lambda x: x["drift"])  # most underweight first

    trigger = "drift"
    trades = []

    if body.deposit_amount and body.deposit_amount > 0:
        trigger = "cash_inflow"
        # Allocate deposit to most underweight position
        most_underweight = drifts[0] if drifts else None
        if most_underweight:
            symbol = most_underweight["symbol"]
            estimated_value = body.deposit_amount * (most_underweight["target_pct"] - most_underweight["current_pct"])
            estimated_value = max(estimated_value, body.deposit_amount * most_underweight["target_pct"])
            trades.append({
                "symbol": symbol,
                "action": "buy",
                "qty_needed": None,
                "estimated_value": round(estimated_value, 2),
            })
    else:
        # Standard drift rebalance: buy underweight, sell overweight
        for d in drifts:
            if abs(d["drift"]) >= 0.02 and total_value > 0:  # only act on > 2% drift
                action = "sell" if d["drift"] > 0 else "buy"
                estimated_value = abs(d["drift"]) * total_value
                trades.append({
                    "symbol": d["symbol"],
                    "action": action,
                    "qty_needed": None,
                    "estimated_value": round(estimated_value, 2),
                })

    max_drift = max((abs(d["drift"]) for d in drifts), default=0.0)
    summary = (
        f"Your portfolio has drifted up to {round(max_drift * 100, 1)}% from target. "
        f"Rebalancing {len(trades)} position(s) will bring you back to your target allocation."
    )

    return {
        "trigger": trigger,
        "trades": trades,
        "summary": summary,
        "taxes_triggered": 0.0,
    }


# ---------------------------------------------------------------------------
# GET /api/robo/direct-index/info
# ---------------------------------------------------------------------------

@router.get("/direct-index/info")
def direct_index_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return DirectIndexPortfolio info, or indicate it's unavailable."""
    core = db.query(CorePortfolio).filter(CorePortfolio.user_id == current_user.id).first()
    min_value = core.direct_index_min_value if core else 25000.0

    di = db.query(DirectIndexPortfolio).filter(
        DirectIndexPortfolio.user_id == current_user.id
    ).first()

    if not di:
        return {
            "available": False,
            "minimum": min_value,
            "message": f"Direct indexing is available for accounts with ${min_value:,.0f}+ in core portfolio.",
        }

    return {
        "available": True,
        "id": di.id,
        "total_value": di.total_value,
        "tracking_error_pct": di.tracking_error_pct,
        "num_positions": di.num_positions,
        "sector_exclusions": json.loads(di.sector_exclusions) if di.sector_exclusions else [],
        "ticker_exclusions": json.loads(di.ticker_exclusions) if di.ticker_exclusions else [],
        "tilts": json.loads(di.tilts) if di.tilts else {},
        "last_rebalanced_at": di.last_rebalanced_at.isoformat() if di.last_rebalanced_at else None,
        "ytd_harvested_losses": di.ytd_harvested_losses,
        "estimated_tax_savings": di.estimated_tax_savings,
    }


# ---------------------------------------------------------------------------
# POST /api/robo/direct-index/customize
# ---------------------------------------------------------------------------

@router.post("/direct-index/customize")
def direct_index_customize(
    body: DirectIndexCustomizeBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update direct index customization. Uses Anthropic if nl_prompt provided."""
    di = db.query(DirectIndexPortfolio).filter(
        DirectIndexPortfolio.user_id == current_user.id
    ).first()
    if not di:
        # Create a stub entry
        di = DirectIndexPortfolio(user_id=current_user.id, total_value=0.0)
        db.add(di)

    # If NL prompt provided, parse it (Anthropic or regex fallback)
    if body.nl_prompt:
        parsed = _call_anthropic_parse(body.nl_prompt)
        sector_excl = parsed.get("exclude_sectors", [])
        ticker_excl = parsed.get("exclude_tickers", [])
        tilts_data = parsed.get("tilts", {})
    else:
        sector_excl = body.sector_exclusions or []
        ticker_excl = body.ticker_exclusions or []
        tilts_data = body.tilts or {}

    # Merge with any existing (override)
    if body.sector_exclusions:
        sector_excl = body.sector_exclusions
    if body.ticker_exclusions:
        ticker_excl = body.ticker_exclusions
    if body.tilts:
        tilts_data = {**tilts_data, **body.tilts}

    di.sector_exclusions = json.dumps(sector_excl)
    di.ticker_exclusions = json.dumps(ticker_excl)
    di.tilts = json.dumps(tilts_data)
    di.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(di)

    return {
        "sector_exclusions": sector_excl,
        "ticker_exclusions": ticker_excl,
        "tilts": tilts_data,
        "total_value": di.total_value,
        "tracking_error_pct": di.tracking_error_pct,
        "ytd_harvested_losses": di.ytd_harvested_losses,
        "estimated_tax_savings": di.estimated_tax_savings,
    }


# ---------------------------------------------------------------------------
# GET /api/robo/wash-sale/check/{symbol}
# ---------------------------------------------------------------------------

@router.get("/wash-sale/check/{symbol}")
def wash_sale_check(
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Check if a symbol is blocked by wash-sale rules for this user."""
    today = date.today()
    cutoff = today - timedelta(days=31)

    guard = (
        db.query(WashSaleGuard)
        .filter(
            WashSaleGuard.user_id == current_user.id,
            WashSaleGuard.symbol == symbol.upper(),
            WashSaleGuard.sold_at >= cutoff,
        )
        .order_by(WashSaleGuard.sold_at.desc())
        .first()
    )

    if not guard:
        return {"blocked": False, "safe_after": None, "loss_amount": None}

    blocked = guard.wash_sale_safe_after > today
    return {
        "blocked": blocked,
        "safe_after": guard.wash_sale_safe_after.isoformat(),
        "loss_amount": guard.loss_amount,
    }


# ---------------------------------------------------------------------------
# POST /api/robo/ai/explain
# ---------------------------------------------------------------------------

@router.post("/ai/explain")
def ai_explain(
    body: AiExplainBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate a 2-sentence plain-English explanation using claude-haiku."""

    context_prompts = {
        "rebalance": (
            "The user's portfolio was rebalanced. Here is the summary data: {data}. "
            "Explain what happened and why it benefits them."
        ),
        "volatility": (
            "The user's portfolio experienced significant volatility. Data: {data}. "
            "Explain what happened in a calm, reassuring way."
        ),
        "goal": (
            "The user has a financial goal with the following status: {data}. "
            "Explain their progress and what they can do to stay on track."
        ),
        "tax": (
            "The user has tax-loss harvesting activity. Data: {data}. "
            "Explain what tax-loss harvesting is and how it helps them."
        ),
    }

    template = context_prompts.get(
        body.context,
        "The user has the following financial data: {data}. Provide a brief explanation."
    )
    user_message = template.format(data=json.dumps(body.data))

    # SHIP 3 R5: render explanation via template (no LLM)
    try:
        from app.services.robo_templates import render_robo_rationale
        allocations_list = [
            {"symbol": k, "weight": v}
            for k, v in (body.data if isinstance(body.data, dict) else {}).items()
        ] if hasattr(body, "data") and isinstance(body.data, dict) else []
        risk = body.context if hasattr(body, "context") else "moderate"
        explanation = render_robo_rationale(allocations_list, risk=risk, horizon=10)
    except Exception as e:
        logger.warning("robo_templates render failed: %s", e)
        explanation = (
            "Your portfolio is being managed according to your risk profile and goals. "
            "Continue making regular contributions and your strategy will compound over time."
        )

    return {"explanation": explanation}


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_core(core: CorePortfolio) -> Dict[str, Any]:
    return {
        "id": core.id,
        "total_value": core.total_value,
        "ytd_return_pct": core.ytd_return_pct,
        "target_allocation": json.loads(core.target_allocation) if core.target_allocation else {},
        "current_allocation": json.loads(core.current_allocation) if core.current_allocation else {},
        "last_rebalanced_at": core.last_rebalanced_at.isoformat() if core.last_rebalanced_at else None,
        "rebalance_needed": core.rebalance_needed,
        "drift_pct": core.drift_pct,
        "direct_index_enabled": core.direct_index_enabled,
        "direct_index_min_value": core.direct_index_min_value,
    }


def _serialize_goal(goal: RoboGoal) -> Dict[str, Any]:
    today = date.today()
    days_remaining = None
    on_track_monthly_needed = None

    if goal.target_date:
        days_remaining = max(0, (goal.target_date - today).days)
        months_remaining = max(1, days_remaining // 30)
        # Rough monthly needed assuming 6% annual return
        r = 0.06 / 12
        if r > 0 and months_remaining > 0:
            fv_current = goal.current_balance * ((1 + r) ** months_remaining)
            remaining = goal.target_amount - fv_current
            if remaining > 0:
                on_track_monthly_needed = round(
                    remaining * r / ((1 + r) ** months_remaining - 1), 2
                )
            else:
                on_track_monthly_needed = 0.0

    return {
        "id": goal.id,
        "name": goal.name,
        "goal_type": goal.goal_type,
        "target_amount": goal.target_amount,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "current_balance": goal.current_balance,
        "monthly_contribution": goal.monthly_contribution,
        "status": goal.status,
        "probability_pct": goal.probability_pct,
        "glide_path": goal.glide_path_list(),
        "notes": goal.notes,
        "days_remaining": days_remaining,
        "on_track_monthly_needed": on_track_monthly_needed,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }
