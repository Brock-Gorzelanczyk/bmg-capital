from __future__ import annotations

import asyncio
import logging
import math
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
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/paper", tags=["paper"])

# ---------------------------------------------------------------------------
# Demo-mode deterministic pricing
# ---------------------------------------------------------------------------

DEMO_EMAIL = "demo@bmgcapital.com"

# Base prices used as anchors for demo accounts (approximate realistic values).
_DEMO_BASE_PRICES: dict[str, float] = {
    "AAPL": 211.0,
    "NVDA": 950.0,
    "MSFT": 435.0,
    "TSLA": 245.0,
    "AMZN": 215.0,
    "SPY":  535.0,
    "META": 620.0,
    # extras sometimes seen in positions
    "AMD":  178.0,
    "SMCI": 420.0,
    "PLTR":  28.0,
    "MSTR": 520.0,
    "COIN": 235.0,
    "QQQ":  465.0,
    "SOFI":  10.8,
    "RKLB":  22.0,
    "IONQ":  28.0,
    # Large-cap equities
    "GOOG":  175.0,
    "GOOGL": 175.0,
    "NFLX":  890.0,
    "JPM":   245.0,
    "V":     290.0,
    "MA":    520.0,
    "JNJ":   155.0,
    "UNH":   520.0,
    "XOM":   115.0,
    "CVX":   155.0,
    "BAC":    45.0,
    "WMT":    90.0,
    "HD":    385.0,
    "PG":    170.0,
    "KO":     65.0,
    "PEP":   170.0,
    "ABBV":  190.0,
    "MRK":   115.0,
    "LLY":   830.0,
    "PFE":    27.0,
    "TMO":   490.0,
    "EMR":   115.0,
    "COF":   175.0,
    "ULTA":  380.0,
    "PHM":   130.0,
    "SYBT":   50.0,
    "TECH":   32.0,
    # ETFs
    "IWM":   220.0,
    "GLD":   230.0,
    "TLT":    92.0,
    "DIA":   430.0,
    "VTI":   270.0,
    "VOO":   495.0,
    "ARKK":   55.0,
    "XLK":   225.0,
    # Tech
    "ADBE":  390.0,
    "CRM":   285.0,
    "ORCL":  145.0,
    "INTC":   22.0,
    "AVGO":  215.0,
    "MU":     85.0,
    "ARM":   135.0,
    "PANW":  185.0,
    "CRWD":  395.0,
    "SNOW":  165.0,
    "NET":   115.0,
    "DDOG":  115.0,
    "SHOP":   95.0,
    "UBER":   78.0,
    "LYFT":   17.0,
    "ROKU":   65.0,
    # Finance
    "GS":    510.0,
    "MS":    120.0,
    "BLK":   960.0,
    "C":      68.0,
    "WFC":    72.0,
    "SCHW":   76.0,
    "AXP":   275.0,
    "BRK.B": 480.0,
    # Consumer / other
    "NKE":    78.0,
    "SBUX":   82.0,
    "MCD":   308.0,
    "TGT":   125.0,
    "COST":  920.0,
    "AMGN":  315.0,
    "DIS":   108.0,
    "CMCSA":  40.0,
    # Crypto-related
    "BTC":  98000.0,
    "ETH":   3800.0,
    "SOL":    195.0,
    "HIMS":   38.0,
    "RXRX":    8.0,
    "ACHR":   15.0,
}


def _demo_price(symbol: str, user_id: int) -> dict:
    """Return a deterministic quote for demo accounts.

    Price drifts smoothly with a sine wave keyed on user_id and minute_of_day,
    giving realistic-looking movement without per-request randomness.
    """
    base = _DEMO_BASE_PRICES.get(symbol.upper(), 100.0)
    now = datetime.utcnow()
    minute_of_day = now.hour * 60 + now.minute
    drift = 1.0 + 0.001 * math.sin(user_id * 7 + minute_of_day)
    last = round(base * drift, 2)
    half_spread = round(last * 0.0005 / 2, 2)
    # prev_close: yesterday's sine at same minute but different seed
    prev_drift = 1.0 + 0.001 * math.sin(user_id * 7 + minute_of_day - 1440)
    prev_close = round(base * prev_drift, 2)
    return {
        "bid": round(last - half_spread, 2),
        "ask": round(last + half_spread, 2),
        "last": last,
        "prev_close": prev_close,
    }


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
    allow_short: bool = False,
) -> None:
    """Update PaperPosition and write PaperTransaction.

    Supports negative qty (short) positions:
      sell with no existing long → creates a short (qty < 0)
      buy against a short → buy-to-cover, records realized P&L
    """
    existing = db.query(PaperPosition).filter_by(user_id=user_id, symbol=symbol).first()

    if side == "buy":
        if existing and existing.qty < 0:
            # ── Buy-to-cover a short position ────────────────────────────────
            abs_short = abs(existing.qty)
            cover_qty = min(qty, abs_short)
            # Short profit = (sold_at - bought_back_at) * qty
            realized_pnl = _money((_d(existing.avg_cost) - _d(fill_price)) * _d(cover_qty))
            txn = PaperTransaction(
                user_id=user_id,
                order_id=order_id,
                symbol=symbol,
                side="buy_to_cover",
                qty=cover_qty,
                fill_price=fill_price,
                cost_basis=existing.avg_cost,
                realized_pnl=realized_pnl,
            )
            db.add(txn)
            existing.qty = round(existing.qty + cover_qty, 6)
            if abs(existing.qty) < 0.0001:
                db.delete(existing)
                existing = None
            remaining = qty - cover_qty
            if remaining > 1e-8:
                # Any excess qty becomes a new long
                pos = PaperPosition(
                    user_id=user_id, symbol=symbol,
                    qty=remaining, avg_cost=fill_price, prev_close=prev_close,
                )
                db.add(pos)
        elif existing and existing.qty > 0:
            # ── Add to existing long position (weighted average) ──────────────
            old_cost = _d(existing.avg_cost)
            old_qty  = _d(existing.qty)
            new_qty  = _d(qty)
            total    = old_qty + new_qty
            existing.avg_cost = float((old_cost * old_qty + _d(fill_price) * new_qty) / total)
            existing.qty = float(total)
            if prev_close and existing.prev_close is None:
                existing.prev_close = prev_close
        else:
            # ── Open new long position ────────────────────────────────────────
            pos = PaperPosition(
                user_id=user_id, symbol=symbol,
                qty=qty, avg_cost=fill_price, prev_close=prev_close,
            )
            db.add(pos)

    else:  # sell
        if existing and existing.qty > 0:
            # ── Reduce / close an existing long position ──────────────────────
            if existing.qty < qty - 1e-6:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient shares. Have {existing.qty:.4f}, selling {qty:.4f}",
                )
            cost_basis = existing.avg_cost
            realized_pnl = _money((_d(fill_price) - _d(cost_basis)) * _d(qty))
            txn = PaperTransaction(
                user_id=user_id, order_id=order_id, symbol=symbol,
                side="sell", qty=qty, fill_price=fill_price,
                cost_basis=cost_basis, realized_pnl=realized_pnl,
            )
            db.add(txn)
            existing.qty = round(existing.qty - qty, 6)
            if existing.qty < 0.0001:
                db.delete(existing)
        elif allow_short:
            if existing and existing.qty < 0:
                # ── Add to existing short position ────────────────────────────
                existing.qty = round(existing.qty - qty, 6)
            else:
                # ── Open new short position ───────────────────────────────────
                pos = PaperPosition(
                    user_id=user_id, symbol=symbol,
                    qty=-qty, avg_cost=fill_price, prev_close=prev_close,
                )
                db.add(pos)
        else:
            raise HTTPException(status_code=400, detail=f"No position found for {symbol}")


# ---------------------------------------------------------------------------
# GET /api/paper/account
# ---------------------------------------------------------------------------

@router.get("/account")
async def get_account(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Return account summary with live market values for all positions."""
    acct = _get_or_create_account(db, user.id)
    positions = db.query(PaperPosition).filter_by(user_id=user.id).all()

    # For demo accounts, use deterministic pricing instead of live quotes so
    # that Portfolio Value, Day's P&L, and Total Return are stable across refreshes.
    is_demo = getattr(user, "email", "") == DEMO_EMAIL

    # Fetch all quotes in parallel (skipped for demo users)
    symbols = [p.symbol for p in positions]
    if symbols and not is_demo:
        quotes_list = await asyncio.gather(
            *[get_quote(s) for s in symbols], return_exceptions=True
        )
        quotes = {}
        for sym, q in zip(symbols, quotes_list):
            if isinstance(q, dict):
                quotes[sym] = q
    elif symbols and is_demo:
        quotes = {sym: _demo_price(sym, user.id) for sym in symbols}
    else:
        quotes = {}

    # Load latest open bracket orders per symbol for TP/SL
    open_orders = (
        db.query(PaperOrder)
        .filter_by(user_id=user.id)
        .filter(PaperOrder.status.in_(["open", "pending"]))
        .filter(PaperOrder.symbol.in_(symbols) if symbols else False)
        .all()
    ) if symbols else []
    tp_by_symbol = {}
    sl_by_symbol = {}
    for o in open_orders:
        if o.take_profit_price:
            tp_by_symbol[o.symbol] = o.take_profit_price
        if o.stop_loss_price:
            sl_by_symbol[o.symbol] = o.stop_loss_price

    position_rows = []
    total_positions_value = 0.0
    day_pnl_total = 0.0

    # Maximum allowed notional per position: 2× the starting balance.
    # Positions above this are legacy bad data (e.g. crypto qty stored in satoshis)
    # and must be excluded to avoid billion-dollar phantom values.
    _MAX_POSITION_NOTIONAL = float(acct.starting_balance) * 2

    for p in positions:
        # Guard: skip positions with clearly bad data (qty or avg_cost out of range)
        if p.qty <= 0 or p.avg_cost <= 0:
            logger.warning(f"Skipping invalid position {p.id} {p.symbol}: qty={p.qty}, avg_cost={p.avg_cost}")
            continue
        raw_notional = p.qty * p.avg_cost
        if raw_notional > _MAX_POSITION_NOTIONAL:
            logger.warning(
                f"Skipping oversized position {p.id} {p.symbol}: qty={p.qty}, avg_cost={p.avg_cost}, "
                f"notional=${raw_notional:,.0f} exceeds max ${_MAX_POSITION_NOTIONAL:,.0f}"
            )
            continue

        q = quotes.get(p.symbol)
        stale = q is None and not is_demo  # H8: track if quote is missing
        if q:
            current_price = q["last"]
        else:
            # When price fetch fails, use last known price (if any) — never a fake constant.
            current_price = getattr(p, "last_price", None)
            if not is_demo:
                logger.warning(f"Quote fetch failed for {p.symbol}, returning null price")
        # prev_close: use stored value or quote value; fall back to None (not avg_cost) so
        # we don't fabricate a 0% day-P&L with a fake baseline.
        prev_close = p.prev_close if p.prev_close is not None else (q["prev_close"] if q else None)

        # H20: use Decimal for all financial math
        # When current_price is None we still compute market_value from avg_cost so totals
        # remain coherent, but we surface None to the frontend for the price cell.
        d_price = _d(current_price if current_price is not None else p.avg_cost)
        d_qty = _d(p.qty)
        d_avg_cost = _d(p.avg_cost)
        d_prev_close = _d(prev_close) if prev_close is not None else None

        market_value = _money(d_price * d_qty)
        cost_basis_total = _money(d_avg_cost * d_qty)
        d_unrealized_pnl = _d(market_value) - _d(cost_basis_total)
        unrealized_pnl = _money(d_unrealized_pnl)
        # Use abs for pct denominator so shorts show correct sign (+/-)
        d_cost_abs = abs(_d(cost_basis_total))
        unrealized_pnl_pct = _money(d_unrealized_pnl / d_cost_abs * _d(100)) if d_cost_abs else 0.0

        # day P&L: only compute when we have a valid previous close
        if d_prev_close is not None and d_prev_close != 0:
            d_pos_day_pnl = (d_price - d_prev_close) * d_qty
            pos_day_pnl = _money(d_pos_day_pnl)
            # Fix day_pct formula: (current - prev_close) / prev_close * 100
            # Clamp to ±50% — values outside that range indicate stale/bad data
            raw_day_pct = float((d_price - d_prev_close) / d_prev_close * _d(100))
            clamped_pct = max(-50.0, min(50.0, raw_day_pct))
            pos_day_pnl_pct = round(clamped_pct, 4)
        else:
            pos_day_pnl = 0.0
            pos_day_pnl_pct = 0.0

        total_positions_value += market_value
        day_pnl_total += pos_day_pnl

        position_rows.append({
            "id": p.id,
            "symbol": p.symbol,
            "qty": p.qty,
            "direction": "short" if p.qty < 0 else "long",
            "avg_cost": p.avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "cost_basis": abs(cost_basis_total),
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "day_pnl": pos_day_pnl,
            "day_pnl_pct": pos_day_pnl_pct,
            "prev_close": prev_close,
            "opened_at": p.opened_at.isoformat(),
            "price_stale": stale,
            "take_profit": tp_by_symbol.get(p.symbol),
            "stop_loss": sl_by_symbol.get(p.symbol),
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
    allow_short: bool = False                  # set True to open short (sell without long position)

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
    is_demo_order = getattr(user, "email", "") == DEMO_EMAIL
    if is_demo_order:
        quote = _demo_price(req.symbol, user.id)
    else:
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
            if not req.allow_short:
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
                db, user.id, req.symbol, req.side, qty, fill_price, quote.get("prev_close"), order.id,
                allow_short=req.allow_short,
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
# POST /api/paper/purge-bad-positions
# ---------------------------------------------------------------------------

@router.post("/purge-bad-positions")
def purge_bad_positions(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Remove positions with clearly corrupted data (qty≤0, avg_cost≤0, or notional >2× starting balance).
    Safe to call — legitimate positions are never deleted.
    """
    acct = _get_or_create_account(db, user.id)
    max_notional = float(acct.starting_balance) * 2
    positions = db.query(PaperPosition).filter_by(user_id=user.id).all()
    purged = []
    for p in positions:
        if p.qty <= 0 or p.avg_cost <= 0 or (p.qty * p.avg_cost) > max_notional:
            purged.append({"id": p.id, "symbol": p.symbol, "qty": p.qty, "avg_cost": p.avg_cost})
            db.delete(p)
    db.commit()
    logger.info(f"purge_bad_positions: user={user.id} removed {len(purged)} bad positions")
    return {"purged": len(purged), "details": purged}


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

        # 2. Use demo prices for seeding (consistent with get_account demo pricing,
        # avoids live-quote failures causing bogus prev_close / day-P&L percentages)
        symbols = [p["symbol"] for p in DEMO_POSITIONS]
        quotes = {sym: _demo_price(sym, user.id) for sym in symbols}

        # 3. Create positions and initial filled orders (representing entry buys)
        now = datetime.now(timezone.utc)
        total_positions_value = 0.0

        # Use a seeded RNG so re-seeding produces identical position dates and
        # snapshot noise — making demo data deterministic across invocations.
        date_str = now.strftime("%Y-%m-%d")
        _rng = random.Random(f"{user.id}:{date_str}")

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
                opened_at=now - timedelta(days=_rng.randint(30, 90)),
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
                filled_at=now - timedelta(days=_rng.randint(30, 90)),
                created_at=now - timedelta(days=_rng.randint(30, 90)),
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
                filled_at=now - timedelta(days=_rng.randint(5, 20)),
                created_at=now - timedelta(days=_rng.randint(5, 20)),
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
            noise = trend_equity * _rng.uniform(-0.008, 0.012)  # -0.8% to +1.2% noise
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


# ---------------------------------------------------------------------------
# POST /api/paper/liquidate-strategy/{strategy_key} — kill switch
# ---------------------------------------------------------------------------

@router.post("/liquidate-strategy/{strategy_key}")
async def liquidate_strategy(
    strategy_key: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Kill switch: close all open/candidate StrategyTrade records for a strategy,
    settle any corresponding PaperPosition, and cancel working paper orders.
    """
    from app.db.models.strategy import StrategyTrade
    from sqlalchemy import select

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    trades = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.preset_key == strategy_key,
            StrategyTrade.user_id == user.id,
            StrategyTrade.status.in_(["open", "candidate"]),
        )
    ).scalars().all()

    if not trades:
        return {"liquidated": 0, "message": f"No open positions for strategy '{strategy_key}'"}

    acct = _get_or_create_account(db, user.id)
    liquidated = []

    for trade in trades:
        if trade.status == "candidate":
            trade.status = "closed"
            trade.exit_date = now
            trade.exit_reason = "kill_switch"
            liquidated.append({"symbol": trade.symbol, "was": "candidate", "fill_price": None})
            continue

        if not (trade.symbol and trade.shares and trade.entry_price and trade.entry_price > 0):
            trade.status = "closed"
            trade.exit_date = now
            trade.exit_reason = "kill_switch"
            continue

        paper_symbol = trade.symbol.replace("/USDT", "-USD") if "/" in trade.symbol else trade.symbol
        direction = getattr(trade, "direction", None) or "long"
        close_side = "sell" if direction == "long" else "buy"

        fill_price = trade.last_known_price or trade.entry_price
        try:
            quote = await get_quote(paper_symbol)
            if quote and quote.get("last"):
                fill_price = quote["last"]
        except Exception:
            pass

        total_proceeds = round(fill_price * trade.shares, 2)

        if close_side == "sell":
            acct.cash = round(acct.cash + total_proceeds, 2)
            logger.info(
                f"CASH_CHANGE user={user.id} delta={total_proceeds:.4f} "
                f"new_balance={acct.cash:.4f} reason='kill_switch sell {paper_symbol}'"
            )
        else:
            acct.cash = round(acct.cash - total_proceeds, 2)
            logger.info(
                f"CASH_CHANGE user={user.id} delta={-total_proceeds:.4f} "
                f"new_balance={acct.cash:.4f} reason='kill_switch cover {paper_symbol}'"
            )

        try:
            _apply_fill_to_position(
                db, user.id, paper_symbol, close_side,
                trade.shares, fill_price, None, 0,
                allow_short=(direction == "short"),
            )
        except HTTPException:
            pass  # paper position may not exist for strategy-only trades
        except Exception as e:
            logger.warning(f"liquidate_strategy: paper position settle failed for {paper_symbol}: {e}")

        trade.status = "closed"
        trade.exit_date = now
        trade.exit_price = round(fill_price, 8)
        trade.exit_reason = "kill_switch"

        liquidated.append({
            "symbol": trade.symbol,
            "direction": direction,
            "fill_price": fill_price,
            "was": "open",
        })

    # Cancel working paper orders for the same symbols
    paper_symbols = {
        t.symbol.replace("/USDT", "-USD") if t.symbol and "/" in t.symbol else t.symbol
        for t in trades if t.symbol
    }
    for sym in paper_symbols:
        working = db.query(PaperOrder).filter(
            PaperOrder.user_id == user.id,
            PaperOrder.symbol == sym,
            PaperOrder.status == "working",
        ).all()
        for o in working:
            o.status = "cancelled"
            o.cancelled_at = now

    db.commit()

    return {
        "liquidated": len(liquidated),
        "positions": liquidated,
        "message": f"Liquidated {len(liquidated)} position(s) for strategy '{strategy_key}'",
    }


# ---------------------------------------------------------------------------
# POST /api/paper/agent-execute  — NL Agent (paper trading only)
# ---------------------------------------------------------------------------

class AgentExecuteRequest(BaseModel):
    instruction: str  # e.g. "Buy $100 of AAPL every Friday"
    confirmed: bool = False  # must be True to actually execute


async def _parse_instruction_with_claude(instruction: str) -> dict:
    """Call Claude to parse a natural language trade instruction into a structured order."""
    import httpx

    if not settings.anthropic_api_key:
        # Fallback simple parser when no API key
        return _fallback_parse(instruction)

    system = (
        "You are a paper trading assistant. Parse the user's instruction into a structured trade order. "
        "Return ONLY valid JSON with these fields: "
        '{"symbol": "TICKER", "action": "buy" or "sell", "amount_dollars": number, "rationale": "brief explanation"}. '
        "If the instruction is ambiguous, make a reasonable assumption. "
        "action must be exactly 'buy' or 'sell'. symbol must be a valid US equity or crypto ticker (e.g. AAPL, BTC-USD). "
        "amount_dollars is the dollar amount to trade (required, positive number). "
        "If the instruction mentions shares instead of dollars, estimate the dollar amount using a reasonable current price. "
        "Return ONLY the JSON object, no markdown, no explanation."
    )
    messages = [{"role": "user", "content": instruction}]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "system": system,
                "messages": messages,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"].strip()

    import json as _json
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = _json.loads(text)
    return parsed


def _fallback_parse(instruction: str) -> dict:
    """
    Simple regex-based fallback parser used when ANTHROPIC_API_KEY is not set.
    Handles patterns like 'Buy $100 of AAPL' or 'Sell 50 dollars of SPY'.
    """
    import re
    text = instruction.lower()
    action = "buy" if "buy" in text else ("sell" if "sell" in text else "buy")

    # Find dollar amount
    amount_match = re.search(r"\$?\s*(\d+(?:\.\d+)?)", text)
    amount_dollars = float(amount_match.group(1)) if amount_match else 100.0

    # Find ticker (1-5 uppercase letters or crypto like BTC-USD)
    ticker_match = re.search(r'\b([A-Z]{1,5}(?:-USD)?)\b', instruction)
    if not ticker_match:
        # Scan for known patterns
        common = ["AAPL", "SPY", "QQQ", "TSLA", "MSFT", "NVDA", "BTC-USD", "ETH-USD", "GLD", "VIX"]
        symbol = next((s for s in common if s.lower() in text), "SPY")
    else:
        symbol = ticker_match.group(1).upper()

    return {
        "symbol": symbol,
        "action": action,
        "amount_dollars": amount_dollars,
        "rationale": f"Parsed from: '{instruction}' (fallback parser — add ANTHROPIC_API_KEY for AI parsing)",
    }


@router.post("/agent-execute")
async def agent_execute(
    req: AgentExecuteRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Parse a natural language instruction and optionally execute a paper trade.

    - confirmed=False: parse only, return structured order for user review
    - confirmed=True: parse and execute the paper trade
    """
    if not req.instruction or not req.instruction.strip():
        raise HTTPException(status_code=400, detail="instruction is required")

    # Parse the instruction
    try:
        parsed = await _parse_instruction_with_claude(req.instruction)
    except Exception as e:
        logger.error(f"Agent parse error: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Could not parse instruction: {str(e)}")

    # Validate parsed fields
    symbol = (parsed.get("symbol") or "").upper().strip()
    action = (parsed.get("action") or "buy").lower()
    amount_dollars = float(parsed.get("amount_dollars") or 100.0)
    rationale = parsed.get("rationale", "")

    if not symbol:
        raise HTTPException(status_code=422, detail="Could not identify a symbol from the instruction")
    if action not in ("buy", "sell"):
        action = "buy"
    if amount_dollars <= 0:
        raise HTTPException(status_code=422, detail="amount_dollars must be positive")

    # Fetch current quote for display
    quote = await get_quote(symbol)
    current_price = quote["last"] if quote else None
    approx_shares = round(amount_dollars / current_price, 4) if current_price else None

    preview = {
        "symbol": symbol,
        "action": action,
        "amount_dollars": amount_dollars,
        "rationale": rationale,
        "current_price": current_price,
        "approx_shares": approx_shares,
        "paper_only": True,
        "confirmed": req.confirmed,
    }

    if not req.confirmed:
        return {
            "status": "preview",
            "order": preview,
            "message": (
                f"I'll {action} ${amount_dollars:,.2f} of {symbol}."
                + (f" Current price: ${current_price:,.2f}. This will purchase ~{approx_shares} shares in paper trading." if current_price and action == "buy" else "")
                + " Confirm to execute this paper trade."
            ),
        }

    # Execute the paper trade
    if not quote:
        raise HTTPException(status_code=400, detail=f"Could not fetch price for {symbol} — cannot execute")

    order_req = OrderRequest(
        symbol=symbol,
        side=action,
        notional=amount_dollars,
        order_type="market",
    )
    result = await place_order(order_req, db=db, user=user)

    return {
        "status": "executed",
        "order": result,
        "preview": preview,
        "message": f"Paper trade executed: {action} ${amount_dollars:,.2f} of {symbol} at ${result.get('fill_price', '?')}.",
    }
