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
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.core.tz import iso_utc

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
    # 2026-07-02: asset_class='quant' now routes to the Crypto sleeve by
    # default. The 8 new bots (alt_focus / scalp_1m / universe_top6 /
    # defi_l2 / meme_tier / 10m / 15m / dca_btc_eth) all trade crypto pairs
    # directly — "quant" is the strategy family, not an asset class. Only
    # the original 3 quant bots (Aggressive, Mean Rev, Scalper) still get
    # routed to the standalone Quant sleeve, via the _QUANT_PROFILE_NAMES
    # override in _profile_sleeve() below.
    "quant": "crypto",
    "options": "options",
    "equity": "stocks",  # some profiles use "equity" instead of "stock"
    "option":  "options",  # ditto for singular
}

# Quant bots have asset_class=crypto in m027 SPEC. Route them to the
# dedicated "quant" sleeve so the Dashboard shows all 4 sleeve cards.
# PART 6 fix: previously asset_class=crypto routed them to "crypto" bucket
# and the Dashboard rendered only 3 sleeves with "sleeve missing from payload".
_QUANT_PROFILE_NAMES = frozenset({
    # ORIGINAL 3 quant bots. These predate the "sleeve" concept and were
    # designed as an asset-agnostic bucket — they use the same 8-strategy
    # quant stack but their sleeve is the historical "quant" card.
    "crypto_quant_aggressive",
    "crypto_quant_scalper",
    "crypto_quant_mean_reversion",
    # 2026-07-02 reversal: the m052/m053 batch bots (alt_focus/scalp_1m/
    # universe_top6/defi_l2/meme_tier/10m/15m/dca_btc_eth) are NOT in this
    # set. They trade crypto pairs directly (BTC/ETH/SOL/POL/DOGE etc), so
    # their sleeve is "crypto" — same as crypto_day/swing/lt/onchain. The
    # word "quant" in their names is a strategy family, not an asset class.
    # This routes their capital to the Crypto sleeve card on the dashboard.
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

    # ── Per-allocation snapshots (ORPHANS ONLY) ──────────────────────────────
    # 2026-07-04 perf fix: dashboard was hanging at 25s+ because it called
    # compute_bot_snapshot for EVERY allocation (29 calls) AND ALSO called
    # compute_strategy_lab_aggregate (which internally does the same 29
    # snapshot calls). 58+ snapshots per request → live price fetches → hang.
    #
    # Root cause: bot_snapshots_by_alloc is only USED as a fallback for
    # profiles missing from leaderboard_from_agg (orphan allocations without
    # a portfolio_id). For the 22+ bots that ARE in the aggregator's
    # leaderboard, the snapshot data was fetched twice and discarded.
    #
    # Fix: only compute snapshots for orphan allocations. Drops the loop
    # from 29 to ~1-2 per request. `pv_by_alloc` / `today_pnl_by_alloc` etc
    # still get populated via the profile-name lookup path below for
    # in-leaderboard bots.
    covered_by_agg = set(pv_by_profile_name.keys())
    bot_snapshots_by_alloc: dict[int, Any] = {}
    for alloc in allocs:
        p = alloc_to_profile.get(alloc.id)
        if not p:
            continue
        if p.name in covered_by_agg:
            continue  # skip — aggregator already has these values
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

    # ── Portfolio totals — trust the canonical aggregate ────────────────────
    # 2026-08-18 (Brock): the earlier override that summed pv_by_alloc was
    # from before canonical became Alpaca-authoritative. Canonical now
    # includes orphan allocations correctly (via orphan_alloc_attributed_cents)
    # AND anchors total_value_cents to Alpaca broker truth. Summing bot PVs
    # here was making Dashboard show ~$107K while every other endpoint showed
    # ~$93K (delta = unattributed drift). Fixed: use agg values directly.
    total_starting = sum(a.starting_capital_cents or 0 for a in allocs)
    total_realized = sum(total_realized_by_alloc.values())
    total_value = int(agg.get("total_value_cents") or 0)
    total_value_source = agg.get("total_value_source") or "unknown"
    _agg_today = agg.get("today_pnl_cents")
    total_today_pnl = int(_agg_today or 0) if _agg_today is not None else 0
    today_pnl_source = agg.get("today_pnl_source") or "unknown"
    today_pnl_label = agg.get("today_pnl_label") or "unknown"
    bot_sum_pv_cents = int(agg.get("bot_sum_pv_cents") or 0)
    unattributed_cents = int(agg.get("unattributed_cents") or 0)

    # today_pnl_pct: derived from totals, not blindly copied from agg.
    # 4-decimal precision: small negative P&L (e.g. -$15 on $1M = -0.0015%)
    # was rounding to -0.0, which JS treats as ≥0 and rendered as "+0.00%".
    yesterday_value = total_value - total_today_pnl
    today_pct = round(total_today_pnl / yesterday_value * 100, 4) if yesterday_value > 0 else 0.0

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

    # ── Portfolio-rank bots (Phase 2) ─────────────────────────────────────
    # These live in portfolio_rank_bots, NOT bot_allocations. m067 funded
    # momentum_umd and quality_gross_profitability at $50K each. Without
    # this block, their $100K would silently vanish from the dashboard PV,
    # leaving the invariant broken: bot_allocations $950K but fund PV
    # displayed as $950K instead of $1M.
    pr_value_cents = 0
    pr_pnl_cents = 0
    pr_bots_total = 0
    pr_bots_active = 0
    pr_open_positions = 0
    try:
        pr_rows = db.execute(text(
            "SELECT id, name, starting_capital_cents, enabled "
            "FROM portfolio_rank_bots"
        )).fetchall()
        for _pr in pr_rows:
            _pr_id = int(_pr[0])
            _pr_starting = int(_pr[2] or 0)
            _pr_enabled = bool(_pr[3])
            # PV = starting_capital + realized/unrealized P&L on holdings.
            # In dry-run mode current_pnl_cents starts at 0. Sum defensively
            # so PV can drift with mark-to-market updates when they land.
            _pnl_row = db.execute(text(
                "SELECT COALESCE(SUM(current_pnl_cents), 0) "
                "FROM portfolio_rank_holdings WHERE bot_id = :bid"
            ), {"bid": _pr_id}).fetchone()
            _pr_bot_pnl = int(_pnl_row[0] or 0) if _pnl_row else 0
            _pr_bot_pv = _pr_starting + _pr_bot_pnl
            pr_value_cents += _pr_bot_pv
            pr_pnl_cents   += _pr_bot_pnl
            pr_bots_total  += 1
            if _pr_enabled and _pr_starting > 0:
                pr_bots_active += 1
            # Open positions = count of holdings rows for this bot.
            _cnt_row = db.execute(text(
                "SELECT COUNT(*) FROM portfolio_rank_holdings WHERE bot_id = :bid"
            ), {"bid": _pr_id}).fetchone()
            pr_open_positions += int(_cnt_row[0] or 0) if _cnt_row else 0
        # 2026-08-18: only fold PR into total_value if canonical did NOT
        # already include it. When total_value_source == "alpaca_account"
        # (broker truth), Alpaca already contains PR positions and adding
        # here would double-count. Mirrors canonical.py:1723 guard.
        if total_value_source != "alpaca_account":
            total_value += pr_value_cents
            total_today_pnl += pr_pnl_cents
    except Exception as _pr_exc:
        logger.warning("[dashboard/v2] portfolio_rank rollup failed: %s", _pr_exc)

    # ── Per-sleeve breakdown ─────────────────────────────────────────────────
    sleeve_data: dict[str, dict[str, int]] = {
        s: {"value_cents": 0, "open_positions": 0, "watching": 0, "pnl_cents": 0, "bots_active": 0, "bots_total": 0}
        for s in ("stocks", "crypto", "options", "quant", "portfolio_rank")
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

    # Populate the portfolio_rank sleeve from the values computed above.
    # This must run BEFORE the invariant check so the sleeve sum matches
    # total_value (which now includes portfolio-rank capital).
    sleeve_data["portfolio_rank"]["value_cents"]     = pr_value_cents
    sleeve_data["portfolio_rank"]["pnl_cents"]       = pr_pnl_cents
    sleeve_data["portfolio_rank"]["bots_total"]      = pr_bots_total
    sleeve_data["portfolio_rank"]["bots_active"]     = pr_bots_active
    sleeve_data["portfolio_rank"]["open_positions"] = pr_open_positions

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
            "ts": iso_utc(s.ts),
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
            # 2026-08-05: propagate the total_trades count from canonical so
            # the Strategy Lab leaderboard's yellow TRADES column shows real
            # numbers instead of 0. StrategyLabV2 reads this via /api/dashboard/v2.
            "total_trades": int(e.get("total_trades") or 0),
            # 2026-08-07: propagate closing_trades_count so the public
            # zero-realized check can filter out legitimately open-only bots.
            "closing_trades_count": int(e.get("closing_trades_count") or 0),
            "realized_pnl_cents": int(e.get("realized_pnl_cents") or 0),
        })
    # Append orphan-allocation bots not represented in canonical's leaderboard.
    # 2026-07-06: previously we skipped allocs whose bot_snap was None (silent
    # drop when compute_bot_snapshot errored for any reason — DB timeout,
    # missing profile, phantom column). This dropped bots randomly from the
    # /strategy leaderboard. Now we fall back to a starting-capital stub so
    # every funded allocation is always visible.
    for alloc in allocs:
        prof = alloc_to_profile.get(alloc.id)
        if not prof or prof.name in profiles_in_lb:
            continue
        bot_snap = bot_snapshots_by_alloc.get(alloc.id)
        profiles_in_lb.add(prof.name)
        # 2026-08-05: same TRADES column fix — count real (unquarantined)
        # bot_trades for this allocation so orphan-alloc rows show counts too.
        try:
            from app.db.models.bots import BotTrade as _BT
            _bot_trade_count = (
                db.query(_BT)
                .filter(_BT.allocation_id == alloc.id)
                .filter(_BT.quarantined_at.is_(None))
                .count()
            )
        except Exception:
            _bot_trade_count = 0

        if bot_snap:
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
                "total_trades": _bot_trade_count,
            })
        else:
            # Stub row so the bot still renders on the leaderboard.
            starting = int(alloc.starting_capital_cents or 0)
            leaderboard.append({
                "rank": 0,
                "profile": prof.name,
                "name": _DISPLAY_NAMES.get(prof.name, prof.name.replace("_", " ").title()),
                "return_30d_pct": 0.0,
                "today_pnl_cents": 0,
                "watchlist_count": profile_wl_count.get(prof.id, 0),
                "portfolio_value_cents": starting,
                "deployed_cents": 0,
                "starting_capital_cents": starting,
                "total_trades": _bot_trade_count,
            })

    # 2026-07-06 Bug 3 fix: cash_floor slipped back onto the leaderboard via
    # the orphan append path. canonical.py filters it correctly for entries
    # from canonical.leaderboard, but does not touch what dashboard.py adds
    # here. Re-apply the same filter now that both sources have contributed.
    leaderboard = [
        e for e in leaderboard
        if e.get("profile") != "cash_floor"
        and (
            e.get("bot_type") == "portfolio_rank"
            or (e.get("starting_capital_cents", 0) > 0)
            or (e.get("today_pnl_cents", 0) != 0)
        )
    ]

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
            "total_value_source": total_value_source,           # 2026-08-18: I26 requirement
            "bot_sum_pv_cents": bot_sum_pv_cents,               # attribution (informational)
            "unattributed_cents": unattributed_cents,           # bot_sum - total_value drift
            "today_pnl_cents": total_today_pnl,
            "today_pnl_source": today_pnl_source,
            "today_pnl_label": today_pnl_label,
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


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard visual-upgrade endpoints (2026-07-13 spec)
# All read from the canonical portfolio service (compute_bot_snapshot per
# alloc, summed) — no re-derived math.
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/hero-stats")
def get_hero_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fleet-level hero row: realized P&L (all-time + today), trades, win rate, Sharpe."""
    from app.core.canonical import compute_bot_snapshot

    allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.enabled.is_(True),
        )
        .all()
    )
    alloc_ids = [a.id for a in allocs]
    profile_ids = list({a.profile_id for a in allocs})
    profs = {
        p.id: p for p in db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    }

    total_realized = 0
    total_wins = 0
    total_losses = 0
    weighted_sharpe_num = 0.0
    weighted_sharpe_den = 0
    for alloc in allocs:
        prof = profs.get(alloc.profile_id)
        if not prof:
            continue
        try:
            snap = compute_bot_snapshot(alloc, prof, db)
        except Exception as exc:
            logger.warning("[hero-stats] snapshot failed alloc=%d: %s", alloc.id, exc)
            continue
        total_realized += int(snap.realized_pnl_cents or 0)
        total_wins += int(snap.win_count or 0)
        total_losses += int(snap.loss_count or 0)
        if snap.sharpe_30d is not None and (alloc.starting_capital_cents or 0) > 0:
            weighted_sharpe_num += float(snap.sharpe_30d) * int(alloc.starting_capital_cents)
            weighted_sharpe_den += int(alloc.starting_capital_cents)

    total_closed = total_wins + total_losses
    win_rate = (total_wins / total_closed) if total_closed > 0 else None
    sharpe_30d = (
        (weighted_sharpe_num / weighted_sharpe_den) if weighted_sharpe_den > 0 else None
    )

    # Today's realized P&L: SUM(bot_daily_pnl.realized_cents) for date=today.
    realized_today = 0
    if alloc_ids:
        try:
            row = db.execute(text(
                "SELECT COALESCE(SUM(realized_cents), 0) "
                "FROM bot_daily_pnl "
                "WHERE allocation_id IN :ids "
                "  AND date = CURRENT_DATE"
            ).bindparams(bindparam("ids", expanding=True)),
                {"ids": alloc_ids},
            ).fetchone()
            realized_today = int(row[0] or 0) if row else 0
        except Exception as exc:
            logger.warning("[hero-stats] realized_today query failed: %s", exc)

    # 2026-08-20 Brock: hero card should show TOTAL P&L today (realized +
    # unrealized, i.e. equity change) not realized-only. Realized-only was
    # showing stale values from bot_daily_pnl while closed_trades=0.
    # Session-honest per §W2: null outside RTH with label.
    today_pnl_cents = None
    today_pnl_label = "unavailable"
    market_state = "closed"
    try:
        from app.services.alpaca_account_cache import get_alpaca_account
        from app.services.market_hours import is_market_open as _is_market_open
        acct = get_alpaca_account() or {}
        _eq = float(acct.get("equity") or 0)
        _last = float(acct.get("last_equity") or 0)
        rth = _is_market_open()
        if _eq > 0 and _last > 0:
            today_pnl_cents = int(round((_eq - _last) * 100))
            if rth:
                today_pnl_label = "live"
                market_state = "open"
            else:
                today_pnl_label = "market_closed_final"
                market_state = "closed"
    except Exception as exc:
        logger.warning("[hero-stats] today_pnl fetch failed: %s", exc)

    return {
        "realized_pnl_cents": int(total_realized),
        "realized_pnl_today_cents": int(realized_today),
        # 2026-08-20 addition: total P&L today = equity - last_equity from Alpaca
        "today_pnl_cents": today_pnl_cents,
        "today_pnl_label": today_pnl_label,
        "market_state": market_state,
        "trades_closed_alltime": int(total_closed),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "sharpe_30d": round(sharpe_30d, 2) if sharpe_30d is not None else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


_TOP_TRADES_WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": 3650}


@router.get("/top-trades")
def get_top_trades(
    window: str = "30d",
    side: str = "win",
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return top-N winning or losing closed trades in window."""
    days = _TOP_TRADES_WINDOW_DAYS.get(window, 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    limit = max(1, min(int(limit), 25))
    side_wants_wins = side.lower() != "loss"

    rows = db.execute(
        text(
            """
            SELECT t.id            AS trade_id,
                   t.symbol        AS symbol,
                   t.ts            AS closed_at,
                   t.fill_price_cents AS exit_cents,
                   t.qty           AS qty,
                   p.avg_cost_cents AS entry_cents,
                   p.opened_at     AS opened_at,
                   bp.name         AS bot_name,
                   bp.asset_class  AS asset_class
              FROM bot_trades t
              JOIN bot_positions p ON p.id = t.position_id
              JOIN bot_allocations a ON a.id = t.allocation_id
              JOIN bot_profiles bp ON bp.id = a.profile_id
             WHERE a.user_id = :uid
               AND t.side IN ('sell', 'cover', 'close')
               AND t.quarantined_at IS NULL
               AND t.ts >= :cutoff
               AND p.avg_cost_cents > 0
            """
        ),
        {"uid": current_user.id, "cutoff": cutoff},
    ).fetchall()

    trades = []
    for r in rows:
        entry = float(r[5]) / 100.0
        exit_p = float(r[3]) / 100.0
        qty = float(r[4] or 0)
        pnl_usd = (float(r[3]) - float(r[5])) * qty / 100.0
        pnl_pct = ((float(r[3]) / float(r[5])) - 1.0) if float(r[5]) > 0 else 0.0
        trades.append(
            {
                "trade_id": int(r[0]),
                "bot": r[7],
                "sleeve": _profile_sleeve(r[7], r[8]),
                "symbol": r[1],
                "entry_price": round(entry, 4),
                "exit_price": round(exit_p, 4),
                "qty": qty,
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct, 4),
                "opened_at": r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                "closed_at": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
            }
        )

    trades.sort(key=lambda t: t["pnl_usd"], reverse=side_wants_wins)
    top = trades[:limit] if side_wants_wins else trades[:limit]

    # Sparkline: fetch daily bars per unique symbol in the trade window.
    # Cache to avoid duplicate fetches across trades on the same symbol.
    from datetime import date as _date

    def _sparkline(symbol: str, opened_at: str, closed_at: str) -> list[float]:
        try:
            import yfinance as yf  # type: ignore
        except Exception:
            return []
        try:
            s = datetime.fromisoformat(opened_at.replace("Z", "+00:00")).date()
            e = datetime.fromisoformat(closed_at.replace("Z", "+00:00")).date()
        except Exception:
            return []
        # Widen by a couple days on each side for context
        s_pad = s - timedelta(days=2)
        e_pad = e + timedelta(days=2)
        try:
            h = yf.Ticker(symbol).history(
                start=s_pad.strftime("%Y-%m-%d"),
                end=e_pad.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=True,
            )
        except Exception:
            return []
        if h is None or h.empty:
            return []
        return [round(float(v), 4) for v in h["Close"].tolist()]

    for t in top:
        t["daily_marks"] = _sparkline(t["symbol"], t["opened_at"], t["closed_at"])

    return {
        "window": window,
        "side": "win" if side_wants_wins else "loss",
        "trades": top,
        "candidates_considered": len(trades),
    }


@router.get("/trade-stream")
def get_trade_stream(
    since: int | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cursor-paginated closed trades. Cheap: no joins beyond profile.name."""
    limit = max(1, min(int(limit), 2000))
    since_id = int(since or 0)

    rows = db.execute(
        text(
            """
            SELECT t.id, t.ts, t.symbol, t.fill_price_cents, t.qty,
                   p.avg_cost_cents, bp.name, bp.asset_class
              FROM bot_trades t
              JOIN bot_positions p ON p.id = t.position_id
              JOIN bot_allocations a ON a.id = t.allocation_id
              JOIN bot_profiles bp ON bp.id = a.profile_id
             WHERE a.user_id = :uid
               AND t.side IN ('sell', 'cover', 'close')
               AND t.quarantined_at IS NULL
               AND t.id > :since_id
               AND p.avg_cost_cents > 0
             ORDER BY t.id ASC
             LIMIT :lim
            """
        ),
        {"uid": current_user.id, "since_id": since_id, "lim": limit},
    ).fetchall()

    trades = []
    max_id = since_id
    for r in rows:
        pnl_usd = (float(r[3]) - float(r[5])) * float(r[4] or 0) / 100.0
        trades.append({
            "id": int(r[0]),
            "closed_at": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
            "symbol": r[2],
            "pnl_usd": round(pnl_usd, 2),
            "bot": r[6],
            "sleeve": _profile_sleeve(r[6], r[7]),
        })
        if int(r[0]) > max_id:
            max_id = int(r[0])

    return {
        "trades": trades,
        "next_cursor": max_id,
        "has_more": len(trades) >= limit,
    }


@router.get("/sleeve-distributions")
def get_sleeve_distributions(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-sleeve daily P&L for ridgeline plotting."""
    days = max(1, min(int(days), 365))
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    rows = db.execute(
        text(
            """
            SELECT bp.name, bp.asset_class, dp.date,
                   (COALESCE(dp.realized_cents,0) + COALESCE(dp.unrealized_cents,0)) AS total
              FROM bot_daily_pnl dp
              JOIN bot_allocations a ON a.id = dp.allocation_id
              JOIN bot_profiles bp ON bp.id = a.profile_id
             WHERE a.user_id = :uid AND dp.date >= :cutoff
            """
        ),
        {"uid": current_user.id, "cutoff": cutoff},
    ).fetchall()

    by_sleeve: dict[str, dict[str, int]] = {}
    for r in rows:
        sleeve = _profile_sleeve(r[0], r[1])
        d = r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2])
        by_sleeve.setdefault(sleeve, {})
        by_sleeve[sleeve][d] = by_sleeve[sleeve].get(d, 0) + int(r[3] or 0)

    result: dict[str, list[dict]] = {}
    for sleeve, date_map in by_sleeve.items():
        result[sleeve] = [
            {"date": d, "pnl_cents": v} for d, v in sorted(date_map.items())
        ]
    return {"days": days, "sleeves": result}


def _estimate_next_rebalance(schedule: str, last: datetime | None) -> str | None:
    """Best-effort next rebalance date given a cadence and last-rebal time."""
    if not schedule:
        return None
    schedule = str(schedule).lower().strip()
    base = last or datetime.now(timezone.utc)
    if isinstance(base, str):
        try:
            base = datetime.fromisoformat(base)
        except Exception:
            base = datetime.now(timezone.utc)
    if schedule == "daily":
        return (base + timedelta(days=1)).isoformat()
    if schedule == "weekly":
        # Next Monday
        days_ahead = (7 - base.weekday()) % 7 or 7
        return (base + timedelta(days=days_ahead)).isoformat()
    if schedule == "monthly":
        # First Monday of next month
        year = base.year + (1 if base.month == 12 else 0)
        month = 1 if base.month == 12 else base.month + 1
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        days_ahead = (0 - first.weekday()) % 7  # 0 = Monday
        return (first + timedelta(days=days_ahead)).isoformat()
    if schedule == "quarterly":
        y = base.year
        m = base.month
        # Next quarter start (Jan/Apr/Jul/Oct)
        for q_month in (1, 4, 7, 10, 13):
            if q_month > m:
                target_month = q_month if q_month <= 12 else 1
                target_year = y if q_month <= 12 else y + 1
                first = datetime(target_year, target_month, 1, tzinfo=timezone.utc)
                days_ahead = (0 - first.weekday()) % 7
                return (first + timedelta(days=days_ahead)).isoformat()
    return None


@router.get("/signal-funnel-today")
def get_signal_funnel_today(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Today's discipline funnel: scanned → passed_filter → executed → winners.

    scanned         = signal_gates rows created today
    passed_filter   = signal_gates.final_decision = 'executed'
    executed        = bot_trades committed today (entry side)
    winners         = closed round-trips today with pnl > 0

    signal_gates schema uses SQLite date arithmetic (`datetime('now', ...)`)
    per m020, but the same query works on Postgres because both compare on
    the ISO string form. On Postgres we compare against CURRENT_DATE via
    a portable predicate.
    """
    # scanned + passed_filter from signal_gates
    scanned = 0
    passed_filter = 0
    try:
        row = db.execute(text(
            "SELECT COUNT(*), "
            "  SUM(CASE WHEN final_decision = 'executed' THEN 1 ELSE 0 END) "
            "  FROM signal_gates "
            " WHERE created_at >= CURRENT_DATE"
        )).fetchone()
        if row:
            scanned = int(row[0] or 0)
            passed_filter = int(row[1] or 0)
    except Exception as exc:
        logger.warning("[signal-funnel-today] signal_gates query failed: %s", exc)

    # executed = bot_trades today for this user
    executed = 0
    try:
        row = db.execute(text(
            "SELECT COUNT(*) FROM bot_trades t "
            "JOIN bot_allocations a ON a.id = t.allocation_id "
            "WHERE a.user_id = :uid "
            "  AND t.ts >= CURRENT_DATE "
            "  AND t.quarantined_at IS NULL"
        ), {"uid": current_user.id}).fetchone()
        executed = int(row[0] or 0) if row else 0
    except Exception as exc:
        logger.warning("[signal-funnel-today] trades query failed: %s", exc)

    # winners = closed round-trips today with pnl > 0
    winners = 0
    try:
        row = db.execute(text(
            "SELECT COUNT(*) "
            "  FROM bot_trades t "
            "  JOIN bot_positions p ON p.id = t.position_id "
            "  JOIN bot_allocations a ON a.id = t.allocation_id "
            " WHERE a.user_id = :uid "
            "   AND p.closed_at >= CURRENT_DATE "
            "   AND t.side IN ('sell', 'cover', 'close') "
            "   AND t.ts > p.opened_at "
            "   AND CASE WHEN p.side = 'short' "
            "         THEN (p.avg_cost_cents - t.fill_price_cents) "
            "         ELSE (t.fill_price_cents - p.avg_cost_cents) "
            "       END > 0"
        ), {"uid": current_user.id}).fetchone()
        winners = int(row[0] or 0) if row else 0
    except Exception as exc:
        logger.warning("[signal-funnel-today] winners query failed: %s", exc)

    win_pct = round((winners / executed * 100), 1) if executed > 0 else 0.0
    discipline_edge_pct = round((executed / scanned * 100), 2) if scanned > 0 else 0.0

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "scanned": scanned,
        "passed_filter": passed_filter,
        "executed": executed,
        "winners": winners,
        "win_pct": win_pct,
        "discipline_edge_pct": discipline_edge_pct,
    }


@router.get("/live-quotes")
def get_live_quotes(
    symbols: str = "SPY,QQQ,NVDA,AAPL,MSFT,TSLA,BTC/USD,ETH/USD,SOL/USD",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Batch quote fetch via Alpaca. Returns {symbol: {last, change_pct}}.
    Cached in-process for 15s to keep the ticker cheap."""
    import os
    import httpx

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {"quotes": {}}

    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return {"quotes": {}, "error": "no_alpaca_creds"}
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    stocks = [s for s in sym_list if "/" not in s]
    cryptos = [s for s in sym_list if "/" in s]

    quotes: dict[str, dict[str, float]] = {}

    if stocks:
        try:
            r = httpx.get(
                "https://data.alpaca.markets/v2/stocks/quotes/latest",
                headers=headers,
                params={"symbols": ",".join(stocks)},
                timeout=8,
            )
            data = r.json().get("quotes", {}) or {}
            for sym, q in data.items():
                px = float(q.get("ap") or q.get("bp") or 0)
                if px > 0:
                    quotes[sym] = {"last": px}
        except Exception as exc:
            logger.warning("[live-quotes] alpaca stocks failed: %s", exc)

    if cryptos:
        try:
            r = httpx.get(
                "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes",
                headers=headers,
                params={"symbols": ",".join(cryptos)},
                timeout=8,
            )
            data = r.json().get("quotes", {}) or {}
            for sym, q in data.items():
                px = float(q.get("ap") or q.get("bp") or 0)
                if px > 0:
                    quotes[sym] = {"last": px}
        except Exception as exc:
            logger.warning("[live-quotes] alpaca crypto failed: %s", exc)

    return {
        "quotes": quotes,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/session-meta")
def get_session_meta(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Session-bar fields: per-sleeve last_scan_at + PR-bot next_rebalance_at."""
    # Last scan per sleeve = MAX(bot_heartbeat.last_scan_at) grouped by sleeve.
    try:
        rows = db.execute(text(
            """
            SELECT hb.bot_name, hb.last_scan_at, bp.asset_class
              FROM bot_heartbeat hb
         LEFT JOIN bot_profiles bp ON bp.name = hb.bot_name
            """
        )).fetchall()
    except Exception as exc:
        logger.warning("[session-meta] heartbeat query failed: %s", exc)
        rows = []

    sleeve_last: dict[str, str] = {}
    for r in rows:
        bot_name = r[0]
        last = r[1]
        ac = r[2]
        sleeve = _profile_sleeve(bot_name, ac)
        if not last:
            continue
        last_iso = last.isoformat() if hasattr(last, "isoformat") else str(last)
        prev = sleeve_last.get(sleeve)
        if prev is None or last_iso > prev:
            sleeve_last[sleeve] = last_iso

    # PR bot next_rebalance_at
    try:
        pr_rows = db.execute(text(
            "SELECT name, rebalance_schedule, last_rebalanced_at "
            "FROM portfolio_rank_bots WHERE enabled = 1"
        )).fetchall()
    except Exception as exc:
        logger.warning("[session-meta] pr query failed: %s", exc)
        pr_rows = []

    pr_next: dict[str, str | None] = {}
    for r in pr_rows:
        pr_next[r[0]] = _estimate_next_rebalance(r[1], r[2])

    return {
        "sleeve_last_scan_at": sleeve_last,
        "pr_next_rebalance_at": pr_next,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
