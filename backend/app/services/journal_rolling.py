"""journal_rolling.py — rolling 30-day aggregates from bot_daily_journals.

Phase 1 stores the rolling summary as a pseudo-row in bot_daily_journals
with bot_id = f'{bot_id}__rolling30' so no second table is needed.
The UNIQUE constraint on (allocation_id, journal_date) means we use
allocation_id=0 as a sentinel for rolling pseudo-rows (no real allocation
has id=0 in SQLite AUTOINCREMENT — starts at 1).

The endpoint distinguishes real rows from rolling rows by the __rolling30 suffix.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SHARPE_RISK_FREE = 0.05   # 5% annualised
_MIN_DAYS_FOR_SHARPE = 5


def _compute_sharpe(daily_return_pcts: list[float]) -> float:
    """Annualised Sharpe from a series of day_return_pct values (already in %).

    Returns 0.0 when fewer than _MIN_DAYS_FOR_SHARPE samples available.
    Mirrors the pattern in app/jobs/compute_bot_stats.py.
    """
    if len(daily_return_pcts) < _MIN_DAYS_FOR_SHARPE:
        return 0.0
    # Convert % to decimal returns
    returns = [r / 100.0 for r in daily_return_pcts]
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / max(n - 1, 1)
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    daily_rf = _SHARPE_RISK_FREE / 252.0
    return (mean - daily_rf) / std * math.sqrt(252.0)


def compute_rolling_30d(db: Session, bot_id: str, end_date: date) -> dict:
    """Aggregate the last up-to-30 journal rows for bot_id ending at end_date (inclusive).

    Returns dict with:
      total_pnl_cents, total_trades, total_winners, total_losers,
      win_rate, rolling_sharpe, best_strategy_30d, worst_strategy_30d,
      journals_count, bot_id, end_date.

    If fewer than _MIN_DAYS_FOR_SHARPE days are available, rolling_sharpe = 0.0.
    """
    from app.db.models.bot_daily_journal import BotDailyJournal
    from sqlalchemy import and_

    rows = (
        db.query(BotDailyJournal)
        .filter(
            and_(
                BotDailyJournal.bot_id == bot_id,
                BotDailyJournal.journal_date <= end_date,
                # Exclude rolling pseudo-rows from the aggregation
                ~BotDailyJournal.bot_id.like("%__rolling30"),
            )
        )
        .order_by(BotDailyJournal.journal_date.desc())
        .limit(30)
        .all()
    )

    total_pnl_cents = 0
    total_trades = 0
    total_winners = 0
    total_losers = 0
    daily_return_pcts: list[float] = []
    strategy_pnl: dict[str, int] = {}

    for row in rows:
        total_pnl_cents += row.day_pnl_cents or 0
        total_trades += row.trades_count or 0
        total_winners += row.winning_trades or 0
        total_losers += row.losing_trades or 0
        if row.day_return_pct is not None:
            daily_return_pcts.append(row.day_return_pct)

        # Aggregate strategy pnl across window
        if row.strategies_breakdown_json:
            try:
                breakdown = json.loads(row.strategies_breakdown_json)
                for strat_name, strat_data in breakdown.items():
                    pnl = strat_data.get("pnl_cents", 0) if isinstance(strat_data, dict) else 0
                    strategy_pnl[strat_name] = strategy_pnl.get(strat_name, 0) + pnl
            except (json.JSONDecodeError, TypeError):
                pass

    denom = total_winners + total_losers
    win_rate = (total_winners / denom) if denom > 0 else None

    rolling_sharpe = _compute_sharpe(daily_return_pcts)

    best_strategy_30d: Optional[str] = None
    worst_strategy_30d: Optional[str] = None
    if strategy_pnl:
        best_strategy_30d = max(strategy_pnl, key=lambda k: strategy_pnl[k])
        worst_strategy_30d = min(strategy_pnl, key=lambda k: strategy_pnl[k])

    return {
        "bot_id": bot_id,
        "end_date": end_date.isoformat() if hasattr(end_date, "isoformat") else str(end_date),
        "journals_count": len(rows),
        "total_pnl_cents": total_pnl_cents,
        "total_trades": total_trades,
        "total_winners": total_winners,
        "total_losers": total_losers,
        "win_rate": win_rate,
        "rolling_sharpe": rolling_sharpe,
        "best_strategy_30d": best_strategy_30d,
        "worst_strategy_30d": worst_strategy_30d,
    }


def write_rolling_summary(
    db: Session, bot_id: str, end_date: date, allocation_id: int = 0
) -> dict:
    """Compute rolling 30d summary and UPSERT as a pseudo-row in bot_daily_journals.

    The pseudo-row uses:
      bot_id = f'{bot_id}__rolling30'
      journal_date = end_date
      allocation_id = -(allocation_id) — negative sentinel so UNIQUE(allocation_id, journal_date)
                       never clashes with the real journal row which uses +allocation_id.
                       Negative IDs are valid in SQLite integers and guaranteed not to
                       collide with AUTOINCREMENT rows (which start at 1).
      user_id = 1

    Returns the aggregated summary dict.
    """
    from app.db.models.bot_daily_journal import BotDailyJournal
    from sqlalchemy import and_

    summary = compute_rolling_30d(db, bot_id, end_date)

    pseudo_bot_id = f"{bot_id}__rolling30"
    summary_json = json.dumps(summary)
    pseudo_alloc_id = -(allocation_id) if allocation_id > 0 else -1

    existing = (
        db.query(BotDailyJournal)
        .filter(
            and_(
                BotDailyJournal.bot_id == pseudo_bot_id,
                BotDailyJournal.journal_date == end_date,
            )
        )
        .first()
    )

    kwargs = dict(
        allocation_id=pseudo_alloc_id,
        bot_id=pseudo_bot_id,
        user_id=1,
        journal_date=end_date,
        sleeve=None,
        asset_class=None,
        starting_capital_cents=0,
        ending_pv_cents=0,
        day_pnl_cents=summary["total_pnl_cents"],
        day_return_pct=0.0,
        trades_count=summary["total_trades"],
        winning_trades=summary["total_winners"],
        losing_trades=summary["total_losers"],
        win_rate=summary["win_rate"],
        avg_winner_cents=None,
        avg_loser_cents=None,
        profit_factor=summary["rolling_sharpe"],  # overloaded as sharpe in rolling row
        avg_hold_minutes=None,
        max_concurrent_positions=0,
        end_of_day_positions=0,
        end_of_day_deployed_cents=0,
        deployment_pct_avg=None,
        regime_vix_band=None,
        regime_trend=None,
        regime_btc_dom_band=None,
        strategies_breakdown_json=summary_json,
        errors_24h=0,
        sentry_issues_json="[]",
        body_md=None,
        frontmatter_yaml=None,
    )

    if existing is not None:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.flush()
    else:
        row = BotDailyJournal(**kwargs)
        db.add(row)
        db.flush()

    logger.info(
        "[rolling_30d] wrote pseudo-row for %s end_date=%s journals_count=%d",
        pseudo_bot_id, end_date, summary["journals_count"],
    )
    return summary
