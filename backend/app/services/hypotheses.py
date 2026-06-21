"""Hypothesis service — join hypothesis config with derived BotTrade stats.

Live stats (n_trades, n_wins, win_rate, expected_r, last_trade) are computed
at query time from bot_trades so no runner.py modifications are required.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Default factor exposures by strategy category — seeded into hypotheses.factor_exposures
# Keys must match the JARVIS sidebar abbreviations.
_DEFAULT_FACTORS_BY_CATEGORY: dict[str, dict[str, float]] = {
    "momentum":      {"mom": 0.85, "trd": 0.75, "vol": 0.55, "flw": 0.40, "mr":  0.05, "time": 0.5, "hyp": 0.7},
    "mean_reversion":{"mom": 0.15, "trd": 0.20, "vol": 0.45, "flw": 0.35, "mr":  0.90, "time": 0.5, "hyp": 0.7},
    "trend":         {"mom": 0.70, "trd": 0.95, "vol": 0.50, "flw": 0.35, "mr":  0.10, "time": 0.5, "hyp": 0.7},
    "breakout":      {"mom": 0.75, "trd": 0.60, "vol": 0.80, "flw": 0.55, "mr":  0.10, "time": 0.6, "hyp": 0.7},
    "volatility":    {"mom": 0.30, "trd": 0.35, "vol": 0.85, "flw": 0.30, "mr":  0.55, "time": 0.5, "hyp": 0.7},
    "options":       {"mom": 0.45, "trd": 0.45, "vol": 0.80, "flw": 0.40, "mr":  0.55, "time": 0.55, "hyp": 0.7},
    "income":        {"mom": 0.25, "trd": 0.30, "vol": 0.45, "flw": 0.30, "mr":  0.70, "time": 0.5, "hyp": 0.7},
    "factor":        {"mom": 0.90, "trd": 0.65, "vol": 0.35, "flw": 0.20, "mr":  0.05, "time": 0.3, "hyp": 0.75},
}


def _default_factors(category: str | None) -> dict[str, float]:
    base = _DEFAULT_FACTORS_BY_CATEGORY.get((category or "").lower())
    if base:
        return dict(base)
    return {"mom": 0.5, "trd": 0.5, "vol": 0.5, "flw": 0.5, "mr": 0.5, "time": 0.5, "hyp": 0.7}


def seed_hypotheses_from_strategies(db: Session) -> int:
    """Insert one Hypothesis per StrategyDefinition that doesn't already have one.

    Idempotent — uses strategy_id uniqueness constraint to skip existing rows.
    """
    from app.db.models.strategy_definition import StrategyDefinition
    from app.db.models.hypotheses import Hypothesis

    inserted = 0
    try:
        strategies = db.query(StrategyDefinition).filter(StrategyDefinition.is_active == True).all()  # noqa: E712
    except Exception as exc:
        logger.warning("[hypotheses] seed: cannot read StrategyDefinition: %s", exc)
        return 0

    for sd in strategies:
        try:
            existing = db.query(Hypothesis).filter_by(strategy_id=sd.strategy_key).first()
            if existing:
                continue
            # Default new hypotheses to "testing" — promotion to live is a
            # manual decision via the /strategy/hypotheses promote button.
            # Existing rows are unaffected because we skip them above.
            row = Hypothesis(
                name=sd.name,
                strategy_id=sd.strategy_key,
                direction="both",
                status="testing",
                regime_preference=(sd.parameters or {}).get("regime_preference"),
                factor_exposures=_default_factors(sd.category),
                notes=None,
            )
            db.add(row)
            inserted += 1
        except Exception as exc:
            db.rollback()
            logger.warning("[hypotheses] seed row failed for %s: %s", sd.strategy_key, exc)
    try:
        db.commit()
        if inserted:
            logger.info("[hypotheses] seeded %d new hypotheses from strategy_definitions", inserted)
    except Exception as exc:
        db.rollback()
        logger.warning("[hypotheses] seed commit failed: %s", exc)
    return inserted


def _session_label(ts: datetime) -> str:
    """Bucket a UTC timestamp into a JARVIS-style session label."""
    if ts is None:
        return "OVERNIGHT"
    # Convert UTC ts to ET (approx — uses fixed offset; close enough for labeling)
    et_offset = -4  # EDT; -5 in winter — labeling only, not trade execution
    h_local = (ts.hour + et_offset) % 24
    if 9 <= h_local <= 11:
        return "NY_AM"
    if 12 <= h_local <= 15:
        return "NY_PM"
    if 3 <= h_local <= 8:
        return "LONDON"
    if 16 <= h_local <= 19:
        return "ASIA"
    return "OVERNIGHT"


_EMPTY_STATS: dict[str, Any] = {
    "n_trades": 0,
    "n_wins": 0,
    "n_losses": 0,
    "n_breakeven": 0,
    "win_rate": 0.0,
    "expected_r": 0.0,
    "r_multiple": 0.0,
    "last_trade": None,
    "total_trades_all_sides": 0,
    "last_signal_ts": None,
}


def _compute_trade_stats(db: Session, strategy_id: str) -> dict[str, Any]:
    """Aggregate per-strategy trade stats by joining BotSignal.strategy → BotTrade.signal_id.

    Neither BotTrade nor BotPosition stores `strategy`, so we route via BotSignal,
    then compute realized P&L from (sell.fill_price - position.avg_cost) × qty.

    Wrapped: any single sub-query failure returns the zero-stats block rather
    than 500-ing the parent endpoint.
    """
    try:
        from app.db.models.bots import BotTrade, BotSignal, BotPosition

        sig_ids_subq = (
            db.query(BotSignal.id)
            .filter(BotSignal.strategy == strategy_id)
            .subquery()
        )

        # All trades whose signal is for this strategy
        all_trades = (
            db.query(BotTrade)
            .filter(
                BotTrade.signal_id.in_(sig_ids_subq),
                BotTrade.quarantined_at.is_(None),
            )
            .all()
        )

        # Last signal time (separate query — useful even when no trades fired)
        last_sig_ts = (
            db.query(func.max(BotSignal.ts))
            .filter(BotSignal.strategy == strategy_id)
            .scalar()
        )

        if not all_trades:
            return {
                **_EMPTY_STATS,
                "last_signal_ts": last_sig_ts.isoformat() if last_sig_ts else None,
            }

        # Group sell-side trades by position_id for P&L matching
        sells_by_pos: dict[int, list] = {}
        for t in all_trades:
            if t.side in ("sell", "cover") and t.position_id:
                sells_by_pos.setdefault(t.position_id, []).append(t)

        # Pull positions referenced by any of our trades
        pos_ids = list({t.position_id for t in all_trades if t.position_id is not None})
        positions_by_id: dict[int, Any] = {}
        if pos_ids:
            for p in db.query(BotPosition).filter(BotPosition.id.in_(pos_ids)).all():
                positions_by_id[p.id] = p

        # Closed-trade outcomes
        outcomes: list[dict[str, Any]] = []
        for pos_id, sells in sells_by_pos.items():
            pos = positions_by_id.get(pos_id)
            if not pos or not pos.closed_at:
                continue
            last_sell = max(sells, key=lambda s: s.ts)
            qty = abs(last_sell.qty or 0)
            avg_cost = float(pos.avg_cost_cents or 0)
            sell_px = float(last_sell.fill_price_cents or 0)
            is_short = (pos.side or "long") == "short"
            if is_short:
                pnl_cents = (avg_cost - sell_px) * qty
            else:
                pnl_cents = (sell_px - avg_cost) * qty
            pnl_cents -= float(last_sell.fees_cents or 0)
            outcomes.append({
                "pnl_cents": int(pnl_cents),
                "sell_trade": last_sell,
                "pos_side": pos.side,
            })

        n = len(outcomes)
        wins = sum(1 for o in outcomes if o["pnl_cents"] > 0)
        losses = sum(1 for o in outcomes if o["pnl_cents"] < 0)
        breakeven = n - wins - losses
        win_rate = (wins / n) if n else 0.0

        avg_win_cents = (
            sum(o["pnl_cents"] for o in outcomes if o["pnl_cents"] > 0) / wins
        ) if wins else 0.0
        avg_loss_cents = (
            sum(-o["pnl_cents"] for o in outcomes if o["pnl_cents"] < 0) / losses
        ) if losses else 0.0
        r_multiple = (avg_win_cents / avg_loss_cents) if avg_loss_cents else 0.0
        expectancy_cents = (win_rate * avg_win_cents) - ((1 - win_rate) * avg_loss_cents)
        expected_r_proxy = (expectancy_cents / avg_loss_cents) if avg_loss_cents else 0.0

        # "Last trade" block — most recent closed-outcome
        last_block: dict[str, Any] | None = None
        if outcomes:
            latest = max(outcomes, key=lambda o: o["sell_trade"].ts)
            sell = latest["sell_trade"]
            pnl_cents = latest["pnl_cents"]
            outcome_word = "win" if pnl_cents > 0 else "loss" if pnl_cents < 0 else "breakeven"
            last_block = {
                "side": sell.side,
                "price": (sell.fill_price_cents / 100.0) if sell.fill_price_cents else None,
                "outcome": outcome_word,
                "pnl_dollars": round(pnl_cents / 100.0, 2),
                "session": _session_label(sell.ts) if sell.ts else "OVERNIGHT",
                "ts": sell.ts.isoformat() if sell.ts else None,
            }

        return {
            "n_trades": n,
            "n_wins": wins,
            "n_losses": losses,
            "n_breakeven": breakeven,
            "win_rate": round(win_rate * 100, 1),
            "expected_r": round(expected_r_proxy, 3),
            "r_multiple": round(r_multiple, 2),
            "last_trade": last_block,
            "total_trades_all_sides": len(all_trades),
            "last_signal_ts": last_sig_ts.isoformat() if last_sig_ts else None,
        }

    except Exception as exc:
        logger.warning("[hypotheses] _compute_trade_stats failed for %s: %s", strategy_id, exc)
        return dict(_EMPTY_STATS)


def list_live_hypotheses(db: Session) -> list[dict]:
    """Return all hypotheses with derived live stats and config.

    Per-row try/except so one corrupt hypothesis or query failure cannot
    500 the whole endpoint.
    """
    from app.db.models.hypotheses import Hypothesis

    try:
        hyps = db.query(Hypothesis).order_by(Hypothesis.status.asc(), Hypothesis.name.asc()).all()
    except Exception as exc:
        logger.error("[hypotheses] list_live_hypotheses query failed: %s", exc, exc_info=True)
        return []

    out: list[dict] = []
    for h in hyps:
        try:
            stats = _compute_trade_stats(db, h.strategy_id)
            out.append({
                "id": h.id,
                "name": h.name,
                "strategy_id": h.strategy_id,
                "direction": h.direction,
                "status": h.status,
                "regime_preference": h.regime_preference,
                "factor_exposures": h.factor_exposures or {},
                "notes": h.notes,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                **stats,
            })
        except Exception as exc:
            logger.warning("[hypotheses] row build failed for hypothesis #%s: %s", getattr(h, "id", "?"), exc)
            try:
                out.append({
                    "id": getattr(h, "id", None),
                    "name": getattr(h, "name", "?"),
                    "strategy_id": getattr(h, "strategy_id", "?"),
                    "direction": getattr(h, "direction", "both"),
                    "status": getattr(h, "status", "testing"),
                    "regime_preference": None,
                    "factor_exposures": {},
                    "notes": None,
                    "created_at": None,
                    "updated_at": None,
                    **_EMPTY_STATS,
                })
            except Exception:
                pass
    return out


def aggregate_factor_exposures(hyps: list[dict]) -> dict[str, float]:
    """Weighted-by-status mean of factor exposures across live hypotheses.

    Only live hypotheses contribute (testing/retired excluded). Returns
    {factor: 0..1} for the sidebar bars.
    """
    keys = ["mom", "trd", "vol", "flw", "mr", "time", "hyp"]
    live = [h for h in hyps if h.get("status") == "live"]
    if not live:
        return {k: 0.0 for k in keys}
    out: dict[str, float] = {}
    for k in keys:
        vals = [float((h.get("factor_exposures") or {}).get(k, 0.0)) for h in live]
        out[k] = round(sum(vals) / len(vals), 2) if vals else 0.0
    return out


def list_system_events(db: Session, limit: int = 20) -> list[dict]:
    from app.db.models.hypotheses import SystemEvent
    rows = db.query(SystemEvent).order_by(SystemEvent.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "event_type": r.event_type,
            "message": r.message,
            "ts": r.ts.isoformat() if r.ts else None,
        }
        for r in rows
    ]


def record_system_event(db: Session, event_type: str, message: str, payload: dict | None = None) -> int | None:
    from app.db.models.hypotheses import SystemEvent
    try:
        row = SystemEvent(event_type=event_type, message=message, payload=payload)
        db.add(row)
        db.commit()
        return row.id
    except Exception:
        db.rollback()
        return None


def set_hypothesis_status(db: Session, hypothesis_id: int, status: str) -> dict | None:
    from app.db.models.hypotheses import Hypothesis
    if status not in ("live", "testing", "retired"):
        return None
    h = db.get(Hypothesis, hypothesis_id)
    if not h:
        return None
    old = h.status
    h.status = status
    db.commit()
    event_type = "hypothesis_retired" if status == "retired" else ("hypothesis_promoted" if status == "live" else "hypothesis_demoted")
    record_system_event(db, event_type, f"{h.name}: {old} → {status}")
    return {"id": h.id, "status": h.status}
