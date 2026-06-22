"""Discipline filter report endpoints — what got filtered today and why."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin

router = APIRouter(prefix="/api/admin/discipline", tags=["discipline"])
logger = logging.getLogger(__name__)


_GATE_LABELS = {
    "regime_mismatch": {
        "title": "REGIME MISMATCH",
        "description": "Market structure inconsistent with strategy edge",
        "icon": "warn",
    },
    "score_below_threshold": {
        "title": "SCORE BELOW THRESHOLD",
        "description": "Composite conviction failed minimum criteria",
        "icon": "warn",
    },
    "insufficient_confluence": {
        "title": "INSUFFICIENT CONFLUENCE",
        "description": "Multi-factor alignment did not meet entry standard",
        "icon": "block",
    },
    "multiple": {
        "title": "MULTIPLE GATES FAILED",
        "description": "Signal failed more than one discipline check",
        "icon": "block",
    },
}


def _utc_day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


@router.get("/filter-report", dependencies=[Depends(require_admin)])
def get_filter_report(
    date_str: Optional[str] = Query(None, alias="date"),
    days: int = Query(1, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Daily (or rolling-window) discipline report.

    Counts signals analyzed, executed, filtered. Breaks down filter reasons
    and gives per-strategy summary.
    """
    from app.db.models.signal_gates import SignalGate

    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    else:
        day = datetime.now(timezone.utc).date()

    start_dt, end_dt = _utc_day_bounds(day)
    if days > 1:
        start_dt = start_dt - timedelta(days=days - 1)

    q = db.query(SignalGate).filter(
        SignalGate.created_at >= start_dt,
        SignalGate.created_at < end_dt,
    )

    rows = q.all()
    analyzed = len(rows)
    executed = sum(1 for r in rows if r.final_decision == "executed")
    filtered = analyzed - executed

    # Breakdown by filter_reason
    breakdown: dict[str, dict] = {}
    for key in ("regime_mismatch", "score_below_threshold", "insufficient_confluence", "multiple"):
        count = sum(1 for r in rows if r.filter_reason == key)
        pct = round(count / analyzed * 100, 1) if analyzed else 0.0
        meta = _GATE_LABELS.get(key, {})
        breakdown[key] = {
            "count": count,
            "percent": pct,
            "title": meta.get("title", key.upper()),
            "description": meta.get("description", ""),
            "icon": meta.get("icon", "warn"),
        }

    gates_triggered = sum(1 for v in breakdown.values() if v["count"] > 0)

    # Per-strategy summary
    by_strategy: dict[str, dict] = {}
    for r in rows:
        key = r.strategy or "(unknown)"
        s = by_strategy.setdefault(key, {
            "strategy": key,
            "analyzed": 0,
            "executed": 0,
            "filtered": 0,
            "top_filter": None,
            "_reason_counts": {},
        })
        s["analyzed"] += 1
        if r.final_decision == "executed":
            s["executed"] += 1
        else:
            s["filtered"] += 1
            if r.filter_reason:
                s["_reason_counts"][r.filter_reason] = s["_reason_counts"].get(r.filter_reason, 0) + 1

    for s in by_strategy.values():
        if s["_reason_counts"]:
            s["top_filter"] = max(s["_reason_counts"], key=s["_reason_counts"].get)
        s.pop("_reason_counts", None)

    by_bot: dict[str, dict] = {}
    for r in rows:
        key = r.bot_name or "(unknown)"
        b = by_bot.setdefault(key, {"bot": key, "analyzed": 0, "executed": 0, "filtered": 0})
        b["analyzed"] += 1
        if r.final_decision == "executed":
            b["executed"] += 1
        else:
            b["filtered"] += 1

    return {
        "date": day.isoformat(),
        "window_days": days,
        "signals_analyzed": analyzed,
        "trades_executed": executed,
        "signals_filtered": filtered,
        "gates_triggered": gates_triggered,
        "breakdown": breakdown,
        "by_strategy": sorted(by_strategy.values(), key=lambda s: s["analyzed"], reverse=True),
        "by_bot": sorted(by_bot.values(), key=lambda b: b["analyzed"], reverse=True),
        "edge_quote": "When the setup isn't clean, we wait. That's the EDGE.",
    }


@router.get("/signal-trace/{signal_id}", dependencies=[Depends(require_admin)])
def get_signal_trace(signal_id: int, db: Session = Depends(get_db)):
    """Full filter trace for one signal — which gates passed, scores, what blocked execution."""
    from app.db.models.signal_gates import SignalGate
    from app.db.models.bots import BotSignal

    sig = db.get(BotSignal, signal_id)
    gate = db.query(SignalGate).filter(SignalGate.signal_id == signal_id).order_by(SignalGate.id.desc()).first()
    if not sig and not gate:
        raise HTTPException(404, f"no signal or gate trace found for signal_id={signal_id}")

    out = {
        "signal_id": signal_id,
        "signal": None,
        "gate": None,
    }
    if sig:
        out["signal"] = {
            "symbol": sig.symbol,
            "side": sig.side,
            "confidence": sig.confidence,
            "strategy": sig.strategy,
            "ts": sig.ts.isoformat() if sig.ts else None,
            "entry_price": sig.entry_price,
            "stop_price": sig.stop_price,
            "target_price": sig.target_price,
            "executed_at": sig.executed_at.isoformat() if sig.executed_at else None,
        }
    if gate:
        out["gate"] = {
            "id": gate.id,
            "bot_name": gate.bot_name,
            "regime_gate_passed": gate.regime_gate_passed,
            "regime_current": gate.regime_current,
            "regime_required": gate.regime_required,
            "composite_score": gate.composite_score,
            "composite_threshold": gate.composite_threshold,
            "score_gate_passed": gate.score_gate_passed,
            "confluence_factors_passed": gate.confluence_factors_passed,
            "confluence_required": gate.confluence_required,
            "confluence_gate_passed": gate.confluence_gate_passed,
            "final_decision": gate.final_decision,
            "filter_reason": gate.filter_reason,
            "created_at": gate.created_at.isoformat() if gate.created_at else None,
        }
    return out


@router.get("/recent-filtered", dependencies=[Depends(require_admin)])
def list_recent_filtered(
    limit: int = Query(50, ge=1, le=200),
    bot: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None, description="Filter by strategy name (e.g. ofi_institutional_flow)"),
    db: Session = Depends(get_db),
):
    """Last N filtered signals — for "click to inspect" on the dashboard.

    Optional ?bot= and ?strategy= filters; both can be combined.
    """
    from app.db.models.signal_gates import SignalGate

    q = db.query(SignalGate).filter(SignalGate.final_decision == "filtered")
    if bot:
        q = q.filter(SignalGate.bot_name == bot)
    if strategy:
        q = q.filter(SignalGate.strategy == strategy)
    rows = q.order_by(SignalGate.id.desc()).limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "signal_id": r.signal_id,
                "bot_name": r.bot_name,
                "strategy": r.strategy,
                "symbol": r.symbol,
                "side": r.side,
                "composite_score": r.composite_score,
                "composite_threshold": r.composite_threshold,
                "confluence_factors_passed": r.confluence_factors_passed,
                "confluence_required": r.confluence_required,
                "filter_reason": r.filter_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
