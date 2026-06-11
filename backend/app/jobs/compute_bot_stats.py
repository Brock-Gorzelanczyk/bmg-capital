"""Daily stats rollup — runs at 2 AM ET after market close.

Computes per-allocation performance metrics, writes to
bot_performance_stats, and evaluates tier promotions/demotions.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.db.models.bots import BotAllocation, BotDailyPnL, BotPosition
from app.db.models.allocation import BotPerformanceStats, BotTierHistory
from app.services.allocation_rules import BotMetrics, evaluate_bot

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 30
_SHARPE_RISK_FREE = 0.05  # 5 % annualised risk-free rate


def _compute_sharpe(daily_returns: list[float]) -> float:
    """Annualised Sharpe ratio from a list of daily returns."""
    if len(daily_returns) < 5:
        return 0.0
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / max(n - 1, 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    daily_rf = _SHARPE_RISK_FREE / 252
    return (mean - daily_rf) / std * math.sqrt(252)


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a fraction (0–1)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_profit_factor(pnl_rows: list) -> float:
    """Profit factor = gross_wins / gross_losses."""
    gross_win = sum(r.realized_cents for r in pnl_rows if r.realized_cents > 0)
    gross_loss = sum(abs(r.realized_cents) for r in pnl_rows if r.realized_cents < 0)
    return gross_win / gross_loss if gross_loss > 0 else (2.0 if gross_win > 0 else 1.0)


def run() -> dict:
    """Entry point called by scheduler."""
    db = SessionLocal()
    processed = 0
    promoted = 0
    demoted = 0
    errors = 0

    try:
        today = date.today()
        cutoff = today - timedelta(days=_LOOKBACK_DAYS)

        allocs = db.query(BotAllocation).filter(BotAllocation.enabled.is_(True)).all()

        for alloc in allocs:
            try:
                pnl_rows = (
                    db.query(BotDailyPnL)
                    .filter(
                        BotDailyPnL.allocation_id == alloc.id,
                        BotDailyPnL.date >= cutoff,
                    )
                    .order_by(BotDailyPnL.date)
                    .all()
                )

                all_pnl_rows = (
                    db.query(BotDailyPnL)
                    .filter(BotDailyPnL.allocation_id == alloc.id)
                    .all()
                )

                starting = alloc.starting_capital_cents or 1
                total_realized = sum(r.realized_cents for r in all_pnl_rows)
                current_value = starting + total_realized

                realized_30d = sum(r.realized_cents for r in pnl_rows)
                return_30d_pct = round(realized_30d / starting * 100, 4) if starting else 0.0
                total_return_pct = round(total_realized / starting * 100, 4) if starting else 0.0

                # Equity curve for drawdown
                equity_curve: list[float] = [float(starting)]
                running = starting
                for r in sorted(all_pnl_rows, key=lambda x: x.date):
                    running += r.realized_cents
                    equity_curve.append(float(running))
                max_dd = _compute_max_drawdown(equity_curve)

                # Daily returns for Sharpe
                daily_returns: list[float] = []
                prev = starting
                for r in sorted(pnl_rows, key=lambda x: x.date):
                    if prev > 0:
                        daily_returns.append(r.realized_cents / prev)
                    prev = max(1, prev + r.realized_cents)

                sharpe = _compute_sharpe(daily_returns)
                pf = _compute_profit_factor(all_pnl_rows)

                # Closed positions for win rate
                closed_positions = (
                    db.query(BotPosition)
                    .filter(
                        BotPosition.allocation_id == alloc.id,
                        BotPosition.closed_at.isnot(None),
                        BotPosition.quarantined_at.is_(None),
                    )
                    .all()
                )
                total_trades = len(closed_positions)
                winning_trades = sum(
                    1 for p in closed_positions
                    if p.avg_cost_cents and (
                        (p.side == "long" and p.avg_cost_cents > 0) or p.side == "short"
                    )
                )
                # Simplified win calc: position closed with realized gain
                winning_trades = max(
                    0,
                    sum(1 for r in all_pnl_rows if r.realized_cents > 0),
                )
                losing_trades = max(
                    0,
                    sum(1 for r in all_pnl_rows if r.realized_cents < 0),
                )
                total_trades = winning_trades + losing_trades
                win_rate = round(winning_trades / total_trades, 4) if total_trades > 0 else 0.0

                # Upsert today's stats row
                existing = (
                    db.query(BotPerformanceStats)
                    .filter(
                        BotPerformanceStats.allocation_id == alloc.id,
                        BotPerformanceStats.stat_date == today,
                    )
                    .first()
                )
                if existing:
                    stats = existing
                else:
                    stats = BotPerformanceStats(allocation_id=alloc.id, stat_date=today)
                    db.add(stats)

                stats.total_return_pct = total_return_pct
                stats.return_30d_pct = return_30d_pct
                stats.win_rate = win_rate
                stats.profit_factor = pf
                stats.max_drawdown_pct = round(max_dd, 6)
                stats.sharpe_ratio = round(sharpe, 4)
                stats.total_trades = total_trades
                stats.winning_trades = winning_trades
                stats.losing_trades = losing_trades
                stats.starting_capital_cents = starting
                stats.current_value_cents = current_value
                stats.realized_pnl_cents = total_realized

                db.flush()

                # Evaluate tier
                current_tier = alloc.tier or "T0"
                metrics = BotMetrics(
                    allocation_id=alloc.id,
                    current_tier=current_tier,
                    total_trades=total_trades,
                    win_rate=win_rate,
                    return_30d_pct=return_30d_pct,
                    profit_factor=pf,
                    max_drawdown_pct=round(max_dd, 6),
                    sharpe_ratio=round(sharpe, 4),
                )
                new_tier, reason = evaluate_bot(metrics)

                if new_tier != current_tier:
                    history = BotTierHistory(
                        allocation_id=alloc.id,
                        previous_tier=current_tier,
                        new_tier=new_tier,
                        reason=reason,
                        triggered_by="daily_job",
                        return_30d_pct_at_change=return_30d_pct,
                        win_rate_at_change=win_rate,
                        max_drawdown_at_change=round(max_dd, 6),
                        trade_count_at_change=total_trades,
                    )
                    db.add(history)
                    alloc.tier = new_tier
                    if new_tier > current_tier:
                        promoted += 1
                        logger.info(
                            "Bot %d promoted %s → %s: %s",
                            alloc.id, current_tier, new_tier, reason,
                        )
                    else:
                        demoted += 1
                        logger.warning(
                            "Bot %d demoted %s → %s: %s",
                            alloc.id, current_tier, new_tier, reason,
                        )

                processed += 1
            except Exception as exc:
                errors += 1
                logger.warning("compute_bot_stats: alloc %d failed: %s", alloc.id, exc)

        db.commit()
        logger.info(
            "compute_bot_stats: processed=%d promoted=%d demoted=%d errors=%d",
            processed, promoted, demoted, errors,
        )
    except Exception as exc:
        logger.error("compute_bot_stats job failed: %s", exc, exc_info=True)
        db.rollback()
    finally:
        db.close()

    return {"processed": processed, "promoted": promoted, "demoted": demoted, "errors": errors}
