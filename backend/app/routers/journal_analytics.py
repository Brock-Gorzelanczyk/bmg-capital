from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.journal import JournalEntry

router = APIRouter(prefix="/api/journal", tags=["journal"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division that returns `default` instead of raising on zero denominators."""
    if denominator == 0:
        return default
    return numerator / denominator


def _r_multiple(entry: JournalEntry) -> Optional[float]:
    """Approximate R-multiple as pnl% of entry price."""
    if entry.pnl is None or not entry.entry_price:
        return None
    return (entry.pnl / entry.entry_price) * 100


def _r_bucket(r: float) -> str:
    if r < -2:
        return "<-2R"
    elif r < -1:
        return "-2R to -1R"
    elif r < 0:
        return "-1R to 0"
    elif r < 1:
        return "0 to 1R"
    elif r < 2:
        return "1R to 2R"
    else:
        return ">2R"


# Ordered bucket labels for the response
_BUCKET_ORDER = ["<-2R", "-2R to -1R", "-1R to 0", "0 to 1R", "1R to 2R", ">2R"]


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@router.get("/analytics")
def journal_analytics(
    days: int = Query(default=365, ge=1, description="Only include trades from the last N days"),
    account_type: str = Query(default="all", description="all | paper | live"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Comprehensive trade analytics computed entirely server-side from journal_entries.
    Only trades where pnl is not None are included in calculations.
    """
    # ---- fetch all user entries once ----------------------------------------
    cutoff: date = date.today() - timedelta(days=days)

    raw_entries: list[JournalEntry] = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.user_id == current_user.id,
            JournalEntry.trade_date >= cutoff,
        )
        .order_by(JournalEntry.trade_date, JournalEntry.created_at)
        .all()
    )

    # ---- account-type filter -------------------------------------------------
    if account_type == "paper":
        raw_entries = [e for e in raw_entries if e.paper_order_id is not None]
    elif account_type == "live":
        raw_entries = [e for e in raw_entries if e.paper_order_id is None]

    # Only aggregate rows that have a settled pnl value
    entries = [e for e in raw_entries if e.pnl is not None]

    if not entries:
        return _empty_response()

    pnls = [e.pnl for e in entries]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    r_multiples = [rm for e in entries if (rm := _r_multiple(e)) is not None]

    # ---- headline stats ------------------------------------------------------
    total_trades = len(entries)
    win_rate = round(_safe_div(len(wins), total_trades) * 100, 2)
    profit_factor = round(
        _safe_div(sum(wins), abs(sum(losses)) if losses else 0, default=0.0), 4
    ) if losses else (float("inf") if wins else 0.0)
    # Cap profit_factor at a reasonable sentinel instead of inf for JSON safety
    if profit_factor == float("inf"):
        profit_factor = 9999.0

    avg_r_multiple = round(_safe_div(sum(r_multiples), len(r_multiples)), 4) if r_multiples else 0.0
    total_pnl = round(sum(pnls), 2)

    # Equity curve + max drawdown -----------------------------------------------
    # Build daily cumulative pnl
    daily_pnl: dict[str, float] = defaultdict(float)
    for e in entries:
        day_key = str(e.trade_date)
        daily_pnl[day_key] += e.pnl  # type: ignore[operator]

    sorted_days = sorted(daily_pnl.keys())
    equity_curve: list[dict] = []
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for day in sorted_days:
        cumulative = round(cumulative + daily_pnl[day], 4)
        equity_curve.append({"date": day, "cumulative_pnl": cumulative})
        if cumulative > peak:
            peak = cumulative
        drawdown = _safe_div(peak - cumulative, abs(peak)) * 100 if peak != 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    max_drawdown = round(max_drawdown, 2)

    # avg_hold_days: use days between trade_date and created_at as proxy
    hold_days_list = [
        (e.created_at.date() - e.trade_date).days
        for e in entries
        if e.created_at and (e.created_at.date() - e.trade_date).days >= 0
    ]
    avg_hold_days = round(
        _safe_div(sum(hold_days_list), len(hold_days_list)), 1
    ) if hold_days_list else 0.0

    # best / worst trade -------------------------------------------------------
    best_entry = max(entries, key=lambda e: e.pnl)  # type: ignore[return-value]
    worst_entry = min(entries, key=lambda e: e.pnl)  # type: ignore[return-value]

    def _trade_summary(e: JournalEntry) -> dict:
        pnl_pct = round(_r_multiple(e) or 0.0, 4)
        return {
            "symbol": e.symbol,
            "pnl": round(e.pnl, 2),  # type: ignore[arg-type]
            "pnl_pct": pnl_pct,
            "date": str(e.trade_date),
        }

    best_trade = _trade_summary(best_entry)
    worst_trade = _trade_summary(worst_entry)

    # ---- by setup ------------------------------------------------------------
    setup_map: dict[str, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        key = e.setup or "(none)"
        setup_map[key].append(e)

    by_setup = []
    for setup_name, group in setup_map.items():
        g_pnls = [e.pnl for e in group]
        g_wins = sum(1 for p in g_pnls if p > 0)
        g_losses = len(g_pnls) - g_wins
        g_r = [rm for e in group if (rm := _r_multiple(e)) is not None]
        by_setup.append({
            "setup": setup_name,
            "trade_count": len(group),
            "wins": g_wins,
            "losses": g_losses,
            "win_rate": round(_safe_div(g_wins, len(group)) * 100, 2),
            "avg_pnl": round(_safe_div(sum(g_pnls), len(g_pnls)), 2),  # type: ignore[arg-type]
            "total_pnl": round(sum(g_pnls), 2),  # type: ignore[arg-type]
            "avg_r_multiple": round(_safe_div(sum(g_r), len(g_r)), 4) if g_r else 0.0,
        })
    by_setup.sort(key=lambda x: x["total_pnl"], reverse=True)

    # ---- by symbol -----------------------------------------------------------
    symbol_map: dict[str, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        symbol_map[e.symbol].append(e)

    by_symbol = []
    for sym, group in symbol_map.items():
        g_pnls = [e.pnl for e in group]
        g_wins = sum(1 for p in g_pnls if p > 0)
        by_symbol.append({
            "symbol": sym,
            "trade_count": len(group),
            "wins": g_wins,
            "losses": len(group) - g_wins,
            "win_rate": round(_safe_div(g_wins, len(group)) * 100, 2),
            "total_pnl": round(sum(g_pnls), 2),  # type: ignore[arg-type]
        })
    by_symbol.sort(key=lambda x: x["total_pnl"], reverse=True)
    by_symbol = by_symbol[:20]

    # ---- by month ------------------------------------------------------------
    month_map: dict[str, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        month_key = str(e.trade_date)[:7]  # "YYYY-MM"
        month_map[month_key].append(e)

    by_month = []
    for month_key in sorted(month_map.keys()):
        group = month_map[month_key]
        g_pnls = [e.pnl for e in group]
        g_wins = sum(1 for p in g_pnls if p > 0)
        by_month.append({
            "month": month_key,
            "trade_count": len(group),
            "total_pnl": round(sum(g_pnls), 2),  # type: ignore[arg-type]
            "win_rate": round(_safe_div(g_wins, len(group)) * 100, 2),
        })

    # ---- R-multiple distribution ---------------------------------------------
    bucket_counts: dict[str, int] = {b: 0 for b in _BUCKET_ORDER}
    for rm in r_multiples:
        bucket_counts[_r_bucket(rm)] += 1

    r_distribution = [{"bucket": b, "count": bucket_counts[b]} for b in _BUCKET_ORDER]

    # ---- streak analysis -----------------------------------------------------
    # entries are already ordered by trade_date asc
    win_flags = [e.pnl > 0 for e in entries]  # type: ignore[operator]

    current_win_streak = 0
    current_loss_streak = 0
    # Walk backward from most recent to find current streaks
    for flag in reversed(win_flags):
        if flag:
            if current_loss_streak > 0:
                break
            current_win_streak += 1
        else:
            if current_win_streak > 0:
                break
            current_loss_streak += 1

    longest_win_streak = 0
    longest_loss_streak = 0
    run_w = run_l = 0
    for flag in win_flags:
        if flag:
            run_w += 1
            run_l = 0
        else:
            run_l += 1
            run_w = 0
        longest_win_streak = max(longest_win_streak, run_w)
        longest_loss_streak = max(longest_loss_streak, run_l)

    streaks = {
        "current_win_streak": current_win_streak,
        "current_loss_streak": current_loss_streak,
        "longest_win_streak": longest_win_streak,
        "longest_loss_streak": longest_loss_streak,
    }

    # ---- by mood -------------------------------------------------------------
    mood_map: dict[int, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        if e.mood is not None:
            mood_map[e.mood].append(e)

    by_mood = []
    for mood_val in sorted(mood_map.keys()):
        group = mood_map[mood_val]
        g_pnls = [e.pnl for e in group]
        g_wins = sum(1 for p in g_pnls if p > 0)
        by_mood.append({
            "mood": mood_val,
            "count": len(group),
            "avg_pnl": round(_safe_div(sum(g_pnls), len(g_pnls)), 2),  # type: ignore[arg-type]
            "win_rate": round(_safe_div(g_wins, len(group)) * 100, 2),
        })

    # ---- assemble response ---------------------------------------------------
    return {
        "headline": {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_r_multiple": avg_r_multiple,
            "total_pnl": total_pnl,
            "max_drawdown": max_drawdown,
            "avg_hold_days": avg_hold_days,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        },
        "equity_curve": equity_curve,
        "by_setup": by_setup,
        "by_symbol": by_symbol,
        "by_month": by_month,
        "r_distribution": r_distribution,
        "streaks": streaks,
        "by_mood": by_mood,
        "filters": {
            "days": days,
            "account_type": account_type,
            "cutoff_date": str(cutoff),
        },
    }


@router.get("/analytics/demo")
async def get_demo_analytics():
    """
    Returns a pre-generated synthetic AnalyticsResult for investor demos.
    Hard-coded fixed numbers — stable across requests, no auth required.
    """
    return {
        "headline": {
            "total_trades": 94,
            "win_rate": 61.7,
            "profit_factor": 2.31,
            "avg_r_multiple": 1.84,
            "total_pnl": 12847.50,
            "max_drawdown": 25.20,
            "avg_hold_days": 4.2,
            "best_trade": {"symbol": "NVDA", "pnl": 4812.00, "pnl_pct": 3.84, "date": "2025-04-25"},
            "worst_trade": {"symbol": "TSLA", "pnl": -1240.00, "pnl_pct": -1.98, "date": "2025-04-04"},
        },
        "equity_curve": [
            {"date": "2025-03-01", "cumulative_pnl": 0},
            {"date": "2025-03-03", "cumulative_pnl": 240},
            {"date": "2025-03-05", "cumulative_pnl": 890},
            {"date": "2025-03-07", "cumulative_pnl": 1240},
            {"date": "2025-03-10", "cumulative_pnl": 2100},
            {"date": "2025-03-12", "cumulative_pnl": 1840},
            {"date": "2025-03-14", "cumulative_pnl": 1320},
            {"date": "2025-03-17", "cumulative_pnl": 2480},
            {"date": "2025-03-19", "cumulative_pnl": 3100},
            {"date": "2025-03-21", "cumulative_pnl": 3890},
            {"date": "2025-03-24", "cumulative_pnl": 4200},
            {"date": "2025-03-26", "cumulative_pnl": 3740},
            {"date": "2025-03-28", "cumulative_pnl": 5120},
            {"date": "2025-03-31", "cumulative_pnl": 5890},
            {"date": "2025-04-02", "cumulative_pnl": 6340},
            {"date": "2025-04-04", "cumulative_pnl": 5100},
            {"date": "2025-04-07", "cumulative_pnl": 4860},
            {"date": "2025-04-09", "cumulative_pnl": 5920},
            {"date": "2025-04-11", "cumulative_pnl": 7200},
            {"date": "2025-04-14", "cumulative_pnl": 7840},
            {"date": "2025-04-16", "cumulative_pnl": 8490},
            {"date": "2025-04-18", "cumulative_pnl": 9120},
            {"date": "2025-04-21", "cumulative_pnl": 9780},
            {"date": "2025-04-23", "cumulative_pnl": 10340},
            {"date": "2025-04-25", "cumulative_pnl": 11200},
            {"date": "2025-04-28", "cumulative_pnl": 11840},
            {"date": "2025-04-30", "cumulative_pnl": 12100},
            {"date": "2025-05-02", "cumulative_pnl": 12847},
        ],
        "by_setup": [
            {"setup": "Breakout", "trade_count": 28, "wins": 19, "losses": 9, "win_rate": 67.9, "avg_pnl": 284.50, "total_pnl": 7966.00, "avg_r_multiple": 2.1},
            {"setup": "Pullback", "trade_count": 22, "wins": 14, "losses": 8, "win_rate": 63.6, "avg_pnl": 198.20, "total_pnl": 4360.40, "avg_r_multiple": 1.8},
            {"setup": "Trend Follow", "trade_count": 18, "wins": 12, "losses": 6, "win_rate": 66.7, "avg_pnl": 156.80, "total_pnl": 2822.40, "avg_r_multiple": 1.6},
            {"setup": "Reversal", "trade_count": 14, "wins": 7, "losses": 7, "win_rate": 50.0, "avg_pnl": -12.40, "total_pnl": -173.60, "avg_r_multiple": 0.9},
            {"setup": "Earnings Play", "trade_count": 12, "wins": 6, "losses": 6, "win_rate": 50.0, "avg_pnl": -87.70, "total_pnl": -1052.40, "avg_r_multiple": 0.7},
        ],
        "by_symbol": [
            {"symbol": "NVDA", "trade_count": 18, "wins": 13, "losses": 5, "win_rate": 72.2, "total_pnl": 4812.00},
            {"symbol": "AAPL", "trade_count": 15, "wins": 10, "losses": 5, "win_rate": 66.7, "total_pnl": 2340.00},
            {"symbol": "MSFT", "trade_count": 12, "wins": 8, "losses": 4, "win_rate": 66.7, "total_pnl": 1890.00},
            {"symbol": "AMD", "trade_count": 10, "wins": 6, "losses": 4, "win_rate": 60.0, "total_pnl": 1240.00},
            {"symbol": "SPY", "trade_count": 8, "wins": 5, "losses": 3, "win_rate": 62.5, "total_pnl": 980.00},
            {"symbol": "TSLA", "trade_count": 14, "wins": 7, "losses": 7, "win_rate": 50.0, "total_pnl": 840.00},
            {"symbol": "QQQ", "trade_count": 6, "wins": 4, "losses": 2, "win_rate": 66.7, "total_pnl": 620.00},
            {"symbol": "META", "trade_count": 11, "wins": 5, "losses": 6, "win_rate": 45.5, "total_pnl": 125.50},
        ],
        "by_month": [
            {"month": "2025-03", "trade_count": 34, "total_pnl": 5890.00, "win_rate": 64.7},
            {"month": "2025-04", "trade_count": 38, "total_pnl": 5210.00, "win_rate": 60.5},
            {"month": "2025-05", "trade_count": 22, "total_pnl": 1747.50, "win_rate": 59.1},
        ],
        "r_distribution": [
            {"bucket": "<-2R", "count": 4},
            {"bucket": "-2R to -1R", "count": 12},
            {"bucket": "-1R to 0", "count": 20},
            {"bucket": "0 to 1R", "count": 18},
            {"bucket": "1R to 2R", "count": 24},
            {"bucket": ">2R", "count": 16},
        ],
        "streaks": {
            "current_win_streak": 3,
            "current_loss_streak": 0,
            "longest_win_streak": 8,
            "longest_loss_streak": 4,
        },
        "by_mood": [
            {"mood": 5, "count": 28, "avg_pnl": 312.40, "win_rate": 71.4},
            {"mood": 4, "count": 32, "avg_pnl": 184.20, "win_rate": 62.5},
            {"mood": 3, "count": 24, "avg_pnl": 48.90, "win_rate": 54.2},
            {"mood": 2, "count": 6, "avg_pnl": -124.00, "win_rate": 33.3},
            {"mood": 1, "count": 4, "avg_pnl": -287.00, "win_rate": 25.0},
        ],
        "filters": {"days": 90, "account_type": "all", "cutoff_date": "2025-03-01"},
    }


def _empty_response() -> dict:
    """Return a zero-value response shape when no matching trades exist."""
    return {
        "headline": {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_r_multiple": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "avg_hold_days": 0.0,
            "best_trade": None,
            "worst_trade": None,
        },
        "equity_curve": [],
        "by_setup": [],
        "by_symbol": [],
        "by_month": [],
        "r_distribution": [{"bucket": b, "count": 0} for b in _BUCKET_ORDER],
        "streaks": {
            "current_win_streak": 0,
            "current_loss_streak": 0,
            "longest_win_streak": 0,
            "longest_loss_streak": 0,
        },
        "by_mood": [],
        "filters": {},
    }
