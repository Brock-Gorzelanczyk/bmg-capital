"""Trade Journal — /api/trades

Closed trade history (entries + matching exits) with filters. Item #3
from Brock's 2026-07-03 audit: "How do I evaluate win rate per bot?
Average winner vs. average loser? Holding period distribution?"

Endpoints:
  GET /api/trades?bot=X&symbol=Y&days=N&outcome=win|loss|all&limit=200
  GET /api/trades/stats?bot=X&days=N  — win rate, avg R:R, hold time
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _round_trip_query(uid: int, days: int) -> str:
    """Return round-trip trades — matches EXIT trades with their position rows.

    2026-07-13 fix: previously the WHERE clause was
    `t.side IN ('sell','cover','close')`. For LONG positions that filters
    correctly (long entry = buy, long exit = sell). But for SHORT positions
    (options credit legs, short-selling stocks) the ENTRY is side='sell' too,
    so entry trades leaked into the "closes" listing with entry=exit=fill
    and pnl=0. That's exactly the 8 phantom options_income closes Brock's
    RIA-stats spec flagged.

    Filter now uses pos.closed_at IS NOT NULL — only positions that are
    actually closed produce rows. For OPTIONS positions that are closed via
    an Alpaca-side settlement without a BMG-recorded BUY-to-close trade
    (expiry-worthless / assignment), the reconcile-options-closes admin
    endpoint materializes a synthetic exit trade with the correct pnl.
    """
    return """
    SELECT
        t.id             AS trade_id,
        pos.id           AS position_id,
        p.name           AS bot,
        p.asset_class    AS asset_class,
        t.symbol         AS symbol,
        pos.side         AS side,
        pos.qty          AS qty,
        pos.avg_cost_cents         AS entry_price_cents,
        t.fill_price_cents         AS exit_price_cents,
        pos.opened_at    AS opened_at,
        t.ts             AS closed_at,
        pos.exit_reason  AS exit_reason,
        (CASE WHEN pos.side = 'short'
              THEN (pos.avg_cost_cents - t.fill_price_cents)
              ELSE (t.fill_price_cents - pos.avg_cost_cents)
         END) * pos.qty AS pnl_cents,
        pos.option_type  AS option_type,
        t.signal_id      AS signal_id
    FROM bot_trades t
    JOIN bot_positions pos ON pos.id = t.position_id
    JOIN bot_allocations a ON a.id = t.allocation_id
    JOIN bot_profiles p ON p.id = a.profile_id
    WHERE a.user_id = :uid
      AND t.side IN ('sell', 'cover', 'close')
      AND t.quarantined_at IS NULL
      AND t.ts >= :cut
      AND pos.closed_at IS NOT NULL
      AND t.ts > pos.opened_at
    """


@router.get("")
def list_trades(
    bot: Optional[str] = Query(None, description="Filter by bot profile name"),
    symbol: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    outcome: str = Query("all", pattern="^(all|win|loss)$"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = _round_trip_query(current_user.id, days)
    params = {"uid": current_user.id, "cut": cut}
    if bot:
        q += " AND p.name = :bot"
        params["bot"] = bot
    if symbol:
        q += " AND t.symbol = :sym"
        params["sym"] = symbol
    q += " ORDER BY t.ts DESC LIMIT :lim"
    params["lim"] = limit

    rows = db.execute(text(q), params).fetchall()

    trades = []
    for r in rows:
        pnl_c = int(r.pnl_cents or 0)
        if outcome == "win" and pnl_c <= 0:
            continue
        if outcome == "loss" and pnl_c >= 0:
            continue
        entry_c = int(r.entry_price_cents or 0)
        exit_c = int(r.exit_price_cents or 0)
        pnl_pct = ((exit_c / entry_c) - 1) * 100 if entry_c > 0 else 0.0
        if r.side == "short" and entry_c > 0:
            pnl_pct = (1 - (exit_c / entry_c)) * 100
        opened = r.opened_at
        closed = r.closed_at
        if isinstance(opened, str):
            opened = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        if isinstance(closed, str):
            closed = datetime.fromisoformat(closed.replace("Z", "+00:00"))
        hold_hours = None
        if opened and closed:
            hold_hours = (closed - opened).total_seconds() / 3600
        trades.append({
            "trade_id": int(r.trade_id),
            "position_id": int(r.position_id),
            "bot": r.bot,
            "asset_class": r.asset_class,
            "symbol": r.symbol,
            "side": r.side,
            "qty": float(r.qty or 0),
            "entry_price_usd": entry_c / 100.0,
            "exit_price_usd": exit_c / 100.0,
            "opened_at": opened.isoformat() if opened else None,
            "closed_at": closed.isoformat() if closed else None,
            "hold_hours": round(hold_hours, 2) if hold_hours is not None else None,
            "exit_reason": r.exit_reason,
            "pnl_usd": round(pnl_c / 100.0, 2),
            "pnl_pct": round(pnl_pct, 3),
            "is_option": r.option_type is not None,
            "signal_id": int(r.signal_id) if r.signal_id else None,
        })

    return {
        "count": len(trades),
        "filters": {"bot": bot, "symbol": symbol, "days": days, "outcome": outcome, "limit": limit},
        "trades": trades,
    }


# ── /api/trades/top ─────────────────────────────────────────────────────────
# MIROFISH dashboard spec (2026-07-13): dir=wins|losses, window=month.
# Alias to dashboard.top-trades so both surfaces read from the same query.
@router.get("/top")
def top_trades_alias(
    dir: str = Query("wins", pattern="^(wins|losses)$"),
    window: str = Query("month", pattern="^(week|month|quarter|all)$"),
    limit: int = Query(5, ge=1, le=25),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from app.routers.dashboard import get_top_trades, _TOP_TRADES_WINDOW_DAYS
    _win_map = {"week": "7d", "month": "30d", "quarter": "90d", "all": "all"}
    _side = "win" if dir == "wins" else "loss"
    return get_top_trades(
        window=_win_map.get(window, "30d"),
        side=_side,
        limit=limit,
        db=db,
        current_user=current_user,
    )


# ── /api/trades/closed ──────────────────────────────────────────────────────
# MIROFISH dashboard spec: closed-trade stream since a cursor (session_open
# is a timestamp on the client; we accept trade_id cursor OR session_open ISO).
@router.get("/closed")
def closed_trades_stream(
    since: str | None = Query(None, description="Trade ID cursor or ISO timestamp"),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from app.routers.dashboard import get_trade_stream
    since_id: int | None = None
    if since:
        # Accept either an int cursor or an ISO timestamp we'll convert to
        # a cursor via a SELECT MIN(id) WHERE ts >= that timestamp.
        try:
            since_id = int(since)
        except (TypeError, ValueError):
            try:
                cut = datetime.fromisoformat(since.replace("Z", "+00:00"))
                row = db.execute(text(
                    "SELECT MIN(t.id) FROM bot_trades t "
                    "JOIN bot_allocations a ON a.id = t.allocation_id "
                    "WHERE a.user_id = :uid AND t.ts >= :cut"
                ), {"uid": current_user.id, "cut": cut}).fetchone()
                min_id = int(row[0]) if row and row[0] else 0
                since_id = max(0, min_id - 1) if min_id else 0
            except Exception:
                since_id = None
    return get_trade_stream(
        since=since_id, limit=limit, db=db, current_user=current_user,
    )


@router.get("/stats")
def trade_stats(
    bot: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Aggregate stats — win rate, avg winner, avg loser, profit factor, hold time."""
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = _round_trip_query(current_user.id, days)
    params = {"uid": current_user.id, "cut": cut}
    if bot:
        q += " AND p.name = :bot"
        params["bot"] = bot

    rows = db.execute(text(q), params).fetchall()

    if not rows:
        return {"trades": 0, "win_rate": None, "avg_winner_usd": None, "avg_loser_usd": None,
                "profit_factor": None, "expectancy_usd": None, "avg_hold_hours": None,
                "total_pnl_usd": 0.0, "bot": bot, "days": days}

    wins = []
    losses = []
    hold_hours_list = []
    total_pnl = 0.0
    for r in rows:
        pnl = float(r.pnl_cents or 0) / 100.0
        total_pnl += pnl
        opened = r.opened_at
        closed = r.closed_at
        if isinstance(opened, str):
            opened = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        if isinstance(closed, str):
            closed = datetime.fromisoformat(closed.replace("Z", "+00:00"))
        if opened and closed:
            hold_hours_list.append((closed - opened).total_seconds() / 3600)
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(pnl)

    n = len(rows)
    n_win = len(wins)
    n_loss = len(losses)
    total_gains = sum(wins)
    total_losses = abs(sum(losses))

    win_rate = n_win / (n_win + n_loss) if (n_win + n_loss) else None
    avg_winner = (total_gains / n_win) if n_win else None
    avg_loser = (sum(losses) / n_loss) if n_loss else None
    profit_factor = (total_gains / total_losses) if total_losses > 0 else None
    expectancy = (total_pnl / n) if n else None
    avg_hold = (sum(hold_hours_list) / len(hold_hours_list)) if hold_hours_list else None

    return {
        "trades": n,
        "wins": n_win,
        "losses": n_loss,
        "scratches": n - n_win - n_loss,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "avg_winner_usd": round(avg_winner, 2) if avg_winner is not None else None,
        "avg_loser_usd": round(avg_loser, 2) if avg_loser is not None else None,
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "expectancy_usd": round(expectancy, 2) if expectancy is not None else None,
        "avg_hold_hours": round(avg_hold, 2) if avg_hold is not None else None,
        "total_pnl_usd": round(total_pnl, 2),
        "bot": bot,
        "days": days,
    }
