from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
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
            total_qty = existing.qty + qty
            existing.avg_cost = round(
                (existing.avg_cost * existing.qty + fill_price * qty) / total_qty, 6
            )
            existing.qty = total_qty
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
        realized_pnl = round((fill_price - cost_basis) * qty, 4)
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
        current_price = q["last"] if q else p.avg_cost
        prev_close = p.prev_close if p.prev_close is not None else (q["prev_close"] if q else p.avg_cost)

        market_value = round(current_price * p.qty, 2)
        cost_basis_total = round(p.avg_cost * p.qty, 2)
        unrealized_pnl = round(market_value - cost_basis_total, 2)
        unrealized_pnl_pct = round((unrealized_pnl / cost_basis_total * 100) if cost_basis_total else 0.0, 4)

        pos_day_pnl = round((current_price - prev_close) * p.qty, 2)
        pos_day_pnl_pct = round(((current_price - prev_close) / prev_close * 100) if prev_close else 0.0, 4)

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
        })

    equity = round(acct.cash + total_positions_value, 2)
    total_pnl = round(equity - acct.starting_balance, 2)
    total_pnl_pct = round((total_pnl / acct.starting_balance * 100) if acct.starting_balance else 0.0, 4)
    day_pnl_pct = round(
        (day_pnl_total / (equity - day_pnl_total) * 100) if (equity - day_pnl_total) != 0 else 0.0, 4
    )

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
        return v.upper().strip()

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

    now = datetime.utcnow()

    # -----------------------------------------------------------------------
    # Market orders: fill immediately
    # -----------------------------------------------------------------------
    if req.order_type == "market":
        fill_price, slippage = simulate_fill(req.side, quote, "market")
        total_cost = round(fill_price * qty, 2)

        if req.side == "buy":
            if acct.cash < total_cost:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient buying power. Need ${total_cost:,.2f}, have ${acct.cash:,.2f}",
                )
            acct.cash = round(acct.cash - total_cost, 2)
        else:
            position = db.query(PaperPosition).filter_by(user_id=user.id, symbol=req.symbol).first()
            if not position or position.qty < qty - 1e-6:
                have = position.qty if position else 0
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient shares. Have {have:.4f}, selling {qty:.4f}",
                )
            acct.cash = round(acct.cash + total_cost, 2)

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
        except HTTPException:
            db.rollback()
            raise

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

        db.commit()
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
        if req.side == "buy" and req.limit_price > quote["ask"] * 1.05:
            logger.warning(f"Limit buy price {req.limit_price} well above ask {quote['ask']}")
        if req.side == "sell" and req.limit_price < quote["bid"] * 0.95:
            logger.warning(f"Limit sell price {req.limit_price} well below bid {quote['bid']}")

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

    order.status = "cancelled"
    order.cancelled_at = datetime.utcnow()

    # Also cancel any child bracket orders
    children = db.query(PaperOrder).filter_by(parent_order_id=order_id, user_id=user.id).all()
    for child in children:
        if child.status == "working":
            child.status = "cancelled"
            child.cancelled_at = datetime.utcnow()

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
    """Reset paper trading account to starting balance."""
    db.query(PaperPosition).filter_by(user_id=user.id).delete()
    db.query(PaperOrder).filter_by(user_id=user.id).delete()
    db.query(PaperTransaction).filter_by(user_id=user.id).delete()
    db.query(PaperDailySnapshot).filter_by(user_id=user.id).delete()

    acct = db.query(PaperAccount).filter_by(user_id=user.id).first()
    if acct:
        acct.cash = STARTING_BALANCE
        acct.starting_balance = STARTING_BALANCE
    else:
        acct = PaperAccount(
            user_id=user.id,
            cash=STARTING_BALANCE,
            starting_balance=STARTING_BALANCE,
        )
        db.add(acct)
    db.commit()
    return {"status": "reset", "cash": STARTING_BALANCE}


# ---------------------------------------------------------------------------
# POST /api/paper/seed-demo
# ---------------------------------------------------------------------------

DEMO_POSITIONS = [
    # (symbol, qty, cost_multiplier)
    ("AAPL", 15, 0.82),
    ("NVDA", 8, 0.70),
    ("MSFT", 12, 0.88),
    ("TSLA", 10, 1.15),
    ("AMZN", 6, 0.79),
    ("SPY", 20, 0.92),
    ("META", 5, 0.75),
]

DEMO_CASH = 35_000.0


@router.post("/seed-demo")
async def seed_demo(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Reset account and populate with a realistic demo portfolio."""
    # 1. Reset everything
    db.query(PaperPosition).filter_by(user_id=user.id).delete()
    db.query(PaperOrder).filter_by(user_id=user.id).delete()
    db.query(PaperTransaction).filter_by(user_id=user.id).delete()
    db.query(PaperDailySnapshot).filter_by(user_id=user.id).delete()

    acct = db.query(PaperAccount).filter_by(user_id=user.id).first()
    if not acct:
        acct = PaperAccount(user_id=user.id, cash=DEMO_CASH, starting_balance=STARTING_BALANCE)
        db.add(acct)
    else:
        acct.cash = DEMO_CASH
        acct.starting_balance = STARTING_BALANCE
    db.commit()

    # 2. Fetch current prices in parallel
    symbols = [s for s, _, _ in DEMO_POSITIONS]
    quotes_list = await asyncio.gather(*[get_quote(s) for s in symbols], return_exceptions=True)
    quotes = {}
    for sym, q in zip(symbols, quotes_list):
        if isinstance(q, dict):
            quotes[sym] = q

    # 3. Create positions and initial filled orders (representing entry buys)
    now = datetime.utcnow()
    total_positions_value = 0.0

    for symbol, qty, cost_mult in DEMO_POSITIONS:
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
    snapshots_equity = base_equity
    final_equity = round(DEMO_CASH + total_positions_value, 2)
    total_gain = final_equity - base_equity
    # Distribute gain over 90 days with noise
    daily_drift = total_gain / 90

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
