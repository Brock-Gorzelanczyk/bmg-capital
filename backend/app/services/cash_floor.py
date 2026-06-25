"""
Cash Floor — passive index-ETF deployment of idle capital.

Rule (per Brock's spec for the 7-day deployment push):
  - Maintain a 25% cash floor.
  - Any cash above that goes 60% SPY / 40% QQQ.
  - Daily rebalance at market close — top up or trim to maintain the floor.
  - Pure beta exposure. No stops, no targets, no signals, no alpha claim.
  - When active strategies need capital, Cash Floor unwinds FIRST.

Outputs a target_allocation dict the operator reviews. Actual position
writes happen behind the same gated execute path as the vol-targeting
allocator (kill switch + Brock-confirm + drawdown checks) — see
backend/app/routers/cash_floor.py.

This module is pure compute. No DB writes. No signal posting.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# Rule constants (greenlit by Brock)
CASH_FLOOR_PCT = 0.25            # never deploy below this from cash
SPY_WEIGHT = 0.60
QQQ_WEIGHT = 0.40
SYMBOLS = ("SPY", "QQQ")


def _fleet_nav_cents(db: Session) -> Optional[int]:
    try:
        row = db.execute(sql_text(
            "SELECT nav_cents FROM nav_history ORDER BY date DESC LIMIT 1"
        )).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception as exc:
        logger.warning("[cash_floor] fleet_nav lookup failed: %s", exc)
        return None


def _current_active_deployment_cents(db: Session) -> int:
    """Sum entry-cost notional across open positions EXCLUDING Cash Floor.

    Cash Floor positions are tagged via the strategy column on bot_trades —
    'cash_floor' — so we can subtract them out and avoid double-counting.
    """
    try:
        row = db.execute(sql_text("""
            SELECT COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0)
              FROM bot_positions bp
              LEFT JOIN bot_trades bt ON bt.position_id = bp.id
             WHERE bp.closed_at IS NULL
               AND bp.quarantined_at IS NULL
               AND COALESCE(bt.strategy, '') != 'cash_floor'
        """)).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logger.warning("[cash_floor] active_deployment lookup failed: %s", exc)
        return 0


def _cash_floor_position(db: Session, symbol: str) -> dict:
    """Read the current open Cash Floor position for a symbol (sum across rows)."""
    try:
        row = db.execute(sql_text("""
            SELECT COALESCE(SUM(bp.qty), 0) AS qty,
                   COALESCE(MAX(bp.avg_cost_cents), 0) AS avg_cost_cents
              FROM bot_positions bp
              LEFT JOIN bot_trades bt ON bt.position_id = bp.id
             WHERE bp.symbol = :sym
               AND bp.closed_at IS NULL
               AND bp.quarantined_at IS NULL
               AND bt.strategy = 'cash_floor'
        """), {"sym": symbol}).fetchone()
        qty = float(row[0]) if row else 0.0
        avg_cost_cents = int(row[1]) if row else 0
        return {
            "symbol": symbol,
            "qty": qty,
            "avg_cost_cents": avg_cost_cents,
            "notional_cents": int(qty * avg_cost_cents),
        }
    except Exception as exc:
        logger.warning("[cash_floor] position lookup failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "qty": 0.0, "avg_cost_cents": 0, "notional_cents": 0}


def _live_price_dollars(symbol: str) -> Optional[float]:
    """Best-effort live price for SPY/QQQ. None if unavailable."""
    try:
        from app.services.live_prices import fetch_live_prices
        prices = fetch_live_prices([symbol])
        p = prices.get(symbol)
        return float(p) if p and p > 0 else None
    except Exception as exc:
        logger.debug("[cash_floor] live price for %s unavailable: %s", symbol, exc)
        return None


def compute_status(db: Session) -> dict[str, Any]:
    """Snapshot of the Cash Floor rule's current state vs target.

    Returns the diagnostic shape used by both /admin/cash-floor/status
    and the Diagnostics console card. No mutations.
    """
    fleet_nav = _fleet_nav_cents(db)
    if fleet_nav is None or fleet_nav <= 0:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": "fleet_nav_unavailable",
            "fleet_nav_cents": fleet_nav,
        }

    active_deployment = _current_active_deployment_cents(db)
    cash_floor_target_cents = int(fleet_nav * CASH_FLOOR_PCT)

    # Deployable cash = fleet_nav - active_deployment - cash_floor_target
    deployable_cents = fleet_nav - active_deployment - cash_floor_target_cents
    deployable_cents = max(0, deployable_cents)

    spy_target_cents = int(deployable_cents * SPY_WEIGHT)
    qqq_target_cents = int(deployable_cents * QQQ_WEIGHT)

    spy_pos = _cash_floor_position(db, "SPY")
    qqq_pos = _cash_floor_position(db, "QQQ")
    held_spy_cents = spy_pos["notional_cents"]
    held_qqq_cents = qqq_pos["notional_cents"]
    held_total_cents = held_spy_cents + held_qqq_cents

    spy_px = _live_price_dollars("SPY")
    qqq_px = _live_price_dollars("QQQ")

    # Drift = held vs target. Positive = need to BUY. Negative = need to TRIM.
    spy_drift_cents = spy_target_cents - held_spy_cents
    qqq_drift_cents = qqq_target_cents - held_qqq_cents

    # Implied trade size in shares if we executed now.
    spy_drift_shares = (spy_drift_cents / 100 / spy_px) if (spy_px and spy_px > 0) else None
    qqq_drift_shares = (qqq_drift_cents / 100 / qqq_px) if (qqq_px and qqq_px > 0) else None

    actual_cash_pct = max(0.0, fleet_nav - active_deployment - held_total_cents) / fleet_nav

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "fleet_nav_cents": fleet_nav,
        "active_deployment_cents": active_deployment,
        "cash_floor_target_pct": CASH_FLOOR_PCT * 100,
        "cash_floor_target_cents": cash_floor_target_cents,
        "actual_cash_pct": round(actual_cash_pct * 100, 3),
        "deployable_cents": deployable_cents,
        "target_allocation": {
            "spy_target_cents": spy_target_cents,
            "qqq_target_cents": qqq_target_cents,
            "spy_weight_pct": SPY_WEIGHT * 100,
            "qqq_weight_pct": QQQ_WEIGHT * 100,
        },
        "current_positions": [
            {
                **spy_pos,
                "target_cents": spy_target_cents,
                "drift_cents": spy_drift_cents,
                "drift_shares": spy_drift_shares,
                "live_price_usd": spy_px,
            },
            {
                **qqq_pos,
                "target_cents": qqq_target_cents,
                "drift_cents": qqq_drift_cents,
                "drift_shares": qqq_drift_shares,
                "live_price_usd": qqq_px,
            },
        ],
        "total_cash_floor_holding_cents": held_total_cents,
        "cash_floor_pct_of_fleet": round(held_total_cents / fleet_nav * 100, 3),
        "needs_buy": bool(spy_drift_cents > 0 or qqq_drift_cents > 0),
        "needs_trim": bool(spy_drift_cents < 0 or qqq_drift_cents < 0),
    }


def propose_rebalance(db: Session) -> dict[str, Any]:
    """Return the rebalance proposal — what trades the rule would generate.

    Pure plan, no writes. Mirrors compute_status() but adds an explicit
    `trades_to_place` list the executor would consume if activated.
    """
    s = compute_status(db)
    if "error" in s:
        return {**s, "trades_to_place": []}

    trades = []
    for pos in s["current_positions"]:
        drift_cents = pos["drift_cents"]
        drift_shares = pos["drift_shares"]
        if abs(drift_cents) < 1000:  # less than $10 — skip noise
            continue
        side = "buy" if drift_cents > 0 else "sell"
        trades.append({
            "symbol": pos["symbol"],
            "side": side,
            "approx_dollars": abs(drift_cents) / 100,
            "approx_shares": abs(drift_shares) if drift_shares else None,
            "limit_price_hint_usd": pos["live_price_usd"],
            "strategy_tag": "cash_floor",
        })

    return {
        **s,
        "trades_to_place": trades,
        "trade_count": len(trades),
    }
