from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.alpaca.client import get_historical_client
from app.db.models.journal import JournalEntry
from app.db.models.portfolio import Portfolio, Position
from app.db.models.users import User
from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tlh", tags=["tlh"])

# ---------------------------------------------------------------------------
# Wash-sale replacement map (substantially identical security alternatives)
# ---------------------------------------------------------------------------

REPLACEMENT_MAP: Dict[str, List[str]] = {
    "SPY": ["IVV", "VOO"],
    "IVV": ["SPY", "VOO"],
    "VOO": ["SPY", "IVV"],
    "QQQ": ["ONEQ", "QQQM"],
    "QQQM": ["QQQ", "ONEQ"],
    "ONEQ": ["QQQ", "QQQM"],
    "IWM": ["VTWO", "SCHA"],
    "VTWO": ["IWM", "SCHA"],
    "SCHA": ["IWM", "VTWO"],
    "EFA": ["VEA", "IEFA"],
    "VEA": ["EFA", "IEFA"],
    "IEFA": ["EFA", "VEA"],
    "EEM": ["VWO", "IEMG"],
    "VWO": ["EEM", "IEMG"],
    "IEMG": ["EEM", "VWO"],
    "AGG": ["BND", "SCHZ"],
    "BND": ["AGG", "SCHZ"],
    "SCHZ": ["AGG", "BND"],
    "GLD": ["IAU", "SGOL"],
    "IAU": ["GLD", "SGOL"],
    "SGOL": ["GLD", "IAU"],
    "VTI": ["ITOT", "SCHB"],
    "ITOT": ["VTI", "SCHB"],
    "SCHB": ["VTI", "ITOT"],
    "XLK": ["VGT", "IYW"],
    "VGT": ["XLK", "IYW"],
    "XLF": ["VFH", "IYF"],
    "VFH": ["XLF", "IYF"],
    "XLE": ["VDE", "IYE"],
    "VDE": ["XLE", "IYE"],
}

# Threshold for flagging as harvestable: loss greater than 5%
HARVEST_THRESHOLD_PCT = -5.0

# Tax bracket used for estimated savings
DEFAULT_TAX_RATE = 0.24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices via Alpaca snapshot; returns {symbol: price}."""
    if not symbols:
        return {}
    prices: Dict[str, float] = {}
    try:
        client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        snapshots = client.get_stock_snapshot(req)
        for sym in symbols:
            if sym in snapshots:
                snap = snapshots[sym]
                daily = snap.daily_bar
                if daily:
                    prices[sym] = float(daily.close)
    except Exception as exc:
        logger.error("TLH price fetch error: %s", exc, exc_info=True)
    return prices


def _wash_sale_risk(
    symbol: str,
    user_id: int,
    db: Session,
) -> bool:
    """
    Return True if the user bought this symbol within the last 30 days
    (which would trigger a wash-sale if they sell at a loss now).
    """
    cutoff = date.today() - timedelta(days=30)
    recent_buy = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.user_id == user_id,
            JournalEntry.symbol == symbol.upper(),
            JournalEntry.side == "buy",
            JournalEntry.trade_date >= cutoff,
        )
        .first()
    )
    return recent_buy is not None


def _ytd_harvested(user_id: int, db: Session) -> float:
    """
    Sum of realised losses from journal sell entries this calendar year
    where pnl < 0 — used as a proxy for harvested losses YTD.
    """
    ytd_start = date(date.today().year, 1, 1)
    entries = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.user_id == user_id,
            JournalEntry.side == "sell",
            JournalEntry.trade_date >= ytd_start,
            JournalEntry.pnl.isnot(None),
        )
        .all()
    )
    return abs(sum(e.pnl for e in entries if e.pnl is not None and e.pnl < 0))


def _wash_sale_warnings_count(user_id: int, db: Session) -> int:
    """Count of distinct symbols bought within 30 days that also have a losing sell."""
    cutoff = date(date.today().year, 1, 1)
    # sold at a loss this year
    loss_sells = (
        db.query(JournalEntry.symbol)
        .filter(
            JournalEntry.user_id == user_id,
            JournalEntry.side == "sell",
            JournalEntry.trade_date >= cutoff,
            JournalEntry.pnl < 0,
        )
        .distinct()
        .all()
    )
    sold_symbols = {row[0] for row in loss_sells}
    if not sold_symbols:
        return 0

    wash_cutoff = date.today() - timedelta(days=30)
    risky_buys = (
        db.query(JournalEntry.symbol)
        .filter(
            JournalEntry.user_id == user_id,
            JournalEntry.side == "buy",
            JournalEntry.trade_date >= wash_cutoff,
            JournalEntry.symbol.in_(list(sold_symbols)),
        )
        .distinct()
        .count()
    )
    return risky_buys


# ---------------------------------------------------------------------------
# GET /api/tlh/opportunities
# ---------------------------------------------------------------------------

@router.get("/opportunities")
def get_tlh_opportunities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Scan the user's portfolio positions for tax-loss harvesting opportunities.
    Flags positions with gain_pct < -5%, checks wash-sale risk, and suggests
    substantially-identical replacement securities.
    """
    portfolios = (
        db.query(Portfolio)
        .filter(Portfolio.user_id == current_user.id)
        .all()
    )

    # Collect all positions across all portfolios
    all_positions: List[Position] = []
    for p in portfolios:
        all_positions.extend(p.positions)

    if not all_positions:
        ytd_harvested = _ytd_harvested(current_user.id, db)
        return {
            "opportunities": [],
            "total_harvestable_loss": 0.0,
            "estimated_tax_savings_24pct": 0.0,
            "year_to_date_harvested": round(ytd_harvested, 2),
        }

    symbols = list({pos.symbol for pos in all_positions})
    prices = _fetch_prices(symbols)

    opportunities: List[Dict[str, Any]] = []
    total_harvestable = 0.0

    for pos in all_positions:
        current_price = prices.get(pos.symbol)
        if current_price is None:
            continue

        cost_basis = pos.shares * pos.average_cost
        market_value = pos.shares * current_price
        loss_dollars = market_value - cost_basis
        gain_pct = (loss_dollars / cost_basis * 100) if cost_basis else 0.0

        if gain_pct >= HARVEST_THRESHOLD_PCT:
            continue  # Not deep enough in the red

        wash_risk = _wash_sale_risk(pos.symbol, current_user.id, db)
        replacements = REPLACEMENT_MAP.get(pos.symbol.upper(), [])
        suggested = replacements[0] if replacements else None

        if suggested:
            harvest_instructions = (
                f"Sell {pos.shares:.4g} shares of {pos.symbol} to realise "
                f"${abs(loss_dollars):,.2f} in losses. "
                f"Immediately buy {suggested} to maintain market exposure. "
                f"Wait 31 days before repurchasing {pos.symbol} to avoid the wash-sale rule."
            )
            suggested_replacement = (
                f"After selling {pos.symbol}, consider {suggested} for 31 days "
                f"to maintain market exposure"
            )
        else:
            harvest_instructions = (
                f"Sell {pos.shares:.4g} shares of {pos.symbol} to realise "
                f"${abs(loss_dollars):,.2f} in losses. "
                f"Wait 31 days before repurchasing the same security."
            )
            suggested_replacement = None

        total_harvestable += abs(loss_dollars)

        opportunities.append({
            "symbol": pos.symbol,
            "portfolio_id": pos.portfolio_id,
            "shares": pos.shares,
            "average_cost": pos.average_cost,
            "current_price": current_price,
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "loss_dollars": round(loss_dollars, 2),
            "loss_pct": round(gain_pct, 2),
            "wash_sale_risk": wash_risk,
            "suggested_replacement": suggested_replacement,
            "replacement_symbols": replacements,
            "harvest_instructions": harvest_instructions,
        })

    # Sort by biggest loss first
    opportunities.sort(key=lambda x: x["loss_dollars"])

    ytd_harvested = _ytd_harvested(current_user.id, db)
    estimated_savings = round(total_harvestable * DEFAULT_TAX_RATE, 2)

    return {
        "opportunities": opportunities,
        "total_harvestable_loss": round(total_harvestable, 2),
        "estimated_tax_savings_24pct": estimated_savings,
        "year_to_date_harvested": round(ytd_harvested, 2),
    }


# ---------------------------------------------------------------------------
# GET /api/tlh/summary
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_tlh_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Year-to-date TLH summary."""
    ytd_harvested = _ytd_harvested(current_user.id, db)
    wash_warnings = _wash_sale_warnings_count(current_user.id, db)
    return {
        "ytd_harvested_dollars": round(ytd_harvested, 2),
        "ytd_tax_saved_est": round(ytd_harvested * DEFAULT_TAX_RATE, 2),
        "wash_sale_warnings": wash_warnings,
    }
