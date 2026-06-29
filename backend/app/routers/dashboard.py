"""
Dashboard v2 — single aggregated read for the Dashboard page.
Pulls directly from BotAllocation / BotPosition / BotSignal / BotWatchlist tables.
No dependency on StrategyPortfolio rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
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
    "crypto_quant_scalper": "Quant Scalper",
    "crypto_quant_mean_reversion": "Quant Mean Rev",
    "options_directional": "Options Directional",
    "options_income": "Options Income",
    "options_flow": "Options Flow",
    "stock_momentum": "Stock Momentum",
    "stock_breakout": "Stock Breakout",
    "stock_mean_reversion": "Stock Mean Rev",
}

_AC_TO_SLEEVE: dict[str, str] = {
    "stock": "stocks",
    "crypto": "crypto",
    "quant": "quant",
    "options": "options",
}

# Quant bots have asset_class=crypto in m027 SPEC. Route them to the
# dedicated "quant" sleeve so the Dashboard shows all 4 sleeve cards.
# PART 6 fix: previously asset_class=crypto routed them to "crypto" bucket
# and the Dashboard rendered only 3 sleeves with "sleeve missing from payload".
_QUANT_PROFILE_NAMES = frozenset({
    "crypto_quant_aggressive",
    "crypto_quant_scalper",
    "crypto_quant_mean_reversion",
})


def _profile_sleeve(profile_name: str, asset_class: str | None) -> str:
    if profile_name in _QUANT_PROFILE_NAMES:
        return "quant"
    return _AC_TO_SLEEVE.get(asset_class or "", "stocks")


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
    # Load ALL allocations for the user (no enabled filter) — same as portfolio.
    # bots_active count below uses alloc.enabled to distinguish active vs total.
    allocs = (
        db.query(BotAllocation)
        .join(BotProfile, BotProfile.id == BotAllocation.profile_id)
        .filter(BotAllocation.user_id == current_user.id)
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

    # ── Delegate financial numbers to canonical aggregator ───────────────────
    # Strategy Lab uses compute_strategy_lab_aggregate and shows correct
    # numbers for this user — so we delegate to the same function here.
    # That way Dashboard, Mission Control, and Strategy Lab all share one
    # source of truth and there's no chance of split-brain.
    from app.core.canonical import compute_strategy_lab_aggregate, compute_bot_snapshot
    try:
        agg = compute_strategy_lab_aggregate(current_user.id, db) or {}
    except Exception as exc:
        logger.warning("[dashboard] canonical aggregate failed: %s", exc)
        agg = {}

    leaderboard_from_agg = agg.get("leaderboard", []) or []
    # Build per-allocation P&L lookups by joining leaderboard entries
    # (keyed by profile.name) back to allocations.
    today_pnl_by_profile_name: dict[str, int] = {
        e.get("profile"): int(e.get("today_pnl_cents") or 0)
        for e in leaderboard_from_agg
    }
    pv_by_profile_name: dict[str, int] = {
        e.get("profile"): int(e.get("portfolio_value_cents") or 0)
        for e in leaderboard_from_agg
    }
    ret30_by_profile_name: dict[str, float] = {
        e.get("profile"): float(e.get("return_30d_pct") or 0.0)
        for e in leaderboard_from_agg
    }
    realized_by_profile_name: dict[str, int] = {
        e.get("profile"): int(e.get("realized_pnl_cents") or 0)
        for e in leaderboard_from_agg
    }

    # ── Per-allocation snapshots (canonical, NOT dependent on StrategyPortfolio) ──
    # These include orphan allocations (no portfolio_id) that compute_strategy_lab_aggregate
    # skips because it iterates StrategyPortfolio rows. We use these as the
    # authoritative per-bot values; canonical's leaderboard is preferred when
    # present (to stay aligned with Strategy Lab) but we fall back to direct
    # snapshots so orphans aren't silently dropped.
    bot_snapshots_by_alloc: dict[int, Any] = {}
    for alloc in allocs:
        p = alloc_to_profile.get(alloc.id)
        if not p:
            continue
        try:
            bot_snapshots_by_alloc[alloc.id] = compute_bot_snapshot(alloc, p, db)
        except Exception as exc:
            logger.warning("[dashboard] compute_bot_snapshot failed for alloc %s: %s", alloc.id, exc)

    today_pnl_by_alloc: dict[int, int] = {}
    pv_by_alloc: dict[int, int] = {}
    ret30_by_alloc: dict[int, float] = {}
    total_realized_by_alloc: dict[int, int] = {}
    for alloc in allocs:
        p = alloc_to_profile.get(alloc.id)
        if not p:
            continue
        bot_snap = bot_snapshots_by_alloc.get(alloc.id)
        # Prefer canonical leaderboard value (matches Strategy Lab exactly);
        # fall back to direct per-bot snapshot for orphans / missing entries.
        today_pnl_by_alloc[alloc.id]  = today_pnl_by_profile_name.get(p.name, bot_snap.today_pnl_cents if bot_snap else 0)
        pv_by_alloc[alloc.id]         = pv_by_profile_name.get(p.name, bot_snap.portfolio_value_cents if bot_snap else 0)
        ret30_by_alloc[alloc.id]      = ret30_by_profile_name.get(p.name, bot_snap.return_30d_pct if bot_snap else 0.0)
        total_realized_by_alloc[alloc.id] = realized_by_profile_name.get(p.name, bot_snap.realized_pnl_cents if bot_snap else 0)

    pnl_30d_by_alloc: dict[int, int] = {
        aid: int(round(ret30_by_alloc.get(aid, 0.0) / 100.0 * (a.starting_capital_cents or 0)))
        for aid, a in {aa.id: aa for aa in allocs}.items()
    }

    # ── Open positions (audit bug 5: add quarantine filter) ──────────────────
    # Canonical excludes quarantined positions from counts. Dashboard was
    # missing this filter so its position count drifted from Strategy Lab.
    open_pos = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
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

    # ── Portfolio totals — sum from per-allocation snapshots ────────────────
    # We sum pv_by_alloc / today_pnl_by_alloc directly instead of trusting
    # agg["total_value_cents"], because canonical's aggregate iterates
    # StrategyPortfolio rows and silently drops orphan allocations (any
    # BotAllocation without a portfolio_id). Those orphans still represent real
    # bot capital — excluding them was the root cause of Dashboard showing $—
    # / a too-low number versus Strategy Lab.
    total_starting = sum(a.starting_capital_cents or 0 for a in allocs)
    total_realized = sum(total_realized_by_alloc.values())
    total_value      = sum(pv_by_alloc.values())
    total_today_pnl  = sum(today_pnl_by_alloc.values())

    # today_pnl_pct: derived from totals, not blindly copied from agg
    yesterday_value = total_value - total_today_pnl
    today_pct = round(total_today_pnl / yesterday_value * 100, 2) if yesterday_value > 0 else 0.0

    # 30d return: weighted average by starting capital across all allocs
    if total_starting > 0:
        return_30d_pct = round(
            sum(
                ret30_by_alloc.get(a.id, 0.0) * (a.starting_capital_cents or 0)
                for a in allocs
            ) / total_starting,
            2,
        )
    else:
        return_30d_pct = float(agg.get("return_30d_pct") or 0.0)

    # Final fallback when there are literally zero allocations / snapshots:
    # use starting capital so the page renders something instead of $—.
    if total_value == 0 and total_starting > 0:
        total_value = total_starting

    # ── Per-sleeve breakdown ─────────────────────────────────────────────────
    sleeve_data: dict[str, dict[str, int]] = {
        s: {"value_cents": 0, "open_positions": 0, "watching": 0, "pnl_cents": 0, "bots_active": 0, "bots_total": 0}
        for s in ("stocks", "crypto", "options", "quant")
    }
    seen_profile_sleeve: set[tuple[int, str]] = set()

    for alloc in allocs:
        p = alloc_to_profile.get(alloc.id)
        if not p:
            continue
        s = _profile_sleeve(p.name, p.asset_class)
        # Per-allocation values bucketed by sleeve. Falls back to starting
        # capital if canonical didn't have data for this profile.
        pv = pv_by_alloc.get(alloc.id) or (alloc.starting_capital_cents or 0)
        sleeve_data[s]["value_cents"] += pv
        sleeve_data[s]["pnl_cents"]   += today_pnl_by_alloc.get(alloc.id, 0)
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
        s = _profile_sleeve(p.name, p.asset_class)
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

    # ── Leaderboard — start from canonical's, then add orphan allocations ────
    # Canonical's leaderboard iterates StrategyPortfolio rows so it omits any
    # BotAllocation without a portfolio_id. We append those orphans from the
    # direct per-bot snapshots so the Top Bot widget sees every active bot.
    profile_by_name: dict[str, BotProfile] = {p.name: p for p in profiles}
    # Build a profile_name → starting_capital_cents map (sum across all
    # allocations of that profile) so leaderboard entries can carry
    # deployed_cents + starting_capital_cents without forcing the Dashboard
    # to fetch /strategy-lab/portfolio just for those two fields.
    starting_by_profile: dict[str, int] = {}
    deployed_by_profile: dict[str, int] = {}
    for alloc in allocs:
        prof = alloc_to_profile.get(alloc.id)
        if not prof:
            continue
        starting_by_profile[prof.name] = starting_by_profile.get(prof.name, 0) + int(alloc.starting_capital_cents or 0)
        bot_snap = bot_snapshots_by_alloc.get(alloc.id)
        if bot_snap is not None:
            deployed_by_profile[prof.name] = deployed_by_profile.get(prof.name, 0) + int(getattr(bot_snap, "deployed_cents", 0) or 0)

    leaderboard = []
    profiles_in_lb: set[str] = set()
    for e in leaderboard_from_agg:
        prof_name = e.get("profile") or ""
        prof = profile_by_name.get(prof_name)
        profiles_in_lb.add(prof_name)
        leaderboard.append({
            "rank": e.get("rank") or 0,
            "profile": prof_name,
            "name": _DISPLAY_NAMES.get(prof_name, prof_name.replace("_", " ").title()),
            "return_30d_pct": e.get("return_30d_pct") or 0.0,
            "today_pnl_cents": e.get("today_pnl_cents") or 0,
            "watchlist_count": profile_wl_count.get(prof.id, 0) if prof else 0,
            "portfolio_value_cents": e.get("portfolio_value_cents") or 0,
            # New: emit per-bot deployed + starting so the Dashboard's
            # Strategy Spotlight widget can show "X% of $Y deployed" without
            # cross-fetching /strategy-lab/portfolio.
            "deployed_cents": int(e.get("deployed_cents") or deployed_by_profile.get(prof_name, 0)),
            "starting_capital_cents": int(e.get("starting_capital_cents") or starting_by_profile.get(prof_name, 0)),
        })
    # Append orphan-allocation bots not represented in canonical's leaderboard.
    for alloc in allocs:
        prof = alloc_to_profile.get(alloc.id)
        if not prof or prof.name in profiles_in_lb:
            continue
        bot_snap = bot_snapshots_by_alloc.get(alloc.id)
        if not bot_snap:
            continue
        profiles_in_lb.add(prof.name)
        leaderboard.append({
            "rank": 0,
            "profile": prof.name,
            "name": _DISPLAY_NAMES.get(prof.name, prof.name.replace("_", " ").title()),
            "return_30d_pct": float(bot_snap.return_30d_pct or 0.0),
            "today_pnl_cents": int(bot_snap.today_pnl_cents or 0),
            "watchlist_count": profile_wl_count.get(prof.id, 0),
            "portfolio_value_cents": int(bot_snap.portfolio_value_cents or 0),
            "deployed_cents": int(getattr(bot_snap, "deployed_cents", 0) or 0),
            "starting_capital_cents": int(bot_snap.starting_capital_cents or 0),
        })
    # Re-rank by return_30d_pct desc so newly appended orphans get proper ranks.
    leaderboard.sort(key=lambda x: x["return_30d_pct"], reverse=True)
    for i, e in enumerate(leaderboard, start=1):
        e["rank"] = i

    # Invariant: sum(sleeve_data.value_cents) == total_value (±$1).
    # Loud log if violated — catches sleeve-bucketing regressions.
    sleeve_sum = sum(sleeve_data[s]["value_cents"] for s in sleeve_data)
    if abs(total_value - sleeve_sum) > 100:
        logger.error(
            "[dashboard/v2] invariant violation user=%s total=%d sleeve_sum=%d diff=%d",
            current_user.id, total_value, sleeve_sum, total_value - sleeve_sum,
        )

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
