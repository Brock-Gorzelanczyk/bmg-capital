from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alpaca.client import get_historical_client
from app.db.models.portfolio import Portfolio, Position
from app.db.models.users import User
from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class PortfolioCreate(BaseModel):
    name: str


class PositionCreate(BaseModel):
    symbol: str
    shares: float
    average_cost: float


class PositionUpdate(BaseModel):
    shares: Optional[float] = None
    average_cost: Optional[float] = None


class KellyRequest(BaseModel):
    win_rate: float           # 0.0–1.0
    avg_win_pct: float        # e.g. 0.15 for 15%
    avg_loss_pct: float       # e.g. 0.08 for 8% (positive number)
    account_size: float       # total account value in dollars
    kelly_fraction: float = 0.25  # default to quarter-Kelly


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _portfolio_to_dict(p: Portfolio, include_positions: bool = False) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": p.id,
        "name": p.name,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
    if include_positions:
        d["positions"] = [_position_to_dict(pos) for pos in p.positions]
    return d


def _position_to_dict(pos: Position) -> Dict[str, Any]:
    return {
        "id": pos.id,
        "portfolio_id": pos.portfolio_id,
        "symbol": pos.symbol,
        "shares": pos.shares,
        "average_cost": pos.average_cost,
        "cost_basis": pos.shares * pos.average_cost,
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_portfolios(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    return {"portfolios": [_portfolio_to_dict(p) for p in portfolios]}


@router.post("", status_code=201)
def create_portfolio(
    body: PortfolioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = Portfolio(name=body.name, user_id=current_user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _portfolio_to_dict(p, include_positions=True)


@router.get("/{portfolio_id:int}")
def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return _portfolio_to_dict(p, include_positions=True)


@router.post("/{portfolio_id}/positions", status_code=201)
def add_position(
    portfolio_id: int,
    body: PositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    symbol = body.symbol.upper().strip()
    existing = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Position for {symbol} already exists in this portfolio"
        )

    pos = Position(
        portfolio_id=portfolio_id,
        symbol=symbol,
        shares=body.shares,
        average_cost=body.average_cost,
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return _position_to_dict(pos)


@router.put("/{portfolio_id}/positions/{symbol}")
def update_position(
    portfolio_id: int,
    symbol: str,
    body: PositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    symbol = symbol.upper()
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    pos = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {symbol} not found")

    if body.shares is not None:
        pos.shares = body.shares
    if body.average_cost is not None:
        pos.average_cost = body.average_cost
    db.commit()
    db.refresh(pos)
    return _position_to_dict(pos)


@router.delete("/{portfolio_id}/positions/{symbol}")
def delete_position(
    portfolio_id: int,
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    symbol = symbol.upper()
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    pos = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {symbol} not found")
    db.delete(pos)
    db.commit()
    return {"ok": True}


@router.post("/kelly")
def kelly_position_sizer(
    body: KellyRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Kelly Criterion position sizer.

    Formula: K = (win_rate * avg_win_pct - loss_rate * avg_loss_pct) / avg_win_pct
    """
    win_rate = body.win_rate
    loss_rate = 1.0 - win_rate
    avg_win = body.avg_win_pct
    avg_loss = body.avg_loss_pct

    # Edge = expected value per dollar risked
    edge = win_rate * avg_win - loss_rate * avg_loss

    if avg_win <= 0:
        raise HTTPException(status_code=422, detail="avg_win_pct must be greater than 0")

    full_kelly_pct = edge / avg_win

    warning: Optional[str] = None
    if edge <= 0:
        warning = "Negative edge — do not trade"
        full_kelly_pct = 0.0

    recommended_pct = body.kelly_fraction * full_kelly_pct
    recommended_dollars = recommended_pct * body.account_size

    fraction_labels = {
        1.0:  "Full Kelly",
        0.5:  "Half-Kelly",
        0.25: "Quarter-Kelly",
        0.1:  "Tenth-Kelly",
    }
    fraction_label = fraction_labels.get(body.kelly_fraction, f"{body.kelly_fraction:.0%}-Kelly")

    if warning:
        interpretation = (
            f"This setup has a negative expected edge ({edge:.2%} per dollar risked). "
            "Do not size a position until the statistics improve."
        )
    else:
        interpretation = (
            f"Full Kelly suggests {full_kelly_pct:.1%} of capital. "
            f"At {fraction_label} ({body.kelly_fraction:.0%}× Kelly) that is "
            f"{recommended_pct:.1%} of your account, or "
            f"${recommended_dollars:,.0f} on a ${body.account_size:,.0f} account. "
            f"Expected edge is {edge:.2%} per dollar risked."
        )

    return {
        "full_kelly_pct": round(full_kelly_pct * 100, 4),
        "recommended_pct": round(recommended_pct * 100, 4),
        "recommended_dollars": round(recommended_dollars, 2),
        "max_shares_example": None,
        "edge": round(edge * 100, 4),
        "interpretation": interpretation,
        "warning": warning,
    }


@router.get("/{portfolio_id}/summary")
async def portfolio_summary(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions = p.positions
    if not positions:
        return {
            "portfolio_id": portfolio_id,
            "name": p.name,
            "positions": [],
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_gain": 0.0,
            "total_gain_pct": 0.0,
        }

    symbols = [pos.symbol for pos in positions]
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
    except Exception as e:
        logger.error(f"Snapshot fetch error for portfolio {portfolio_id}: {e}", exc_info=True)

    enriched: List[Dict[str, Any]] = []
    total_value = 0.0
    total_cost = 0.0

    for pos in positions:
        current_price = prices.get(pos.symbol)
        cost_basis = pos.shares * pos.average_cost
        market_value = pos.shares * current_price if current_price is not None else None
        gain = (market_value - cost_basis) if market_value is not None else None
        gain_pct = (gain / cost_basis * 100) if (gain is not None and cost_basis) else None

        total_cost += cost_basis
        if market_value is not None:
            total_value += market_value

        enriched.append(
            {
                **_position_to_dict(pos),
                "current_price": current_price,
                "market_value": market_value,
                "gain": gain,
                "gain_pct": gain_pct,
            }
        )

    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0.0

    return {
        "portfolio_id": portfolio_id,
        "name": p.name,
        "positions": enriched,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_gain": total_gain,
        "total_gain_pct": total_gain_pct,
    }


# ---------------------------------------------------------------------------
# Benchmark constants (approximate SPY placeholder values)
# ---------------------------------------------------------------------------

_BENCHMARK = {
    "ytd": 8.2,
    "1y": 24.1,
    "3y": 10.2,
}


@router.get("/{portfolio_id}/performance")
async def portfolio_performance(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Return TWR, MWR (IRR approximation), benchmark comparison, and attribution.

    Notes
    -----
    * Simple Return  = (current_value - cost_basis) / cost_basis * 100
    * MWR (annualised) ~= (ending_value / beginning_value)^(365/days_held) - 1
      where beginning_value = total cost basis.  This is a simplified IRR
      approximation; full GIPS-compliant MWR requires all cash-flow timestamps.
    * TWR ~= simple return because we lack daily NAV sub-periods.
    * Benchmark (SPY) figures are hardcoded placeholders.
    """
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions = p.positions
    if not positions:
        return {
            "portfolio_id": portfolio_id,
            "name": p.name,
            "simple_return_pct": 0.0,
            "mwr_annualized_pct": 0.0,
            "twr_pct": 0.0,
            "twr_note": "Full TWR requires daily NAV history; shown value equals simple return.",
            "total_gain_dollars": 0.0,
            "benchmark_ytd": _BENCHMARK["ytd"],
            "benchmark_1y": _BENCHMARK["1y"],
            "days_held": 0,
            "best_contributor": None,
            "worst_contributor": None,
            "winners": 0,
            "losers": 0,
            "concentration_pct": 0.0,
            "concentration_warning": False,
        }

    # ------------------------------------------------------------------
    # Fetch live prices via Alpaca snapshot
    # ------------------------------------------------------------------
    symbols = [pos.symbol for pos in positions]
    prices: Dict[str, float] = {}

    try:
        alpaca_client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        snapshots_data = alpaca_client.get_stock_snapshot(req)
        for sym in symbols:
            if sym in snapshots_data:
                snap = snapshots_data[sym]
                daily = snap.daily_bar
                if daily:
                    prices[sym] = float(daily.close)
    except Exception as exc:
        logger.error(
            "Snapshot fetch error for performance endpoint (portfolio %s): %s",
            portfolio_id,
            exc,
            exc_info=True,
        )

    # ------------------------------------------------------------------
    # Per-position metrics
    # ------------------------------------------------------------------
    now = datetime.now(tz=timezone.utc)

    position_results: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_value = 0.0

    for pos in positions:
        cost_basis = pos.shares * pos.average_cost
        current_price = prices.get(pos.symbol)
        market_value = pos.shares * current_price if current_price is not None else cost_basis

        gain_dollars = market_value - cost_basis
        gain_pct = (gain_dollars / cost_basis * 100) if cost_basis else 0.0

        total_cost += cost_basis
        total_value += market_value

        position_results.append({
            "symbol": pos.symbol,
            "gain_dollars": gain_dollars,
            "gain_pct": gain_pct,
            "market_value": market_value,
        })

    # ------------------------------------------------------------------
    # Portfolio inception date -> days_held
    # ------------------------------------------------------------------
    oldest_date = p.created_at
    for pos in positions:
        candidate = pos.opened_at or p.created_at
        if candidate and (oldest_date is None or candidate < oldest_date):
            oldest_date = candidate

    if oldest_date:
        oldest_tz = getattr(oldest_date, "tzinfo", None)
        oldest_dt = oldest_date if oldest_tz else oldest_date.replace(tzinfo=timezone.utc)
        days_held = max(1, (now - oldest_dt).days)
    else:
        days_held = 365

    # ------------------------------------------------------------------
    # Return calculations
    # ------------------------------------------------------------------
    total_gain = total_value - total_cost
    simple_return_pct = (total_gain / total_cost * 100) if total_cost else 0.0

    # TWR ~= simple return (no daily NAV sub-periods available)
    twr_pct = simple_return_pct

    # MWR (annualised): (V_end / V_begin)^(365/days) - 1
    if total_cost > 0 and total_value > 0:
        mwr_annualized = ((total_value / total_cost) ** (365.0 / days_held) - 1) * 100
    else:
        mwr_annualized = 0.0

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------
    sorted_by_gain = sorted(position_results, key=lambda x: x["gain_dollars"], reverse=True)
    winners = [r for r in position_results if r["gain_dollars"] >= 0]
    losers = [r for r in position_results if r["gain_dollars"] < 0]

    best = sorted_by_gain[0] if sorted_by_gain else None
    worst = sorted_by_gain[-1] if len(sorted_by_gain) > 1 else None

    def _contrib(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if r is None:
            return None
        return {
            "symbol": r["symbol"],
            "gain_dollars": round(r["gain_dollars"], 2),
            "gain_pct": round(r["gain_pct"], 2),
        }

    # ------------------------------------------------------------------
    # Concentration (largest single position as % of total market value)
    # ------------------------------------------------------------------
    concentration_pct = 0.0
    if total_value > 0 and position_results:
        max_mv = max(r["market_value"] for r in position_results)
        concentration_pct = round(max_mv / total_value * 100, 2)

    return {
        "portfolio_id": portfolio_id,
        "name": p.name,
        "simple_return_pct": round(simple_return_pct, 4),
        "mwr_annualized_pct": round(mwr_annualized, 4),
        "twr_pct": round(twr_pct, 4),
        "twr_note": "Full TWR requires daily NAV history; shown value equals simple return.",
        "total_gain_dollars": round(total_gain, 2),
        "benchmark_ytd": _BENCHMARK["ytd"],
        "benchmark_1y": _BENCHMARK["1y"],
        "days_held": days_held,
        "best_contributor": _contrib(best),
        "worst_contributor": _contrib(worst),
        "winners": len(winners),
        "losers": len(losers),
        "concentration_pct": concentration_pct,
        "concentration_warning": concentration_pct > 10.0,
    }


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

SECTOR_MAP_MILESTONES: Dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "GOOG": "Technology", "META": "Technology",
    "AMD": "Technology", "INTC": "Technology", "AVGO": "Technology",
    "ADBE": "Technology", "CRM": "Technology", "ORCL": "Technology",
    "AMZN": "Consumer Disc.", "TSLA": "Consumer Disc.", "NFLX": "Consumer Disc.",
    "NKE": "Consumer Disc.", "SBUX": "Consumer Disc.", "TGT": "Consumer Disc.",
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
    "WFC": "Financials", "MS": "Financials", "BLK": "Financials",
    "JNJ": "Healthcare", "PFE": "Healthcare", "UNH": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "LLY": "Healthcare",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SPY": "ETF", "QQQ": "ETF", "IWM": "ETF",
    "DIA": "ETF", "GLD": "ETF", "SLV": "ETF",
    "VTI": "ETF", "TLT": "Bonds", "DJP": "Commodities",
    "SGOV": "Cash",
}


@router.get("/milestones", response_model=None)
def get_milestones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return milestone achievements for the current user across all portfolios."""
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    all_positions: List[Position] = []
    for p in portfolios:
        all_positions.extend(p.positions)

    total_cost_basis = sum(pos.shares * pos.average_cost for pos in all_positions)
    sectors = set(SECTOR_MAP_MILESTONES.get(pos.symbol, "Other") for pos in all_positions)

    has_positions = len(all_positions) > 0
    has_profitable = any(pos.shares > 0 and pos.average_cost > 0 for pos in all_positions)

    # Total gain: without live prices we approximate 0; frontend can enrich
    total_gain = 0.0

    # Seed 3 placeholder milestones for new users with no positions yet
    placeholder_milestones: List[Dict[str, Any]] = []
    if not has_positions:
        placeholder_milestones = [
            {
                "id": "paper_trading_activated",
                "label": "Paper trading activated",
                "description": "First trade — Paper trading activated",
                "achieved": True,
                "achieved_at": None,
                "icon_emoji": "🚀",
                "placeholder": True,
            },
            {
                "id": "watchlist_started",
                "label": "Watchlist started",
                "description": "Watchlist started — Added first ticker",
                "achieved": True,
                "achieved_at": None,
                "icon_emoji": "👀",
                "placeholder": True,
            },
            {
                "id": "strategy_scan_completed",
                "label": "Strategy scan completed",
                "description": "Strategy scan completed",
                "achieved": True,
                "achieved_at": None,
                "icon_emoji": "🔍",
                "placeholder": True,
            },
        ]
        return {"milestones": placeholder_milestones}

    milestones: List[Dict[str, Any]] = [
        {
            "id": "first_position",
            "label": "First Position",
            "description": "Add your first position to a portfolio",
            "achieved": has_positions,
            "achieved_at": (
                min((pos.opened_at.isoformat() for pos in all_positions if pos.opened_at), default=None)
                if has_positions else None
            ),
            "icon_emoji": "🌱",
        },
        {
            "id": "first_1k_invested",
            "label": "First $1K Invested",
            "description": "Reach $1,000 in total cost basis",
            "achieved": total_cost_basis >= 1_000,
            "achieved_at": None,
            "icon_emoji": "💰",
        },
        {
            "id": "first_10k_invested",
            "label": "First $10K Invested",
            "description": "Reach $10,000 in total cost basis",
            "achieved": total_cost_basis >= 10_000,
            "achieved_at": None,
            "icon_emoji": "🏦",
        },
        {
            "id": "first_profitable_position",
            "label": "First Profitable Position",
            "description": "Hold a position with positive gain",
            "achieved": has_profitable,
            "achieved_at": None,
            "icon_emoji": "📈",
        },
        {
            "id": "diversified",
            "label": "Diversified",
            "description": "Hold positions in 3 or more different sectors",
            "achieved": len(sectors) >= 3,
            "achieved_at": None,
            "icon_emoji": "🌐",
        },
        {
            "id": "first_100_gain",
            "label": "First $100 Gain",
            "description": "Earn $100 in unrealized gains",
            "achieved": total_gain >= 100,
            "achieved_at": None,
            "icon_emoji": "✨",
        },
        {
            "id": "first_1k_gain",
            "label": "First $1K Gain",
            "description": "Earn $1,000 in unrealized gains",
            "achieved": total_gain >= 1_000,
            "achieved_at": None,
            "icon_emoji": "🏆",
        },
    ]

    return {"milestones": milestones}


# ---------------------------------------------------------------------------
# Streak
# ---------------------------------------------------------------------------

def _iso_week(d: date) -> Tuple[int, int]:
    """Return (ISO year, ISO week number) for a date."""
    iso = d.isocalendar()
    return (iso[0], iso[1])


@router.get("/streak", response_model=None)
def get_streak(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return activity streak info based on position open dates."""
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    all_positions: List[Position] = []
    for p in portfolios:
        all_positions.extend(p.positions)

    if not all_positions:
        return {
            "current_streak_weeks": 0,
            "longest_streak_weeks": 0,
            "last_activity_date": None,
        }

    activity_dates: List[date] = [
        pos.opened_at.date() if isinstance(pos.opened_at, datetime) else pos.opened_at
        for pos in all_positions
        if pos.opened_at is not None
    ]

    if not activity_dates:
        return {
            "current_streak_weeks": 0,
            "longest_streak_weeks": 0,
            "last_activity_date": None,
        }

    last_activity = max(activity_dates)
    active_weeks = sorted(set(_iso_week(d) for d in activity_dates))

    # Compute longest streak
    longest = 1
    current_run = 1
    for i in range(1, len(active_weeks)):
        prev_year, prev_week = active_weeks[i - 1]
        curr_year, curr_week = active_weeks[i]
        prev_d = date.fromisocalendar(prev_year, prev_week, 1)
        curr_d = date.fromisocalendar(curr_year, curr_week, 1)
        if (curr_d - prev_d).days == 7:
            current_run += 1
            longest = max(longest, current_run)
        else:
            current_run = 1

    # Compute current streak (from today backwards)
    today_week = _iso_week(date.today())
    current_streak = 0
    check_year, check_week = today_week
    active_week_set = set(active_weeks)
    while True:
        if (check_year, check_week) in active_week_set:
            current_streak += 1
        else:
            break
        check_d = date.fromisocalendar(check_year, check_week, 1) - timedelta(weeks=1)
        check_year, check_week = _iso_week(check_d)
        if current_streak > 52:
            break

    return {
        "current_streak_weeks": current_streak,
        "longest_streak_weeks": longest,
        "last_activity_date": last_activity.isoformat(),
    }


# ---------------------------------------------------------------------------
# Risk Parity Allocator
# ---------------------------------------------------------------------------

SLEEVES: Dict[str, Dict[str, Any]] = {
    "equities": {
        "base": 30.0,
        "recession_adj": -10.0,
        "growth_adj": +5.0,
        "inflation_adj": -5.0,
        "ticker": "VTI",
        "label": "Equities",
        "color": "#3B82F6",
    },
    "long_bonds": {
        "base": 40.0,
        "recession_adj": +10.0,
        "growth_adj": -5.0,
        "inflation_adj": -15.0,
        "ticker": "TLT",
        "label": "Long Bonds",
        "color": "#8B5CF6",
    },
    "gold": {
        "base": 7.5,
        "recession_adj": +5.0,
        "growth_adj": -2.0,
        "inflation_adj": +10.0,
        "ticker": "GLD",
        "label": "Gold",
        "color": "#F59E0B",
    },
    "commodities": {
        "base": 7.5,
        "recession_adj": -2.0,
        "growth_adj": +2.0,
        "inflation_adj": +12.0,
        "ticker": "DJP",
        "label": "Commodities",
        "color": "#EF4444",
    },
    "crypto": {
        "base": 5.0,
        "recession_adj": -3.0,
        "growth_adj": +5.0,
        "inflation_adj": +3.0,
        "ticker": "BTC",
        "label": "Crypto",
        "color": "#F97316",
    },
    "cash": {
        "base": 10.0,
        "recession_adj": +5.0,
        "growth_adj": -5.0,
        "inflation_adj": +5.0,
        "ticker": "SGOV",
        "label": "Cash",
        "color": "#22C55E",
    },
}

REGIME_EXPLANATIONS: Dict[str, str] = {
    "growth": (
        "In a growth regime, corporate earnings expand and risk assets outperform. "
        "We tilt toward equities and crypto, trim defensive long bonds and cash, "
        "keeping commodities flat. The goal is to capture the equity risk premium "
        "while the economic tailwind is at your back."
    ),
    "recession": (
        "Recessions bring falling earnings and risk-off flows. We shift capital into "
        "long-duration Treasuries (which rally as the Fed cuts rates), raise cash for "
        "optionality, and boost gold as a safe-haven. Equities, commodities, and crypto "
        "are trimmed to reduce drawdown risk."
    ),
    "inflation-rising": (
        "Rising inflation erodes the real value of bonds and cash. We overweight real "
        "assets — gold and commodities — which historically hedge inflation well. "
        "Equities are trimmed slightly (margins compress), long bonds are cut sharply "
        "(duration risk in a rising-rate environment), and crypto gets a modest lift "
        "as a speculative inflation hedge."
    ),
    "inflation-falling": (
        "Falling inflation is the classic Goldilocks environment: bonds rally as real "
        "yields drop, equities benefit from lower discount rates, and the All-Weather "
        "base allocation is close to optimal. No dramatic tilts needed — hold the "
        "balanced baseline."
    ),
    "neutral": (
        "In a neutral or uncertain regime we hold the Bridgewater All-Weather baseline: "
        "30% equities, 40% long bonds, 7.5% gold, 7.5% commodities, 5% crypto, and "
        "10% cash. Each sleeve is sized to contribute equal risk (volatility) to the "
        "portfolio rather than equal dollars, which smooths the ride across economic cycles."
    ),
}


class RiskParityRequest(BaseModel):
    capital: float
    regime: str = "neutral"


@router.post("/risk-parity")
def risk_parity_allocator(
    body: RiskParityRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return All-Weather risk-parity allocation adjusted for economic regime."""
    regime = body.regime.lower().strip()
    valid_regimes = {"growth", "recession", "inflation-rising", "inflation-falling", "neutral"}
    if regime not in valid_regimes:
        raise HTTPException(status_code=422, detail=f"regime must be one of {sorted(valid_regimes)}")

    adj_key: Optional[str] = {
        "growth": "growth_adj",
        "recession": "recession_adj",
        "inflation-rising": "inflation_adj",
        "inflation-falling": None,
        "neutral": None,
    }[regime]

    raw: Dict[str, float] = {}
    for sleeve_id, sleeve in SLEEVES.items():
        pct = sleeve["base"]
        if adj_key:
            pct += sleeve.get(adj_key, 0.0)
        raw[sleeve_id] = max(pct, 0.0)

    total = sum(raw.values())
    allocations = []
    for sleeve_id, sleeve in SLEEVES.items():
        norm_pct = (raw[sleeve_id] / total) * 100 if total > 0 else 0.0
        dollar_amount = (norm_pct / 100) * body.capital
        allocations.append({
            "sleeve": sleeve_id,
            "label": sleeve["label"],
            "ticker": sleeve["ticker"],
            "color": sleeve["color"],
            "raw_pct": round(raw[sleeve_id], 2),
            "normalized_pct": round(norm_pct, 2),
            "dollar_amount": round(dollar_amount, 2),
        })

    explanation = REGIME_EXPLANATIONS.get(regime, REGIME_EXPLANATIONS["neutral"])

    return {
        "regime": regime,
        "capital": body.capital,
        "allocations": allocations,
        "regime_explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Factor Exposure helpers & endpoint
# ---------------------------------------------------------------------------

_FE_SECTOR_MAP: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "GOOG": "Technology", "AMD": "Technology",
    "INTC": "Technology", "AVGO": "Technology", "ADBE": "Technology",
    "CRM": "Technology", "ORCL": "Technology", "IBM": "Technology",
    "QCOM": "Technology", "TXN": "Technology", "MU": "Technology",
    "AMAT": "Technology", "LRCX": "Technology", "KLAC": "Technology",
    "SNPS": "Technology", "CDNS": "Technology", "CRWD": "Technology",
    "PANW": "Technology", "SNOW": "Technology", "PLTR": "Technology",
    "DDOG": "Technology", "NET": "Technology", "ZS": "Technology",
    "OKTA": "Technology", "HUBS": "Technology", "WDAY": "Technology",
    "NOW": "Technology", "INTU": "Technology", "TEAM": "Technology",
    "FTNT": "Technology", "DELL": "Technology", "HPQ": "Technology",
    "HPE": "Technology", "ANET": "Technology", "MRVL": "Technology",
    "META": "Comm. Services", "NFLX": "Comm. Services",
    "DIS": "Comm. Services", "CMCSA": "Comm. Services", "T": "Comm. Services",
    "VZ": "Comm. Services", "TMUS": "Comm. Services", "SNAP": "Comm. Services",
    "SPOT": "Comm. Services", "PINS": "Comm. Services", "ZM": "Comm. Services",
    "RBLX": "Comm. Services", "EA": "Comm. Services", "TTWO": "Comm. Services",
    "CHTR": "Comm. Services", "PARA": "Comm. Services",
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
    "WFC": "Financials", "MS": "Financials", "BLK": "Financials",
    "C": "Financials", "AXP": "Financials", "COF": "Financials",
    "SCHW": "Financials", "USB": "Financials", "PNC": "Financials",
    "TFC": "Financials", "SPGI": "Financials", "MCO": "Financials",
    "ICE": "Financials", "CME": "Financials", "CB": "Financials",
    "JNJ": "Healthcare", "PFE": "Healthcare", "UNH": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "LLY": "Healthcare",
    "TMO": "Healthcare", "ABT": "Healthcare", "DHR": "Healthcare",
    "BMY": "Healthcare", "AMGN": "Healthcare", "GILD": "Healthcare",
    "CVS": "Healthcare", "CI": "Healthcare", "HCA": "Healthcare",
    "ISRG": "Healthcare", "REGN": "Healthcare", "VRTX": "Healthcare",
    "AMZN": "Consumer Disc.", "TSLA": "Consumer Disc.", "NKE": "Consumer Disc.",
    "MCD": "Consumer Disc.", "SBUX": "Consumer Disc.", "TGT": "Consumer Disc.",
    "HD": "Consumer Disc.", "LOW": "Consumer Disc.", "TJX": "Consumer Disc.",
    "BKNG": "Consumer Disc.", "ABNB": "Consumer Disc.", "UBER": "Consumer Disc.",
    "GM": "Consumer Disc.", "F": "Consumer Disc.", "RCL": "Consumer Disc.",
    "WMT": "Consumer Staples", "PG": "Consumer Staples", "KO": "Consumer Staples",
    "PEP": "Consumer Staples", "COST": "Consumer Staples", "CL": "Consumer Staples",
    "MO": "Consumer Staples", "PM": "Consumer Staples",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "EOG": "Energy",
    "SLB": "Energy", "OXY": "Energy", "HAL": "Energy", "MPC": "Energy",
    "CAT": "Industrials", "DE": "Industrials", "HON": "Industrials",
    "GE": "Industrials", "RTX": "Industrials", "BA": "Industrials",
    "LMT": "Industrials", "NOC": "Industrials", "UPS": "Industrials",
    "FDX": "Industrials",
    "LIN": "Materials", "APD": "Materials", "NEM": "Materials", "FCX": "Materials",
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    "D": "Utilities", "AEP": "Utilities",
    "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    "SPY": "ETF", "QQQ": "ETF", "IWM": "ETF", "DIA": "ETF",
    "GLD": "ETF", "SLV": "ETF", "TLT": "ETF", "VTI": "ETF", "VOO": "ETF",
}

_FE_PE: dict[str, float] = {
    "Technology": 25.0, "Comm. Services": 22.0, "Financials": 12.0,
    "Energy": 10.0, "Utilities": 15.0, "Healthcare": 18.0,
    "Consumer Disc.": 20.0, "Consumer Staples": 20.0, "Industrials": 17.0,
    "Materials": 14.0, "Real Estate": 35.0, "ETF": 20.0, "Other": 20.0,
}

_FE_BETA: dict[str, float] = {
    "Technology": 1.3, "Comm. Services": 1.2, "Consumer Disc.": 1.15,
    "Industrials": 1.0, "Materials": 1.0, "Financials": 1.1,
    "Healthcare": 0.75, "Consumer Staples": 0.55, "Utilities": 0.45,
    "Real Estate": 0.8, "Energy": 1.2, "ETF": 1.0, "Other": 1.0,
}

_FE_USD_SECTORS = {"Consumer Staples", "Technology", "Energy", "Materials"}
_FE_QUALITY_SECTORS = {"Healthcare", "Technology", "Financials"}
_FE_TECH_SECTORS = {"Technology", "Comm. Services"}


def _fe_label(score: float) -> str:
    if score >= 70:
        return "High"
    if score >= 40:
        return "Moderate"
    return "Low"


def _build_factor_exposure(pos_list: list[dict]) -> dict:
    if not pos_list:
        return {
            "factors": [],
            "insight": "No positions to analyze.",
            "top_factors": [],
            "concentration_pct": 0.0,
        }

    total_mv = sum(float(p.get("market_value") or 0) for p in pos_list)
    if total_mv <= 0:
        total_mv = sum(float(p["shares"]) * float(p["average_cost"]) for p in pos_list)
    if total_mv <= 0:
        total_mv = 1.0

    weights = []
    secs = []
    for p in pos_list:
        mv = float(p.get("market_value") or (float(p["shares"]) * float(p["average_cost"])))
        weights.append(mv / total_mv)
        secs.append(_FE_SECTOR_MAP.get(p["symbol"].upper(), "Other"))

    gain_pcts = [p.get("gain_pct") for p in pos_list]

    avg_pe = sum(_FE_PE.get(s, 20.0) * w for s, w in zip(secs, weights))
    value_score = max(0.0, min(100.0, (35.0 - avg_pe) / 25.0 * 100.0))

    valid_gains = [g for g in gain_pcts if g is not None]
    momentum_score = (
        (sum(1 for g in valid_gains if g > 0) / len(valid_gains)) * 100.0
        if valid_gains else 50.0
    )

    quality_score = sum(w for w, s in zip(weights, secs) if s in _FE_QUALITY_SECTORS) * 100.0

    avg_beta = sum(_FE_BETA.get(s, 1.0) * w for s, w in zip(secs, weights))
    low_vol_score = max(0.0, min(100.0, (1.3 - avg_beta) / 0.85 * 100.0))

    usd_score = sum(w for w, s in zip(weights, secs) if s in _FE_USD_SECTORS) * 100.0

    crypto_score = 0.0

    tech_score = sum(w for w, s in zip(weights, secs) if s in _FE_TECH_SECTORS) * 100.0

    concentration_score = min(100.0, sum(w ** 2 for w in weights) * 100.0)

    factors_raw: list[tuple[str, float]] = [
        ("Value",         value_score),
        ("Momentum",      momentum_score),
        ("Quality",       quality_score),
        ("Low-Vol",       low_vol_score),
        ("USD-Beta",      usd_score),
        ("Crypto-Beta",   crypto_score),
        ("Tech-Growth",   tech_score),
        ("Concentration", concentration_score),
    ]

    factors_out = [
        {"name": n, "score": round(s, 1), "label": _fe_label(s)}
        for n, s in factors_raw
    ]

    top_factors_out = [
        n for n, _ in sorted(
            [(n, s) for n, s in factors_raw if n != "Concentration"],
            key=lambda x: x[1],
            reverse=True,
        )[:2]
    ]

    n_pos = len(pos_list)
    if len(top_factors_out) >= 2:
        insight = (
            f"You think you own {n_pos} stock{'s' if n_pos != 1 else ''}; "
            f"you actually own 2 dominant factors: "
            f"{top_factors_out[0]} and {top_factors_out[1]}."
        )
    else:
        insight = f"You hold {n_pos} position{'s' if n_pos != 1 else ''}."

    return {
        "factors": factors_out,
        "insight": insight,
        "top_factors": top_factors_out,
        "concentration_pct": round(concentration_score, 1),
    }


@router.get("/{portfolio_id}/factor-exposure")
async def portfolio_factor_exposure(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Compute 8-factor exposure scores (0-100) for the portfolio."""
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    if not p.positions:
        return {
            "factors": [],
            "insight": "No positions in this portfolio.",
            "top_factors": [],
            "concentration_pct": 0.0,
        }

    symbols = [pos.symbol for pos in p.positions]
    prices: Dict[str, float] = {}
    try:
        hist_client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        snaps = hist_client.get_stock_snapshot(req)
        for sym in symbols:
            if sym in snaps and snaps[sym].daily_bar:
                prices[sym] = float(snaps[sym].daily_bar.close)
    except Exception as exc:
        logger.warning("Price fetch failed for factor-exposure (portfolio %s): %s", portfolio_id, exc)

    pos_list = []
    for pos in p.positions:
        cp = prices.get(pos.symbol)
        cb = pos.shares * pos.average_cost
        mv = pos.shares * cp if cp is not None else cb
        gain = mv - cb if cp is not None else None
        gp = (gain / cb * 100) if (gain is not None and cb > 0) else None
        pos_list.append({
            "symbol": pos.symbol,
            "shares": pos.shares,
            "average_cost": pos.average_cost,
            "market_value": mv,
            "gain_pct": gp,
        })

    return _build_factor_exposure(pos_list)
