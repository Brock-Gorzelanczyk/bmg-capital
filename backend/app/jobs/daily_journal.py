"""daily_journal.py — nightly 04:00 UTC per-bot journal job.

Phase 1 of the closed-loop learning system. Runs for each enabled
BotAllocation (user_id=1) and writes one row per bot to bot_daily_journals.

Standing decisions:
  - READ-ONLY against bot_trades / bot_positions / bot_allocations / bot_daily_pnl.
  - WRITES go to bot_daily_journals ONLY.
  - NO _ensure_portfolios_for_user — hardcode user_id=1.
  - NO LLM — body is template-only (Phase 1).
  - NO filesystem writes — vault sync is Phase 1b.
  - NO canonical aggregator in per-bot loop — approximation only (Phase 2).
  - starting_capital_cents is ONLY used for day_return_pct (not all-time %).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.bots import (
    BotAllocation,
    BotProfile,
    BotTrade,
    BotPosition,
    BotSignal,
)
from app.services import regime_snapshot as _regime_snapshot
from app.services.journal_writer import infer_sleeve, write_journal_row
from app.services.journal_rolling import write_rolling_summary

logger = logging.getLogger(__name__)

UTC = timezone.utc


def run_daily_journal(
    db: Session,
    target_date: Optional[date] = None,
    user_id: int = 1,
) -> dict:
    """Main entry point — called by APScheduler at 04:00 UTC daily.

    If target_date is None, uses (UTC now - 1 day).date().
    Returns summary dict with bots_processed, rows_written, errors list.

    Per-bot commits so one bad bot doesn't void all others.
    """
    if target_date is None:
        target_date = (datetime.now(UTC) - timedelta(days=1)).date()

    logger.warning("[daily-journal] starting run target_date=%s user_id=%d", target_date, user_id)

    allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == user_id,
            BotAllocation.enabled.is_(True),
        )
        .all()
    )

    bots_processed = 0
    rows_written = 0
    errors: list[dict] = []

    # Check for duplicate bot_ids (known-issues #3 guard)
    bot_id_counts: dict[str, int] = {}
    for alloc in allocs:
        profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        if profile:
            bot_id_counts[profile.name] = bot_id_counts.get(profile.name, 0) + 1
    dup_bots = [bid for bid, cnt in bot_id_counts.items() if cnt > 1]
    if dup_bots:
        logger.warning(
            "[daily-journal] DUPLICATE bot_ids detected (known-issues #3): %s",
            dup_bots,
        )

    for alloc in allocs:
        # Fetch profile
        profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        if profile is None:
            msg = f"BotProfile missing for allocation id={alloc.id} profile_id={alloc.profile_id}"
            logger.error("[daily-journal] %s — skipping", msg)
            errors.append({"bot_id": f"alloc_{alloc.id}", "error": msg})
            continue

        # Edge case: orphan allocation (starting_capital_cents==0 AND disabled)
        if alloc.starting_capital_cents == 0 and not alloc.enabled:
            logger.warning(
                "[daily-journal] skipping orphan alloc id=%d bot=%s (capital=0, disabled)",
                alloc.id, profile.name,
            )
            continue

        try:
            data = _compute_bot_day(db, alloc, profile, target_date)
            row_id = write_journal_row(db, data)
            db.commit()
            write_rolling_summary(db, profile.name, target_date, allocation_id=alloc.id)
            db.commit()
            rows_written += 1
            bots_processed += 1
            logger.info(
                "[daily-journal] wrote journal row_id=%d bot=%s date=%s",
                row_id, profile.name, target_date,
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                "[daily-journal] failed for bot=%s: %s",
                profile.name, exc, exc_info=True,
            )
            errors.append({"bot_id": profile.name, "error": str(exc)})

    logger.warning(
        "[daily-journal] done target_date=%s bots_processed=%d rows_written=%d errors=%d",
        target_date, bots_processed, rows_written, len(errors),
    )

    return {
        "date": target_date.isoformat(),
        "bots_processed": bots_processed,
        "rows_written": rows_written,
        "errors": errors,
    }


def _compute_bot_day(
    db: Session,
    alloc: BotAllocation,
    profile: BotProfile,
    target_date: date,
) -> dict:
    """Compute all metrics for one bot on target_date.

    Returns the data dict consumed by journal_writer.write_journal_row.
    All queries scoped to allocation_id=alloc.id to guarantee user-scoping.
    READ-ONLY — no writes to any table here.
    """
    day_start = datetime.combine(target_date, time.min).replace(tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    def _make_aware(dt: datetime) -> datetime:
        """Ensure datetime is UTC-aware (SQLite returns naive datetimes)."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    # ── Queries ──────────────────────────────────────────────────────────────
    trades_today = (
        db.query(BotTrade)
        .filter(
            BotTrade.allocation_id == alloc.id,
            BotTrade.ts >= day_start,
            BotTrade.ts < day_end,
        )
        .all()
    )

    positions_closed = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == alloc.id,
            BotPosition.closed_at >= day_start,
            BotPosition.closed_at < day_end,
        )
        .all()
    )

    positions_open_eod = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == alloc.id,
            BotPosition.opened_at < day_end,
            or_(
                BotPosition.closed_at.is_(None),
                BotPosition.closed_at >= day_end,
            ),
        )
        .all()
    )

    # ── Trade counts ─────────────────────────────────────────────────────────
    trades_count = len(trades_today)

    # ── Build position_id → exit trade map ───────────────────────────────────
    # Maps position_id → exit trade (side='sell' for long, or the closing trade)
    exit_trade_by_pos: dict[int, BotTrade] = {}
    for t in trades_today:
        if t.position_id and t.side in ("sell", "cover"):
            # Keep last exit trade per position
            exit_trade_by_pos[t.position_id] = t

    # ── Win/loss classification ───────────────────────────────────────────────
    winner_pnls: list[int] = []
    loser_pnls: list[int] = []
    total_realized_pnl_cents = 0

    for pos in positions_closed:
        exit_trade = exit_trade_by_pos.get(pos.id)
        if exit_trade is None:
            # Edge case: missing exit trade — treat as 0 pnl, warn
            logger.warning(
                "[daily-journal] position_id=%d has no exit trade in window — treating as 0 pnl",
                pos.id,
            )
            continue

        # P&L formula: (exit_fill - avg_cost) * qty - fees; negate for shorts
        exit_fill = exit_trade.fill_price_cents
        avg_cost = pos.avg_cost_cents
        qty = pos.qty
        fees = exit_trade.fees_cents or 0

        raw_pnl = (exit_fill - avg_cost) * qty - fees
        if pos.side == "short":
            raw_pnl = -raw_pnl

        pnl_cents = int(round(raw_pnl))
        total_realized_pnl_cents += pnl_cents

        if pnl_cents > 0:
            winner_pnls.append(pnl_cents)
        elif pnl_cents < 0:
            loser_pnls.append(pnl_cents)
        # pnl == 0 counts as neither winner nor loser

    winning_trades = len(winner_pnls)
    losing_trades = len(loser_pnls)
    denom = winning_trades + losing_trades
    win_rate: Optional[float] = (winning_trades / denom) if denom > 0 else None
    avg_winner_cents: Optional[int] = int(mean(winner_pnls)) if winner_pnls else None
    avg_loser_cents: Optional[int] = int(mean(loser_pnls)) if loser_pnls else None

    gross_wins = sum(winner_pnls)
    gross_losses = abs(sum(loser_pnls))
    if gross_losses > 0:
        profit_factor: Optional[float] = gross_wins / gross_losses
    elif gross_wins > 0:
        profit_factor = min(gross_wins / 1, 999.99)   # cap at 999.99
    else:
        profit_factor = None

    # ── Avg hold minutes ──────────────────────────────────────────────────────
    avg_hold_minutes: Optional[float] = None
    if positions_closed:
        hold_durations = []
        for pos in positions_closed:
            if pos.closed_at and pos.opened_at:
                p_opened = _make_aware(pos.opened_at)
                p_closed = _make_aware(pos.closed_at)
                mins = (p_closed - p_opened).total_seconds() / 60.0
                hold_durations.append(mins)
        if hold_durations:
            avg_hold_minutes = mean(hold_durations)

    # ── Max concurrent positions ──────────────────────────────────────────────
    all_positions_in_window = [
        p for p in (positions_closed + positions_open_eod)
        if _make_aware(p.opened_at) < day_end
    ]

    events: list[tuple[datetime, int]] = []
    for p in all_positions_in_window:
        open_ts = _make_aware(p.opened_at)
        raw_close = p.closed_at
        if raw_close is not None:
            raw_close = _make_aware(raw_close)
        close_ts = raw_close if (raw_close and raw_close < day_end) else day_end
        if open_ts.tzinfo is None:
            open_ts = open_ts.replace(tzinfo=UTC)
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        events.append((open_ts, +1))
        events.append((close_ts, -1))

    events.sort(key=lambda e: e[0])
    max_concurrent = 0
    current = 0
    for _, delta in events:
        current += delta
        if current > max_concurrent:
            max_concurrent = current

    # ── EOD positions & deployed ──────────────────────────────────────────────
    end_of_day_positions = len(positions_open_eod)
    end_of_day_deployed_cents = int(
        sum(p.qty * p.avg_cost_cents for p in positions_open_eod)
    )

    # ── Deployment pct avg (hourly sampling) ─────────────────────────────────
    starting_capital_cents = alloc.starting_capital_cents or 0
    deployment_pct_avg: float = 0.0
    if starting_capital_cents > 0:
        hourly_deployed: list[float] = []
        for h in range(24):
            hour_ts = day_start + timedelta(hours=h)
            deployed_at_hour = 0.0
            for p in positions_open_eod + positions_closed:
                p_open = _make_aware(p.opened_at)
                p_close = _make_aware(p.closed_at) if p.closed_at is not None else None
                is_open_at_hour = (
                    p_open <= hour_ts and
                    (p_close is None or p_close > hour_ts)
                )
                if is_open_at_hour:
                    deployed_at_hour += float(p.qty) * float(p.avg_cost_cents)
            hourly_deployed.append(deployed_at_hour)
        deployment_pct_avg = (
            mean(hourly_deployed) / starting_capital_cents
            if hourly_deployed else 0.0
        )

    # ── Day P&L (realized only in Phase 1) ───────────────────────────────────
    day_pnl_cents = total_realized_pnl_cents
    # unrealized delta = 0 for Phase 1 (no MTM service call)

    # ── Day return % ─────────────────────────────────────────────────────────
    if starting_capital_cents > 0:
        day_return_pct = round(day_pnl_cents / starting_capital_cents * 100, 4)
    else:
        day_return_pct = 0.0

    # ── ending_pv_cents (approximation) ──────────────────────────────────────
    ending_pv_cents = starting_capital_cents + day_pnl_cents

    # ── Strategies breakdown ──────────────────────────────────────────────────
    # Map trade → signal → strategy via signal_id join
    strategies_breakdown: dict[str, dict] = {}

    # Build signal_id → strategy map for trades today
    signal_ids = [t.signal_id for t in trades_today if t.signal_id is not None]
    signal_strategy_map: dict[int, str] = {}
    if signal_ids:
        signals = (
            db.query(BotSignal)
            .filter(BotSignal.id.in_(signal_ids))
            .all()
        )
        for sig in signals:
            signal_strategy_map[sig.id] = sig.strategy or "unknown"

    # Build position_id → pnl map from classified positions
    pos_pnl: dict[int, int] = {}
    for pos in positions_closed:
        exit_trade = exit_trade_by_pos.get(pos.id)
        if exit_trade is None:
            continue
        raw_pnl = (exit_trade.fill_price_cents - pos.avg_cost_cents) * pos.qty - (exit_trade.fees_cents or 0)
        if pos.side == "short":
            raw_pnl = -raw_pnl
        pos_pnl[pos.id] = int(round(raw_pnl))

    for trade in trades_today:
        strategy = signal_strategy_map.get(trade.signal_id, "unknown") if trade.signal_id else "unknown"
        if strategy not in strategies_breakdown:
            strategies_breakdown[strategy] = {"signals": 0, "trades": 0, "pnl_cents": 0}
        strategies_breakdown[strategy]["signals"] += 1
        strategies_breakdown[strategy]["trades"] += 1
        # Add pnl for this trade's position if we have it
        if trade.position_id and trade.position_id in pos_pnl:
            strategies_breakdown[strategy]["pnl_cents"] += pos_pnl[trade.position_id]

    # ── Regime snapshot ────────────────────────────────────────────────────────
    regime = _regime_snapshot.snapshot(db)

    # ── Sleeve / asset_class ──────────────────────────────────────────────────
    config_json = profile.config_json if isinstance(profile.config_json, dict) else None
    sleeve = infer_sleeve(profile.name, config_json)
    asset_class = profile.asset_class  # stock|crypto from BotProfile

    return {
        "allocation_id": alloc.id,
        "bot_id": profile.name,
        "user_id": alloc.user_id,
        "journal_date": target_date,
        "date": target_date.isoformat(),
        "sleeve": sleeve,
        "asset_class": asset_class,
        "starting_capital_cents": starting_capital_cents,
        "ending_pv_cents": ending_pv_cents,
        "day_pnl_cents": day_pnl_cents,
        "day_return_pct": day_return_pct,
        "trades_count": trades_count,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "avg_winner_cents": avg_winner_cents,
        "avg_loser_cents": avg_loser_cents,
        "profit_factor": profit_factor,
        "avg_hold_minutes": avg_hold_minutes,
        "max_concurrent_positions": max_concurrent,
        "end_of_day_positions": end_of_day_positions,
        "end_of_day_deployed_cents": end_of_day_deployed_cents,
        "deployment_pct_avg": deployment_pct_avg,
        "regime_vix_band": regime["vix_band"],
        "regime_trend": regime["trend"],
        "regime_btc_dom_band": regime["btc_dom_band"],
        "regime_when_active": regime,
        "strategies_breakdown": strategies_breakdown,
        "strategies_breakdown_json": json.dumps(strategies_breakdown),
        "errors_24h": 0,
        "sentry_issues_24h": [],
    }
