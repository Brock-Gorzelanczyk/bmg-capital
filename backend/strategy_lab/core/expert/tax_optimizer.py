"""
HIFO (highest-in, first-out) lot selection for sells.
Wash sale awareness: flag if buying back within 30 days of a loss.
Loss harvesting: surface positions with unrealized loss > 5% that
could be harvested (don't auto-harvest; just flag).

For paper trading: compute tax impact as informational only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_WASH_SALE_DAYS = 30
_HARVEST_THRESHOLD_PCT = 5.0  # unrealized loss > 5% → flag for harvesting


def select_lots_hifo(
    symbol: str,
    qty_to_sell: int,
    open_lots: list[dict],  # [{qty, cost_basis_cents, opened_at}, ...]
) -> list[dict]:
    """Returns lots to sell, highest cost basis first."""
    if not open_lots or qty_to_sell <= 0:
        return []

    # Sort by cost_basis_cents descending (HIFO)
    sorted_lots = sorted(
        open_lots,
        key=lambda lot: lot.get("cost_basis_cents", 0),
        reverse=True,
    )

    result = []
    remaining = qty_to_sell

    for lot in sorted_lots:
        if remaining <= 0:
            break

        lot_qty = lot.get("qty", 0)
        if lot_qty <= 0:
            continue

        use_qty = min(lot_qty, remaining)
        result.append({
            "qty": use_qty,
            "cost_basis_cents": lot.get("cost_basis_cents", 0),
            "opened_at": lot.get("opened_at"),
            "partial": use_qty < lot_qty,
        })
        remaining -= use_qty

    logger.debug(
        "[tax_optimizer:%s] HIFO selection: selling %d shares from %d lots",
        symbol, qty_to_sell, len(result),
    )
    return result


def check_wash_sale(
    symbol: str,
    recent_trades: list[dict],  # last 60 days
) -> dict:
    """Returns {is_wash_sale: bool, days_since_loss: int | None}."""
    if not recent_trades:
        return {"is_wash_sale": False, "days_since_loss": None}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_WASH_SALE_DAYS)

    # Find the most recent realized loss for this symbol
    loss_trades = []
    for trade in recent_trades:
        trade_symbol = trade.get("symbol", "")
        if trade_symbol != symbol:
            continue

        side = trade.get("side", "")
        if side != "sell":
            continue

        pnl = trade.get("pnl_cents", None)
        if pnl is None:
            # Try fill_price vs cost_basis
            fill = trade.get("fill_price_cents", 0)
            cost = trade.get("cost_basis_cents", 0)
            if fill and cost:
                pnl = fill - cost

        if pnl is not None and pnl < 0:
            ts = trade.get("ts") or trade.get("closed_at")
            if isinstance(ts, str):
                try:
                    from dateutil.parser import parse
                    ts = parse(ts)
                except Exception:
                    ts = None
            if ts:
                if not getattr(ts, "tzinfo", None):
                    ts = ts.replace(tzinfo=timezone.utc)
                loss_trades.append(ts)

    if not loss_trades:
        return {"is_wash_sale": False, "days_since_loss": None}

    # Most recent loss
    most_recent_loss = max(loss_trades)
    days_since_loss = (now - most_recent_loss).days

    # Wash sale: buying back within 30 days of a realized loss
    is_wash_sale = days_since_loss <= _WASH_SALE_DAYS

    if is_wash_sale:
        logger.info(
            "[tax_optimizer:%s] Wash sale risk: loss trade %d days ago (within %d-day window)",
            symbol, days_since_loss, _WASH_SALE_DAYS,
        )

    return {
        "is_wash_sale": is_wash_sale,
        "days_since_loss": days_since_loss,
    }


def flag_harvest_candidates(
    open_positions: list[dict],  # [{symbol, avg_cost_cents, current_price_cents, qty}, ...]
) -> list[dict]:
    """
    Surface positions with unrealized loss > 5% for potential tax-loss harvesting.
    Does NOT auto-harvest — informational only.
    Returns list of {symbol, unrealized_loss_pct, unrealized_loss_cents}.
    """
    candidates = []
    for pos in open_positions:
        avg_cost = pos.get("avg_cost_cents", 0)
        current = pos.get("current_price_cents", 0)
        qty = pos.get("qty", 0)

        if avg_cost <= 0 or current <= 0 or qty <= 0:
            continue

        loss_pct = ((avg_cost - current) / avg_cost) * 100
        if loss_pct >= _HARVEST_THRESHOLD_PCT:
            loss_cents = (avg_cost - current) * qty
            candidates.append({
                "symbol": pos.get("symbol", "?"),
                "unrealized_loss_pct": round(loss_pct, 2),
                "unrealized_loss_cents": int(loss_cents),
            })
            logger.debug(
                "[tax_optimizer:%s] Harvest candidate: -%.2f%% ($%.2f)",
                pos.get("symbol"), loss_pct, loss_cents / 100.0,
            )

    return sorted(candidates, key=lambda c: c["unrealized_loss_pct"], reverse=True)
