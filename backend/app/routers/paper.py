from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.paper import (
    PaperAccount,
    PaperDailySnapshot,
    PaperOrder,
    PaperPosition,
    PaperTransaction,
    STARTING_BALANCE,
)
from app.services.fill_simulator import get_quote, simulate_fill

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/paper", tags=["paper"])


# ---------------------------------------------------------------------------
# Decimal helpers (H20)
# ---------------------------------------------------------------------------

def _d(v) -> Decimal:
    """Convert float/int/str to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal("0")


def _money(v: Decimal) -> float:
    """Round to 4dp for storage; 2dp display happens in serializer."""
    return float(v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_or_create_account(db: Session, user_id: int) -> PaperAccount:
    acct = db.query(PaperAccount).filter_by(user_id=user_id).first()
    if not acct:
        acct = PaperAccount(
            user_id=user_id,
            cash=STARTING_BALANCE,
            starting_balance=STARTING_BALANCE,
        )
        db.add(acct)
        db.commit()
        db.refresh(acct)
    return acct


def _serialize_order(o: PaperOrder) -> dict:
    return {
        "id": o.id,
        "symbol": o.symbol,
        "side": o.side,
        "qty": o.qty,
        "notional": o.notional,
        "order_type": o.order_type,
        "limit_price": o.limit_price,
        "stop_price": o.stop_price,
        "take_profit_price": o.take_profit_price,
        "stop_loss_price": o.stop_loss_price,
        "tif": o.tif,
        "extended_hours": o.extended_hours,
        "status": o.status,
        "fill_price": o.fill_price,
        "fill_qty": o.fill_qty,
        "slippage": o.slippage,
        "total": round((o.fill_price or 0) * (o.fill_qty or o.qty), 2),
        "reject_reason": o.reject_reason,
        "parent_order_id": o.parent_order_id,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
        "created_at": o.created_at.isoformat(),
    }


def _apply_fill_to_position(
    db: Session,
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    fill_price: float,
    prev_close: Optional[float],
    order_id: int,
) -> None:
    """Update PaperPosition and write PaperTransaction for sells."""
    if side == "buy":
        existing = db.query(PaperPosition).filter_by(user_id=user_id, symbol=symbol).first()
        if existing:
            old_cost = Decimal(str(existing.avg_cost))
            old_qty = Decimal(str(existing.qty))
            new_price = Decimal(str(fill_price))
            new_qty = Decimal(str(qty))
            total = old_qty + new_qty
            existing.avg_cost = float((old_cost * old_qty + new_price * new_qty) / total)
            existing.qty = float(total)
            if prev_close and existing.prev_close is None:
                existing.prev_close = prev_close
        else:
            pos = PaperPosition(
                user_id=user_id,
                symbol=symbol,
                qty=qty,
                avg_cost=fill_price,
                prev_close=prev_close,
            )
            db.add(pos)
    else:  # sell
        position = db.query(PaperPosition).filter_by(user_id=user_id, symbol=symbol).first()
        if not position:
            raise HTTPException(status_code=400, detail=f"No position found for {symbol}")
        if position.qty < qty - 1e-6:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient shares. Have {position.qty:.4f}, selling {qty:.4f}",
            )
        cost_basis = position.avg_cost
        # H20: use Decimal for realized P&L calculation
        realized_pnl = _money((_d(fill_price) - _d(cost_basis)) * _d(qty))
        txn = PaperTransaction(
            user_id=user_id,
            order_id=order_id,
            symbol=symbol,
            side="sell",
            qty=qty,
            fill_price=fill_price,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
        )
        db.add(txn)
        position.qty = round(position.qty - qty, 6)
        if position.qty < 0.0001:
            db.delete(position)


# ---------------------------------------------------------------------------
# GET /api/paper/account
# ---------------------------------------------------------------------------

@router.get("/account")
async def get_account(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Return account summary with live market values for all positions."""
    acct = _get_or_create_account(db, user.id)
    positions = db.query(PaperPosition).filter_by(user_id=user.id).all()

    # Fetch all quotes in parallel
    symbols = [p.symbol for p in positions]
    if symbols:
        quotes_list = await asyncio.gather(
            *[get_quote(s) for s in symbols], return_exceptions=True
        )
        quotes = {}
        for sym, q in zip(symbols, quotes_list):
            if isinstance(q, dict):
                quotes[sym] = q
    else:
        quotes = {}

    position_rows = []
    total_positions_value = 0.0
    day_pnl_total = 0.0

    for p in positions:
        q = quotes.get(p.symbol)
        stale = q is None  # H8: track if quote is missing
        if q:
            current_price = q["last"]
        else:
            current_price = getattr(p, "last_price", None) or p.avg_cost
            logger.warning(f"Quote fetch failed for {p.symbol}, using fallback price")
        prev_close = p.prev_close if p.prev_close is not None else (q["prev_close"] if q else p.avg_cost)

        # H20: use Decimal for all financial math
        d_price = _d(current_price)
        d_qty = _d(p.qty)
        d_avg_cost = _d(p.avg_cost)
        d_prev_close = _d(prev_close)

        market_value = _money(d_price * d_qty)
        cost_basis_total = _money(d_avg_cost * d_qty)
        d_unrealized_pnl = _d(market_value) - _d(cost_basis_total)
        unrealized_pnl = _money(d_unrealized_pnl)
        unrealized_pnl_pct = _money(d_unrealized_pnl / _d(cost_basis_total) * _d(100)) if cost_basis_total else 0.0

        d_pos_day_pnl = (d_price - d_prev_close) * d_qty
        pos_day_pnl = _money(d_pos_day_pnl)
        pos_day_pnl_pct = _money(d_pos_day_pnl / d_prev_close * _d(100)) if prev_close else 0.0

        total_positions_value += market_value
        day_pnl_total += pos_day_pnl

        position_rows.append({
            "id": p.id,
            "symbol": p.symbol,
            "qty": p.qty,
            "avg_cost": p.avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "cost_basis": cost_basis_total,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "day_pnl": pos_day_pnl,
            "day_pnl_pct": pos_day_pnl_pct,
            "prev_close": prev_close,
            "opened_at": p.opened_at.isoformat(),
            "price_stale": stale,  # H8: frontend warning indicator
        })

    d_equity = _d(acct.cash) + _d(total_positions_value)
    equity = _money(d_equity)
    d_total_pnl = d_equity - _d(acct.starting_balance)
    total_pnl = _money(d_total_pnl)
    total_pnl_pct = _money(d_total_pnl / _d(acct.starting_balance) * _d(100)) if acct.starting_balance else 0.0
    d_baseline = d_equity - _d(day_pnl_total)
    day_pnl_pct = _money(_d(day_pnl_total) / d_baseline * _d(100)) if float(d_baseline) > 0 else 0.0

    return {
        "cash": round(acct.cash, 2),
        "starting_balance": acct.starting_balance,
        "equity": equity,
        "day_pnl": round(day_pnl_total, 2),
        "day_pnl_pct": day_pnl_pct,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "created_at": acct.created_at.isoformat(),
        "positions": position_rows,
    }


# ---------------------------------------------------------------------------
# POST /api/paper/orders — place order
# ---------------------------------------------------------------------------

class OrderRequest(BaseModel):
    symbol: str
    side: str
    qty: Optional[float] = None
    notional: Optional[float] = None  # dollar-based; qty computed from price
    order_type: str = "market"        # market | limit | stop | stop_limit | trailing_stop
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None  # bracket TP leg
    stop_loss_price: Optional[float] = None    # bracket SL leg
    trailing_amount: Optional[float] = None
    trailing_type: Optional[str] = None        # amount | percent
    tif: str = "day"                           # day | gtc | ioc | fok
    extended_hours: bool = False

    @field_validator("side")
    @classmethod
    def validate_side(cls, v):
        if v not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        return v

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v):
        v = v.upper().strip()
        equity = re.match(r'^[A-Z]{1,5}$', v) or re.match(r'^[A-Z]{1,4}\.[A-Z]$', v)
        crypto = re.match(r'^[A-Z]{2,10}-USD$', v)
        if not equity and not crypto:
            raise ValueError("Invalid symbol format")
        return v

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v):
        allowed = ("market", "limit", "stop", "stop_limit", "trailing_stop")
        if v not in allowed:
            raise ValueError(f"order_type must be one of {allowed}")
        return v

    @field_validator("tif")
    @classmethod
    def validate_tif(cls, v):
        if v not in ("day", "gtc", "ioc", "fok"):
            raise ValueError("tif must be day | gtc | ioc | fok")
        return v


@router.post("/orders")
async def place_order(
    req: OrderRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Validate qty / notional
    if req.qty is None and req.notional is None:
        raise HTTPException(status_code=400, detail="Provide either qty or notional")
    if req.qty is not None and req.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be positive")
    if req.notional is not None and req.notional <= 0:
        raise HTTPException(status_code=400, detail="notional must be positive")
    if req.notional is not None and req.notional < 1.0:
        raise HTTPException(status_code=400, detail="Minimum order size is $1.00")

    acct = _get_or_create_account(db, user.id)

    # Always fetch a quote so we can compute qty from notional and validate limit orders
    quote = await get_quote(req.symbol)
    if not quote:
        raise HTTPException(status_code=400, detail=f"Could not fetch price for {req.symbol}")

    # Resolve qty from notional
    qty = req.qty
    if qty is None:
        ask = quote["ask"]
        qty = round(req.notional / ask, 6)
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Computed qty is zero — notional too small")

    now = datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # Market orders: fill immediately
    # -----------------------------------------------------------------------
    if req.order_type == "market":
        fill_price, slippage = simulate_fill(req.side, quote, "market")
        # H20: use Decimal for total cost calculation
        total_cost = _money(_d(fill_price) * _d(qty))

        if req.side == "buy":
            if acct.cash < total_cost:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient buying power. Need ${total_cost:,.2f}, have ${acct.cash:,.2f}",
                )
            _delta = -total_cost
            acct.cash = round(acct.cash - total_cost, 2)
            logger.info(f"CASH_CHANGE user={user.id} delta={_delta:.4f} new_balance={acct.cash:.4f} reason='market buy {req.symbol} qty={qty}'")
        else:
            position = db.query(PaperPosition).filter_by(user_id=user.id, symbol=req.symbol).first()
            if not position or position.qty < qty - 1e-6:
                have = position.qty if position else 0
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient shares. Have {have:.4f}, selling {qty:.4f}",
                )
            _delta = total_cost
            acct.cash = round(acct.cash + total_cost, 2)
            logger.info(f"CASH_CHANGE user={user.id} delta={_delta:.4f} new_balance={acct.cash:.4f} reason='market sell {req.symbol} qty={qty}'")

        order = PaperOrder(
            user_id=user.id,
            symbol=req.symbol,
            side=req.side,
            qty=qty,
            notional=req.notional,
            order_type="market",
            tif=req.tif,
            extended_hours=req.extended_hours,
            status="filled",
            fill_price=fill_price,
            fill_qty=qty,
            slippage=round(slippage, 4),
            filled_at=now,
        )
        db.add(order)
        db.flush()  # get order.id before _apply_fill_to_position

        try:
            _apply_fill_to_position(
                db, user.id, req.symbol, req.side, qty, fill_price, quote.get("prev_close"), order.id
            )

            # Handle bracket: create TP and SL child working orders
            if req.take_profit_price or req.stop_loss_price:
                child_side = "sell" if req.side == "buy" else "buy"
                if req.take_profit_price:
                    tp = PaperOrder(
                        user_id=user.id,
                        symbol=req.symbol,
                        side=child_side,
                        qty=qty,
                        order_type="limit",
                        limit_price=req.take_profit_price,
                        tif="gtc",
                        status="working",
                        parent_order_id=order.id,
                    )
                    db.add(tp)
                if req.stop_loss_price:
                    sl = PaperOrder(
                        user_id=user.id,
                        symbol=req.symbol,
                        side=child_side,
                        qty=qty,
                        order_type="stop",
                        stop_price=req.stop_loss_price,
                        tif="gtc",
                        status="working",
                        parent_order_id=order.id,
                    )
                    db.add(sl)

            db.commit()  # H15: single commit at the end of entire fill sequence
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="Order processing failed. Please try again.")

        db.refresh(order)
        return _serialize_order(order)

    # -----------------------------------------------------------------------
    # Limit / Stop / Stop-limit / Trailing-stop: save as "working"
    # -----------------------------------------------------------------------
    order = PaperOrder(
        user_id=user.id,
        symbol=req.symbol,
        side=req.side,
        qty=qty,
        notional=req.notional,
        order_type=req.order_type,
        limit_price=req.limit_price,
        stop_price=req.stop_price,
        take_profit_price=req.take_profit_price,
        stop_loss_price=req.stop_loss_price,
        trailing_amount=req.trailing_amount,
        trailing_type=req.trailing_type,
        tif=req.tif,
        extended_hours=req.extended_hours,
        status="working",
    )

    # Basic validation: limit buy must be below ask; limit sell must be above bid
    if req.order_type == "limit":
        if req.limit_price is None:
            raise HTTPException(status_code=400, detail="limit_price required for limit orders")
        ask = quote.get("ask", 0)
        bid = quote.get("bid", 0)
        # H11: hard-reject limit orders that are unreasonably priced
        if req.side == "buy" and ask and req.limit_price > ask * 1.05:
            raise HTTPException(
                status_code=400,
                detail=f"Limit buy price ${req.limit_price} is more than 5% above current ask ${ask:.2f}. Use a market order or lower your limit.",
            )
        if req.side == "sell" and bid and req.limit_price < bid * 0.95:
            raise HTTPException(
                status_code=400,
                detail=f"Limit sell price ${req.limit_price} is more than 5% below current bid ${bid:.2f}.",
            )

    # Reserve buying power for working buy orders
    if req.side == "buy":
        reserve_price = req.limit_price or req.stop_price or quote["ask"]
        reserved = round(reserve_price * qty, 2)
        if acct.cash < reserved:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient buying power to reserve ${reserved:,.2f}. Available: ${acct.cash:,.2f}",
            )

    db.add(order)
    db.commit()
    db.refresh(order)

    # Create bracket legs if specified
    if (req.take_profit_price or req.stop_loss_price) and req.side == "buy":
        child_side = "sell"
        if req.take_profit_price:
            tp = PaperOrder(
                user_id=user.id,
                symbol=req.symbol,
                side=child_side,
                qty=qty,
                order_type="limit",
                limit_price=req.take_profit_price,
                tif="gtc",
                status="working",
                parent_order_id=order.id,
            )
            db.add(tp)
        if req.stop_loss_price:
            sl = PaperOrder(
                user_id=user.id,
                symbol=req.symbol,
                side=child_side,
                qty=qty,
                order_type="stop",
                stop_price=req.stop_loss_price,
                tif="gtc",
                status="working",
                parent_order_id=order.id,
            )
            db.add(sl)
        db.commit()

    return _serialize_order(order)


# ---------------------------------------------------------------------------
# GET /api/paper/orders
# ---------------------------------------------------------------------------

@router.get("/orders")
def get_orders(
    status: Optional[str] = Query(None, description="Filter by status (working|filled|cancelled|rejected|expired)"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(PaperOrder).filter_by(user_id=user.id)
    if status:
        q = q.filter(PaperOrder.status == status)
    orders = q.order_by(PaperOrder.created_at.desc()).limit(limit).all()
    return [_serialize_order(o) for o in orders]


# ---------------------------------------------------------------------------
# DELETE /api/paper/orders/{id} — cancel working order
# ---------------------------------------------------------------------------

@router.delete("/orders/{order_id}")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    order = db.query(PaperOrder).filter_by(id=order_id, user_id=user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "working":
        raise HTTPException(status_code=400, detail=f"Cannot cancel order with status '{order.status}'")

    # C7: SQLite cannot enforce FK constraints via ALTER TABLE.
    # If any PaperTransaction references this order, soft-cancel only (never hard delete).
    has_txn = db.query(PaperTransaction).filter_by(order_id=order.id).first()
    if has_txn:
        order.status = "cancelled"
        db.commit()
        return {"ok": True}

    order.status = "cancelled"
    order.cancelled_at = datetime.now(timezone.utc)

    # Also cancel any child bracket orders
    children = db.query(PaperOrder).filter_by(parent_order_id=order_id, user_id=user.id).all()
    for child in children:
        if child.status == "working":
            child.status = "cancelled"
            child.cancelled_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(order)
    return _serialize_order(order)


# ---------------------------------------------------------------------------
# GET /api/paper/transactions
# ---------------------------------------------------------------------------

@router.get("/transactions")
def get_transactions(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    txns = (
        db.query(PaperTransaction)
        .filter_by(user_id=user.id)
        .order_by(PaperTransaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "order_id": t.order_id,
            "symbol": t.symbol,
            "side": t.side,
            "qty": t.qty,
            "fill_price": t.fill_price,
            "cost_basis": t.cost_basis,
            "realized_pnl": t.realized_pnl,
            "total_proceeds": round(t.fill_price * t.qty, 2),
            "created_at": t.created_at.isoformat(),
        }
        for t in txns
    ]


# ---------------------------------------------------------------------------
# GET /api/paper/snapshots — daily equity history
# ---------------------------------------------------------------------------

@router.get("/snapshots")
def get_snapshots(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    snapshots = (
        db.query(PaperDailySnapshot)
        .filter_by(user_id=user.id)
        .order_by(PaperDailySnapshot.date.asc())
        .limit(days)
        .all()
    )
    return [
        {
            "date": s.date,
            "equity": s.equity,
            "cash": s.cash,
            "positions_value": s.positions_value,
            "day_pnl": s.day_pnl,
        }
        for s in snapshots
    ]


# ---------------------------------------------------------------------------
# POST /api/paper/reset
# ---------------------------------------------------------------------------

@router.post("/reset")
def reset_account(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Reset paper trading account to starting balance. Preserves transaction ledger."""
    try:
        db.query(PaperPosition).filter_by(user_id=user.id).delete()
        db.query(PaperOrder).filter_by(user_id=user.id).delete()
        db.query(PaperDailySnapshot).filter_by(user_id=user.id).delete()
        # DO NOT delete PaperTransaction — it's the financial ledger.
        # Add a reset marker transaction instead.
        reset_txn = PaperTransaction(
            user_id=user.id,
            symbol="RESET",
            side="reset",
            qty=0,
            fill_price=0,
            cost_basis=0,
            notes=f"Account reset at {datetime.now(timezone.utc).isoformat()}",
        )
        db.add(reset_txn)

        acct = db.query(PaperAccount).filter_by(user_id=user.id).first()
        if acct:
            acct.cash = STARTING_BALANCE
            acct.starting_balance = STARTING_BALANCE
            logger.info(f"CASH_CHANGE user={user.id} delta={STARTING_BALANCE:.4f} new_balance={acct.cash:.4f} reason='account reset'")
        else:
            acct = PaperAccount(
                user_id=user.id,
                cash=STARTING_BALANCE,
                starting_balance=STARTING_BALANCE,
            )
            db.add(acct)
            logger.info(f"CASH_CHANGE user={user.id} delta={STARTING_BALANCE:.4f} new_balance={STARTING_BALANCE:.4f} reason='account created on reset'")
        db.commit()
        return {"status": "reset", "cash": STARTING_BALANCE}
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# POST /api/paper/seed-demo
# ---------------------------------------------------------------------------

DEMO_POSITIONS = [
    {"symbol": "AAPL", "qty": 15, "cost_pct_of_current": 0.82},
    {"symbol": "NVDA", "qty": 8,  "cost_pct_of_current": 0.70},
    {"symbol": "MSFT", "qty": 12, "cost_pct_of_current": 0.88},
    {"symbol": "TSLA", "qty": 10, "cost_pct_of_current": 1.15},
    {"symbol": "AMZN", "qty": 6,  "cost_pct_of_current": 0.79},
    {"symbol": "SPY",  "qty": 20, "cost_pct_of_current": 0.92},
    {"symbol": "META", "qty": 5,  "cost_pct_of_current": 0.75},
]

DEMO_CASH = 35_000.0


@router.post("/seed-demo")
async def seed_demo(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Reset account and populate with a realistic demo portfolio."""
    try:
        # 1. Reset positions, orders, and snapshots — but NOT PaperTransaction (financial ledger)
        db.query(PaperPosition).filter_by(user_id=user.id).delete()
        db.query(PaperOrder).filter_by(user_id=user.id).delete()
        # DO NOT delete PaperTransaction records — insert a seed marker instead
        db.query(PaperDailySnapshot).filter_by(user_id=user.id).delete()

        # H7: insert seed marker transaction instead of deleting records
        seed_txn = PaperTransaction(
            user_id=user.id,
            symbol="SEED",
            side="seed",
            qty=0,
            fill_price=0,
            cost_basis=0,
            notes=f"Demo seed at {datetime.now(timezone.utc).isoformat()}",
        )
        db.add(seed_txn)

        acct = db.query(PaperAccount).filter_by(user_id=user.id).first()
        if not acct:
            acct = PaperAccount(user_id=user.id, cash=DEMO_CASH, starting_balance=STARTING_BALANCE)
            db.add(acct)
            logger.info(f"CASH_CHANGE user={user.id} delta={DEMO_CASH:.4f} new_balance={DEMO_CASH:.4f} reason='demo seed account created'")
        else:
            acct.cash = DEMO_CASH
            acct.starting_balance = STARTING_BALANCE
            logger.info(f"CASH_CHANGE user={user.id} delta={DEMO_CASH:.4f} new_balance={acct.cash:.4f} reason='demo seed reset'")
        db.commit()

        # 2. Fetch current prices in parallel
        symbols = [p["symbol"] for p in DEMO_POSITIONS]
        quotes_list = await asyncio.gather(*[get_quote(s) for s in symbols], return_exceptions=True)
        quotes = {}
        for sym, q in zip(symbols, quotes_list):
            if isinstance(q, dict):
                quotes[sym] = q

        # 3. Create positions and initial filled orders (representing entry buys)
        now = datetime.now(timezone.utc)
        total_positions_value = 0.0

        for dp in DEMO_POSITIONS:
            symbol = dp["symbol"]
            qty = dp["qty"]
            cost_mult = dp["cost_pct_of_current"]
            q = quotes.get(symbol)
            current_price = q["last"] if q else 150.0  # fallback
            avg_cost = round(current_price * cost_mult, 2)
            prev_close = q.get("prev_close", current_price) if q else current_price

            pos = PaperPosition(
                user_id=user.id,
                symbol=symbol,
                qty=qty,
                avg_cost=avg_cost,
                prev_close=prev_close,
                opened_at=now - timedelta(days=random.randint(30, 90)),
            )
            db.add(pos)
            total_positions_value += current_price * qty

            # Historical buy order
            entry_order = PaperOrder(
                user_id=user.id,
                symbol=symbol,
                side="buy",
                qty=qty,
                order_type="market",
                tif="day",
                status="filled",
                fill_price=avg_cost,
                fill_qty=qty,
                slippage=round(avg_cost * 0.0001, 4),
                filled_at=now - timedelta(days=random.randint(30, 90)),
                created_at=now - timedelta(days=random.randint(30, 90)),
            )
            db.add(entry_order)

        db.commit()

        # 4. Create a few sample sell transactions (realized P&L)
        sample_sells = [
            ("AAPL", 5, 0.78, 0.95),   # bought cheaper, sold at a small gain
            ("TSLA", 3, 1.20, 1.05),   # small realized loss
        ]
        for sym, qty_sold, buy_mult, sell_mult in sample_sells:
            q = quotes.get(sym)
            base_price = q["last"] if q else 150.0
            buy_price = round(base_price * buy_mult, 2)
            sell_price = round(base_price * sell_mult, 2)
            sell_order = PaperOrder(
                user_id=user.id,
                symbol=sym,
                side="sell",
                qty=qty_sold,
                order_type="market",
                tif="day",
                status="filled",
                fill_price=sell_price,
                fill_qty=qty_sold,
                slippage=round(sell_price * 0.0001, 4),
                filled_at=now - timedelta(days=random.randint(5, 20)),
                created_at=now - timedelta(days=random.randint(5, 20)),
            )
            db.add(sell_order)
            db.flush()
            txn = PaperTransaction(
                user_id=user.id,
                order_id=sell_order.id,
                symbol=sym,
                side="sell",
                qty=qty_sold,
                fill_price=sell_price,
                cost_basis=buy_price,
                realized_pnl=round((sell_price - buy_price) * qty_sold, 4),
            )
            db.add(txn)

        db.commit()

        # 5. Create 90 daily snapshots simulating equity growth from $100K
        # Build a smooth curve with some daily noise
        base_equity = STARTING_BALANCE
        final_equity = round(DEMO_CASH + total_positions_value, 2)
        total_gain = final_equity - base_equity

        today = now.date()
        prev_snap_equity = base_equity
        for i in range(90, 0, -1):
            snap_date = today - timedelta(days=i)
            day_fraction = (90 - i) / 90
            trend_equity = base_equity + total_gain * day_fraction
            noise = trend_equity * random.uniform(-0.008, 0.012)  # -0.8% to +1.2% noise
            snap_equity = round(max(trend_equity + noise, base_equity * 0.85), 2)
            day_pnl = round(snap_equity - prev_snap_equity, 2)
            snap_positions_value = round(snap_equity * 0.65, 2)  # ~65% invested
            snap_cash = round(snap_equity - snap_positions_value, 2)

            snap = PaperDailySnapshot(
                user_id=user.id,
                date=snap_date.isoformat(),
                equity=snap_equity,
                cash=snap_cash,
                positions_value=snap_positions_value,
                day_pnl=day_pnl,
            )
            db.add(snap)
            prev_snap_equity = snap_equity

        db.commit()

        return {
            "status": "seeded",
            "cash": DEMO_CASH,
            "positions": len(DEMO_POSITIONS),
            "equity_estimate": round(DEMO_CASH + total_positions_value, 2),
            "snapshots": 90,
        }
    except Exception:
        db.rollback()
        raise
