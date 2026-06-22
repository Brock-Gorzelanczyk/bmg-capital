"""Tuning Advisor — surfaces actionable per-strategy adjustments based on
discipline-filter outcomes and live hypothesis stats.

Two consumers:
  - /api/admin/tuning/recommendations — Monday triage view
  - /api/admin/tuning/promotion-candidates — strategies ready for TESTING → LIVE

All queries soft-fail; a missing table never 500s the endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Thresholds that drive recommendations. Tuned to the spec's monitoring rules:
#   "If signal volume from new strategies exceeds 500/day per strategy, throttle"
#   "If either strategy hits >95% filtered, the regime/confluence config is wrong"
_VOLUME_RED_LINE = 500
_REJECT_RATE_RED = 0.95
_REJECT_RATE_WARN = 0.80
_PROMO_MIN_TRADES = 10
_PROMO_MIN_WIN_RATE = 55.0    # percent
_PROMO_MIN_EXP_R = 0.10       # expectancy in R units (proxy)


def _window_bounds(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days), now)


def get_tuning_recommendations(db: Session, days: int = 1) -> dict[str, Any]:
    """Per-strategy signal-volume / rejection-rate snapshot with suggested actions."""
    from app.db.models.signal_gates import SignalGate
    from app.db.models.hypotheses import Hypothesis

    start, _ = _window_bounds(days)

    # Pull all gate rows in window
    try:
        rows = db.query(SignalGate).filter(SignalGate.created_at >= start).all()
    except Exception as exc:
        logger.warning("[tuning] signal_gates query failed: %s", exc)
        rows = []

    # Pull current hypothesis statuses for context
    hyp_status: dict[str, str] = {}
    try:
        for h in db.query(Hypothesis).all():
            hyp_status[h.strategy_id] = h.status
    except Exception as exc:
        logger.warning("[tuning] hypotheses query failed: %s", exc)

    # Aggregate per-strategy
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        strat = r.strategy or "(unknown)"
        s = agg.setdefault(strat, {
            "strategy": strat,
            "analyzed": 0,
            "executed": 0,
            "filtered": 0,
            "by_reason": {},
            "avg_score": 0.0,
            "_score_sum": 0,
        })
        s["analyzed"] += 1
        s["_score_sum"] += r.composite_score or 0
        if r.final_decision == "executed":
            s["executed"] += 1
        else:
            s["filtered"] += 1
            reason = r.filter_reason or "unknown"
            s["by_reason"][reason] = s["by_reason"].get(reason, 0) + 1

    # Compute derived metrics and suggested action per strategy
    out_rows: list[dict[str, Any]] = []
    for strat, s in agg.items():
        n = s["analyzed"]
        s["reject_rate"] = round(s["filtered"] / n, 3) if n else 0.0
        s["avg_score"] = round(s["_score_sum"] / n, 1) if n else 0.0
        s.pop("_score_sum", None)
        top_reason, top_count = ("none", 0)
        if s["by_reason"]:
            top_reason, top_count = max(s["by_reason"].items(), key=lambda kv: kv[1])
        s["top_filter_reason"] = top_reason
        s["top_filter_count"] = top_count
        s["status"] = hyp_status.get(strat, "unknown")
        s["action"] = _suggest_action(s)
        out_rows.append(s)

    # Ranked summaries
    by_volume = sorted(out_rows, key=lambda x: x["analyzed"], reverse=True)
    by_reject_rate = sorted(out_rows, key=lambda x: x["reject_rate"], reverse=True)

    # Red flags: high signal volume but zero executed → gate is too tight
    red_flags = [
        s for s in out_rows
        if s["analyzed"] >= 50 and s["executed"] == 0
    ]
    # Volume bombs: >500/day → throttle threshold
    volume_bombs = [s for s in out_rows if s["analyzed"] >= _VOLUME_RED_LINE]
    # Strategies firing too easily (zero rejection on 20+ signals)
    too_loose = [
        s for s in out_rows
        if s["analyzed"] >= 20 and s["reject_rate"] < 0.10 and s["executed"] >= 20
    ]

    return {
        "window_days": days,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "total_strategies_with_activity": len(out_rows),
        "total_analyzed": sum(s["analyzed"] for s in out_rows),
        "total_executed": sum(s["executed"] for s in out_rows),
        "by_volume": by_volume[:10],
        "by_reject_rate": [s for s in by_reject_rate if s["analyzed"] >= 10][:10],
        "red_flags": red_flags,
        "volume_bombs": volume_bombs,
        "too_loose": too_loose,
        "thresholds": {
            "volume_red_line": _VOLUME_RED_LINE,
            "reject_rate_warn": _REJECT_RATE_WARN,
            "reject_rate_red": _REJECT_RATE_RED,
        },
    }


def _suggest_action(s: dict[str, Any]) -> dict[str, str]:
    """Return {severity, label, detail} for one strategy aggregation."""
    n = s["analyzed"]
    rr = s["reject_rate"]
    executed = s["executed"]

    if n == 0:
        return {"severity": "info", "label": "no activity",
                "detail": "no signals analyzed in this window"}

    # Volume bombs — discord/cost concern
    if n >= _VOLUME_RED_LINE:
        return {
            "severity": "red",
            "label": "throttle volume",
            "detail": f"{n} signals/window exceeds {_VOLUME_RED_LINE}/day red line — "
                      f"raise composite_threshold for this strategy via "
                      f"strategy_thresholds override in the bot's YAML",
        }

    # Red flags — analyzed but zero executed
    if n >= 50 and executed == 0:
        return {
            "severity": "red",
            "label": "filter too tight",
            "detail": f"{n} signals analyzed, 0 executed — top reason: {s['top_filter_reason']}. "
                      f"Consider relaxing regime_preference, lowering composite_threshold, "
                      f"or dropping confluence_required from 3 to 2",
        }

    # >95% rejection rate
    if rr >= _REJECT_RATE_RED and n >= 20:
        return {
            "severity": "red",
            "label": "near-total rejection",
            "detail": f"{int(rr * 100)}% rejected ({s['filtered']}/{n}) — "
                      f"top reason: {s['top_filter_reason']}. "
                      f"Strategy may be miscoded for current regime",
        }

    # 80-95% rejection rate
    if rr >= _REJECT_RATE_WARN and n >= 20:
        return {
            "severity": "warn",
            "label": "high rejection",
            "detail": f"{int(rr * 100)}% rejected — top reason: {s['top_filter_reason']}. "
                      f"Watch tomorrow; if it persists, tune the relevant gate",
        }

    # Healthy execution
    if rr <= 0.50 and executed >= 10:
        return {
            "severity": "ok",
            "label": "healthy",
            "detail": f"{int((1 - rr) * 100)}% pass rate, {executed} executed — "
                      f"check the hypothesis card for win rate",
        }

    return {"severity": "info", "label": "monitoring",
            "detail": f"{n} analyzed, {executed} executed, {int(rr * 100)}% rejected"}


def get_promotion_candidates(db: Session) -> dict[str, Any]:
    """Find TESTING hypotheses ready for LIVE promotion.

    Criteria (per Option A plan):
      N ≥ 10 trades
      AND win_rate ≥ 55%
      AND expected_r > 0.10
    """
    from app.services.hypotheses import list_live_hypotheses

    try:
        all_hyps = list_live_hypotheses(db)
    except Exception as exc:
        logger.warning("[tuning] list_live_hypotheses failed: %s", exc)
        return {"candidates": [], "rejected": [], "as_of": datetime.now(timezone.utc).isoformat()}

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for h in all_hyps:
        if h.get("status") != "testing":
            continue
        n = h.get("n_trades", 0)
        wr = h.get("win_rate", 0.0)
        er = h.get("expected_r", 0.0)
        rec = {
            "id": h["id"],
            "name": h["name"],
            "strategy_id": h["strategy_id"],
            "n_trades": n,
            "win_rate": wr,
            "expected_r": er,
            "last_trade": h.get("last_trade"),
        }
        if n >= _PROMO_MIN_TRADES and wr >= _PROMO_MIN_WIN_RATE and er >= _PROMO_MIN_EXP_R:
            rec["why"] = f"{n} trades, WR {wr:.1f}%, EXP +{er:.2f}R — all gates passed"
            candidates.append(rec)
        else:
            misses = []
            if n < _PROMO_MIN_TRADES:
                misses.append(f"need ≥ {_PROMO_MIN_TRADES} trades (has {n})")
            if wr < _PROMO_MIN_WIN_RATE:
                misses.append(f"need WR ≥ {_PROMO_MIN_WIN_RATE}% (has {wr:.1f}%)")
            if er < _PROMO_MIN_EXP_R:
                misses.append(f"need EXP ≥ +{_PROMO_MIN_EXP_R:.2f}R (has {er:.3f})")
            rec["why_not"] = "; ".join(misses)
            rejected.append(rec)

    return {
        "candidates": candidates,
        "rejected": rejected,
        "rules": {
            "min_trades": _PROMO_MIN_TRADES,
            "min_win_rate": _PROMO_MIN_WIN_RATE,
            "min_expected_r": _PROMO_MIN_EXP_R,
        },
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
