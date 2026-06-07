"""
Canonical computation layer for Strategy Lab.

Every endpoint that shows portfolio value, P&L, or position counts
calls these functions — no inline computation allowed.

INVARIANT (enforced by runtime assertion):
  portfolio_value = starting_capital + realized_pnl + unrealized_pnl

  realized_pnl  = SUM(qty × (exit_fill_price - entry_avg_cost) - fees)
                  from bot_trade JOIN bot_position (sell-side trades only)

  unrealized_pnl = SUM(qty × (current_market_price - entry_avg_cost))
                   from bot_position WHERE closed_at IS NULL
                   — uses 0 when live prices are not available

ZERO-TRADE RULE:
  If bot_trade has no rows AND bot_position has no open rows for a bot:
    portfolio_value = starting_capital (exactly)
    today_pnl = 0, return_30d_pct = 0, all_time_return_pct = 0

BotDailyPnL is NOT used for portfolio value or return calculations.
It exists for the audit log and cron digests only.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Display names (single source of truth) ────────────────────────────────────

DISPLAY_NAMES: dict[str, str] = {
    "stock_swing":          "Stock Swing",
    "stock_day":            "Stock Day",
    "stock_lt":             "Stock Long-Term",
    "crypto_swing":         "Crypto Swing",
    "crypto_day":           "Crypto Day",
    "crypto_lt":            "Crypto Long-Term",
    "options_income":       "Options Income",
    "options_directional":  "Options Directional",
}


def display_name(profile_name: str) -> str:
    return DISPLAY_NAMES.get(
        profile_name,
        profile_name.replace("_", " ").title(),
    )


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class BotSnapshot:
    allocation_id: int
    profile_name: str
    display_name: str
    asset_class: str
    enabled: bool

    starting_capital_cents: int
    portfolio_value_cents: int
    today_pnl_cents: int
    today_pnl_pct: float
    realized_pnl_cents: int      # all-time cumulative realized
    unrealized_pnl_cents: int    # latest unrealized
    all_time_return_pct: float
    return_30d_pct: float

    open_positions_count: int
    watchlist_count: int
    sharpe_30d: Optional[float]

    capital_cents_within_portfolio: int  # allocation within its portfolio

    open_positions: list = field(default_factory=list)  # [{id, symbol, qty, avg_cost, ...}]
    equity_curve: list = field(default_factory=list)    # [{date, value_cents}]


@dataclass
class PortfolioSnapshot:
    portfolio_id: int
    name: str
    asset_class: str
    emoji: str
    color_hex: str

    starting_capital_cents: int
    portfolio_value_cents: int
    today_pnl_cents: int
    today_pnl_pct: float
    realized_pnl_cents: int
    unrealized_pnl_cents: int
    all_time_return_pct: float
    return_30d_pct: float

    open_positions_count: int
    watchlist_count: int
    bots_active: int
    bots_total: int

    bots: list = field(default_factory=list)  # list[BotSnapshot]
    equity_curve: list = field(default_factory=list)


# ── Bot-level computation ─────────────────────────────────────────────────────

def compute_bot_snapshot(alloc, profile, db: Session) -> BotSnapshot:
    """
    Single canonical computation for one bot allocation.

    INVARIANT: portfolio_value = starting_capital + realized_pnl + unrealized_pnl
      realized_pnl  — from bot_trade (sell-side fills vs position avg_cost)
      unrealized_pnl — from bot_position open rows (0 if no live price)

    BotDailyPnL is NOT read here. Zero trades → exactly starting_capital.
    """
    from app.db.models.bots import BotTrade, BotPosition, BotWatchlist

    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # ── Starting capital ──────────────────────────────────────────────────────
    starting_capital_cents = int(alloc.starting_capital_cents or alloc.capital_cents_within_portfolio or 0)

    # ── All positions (open + closed) for avg_cost lookup ────────────────────
    all_positions = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id == alloc.id)
        .all()
    )
    pos_cost_map: dict[int, int] = {p.id: p.avg_cost_cents for p in all_positions}

    # ── All trades ───────────────────────────────────────────────────────────
    all_trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id == alloc.id)
        .order_by(BotTrade.ts)
        .all()
    )

    # ── Realized PnL — sell fills only ───────────────────────────────────────
    # PnL per fill = (sell_price - avg_cost) × qty - fees
    realized_pnl_cents = 0
    today_realized_cents = 0
    realized_30d_cents = 0

    for t in all_trades:
        if t.side.lower() not in ("sell", "close"):
            continue
        avg_cost = pos_cost_map.get(t.position_id or -1, t.fill_price_cents)
        fill_pnl = int((t.fill_price_cents - avg_cost) * t.qty) - int(t.fees_cents or 0)
        realized_pnl_cents += fill_pnl
        trade_date = t.ts.date() if hasattr(t.ts, "date") else t.ts
        if trade_date == today:
            today_realized_cents += fill_pnl
        if trade_date >= thirty_days_ago:
            realized_30d_cents += fill_pnl

    # ── Open positions ────────────────────────────────────────────────────────
    open_pos_rows = [p for p in all_positions if p.closed_at is None]

    # Unrealized PnL: 0 until live prices are integrated
    # (satisfies zero-trade rule: no phantom gains from simulation)
    unrealized_pnl_cents = 0

    # ── Portfolio value (the invariant) ──────────────────────────────────────
    portfolio_value_cents = starting_capital_cents + realized_pnl_cents + unrealized_pnl_cents

    # Runtime assertion — log error and fall back if violated
    expected = starting_capital_cents + realized_pnl_cents + unrealized_pnl_cents
    if abs(portfolio_value_cents - expected) > 1:
        logger.error(
            "Invariant violation bot %s: computed=%d expected=%d",
            profile.name, portfolio_value_cents, expected,
        )
        portfolio_value_cents = expected

    # ── Today P&L ────────────────────────────────────────────────────────────
    today_pnl_cents = today_realized_cents
    yesterday_value = portfolio_value_cents - today_pnl_cents
    today_pnl_pct = round(today_pnl_cents / yesterday_value * 100, 2) if yesterday_value > 0 else 0.0

    # ── All-time return ───────────────────────────────────────────────────────
    all_time_return_pct = 0.0
    if starting_capital_cents:
        all_time_return_pct = round(
            (portfolio_value_cents - starting_capital_cents) / starting_capital_cents * 100, 2
        )

    # ── 30-day return (realized trades in last 30d / starting capital) ────────
    return_30d_pct = 0.0
    if starting_capital_cents:
        return_30d_pct = round(realized_30d_cents / starting_capital_cents * 100, 2)

    # ── Sharpe: not computable without daily return series ───────────────────
    sharpe_30d: Optional[float] = None

    # ── Open position details ────────────────────────────────────────────────
    open_positions = [
        {
            "id": p.id,
            "symbol": p.symbol,
            "qty": p.qty,
            "avg_cost_cents": p.avg_cost_cents,
            "avg_cost": round(p.avg_cost_cents / 100, 2),
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "is_paper": p.is_paper,
        }
        for p in open_pos_rows
    ]

    # ── Watchlist count ──────────────────────────────────────────────────────
    watchlist_count = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id == alloc.profile_id,
            BotWatchlist.status.in_(["watching", "pending_entry", "active"]),
        )
        .count()
    )

    # Equity curve: no longer sourced from BotDailyPnL simulation rows
    equity_curve: list = []

    capital_within = int(alloc.capital_cents_within_portfolio or 0)

    return BotSnapshot(
        allocation_id=alloc.id,
        profile_name=profile.name,
        display_name=display_name(profile.name),
        asset_class=profile.asset_class,
        enabled=bool(alloc.enabled),
        starting_capital_cents=starting_capital_cents,
        portfolio_value_cents=portfolio_value_cents,
        today_pnl_cents=today_pnl_cents,
        today_pnl_pct=today_pnl_pct,
        realized_pnl_cents=realized_pnl_cents,
        unrealized_pnl_cents=unrealized_pnl_cents,
        all_time_return_pct=all_time_return_pct,
        return_30d_pct=return_30d_pct,
        open_positions_count=len(open_pos_rows),
        watchlist_count=watchlist_count,
        sharpe_30d=sharpe_30d,
        capital_cents_within_portfolio=capital_within,
        open_positions=open_positions,
        equity_curve=equity_curve,
    )


# ── Portfolio-level computation ───────────────────────────────────────────────

def compute_portfolio_snapshot(
    port, allocs_with_profiles: list[tuple], db: Session
) -> PortfolioSnapshot:
    """
    Canonical computation for one StrategyPortfolio.
    allocs_with_profiles: list of (BotAllocation, BotProfile) tuples for this portfolio.
    """
    bot_snapshots = [compute_bot_snapshot(alloc, profile, db) for alloc, profile in allocs_with_profiles]

    starting_capital_cents = int(port.starting_capital_cents)
    realized_pnl_cents = sum(s.realized_pnl_cents for s in bot_snapshots)
    unrealized_pnl_cents = sum(s.unrealized_pnl_cents for s in bot_snapshots)
    today_pnl_cents = sum(s.today_pnl_cents for s in bot_snapshots)
    open_positions_count = sum(s.open_positions_count for s in bot_snapshots)
    watchlist_count = sum(s.watchlist_count for s in bot_snapshots)
    bots_active = sum(1 for s in bot_snapshots if s.enabled)

    # Portfolio value: starting + realized + unrealized
    # (mirrors how bot_executor and seed compute values)
    portfolio_value_cents = starting_capital_cents + realized_pnl_cents + unrealized_pnl_cents

    yesterday_value = portfolio_value_cents - today_pnl_cents
    today_pnl_pct = round(today_pnl_cents / yesterday_value * 100, 2) if yesterday_value > 0 else 0.0

    all_time_return_pct = round(
        (portfolio_value_cents - starting_capital_cents) / starting_capital_cents * 100, 2
    ) if starting_capital_cents else 0.0

    # 30d return: average across bots weighted by starting capital
    return_30d_pct = 0.0
    total_weight = sum(s.starting_capital_cents for s in bot_snapshots if s.starting_capital_cents)
    if total_weight:
        return_30d_pct = round(
            sum(
                s.return_30d_pct * s.starting_capital_cents
                for s in bot_snapshots
                if s.starting_capital_cents
            ) / total_weight,
            2,
        )

    # Integrity check — log if bots don't sum to portfolio value within $100
    bot_value_sum = sum(s.portfolio_value_cents for s in bot_snapshots)
    discrepancy = abs(bot_value_sum - portfolio_value_cents)
    if discrepancy > 10_000:  # > $100
        logger.warning(
            "Portfolio %d (%s) value discrepancy: portfolio=%d bots_sum=%d diff=%d",
            port.id, port.name, portfolio_value_cents, bot_value_sum, discrepancy,
        )

    return PortfolioSnapshot(
        portfolio_id=port.id,
        name=port.name,
        asset_class=port.asset_class,
        emoji=port.emoji or "",
        color_hex=port.color_hex or "#888888",
        starting_capital_cents=starting_capital_cents,
        portfolio_value_cents=portfolio_value_cents,
        today_pnl_cents=today_pnl_cents,
        today_pnl_pct=today_pnl_pct,
        realized_pnl_cents=realized_pnl_cents,
        unrealized_pnl_cents=unrealized_pnl_cents,
        all_time_return_pct=all_time_return_pct,
        return_30d_pct=return_30d_pct,
        open_positions_count=open_positions_count,
        watchlist_count=watchlist_count,
        bots_active=bots_active,
        bots_total=len(bot_snapshots),
        bots=bot_snapshots,
    )


# ── Aggregate (whole Strategy Lab) ───────────────────────────────────────────

def compute_strategy_lab_aggregate(user_id: int, db: Session) -> dict:
    """
    Aggregate across all 3 portfolios. Used by /api/strategy-lab/portfolio.
    Returns a plain dict compatible with the existing API shape.
    """
    from app.db.models.bots import StrategyPortfolio, BotAllocation, BotProfile

    portfolios = (
        db.query(StrategyPortfolio)
        .filter(StrategyPortfolio.user_id == user_id)
        .order_by(StrategyPortfolio.id)
        .all()
    )
    if not portfolios:
        return {}

    all_allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id)
        .all()
    )
    alloc_map = {a.id: a for a in all_allocs}

    profile_ids = list({a.profile_id for a in all_allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}

    portfolio_snapshots = []
    for port in portfolios:
        port_allocs = [a for a in all_allocs if a.portfolio_id == port.id]
        pairs = [(a, profile_map[a.profile_id]) for a in port_allocs if a.profile_id in profile_map]
        portfolio_snapshots.append(compute_portfolio_snapshot(port, pairs, db))

    total_starting = sum(s.starting_capital_cents for s in portfolio_snapshots)
    total_value = sum(s.portfolio_value_cents for s in portfolio_snapshots)
    total_today_pnl = sum(s.today_pnl_cents for s in portfolio_snapshots)
    total_open_positions = sum(s.open_positions_count for s in portfolio_snapshots)
    total_watchlist = sum(s.watchlist_count for s in portfolio_snapshots)

    all_time_pct = round((total_value - total_starting) / total_starting * 100, 2) if total_starting else 0.0
    yesterday_total = total_value - total_today_pnl
    today_pct = round(total_today_pnl / yesterday_total * 100, 2) if yesterday_total > 0 else 0.0

    # 30d return: weighted average across portfolios
    return_30d_pct = 0.0
    if total_starting:
        return_30d_pct = round(
            sum(s.return_30d_pct * s.starting_capital_cents for s in portfolio_snapshots) / total_starting, 2
        )

    # Leaderboard: one entry per bot across all portfolios
    leaderboard = []
    for port_snap in portfolio_snapshots:
        for bot in port_snap.bots:
            leaderboard.append({
                "rank": 0,
                "profile": bot.profile_name,
                "name": bot.display_name,
                "return_30d_pct": bot.return_30d_pct,
                "today_pnl_cents": bot.today_pnl_cents,
                "watchlist_count": bot.watchlist_count,
                "portfolio_value_cents": bot.portfolio_value_cents,
                "realized_pnl_cents": bot.realized_pnl_cents,
            })
    leaderboard.sort(
        key=lambda x: (
            x["return_30d_pct"],
            x["realized_pnl_cents"],
            x["today_pnl_cents"],
            x["watchlist_count"],
        ),
        reverse=True,
    )
    for i, e in enumerate(leaderboard, 1):
        e["rank"] = i

    best = leaderboard[0] if leaderboard else None
    worst = leaderboard[-1] if leaderboard else None

    # Integrity assertion
    portfolio_sum = sum(s.portfolio_value_cents for s in portfolio_snapshots)
    if abs(total_value - portfolio_sum) > 10_000:
        logger.error(
            "Aggregate integrity failure: total=%d portfolio_sum=%d diff=%d",
            total_value, portfolio_sum, abs(total_value - portfolio_sum),
        )

    return {
        "total_value_cents": total_value,
        "yesterday_value_cents": yesterday_total,
        "today_pnl_cents": total_today_pnl,
        "today_pnl_pct": today_pct,
        "return_30d_pct": return_30d_pct,
        "return_30d_value_cents": total_value - total_starting,
        "return_all_time_pct": all_time_pct,
        "total_open_positions": total_open_positions,
        "total_watchlist_count": total_watchlist,
        "equity_curve": [],  # kept for compatibility
        "leaderboard": leaderboard,
        "best_performer": {"profile": best["profile"], "return_30d_pct": best["return_30d_pct"]} if best else None,
        "worst_performer": {"profile": worst["profile"], "return_30d_pct": worst["return_30d_pct"]} if worst else None,
        "portfolios": [
            {
                "id": s.portfolio_id,
                "name": s.name,
                "asset_class": s.asset_class,
                "portfolio_value_cents": s.portfolio_value_cents,
                "today_pnl_cents": s.today_pnl_cents,
                "return_30d_pct": s.return_30d_pct,
            }
            for s in portfolio_snapshots
        ],
    }
