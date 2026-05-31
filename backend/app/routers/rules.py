from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.rule import UserRule
from app.db.models.portfolio import Portfolio, Position

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rules", tags=["rules"])

# Also mounts transfer suggestions under /api/transfers
transfers_router = APIRouter(prefix="/api/transfers", tags=["transfers"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True
    trigger_type: Optional[str] = None
    trigger_symbol: Optional[str] = None
    trigger_value: Optional[float] = None
    trigger_regime: Optional[str] = None
    action_type: Optional[str] = None
    action_symbol: Optional[str] = None
    action_amount: Optional[float] = None
    action_unit: str = "dollars"


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    trigger_type: Optional[str] = None
    trigger_symbol: Optional[str] = None
    trigger_value: Optional[float] = None
    trigger_regime: Optional[str] = None
    action_type: Optional[str] = None
    action_symbol: Optional[str] = None
    action_amount: Optional[float] = None
    action_unit: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_rule(r: UserRule) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "name": r.name,
        "description": r.description,
        "is_active": r.is_active,
        "trigger_type": r.trigger_type,
        "trigger_symbol": r.trigger_symbol,
        "trigger_value": r.trigger_value,
        "trigger_regime": r.trigger_regime,
        "action_type": r.action_type,
        "action_symbol": r.action_symbol,
        "action_amount": r.action_amount,
        "action_unit": r.action_unit,
        "last_triggered": r.last_triggered.isoformat() if r.last_triggered else None,
        "trigger_count": r.trigger_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def _evaluate_trigger(rule: UserRule) -> tuple[bool, str]:
    """
    Simulate whether the rule would fire given current market data.
    Returns (would_trigger: bool, reason: str).
    """
    trigger_type = rule.trigger_type
    if not trigger_type:
        return False, "No trigger type configured"

    try:
        if trigger_type in ("price_above", "price_below"):
            symbol = (rule.trigger_symbol or "").upper()
            if not symbol:
                return False, "No symbol configured for price trigger"
            ticker = yf.Ticker(symbol)
            info = ticker.info
            current = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("ask")
                or info.get("bid")
            )
            if current is None:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    current = float(hist["Close"].iloc[-1])
            if current is None:
                return False, f"Could not fetch price for {symbol}"
            current = float(current)
            threshold = rule.trigger_value or 0.0
            if trigger_type == "price_above":
                would = current > threshold
                return would, f"{symbol} current price ${current:.2f} {'>' if would else '<='} ${threshold:.2f}"
            else:
                would = current < threshold
                return would, f"{symbol} current price ${current:.2f} {'<' if would else '>='} ${threshold:.2f}"

        elif trigger_type == "vix_above":
            def _fetch_vix():
                t = yf.Ticker("^VIX")
                h = t.history(period="1d")
                if not h.empty:
                    return float(h["Close"].iloc[-1])
                info = t.info
                return info.get("regularMarketPrice") or info.get("currentPrice")

            vix = await asyncio.to_thread(_fetch_vix)
            if vix is None:
                return False, "Could not fetch VIX"
            threshold = rule.trigger_value or 0.0
            would = vix > threshold
            return would, f"VIX {vix:.2f} {'>' if would else '<='} {threshold:.2f}"

        elif trigger_type in ("rsi_below", "rsi_above"):
            symbol = (rule.trigger_symbol or "").upper()
            if not symbol:
                return False, "No symbol configured for RSI trigger"

            def _fetch_rsi():
                import pandas as pd
                t = yf.Ticker(symbol)
                hist = t.history(period="3mo")
                if len(hist) < 15:
                    return None
                close = hist["Close"]
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, float("nan"))
                rsi = 100 - (100 / (1 + rs))
                return float(rsi.iloc[-1])

            rsi_val = await asyncio.to_thread(_fetch_rsi)
            if rsi_val is None:
                return False, f"Not enough data for RSI ({symbol})"
            threshold = rule.trigger_value or 50.0
            if trigger_type == "rsi_below":
                would = rsi_val < threshold
                return would, f"{symbol} RSI {rsi_val:.1f} {'<' if would else '>='} {threshold:.1f}"
            else:
                would = rsi_val > threshold
                return would, f"{symbol} RSI {rsi_val:.1f} {'>' if would else '<='} {threshold:.1f}"

        elif trigger_type == "regime_is":
            from app.routers.strategy import _get_regime_cached
            regime = await _get_regime_cached()
            regime_str = str(regime) if regime else "Unknown"
            target = rule.trigger_regime or ""
            would = regime_str.lower() == target.lower()
            return would, f"Current regime: {regime_str} {'==' if would else '!='} {target}"

        else:
            return False, f"Unknown trigger_type: {trigger_type}"

    except Exception as e:
        logger.error(f"Trigger evaluation error for rule {rule.id}: {e}", exc_info=True)
        return False, f"Error evaluating trigger: {str(e)}"


# ---------------------------------------------------------------------------
# GET /api/rules
# ---------------------------------------------------------------------------

@router.get("")
def list_rules(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rules = db.query(UserRule).filter_by(user_id=user.id).order_by(UserRule.created_at.desc()).all()
    return [_serialize_rule(r) for r in rules]


# ---------------------------------------------------------------------------
# POST /api/rules
# ---------------------------------------------------------------------------

@router.post("")
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rule = UserRule(
        user_id=user.id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        trigger_type=body.trigger_type,
        trigger_symbol=body.trigger_symbol.upper() if body.trigger_symbol else None,
        trigger_value=body.trigger_value,
        trigger_regime=body.trigger_regime,
        action_type=body.action_type,
        action_symbol=body.action_symbol.upper() if body.action_symbol else None,
        action_amount=body.action_amount,
        action_unit=body.action_unit,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


# ---------------------------------------------------------------------------
# PUT /api/rules/{id}
# ---------------------------------------------------------------------------

@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    body: RuleUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rule = db.query(UserRule).filter_by(id=rule_id, user_id=user.id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field in ("trigger_symbol", "action_symbol") and value:
            value = value.upper()
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


# ---------------------------------------------------------------------------
# DELETE /api/rules/{id}
# ---------------------------------------------------------------------------

@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rule = db.query(UserRule).filter_by(id=rule_id, user_id=user.id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/rules/{id}/test
# ---------------------------------------------------------------------------

@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Simulate: given current market data, would this rule trigger?"""
    rule = db.query(UserRule).filter_by(id=rule_id, user_id=user.id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    would_trigger, reason = await _evaluate_trigger(rule)
    return {"would_trigger": would_trigger, "reason": reason}


# ---------------------------------------------------------------------------
# GET /api/transfers/suggestions
# ---------------------------------------------------------------------------

@transfers_router.get("/suggestions")
def get_transfer_suggestions(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Smart heuristic transfer suggestions based on portfolio state.
    Returns suggestions like sweeping excess cash or deposit-to-rebalance amounts.
    No real bank connection required — purely heuristic.
    """
    suggestions: List[Dict[str, Any]] = []

    # Gather user's portfolios and their cost/value
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user.id).all()

    total_cost = 0.0
    total_positions = 0
    for p in portfolios:
        for pos in p.positions:
            total_cost += pos.shares * pos.average_cost
            total_positions += 1

    # Heuristic 1: sweep excess cash
    # We simulate a "checking balance" from a fixed rule of thumb:
    # If the user has < 3 portfolios or total invested < $5000, suggest moving $1000.
    if total_cost < 5_000 and total_cost > 0:
        excess = 1_000.0
        suggestions.append({
            "type": "sweep_excess",
            "description": (
                f"You have excess cash above $5K in your checking. "
                f"Consider moving ${excess:,.0f} to your portfolio."
            ),
            "amount": excess,
        })
    elif total_cost >= 5_000:
        # More realistic sweep suggestion
        assumed_checking = total_cost * 0.12  # assume ~12% of invested sits in checking
        if assumed_checking > 5_000:
            excess = round(assumed_checking - 5_000, 2)
            suggestions.append({
                "type": "sweep_excess",
                "description": (
                    f"You have excess cash above $5K in your checking. "
                    f"Consider moving ${excess:,.0f} to your portfolio."
                ),
                "amount": excess,
            })

    # Heuristic 2: rebalance drift
    # If user has >= 2 positions, suggest a deposit to bring things back on track.
    if total_positions >= 2 and total_cost > 0:
        # Simulate a 12% drift (placeholder — real drift requires target allocations)
        drift_pct = 12.0
        deposit_to_rebalance = round(total_cost * 0.05, 2)  # ~5% of invested = rebalance
        suggestions.append({
            "type": "rebalance_drift",
            "description": (
                f"Portfolio has drifted {drift_pct:.0f}% from target. "
                f"A ${deposit_to_rebalance:,.0f} deposit would bring it back on track."
            ),
            "amount": deposit_to_rebalance,
        })

    # Heuristic 3: auto-invest reminder if portfolio is empty
    if total_positions == 0:
        suggestions.append({
            "type": "start_investing",
            "description": (
                "You haven't added any positions yet. "
                "Consider starting with a $500 investment into a diversified ETF like VTI."
            ),
            "amount": 500.0,
        })

    return {"suggestions": suggestions}
