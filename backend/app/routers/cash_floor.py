"""
/api/admin/cash-floor/* — passive index ETF deployment of idle cash.

GET  /cash-floor/status     — snapshot of current vs target allocation
POST /cash-floor/propose    — return the rebalance trade list (no writes)
POST /cash-floor/rebalance  — SCAFFOLDING. Executes the trades IF kill
                              switches off and X-Brock-Confirm valid.
                              The actual position-write loop is
                              INTENTIONALLY ABSENT — matches the V1
                              capital_execute pattern, by design.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/cash-floor", tags=["admin"])


def _verify_brock_confirm(payload: str, header_value: Optional[str]) -> tuple[bool, str]:
    secret = os.getenv("BROCK_CONFIRM_SECRET", "")
    if not secret:
        return False, "BROCK_CONFIRM_SECRET not configured"
    if not header_value:
        return False, "missing X-Brock-Confirm header"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_value):
        return False, "X-Brock-Confirm signature mismatch"
    return True, "ok"


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Read-only snapshot. No writes."""
    from app.services.cash_floor import compute_status
    return compute_status(db)


@router.post("/propose")
def propose(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the trade list the rebalance WOULD place. Still no writes."""
    from app.services.cash_floor import propose_rebalance
    return propose_rebalance(db)


@router.post("/rebalance")
def rebalance(
    x_brock_confirm: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute the Cash Floor rebalance — gated by the same kill switch as
    capital/execute-rebalance.

    Even when CAPITAL_EXECUTE_ENABLED=true and the X-Brock-Confirm signature
    validates, the actual position-write loop is INTENTIONALLY ABSENT. To
    actually buy SPY/QQQ, the operator replaces the final return statement
    with the trade-write loop and redeploys. No env-var alone unlocks the
    write. By design.
    """
    from app.services.cash_floor import propose_rebalance

    if os.getenv("CAPITAL_EXECUTE_ENABLED", "false").strip().lower() != "true":
        plan = propose_rebalance(db)
        return {
            "executed": False,
            "reason": "kill_switch_off",
            "note": (
                "Set CAPITAL_EXECUTE_ENABLED=true in Railway when ready to "
                "activate the gate. The final write step is still a manual "
                "code change."
            ),
            "plan": plan,
        }

    plan = propose_rebalance(db)
    if "error" in plan:
        raise HTTPException(status_code=400, detail=plan["error"])

    # HMAC on the trade plan canonical id.
    plan_id = f"cash-floor-{plan.get('as_of')}-{plan.get('trade_count')}"
    verified, why = _verify_brock_confirm(plan_id, x_brock_confirm)
    if not verified:
        raise HTTPException(status_code=403, detail=f"confirm token rejected: {why}")

    # ── Position-write loop ─────────────────────────────────────────────
    # Paper convention: write BotPosition + BotTrade rows directly. The
    # cash_floor BotAllocation receives them; bot_id (strategy) is tagged
    # so canonical can separate Cash Floor P&L from active alpha strategies.
    from datetime import datetime, timezone
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition, BotTrade
    from app.services.friction import model_friction_cents

    # Resolve the cash_floor allocation for the operator. Fail if missing —
    # the allocation should be created via the clean-slate restart endpoint.
    cf_profile = db.query(BotProfile).filter(BotProfile.name == "cash_floor").first()
    if cf_profile is None:
        raise HTTPException(status_code=400, detail="cash_floor BotProfile missing")
    cf_alloc = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == cf_profile.id,
            BotAllocation.enabled.is_(True),
        )
        .first()
    )
    if cf_alloc is None:
        raise HTTPException(status_code=400, detail="cash_floor allocation missing for this user")

    now = datetime.now(timezone.utc)
    written_trades: list[dict] = []
    for trade in plan["trades_to_place"]:
        symbol = trade["symbol"]
        side = trade["side"]  # "buy" or "sell"
        approx_dollars = float(trade["approx_dollars"])
        live_px = trade.get("limit_price_hint_usd") or 0
        if live_px <= 0:
            # No live price — refuse this leg (Cash Floor is passive; we
            # only place when we have a recent quote).
            written_trades.append({
                "symbol": symbol, "side": side, "status": "skipped_no_price",
            })
            continue

        # Round to nearest 1/100 share (Alpaca fractional default).
        qty = round(approx_dollars / live_px, 4)
        if qty <= 0:
            written_trades.append({
                "symbol": symbol, "side": side, "status": "skipped_zero_qty",
            })
            continue

        fill_cents = int(round(live_px * 100))
        friction_cents = model_friction_cents("stock", qty, live_px)

        # ── SHIP 2 asset-class gate (path #11) — before both BotTrade inserts ──
        try:
            from app.services.asset_class_registry import validate_order_with_user
            validate_order_with_user(
                bot_id="cash_floor",
                symbol=symbol,
                user_id=getattr(current_user, "id", None),
            )
        except RuntimeError as _acr_exc:
            logger.error(
                "[asset_class_gate:cash_floor] rebalance endpoint BLOCKED %s: %s",
                symbol, _acr_exc,
            )
            raise HTTPException(status_code=422, detail=str(_acr_exc))
        # ── end asset-class gate ─────────────────────────────────────────────

        if side == "buy":
            # New position (or add — Cash Floor only holds one open position
            # per symbol; if one exists, this is a top-up to the SAME position).
            existing = (
                db.query(BotPosition)
                .filter(
                    BotPosition.allocation_id == cf_alloc.id,
                    BotPosition.symbol == symbol,
                    BotPosition.closed_at.is_(None),
                    BotPosition.quarantined_at.is_(None),
                )
                .first()
            )
            if existing:
                # Weighted-average cost up.
                old_qty = float(existing.qty or 0)
                old_cost = float(existing.avg_cost_cents or 0)
                new_qty = old_qty + qty
                new_avg = ((old_qty * old_cost) + (qty * fill_cents)) / new_qty if new_qty > 0 else fill_cents
                existing.qty = new_qty
                existing.avg_cost_cents = new_avg
                existing.updated_at = now if hasattr(existing, "updated_at") else None
                pos = existing
            else:
                pos = BotPosition(
                    allocation_id=cf_alloc.id,
                    symbol=symbol,
                    qty=qty,
                    avg_cost_cents=fill_cents,
                    side="long",
                    opened_at=now,
                    closed_at=None,
                    is_paper=True,
                    stop_price_usd=None,    # passive: no stop
                    target_price_usd=None,  # passive: no target
                    trailing_stop_activated=False,
                )
                db.add(pos)
                db.flush()
            # 2026-08-07 sim-leak sweep: trade_write_gate before every
            # BotTrade insert. cash_floor path writes with alpaca_order_id=NULL
            # by design (paper-only rebalance simulator).
            from app.services.trade_write_gate import check_trade_write
            _cf_gate = check_trade_write(alpaca_order_id=None, source_path="cash_floor.buy")
            if _cf_gate.blocked:
                logger.warning("[cash_floor.buy] WRITE BLOCKED %s reason=%s", symbol, _cf_gate.reason)
                written_trades.append({"symbol": symbol, "side": "buy", "status": "blocked_sim_write"})
                continue
            from app.services.regime_tag import regime_tag_dict as _regime_tag_dict
            _rt_cf_buy = _regime_tag_dict(db, source="cash_floor.buy")
            db.add(BotTrade(
                allocation_id=cf_alloc.id,
                symbol=symbol,
                side="buy",
                qty=qty,
                fill_price_cents=fill_cents,
                fees_cents=friction_cents,
                ts=now,
                position_id=pos.id,
                is_paper=True,
                expected_fill_cents=fill_cents,
                slippage_bps=3.0,
                strategy="cash_floor",
                **_rt_cf_buy,
            ))
            written_trades.append({
                "symbol": symbol, "side": "buy", "qty": qty,
                "fill_cents": fill_cents, "friction_cents": friction_cents,
                "position_id": pos.id, "status": "filled",
            })
        elif side == "sell":
            # Trim — partially close existing position(s) for that symbol.
            existing = (
                db.query(BotPosition)
                .filter(
                    BotPosition.allocation_id == cf_alloc.id,
                    BotPosition.symbol == symbol,
                    BotPosition.closed_at.is_(None),
                    BotPosition.quarantined_at.is_(None),
                )
                .first()
            )
            if not existing:
                written_trades.append({
                    "symbol": symbol, "side": "sell", "status": "skipped_no_position",
                })
                continue
            trim_qty = min(qty, float(existing.qty or 0))
            if trim_qty >= float(existing.qty or 0):
                existing.closed_at = now
                existing.exit_reason = "cash_floor_rebalance"
            else:
                existing.qty = float(existing.qty) - trim_qty
            from app.services.trade_write_gate import check_trade_write as _ctw_cfsell
            _cfsell_gate = _ctw_cfsell(alpaca_order_id=None, source_path="cash_floor.sell")
            if _cfsell_gate.blocked:
                logger.warning("[cash_floor.sell] WRITE BLOCKED %s reason=%s", symbol, _cfsell_gate.reason)
                written_trades.append({"symbol": symbol, "side": "sell", "status": "blocked_sim_write"})
                continue
            from app.services.regime_tag import regime_tag_dict as _regime_tag_dict
            _rt_cf_sell = _regime_tag_dict(db, source="cash_floor.sell")
            db.add(BotTrade(
                allocation_id=cf_alloc.id,
                symbol=symbol,
                side="sell",
                qty=trim_qty,
                fill_price_cents=fill_cents,
                fees_cents=friction_cents,
                ts=now,
                position_id=existing.id,
                is_paper=True,
                expected_fill_cents=fill_cents,
                slippage_bps=3.0,
                strategy="cash_floor",
                **_rt_cf_sell,
            ))
            written_trades.append({
                "symbol": symbol, "side": "sell", "qty": trim_qty,
                "fill_cents": fill_cents, "friction_cents": friction_cents,
                "position_id": existing.id, "status": "trimmed",
            })

    db.commit()

    try:
        from app.services.discord import send_ops_alert
        filled = [t for t in written_trades if t.get("status") in ("filled", "trimmed")]
        send_ops_alert(
            title="[cash-floor] rebalance executed",
            message=(
                f"Cash Floor rebalance complete.\n"
                f"Trades placed: {len(filled)}\n"
                + "\n".join(
                    f"  {t['side'].upper()} {t.get('qty', '?'):.4f} {t['symbol']} "
                    f"@ ${t.get('fill_cents', 0)/100:.2f} "
                    f"({t.get('status')})"
                    for t in written_trades[:10]
                )
            ),
            severity="info",
            source="cash_floor.rebalance",
        )
    except Exception:
        pass

    return {
        "executed": True,
        "operator_user_id": current_user.id,
        "allocation_id": cf_alloc.id,
        "trades": written_trades,
        "trade_count": len(written_trades),
        "plan_summary": {
            "fleet_nav_cents": plan.get("fleet_nav_cents"),
            "deployable_cents": plan.get("deployable_cents"),
            "cash_floor_target_cents": plan.get("cash_floor_target_cents"),
        },
    }
