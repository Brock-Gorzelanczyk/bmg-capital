"""
Dashboard v2 — single aggregated read for the Dashboard page.
Pulls directly from BotAllocation / BotPosition / BotSignal / BotWatchlist tables.
No dependency on StrategyPortfolio rows.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.bots import (
    BotAllocation,
    BotProfile,
    BotPosition,
    BotSignal,
    BotWatchlist,
    BotDailyPnL,
    RegimeSnapshot,
)
from app.db.models.users import User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_REGIME_LABELS: dict[tuple[str, str], tuple[str, str]] = {
    ("low",   "bull"):  ("VIX LOW / BULL",   "Low volatility bull run — bots in full risk-on mode"),
    ("low",   "chop"):  ("VIX LOW / CHOP",   "Low vol but choppy — bots filtering signals tighter"),
    ("low",   "bear"):  ("VIX LOW / BEAR",   "Low vol downtrend — bots in capital-preservation mode"),
    ("mid",   "bull"):  ("VIX MID / BULL",   "Moderate vol with uptrend — balanced opportunity"),
    ("mid",   "chop"):  ("VIX MID / CHOP",   "Choppy market — tighter filters, fewer entries"),
    ("mid",   "bear"):  ("VIX MID / BEAR",   "Mid-vol downtrend — bots defensive"),
    ("high",  "bull"):  ("VIX HIGH / BULL",  "High vol rally — bots sizing down, wider stops"),
    ("high",  "chop"):  ("VIX HIGH / CHOP",  "Elevated vol, no clear trend — wait and see"),
    ("high",  "bear"):  ("VIX HIGH / BEAR",  "High vol selloff — most entries suspended"),
    ("panic", "bull"):  ("PANIC / BULL",      "Panic spike with reversal — rare buy signal"),
    ("panic", "chop"):  ("PANIC / CHOP",      "Full panic mode — bots idle"),
    ("panic", "bear"):  ("PANIC / BEAR",      "Market panic — bots idle, capital protected"),
}

_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing": "Stock Swing",
    "stock_day": "Stock Day",
    "stock_lt": "Stock Long-Term",
    "crypto_swing": "Crypto Swing",
    "crypto_day": "Crypto Day",
    "crypto_lt": "Crypto Long-Term",
    "crypto_onchain": "Crypto On-Chain",
    "crypto_quant_aggressive": "Quant Aggressive",
    "options_flow": "Options Flow",
    "stock_momentum": "Stock Momentum",
    "stock_breakout": "Stock Breakout",
    "stock_mean_reversion": "Stock Mean Rev",
}

_AC_TO_SLEEVE: dict[str, str] = {
    "stock": "stocks",
    "crypto": "crypto",
    "quant": "crypto",
    "options": "options",
}


@router.get("/v2")
def get_dashboard_v2(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Single aggregated read for the Dashboard page. No StrategyPortfolio dependency."""
    now = datetime.now(timezone.utc)
    today = now.date()
    cutoff_30d = (now - timedelta(days=30)).date()

    # ── Load allocations + profiles ──────────────────────────────────────────
    # Filter by BotAllocation.enabled (per-user flag) NOT BotProfile.enabled
    # (global YAML flag). Profile-level enabled is unreliable — many profiles
    # have enabled=False in DB while the allocation itself is active.
    allocs = (
        db.query(BotAllocation)
        .join(BotProfile, BotProfile.id == BotAllocation.profile_id)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.enabled.is_(True),
        )
        .all()
    )
    alloc_ids = [a.id for a in allocs]
    profile_ids = list({a.profile_id for a in allocs})

    profiles = (
        db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
        if profile_ids else []
    )
    profile_map: dict[int, BotProfile] = {p.id: p for p in profiles}
    alloc_to_profile: dict[int, BotProfile] = {
        a.id: profile_map[a.profile_id]
        for a in allocs
        if a.profile_id in profile_map
    }

    # ── P&L rows ─────────────────────────────────────────────────────────────
    pnl_rows = (
        db.query(BotDailyPnL).filter(BotDailyPnL.allocation_id.in_(alloc_ids)).all()
        if alloc_ids else []
    )

    total_realized_by_alloc: dict[int, int] = {}
    today_pnl_by_alloc: dict[int, int] = {}
    pnl_30d_by_alloc: dict[int, int] = {}
    for row in pnl_rows:
        aid = row.allocation_id
        total_realized_by_alloc[aid] = total_realized_by_alloc.get(aid, 0) + row.realized_cents
        if row.date == today:
            today_pnl_by_alloc[aid] = (
                today_pnl_by_alloc.get(aid, 0) + row.realized_cents + row.unrealized_cents
            )
        if row.date >= cutoff_30d:
            pnl_30d_by_alloc[aid] = pnl_30d_by_alloc.get(aid, 0) + row.realized_cents

    # ── Open positions ───────────────────────────────────────────────────────
    open_pos = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.is_(None),
        )
        .all()
        if alloc_ids else []
    )

    # ── Recent signals ───────────────────────────────────────────────────────
    sigs = (
        db.query(BotSignal)
        .filter(BotSignal.allocation_id.in_(alloc_ids))
        .order_by(BotSignal.ts.desc())
        .limit(20)
        .all()
        if alloc_ids else []
    )

    # ── Watchlist ────────────────────────────────────────────────────────────
    wl_rows = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id.in_(profile_ids),
            BotWatchlist.status.in_(["active", "watching", "pending_entry"]),
        )
        .all()
        if profile_ids else []
    )

    profile_wl_count: dict[int, int] = {}
    for wl in wl_rows:
        profile_wl_count[wl.profile_id] = profile_wl_count.get(wl.profile_id, 0) + 1

    # ── Portfolio totals ──────────────────────────────────────────────────────
    # allocs is already filtered to enabled allocations only (see query above).
    total_starting = sum(a.starting_capital_cents or 0 for a in allocs)
    total_realized = sum(total_realized_by_alloc.values())
    total_today_pnl = sum(today_pnl_by_alloc.values())
    # Include today's unrealized so open positions are reflected in portfolio value.
    total_unrealized_today = sum(
        row.unrealized_cents
        for row in pnl_rows
        if row.date == today and row.allocation_id in set(alloc_ids)
    )
    total_value = total_starting + total_realized + total_unrealized_today
    prev_value = total_value - total_today_pnl
    today_pct = round(total_today_pnl / prev_value * 100, 2) if prev_value > 0 else 0.0
    total_30d_pnl = sum(pnl_30d_by_alloc.values())
    return_30d_pct = round(total_30d_pnl / total_starting * 100, 2) if total_starting else 0.0

    # ── Per-sleeve breakdown ─────────────────────────────────────────────────
    sleeve_data: dict[str, dict[str, int]] = {
        s: {"value_cents": 0, "open_positions": 0, "watching": 0, "pnl_cents": 0, "bots_active": 0, "bots_total": 0}
        for s in ("stocks", "crypto", "options")
    }
    seen_profile_sleeve: set[tuple[int, str]] = set()

    for alloc in allocs:
        p = alloc_to_profile.get(alloc.id)
        if not p:
            continue
        s = _AC_TO_SLEEVE.get(p.asset_class, "stocks")
        start = alloc.starting_capital_cents or 0
        realized = total_realized_by_alloc.get(alloc.id, 0)
        sleeve_data[s]["value_cents"] += start + realized
        sleeve_data[s]["pnl_cents"] += realized
        sleeve_data[s]["bots_total"] += 1
        if alloc.enabled:
            sleeve_data[s]["bots_active"] += 1
        key = (alloc.profile_id, s)
        if key not in seen_profile_sleeve:
            sleeve_data[s]["watching"] += profile_wl_count.get(alloc.profile_id, 0)
            seen_profile_sleeve.add(key)

    for pos in open_pos:
        p = alloc_to_profile.get(pos.allocation_id)
        if not p:
            continue
        s = _AC_TO_SLEEVE.get(p.asset_class, "stocks")
        sleeve_data[s]["open_positions"] += 1

    # ── Sleeve reservations ───────────────────────────────────────────────────
    try:
        reservations = {
            row[0]: int(row[1])
            for row in db.execute(
                text("SELECT sleeve_name, reserved_capital_cents FROM sleeve_config")
            ).fetchall()
        }
    except Exception:
        reservations = {}
    for s in sleeve_data:
        sleeve_data[s]["reserved_capital_cents"] = reservations.get(s, 0)

    # ── Health ───────────────────────────────────────────────────────────────
    bots_active = sum(1 for a in allocs if a.enabled)
    bots_total = len(allocs)

    last_signal_ts = sigs[0].ts if sigs else None
    last_signal_minutes_ago: int | None = None
    if last_signal_ts:
        ts = last_signal_ts if last_signal_ts.tzinfo else last_signal_ts.replace(tzinfo=timezone.utc)
        last_signal_minutes_ago = max(0, int((now - ts).total_seconds() / 60))

    health_status = "ok" if bots_active > 0 else "warn"

    # ── Regime ───────────────────────────────────────────────────────────────
    snap = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).first()
    vix_r = snap.vix_regime if snap else "mid"
    trend_r = snap.trend_regime if snap else "chop"
    label, description = _REGIME_LABELS.get(
        (vix_r, trend_r),
        (f"VIX {vix_r.upper()}", "Bots optimizing for current conditions"),
    )

    # ── Recent signals ────────────────────────────────────────────────────────
    recent_signals = []
    for s in sigs:
        profile = alloc_to_profile.get(s.allocation_id)
        bot_name = profile.name if profile else ""
        recent_signals.append({
            "id": s.id,
            "ts": s.ts.isoformat() if s.ts else None,
            "bot_name": bot_name,
            "display_name": _DISPLAY_NAMES.get(bot_name, ""),
            "symbol": s.symbol,
            "side": s.side,
            "confidence": round(float(s.confidence), 4) if s.confidence else 0.0,
            "reason": s.reason or "",
            "strategy": s.strategy or "",
        })

    # ── Open positions list ──────────────────────────────────────────────────
    sorted_pos = sorted(open_pos, key=lambda p: abs(p.qty * (p.avg_cost_cents or 0)), reverse=True)
    open_positions_list = []
    for pos in sorted_pos[:10]:
        profile = alloc_to_profile.get(pos.allocation_id)
        open_positions_list.append({
            "id": pos.id,
            "symbol": pos.symbol,
            "side": pos.side or "long",
            "qty": pos.qty,
            "avg_cost_cents": int(pos.avg_cost_cents),
            "current_price_cents": None,
            "bot_name": profile.name if profile else "",
        })

    # ── Analyst highlights — top-scored watchlist symbols ────────────────────
    seen_syms: set[str] = set()
    highlights = []
    for row in sorted(wl_rows, key=lambda r: -(r.score or 0)):
        if row.symbol in seen_syms or len(highlights) >= 4:
            continue
        seen_syms.add(row.symbol)
        score = row.score or 0
        conviction = "HIGH" if score >= 80 else "MED" if score >= 60 else "LOW"
        thesis = (
            f"Score {score:.0f} — momentum + volume signal"
            if "/" in row.symbol
            else f"Score {score:.0f} — technical breakout candidate"
        )
        highlights.append({"symbol": row.symbol, "conviction": conviction, "thesis": thesis})

    # ── Leaderboard ──────────────────────────────────────────────────────────
    leaderboard = []
    for alloc in allocs:
        p = alloc_to_profile.get(alloc.id)
        if not p:
            continue
        start = alloc.starting_capital_cents or 1
        pnl30 = pnl_30d_by_alloc.get(alloc.id, 0)
        leaderboard.append({
            "rank": 0,
            "profile": p.name,
            "name": _DISPLAY_NAMES.get(p.name, p.name.replace("_", " ").title()),
            "return_30d_pct": round(pnl30 / start * 100, 2) if start else 0.0,
            "today_pnl_cents": today_pnl_by_alloc.get(alloc.id, 0),
            "watchlist_count": profile_wl_count.get(alloc.profile_id, 0),
            "portfolio_value_cents": start + total_realized_by_alloc.get(alloc.id, 0) + sum(
            r.unrealized_cents for r in pnl_rows
            if r.allocation_id == alloc.id and r.date == today
        ),
        })
    leaderboard.sort(key=lambda x: x["return_30d_pct"], reverse=True)
    for i, e in enumerate(leaderboard, 1):
        e["rank"] = i

    return {
        "portfolio": {
            "total_value_cents": total_value,
            "today_pnl_cents": total_today_pnl,
            "today_pnl_pct": today_pct,
            "return_30d_pct": return_30d_pct,
            "leaderboard": leaderboard,
        },
        "regime": {
            "vix_regime": vix_r,
            "trend_regime": trend_r,
            "btc_dominance": float(snap.btc_dominance) if snap and snap.btc_dominance is not None else 50.0,
            "btc_funding_rate": float(snap.btc_funding_rate) if snap and snap.btc_funding_rate is not None else 0.0,
            "ts": snap.ts.isoformat() if snap and snap.ts else None,
            "label": label,
            "description": description,
        },
        "sleeves": sleeve_data,
        "health": {
            "bots_active": bots_active,
            "bots_total": bots_total,
            "last_signal_minutes_ago": last_signal_minutes_ago,
            "status": health_status,
        },
        "recent_signals": recent_signals,
        "analyst_highlights": highlights,
        "open_positions": open_positions_list,
    }
