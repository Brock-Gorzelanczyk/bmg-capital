"""Risk Console — /api/risk

Institutional-grade portfolio risk view + hard kill switch.

Endpoints:
  GET  /api/risk/console       — snapshot: PV, drawdown, net exposure, VaR,
                                 correlation matrix, deployment
  POST /api/risk/flatten-all   — HARD KILL: liquidate every open position
                                 for user_id=1. Requires confirm=FLATTEN_ALL
                                 in the JSON body.

Author's note (2026-07-03): Brock's audit item #1 — "you don't need to
know what every trade is doing in real time, but you MUST know your
total risk at all times." Built to be a top-of-book dashboard for a
multi-strategy paper prop book.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/risk", tags=["risk"])

_FUND_INCEPTION_CENTS = 1_000_000  # $10,000 — post-2026-08-21 strategic reset baseline


def _open_positions_with_live_price(db: Session, user_id: int) -> list[dict]:
    """Return open positions across all user allocations with live price."""
    from app.db.models.bots import BotPosition, BotAllocation, BotProfile
    from app.core.canonical import _cached_live_prices

    rows = db.execute(text(
        "SELECT p.id, p.symbol, p.qty, p.avg_cost_cents, p.side, p.option_type, "
        "       p.opened_at, p.allocation_id, bp.name AS bot_name, bp.asset_class "
        "FROM bot_positions p "
        "JOIN bot_allocations a ON a.id = p.allocation_id "
        "JOIN bot_profiles bp ON bp.id = a.profile_id "
        "WHERE a.user_id = :uid "
        "  AND p.closed_at IS NULL "
        "  AND p.quarantined_at IS NULL"
    ), {"uid": user_id}).fetchall()

    symbols = list({r[1] for r in rows if r[5] is None})  # equity/crypto
    live = _cached_live_prices(symbols)

    out = []
    for r in rows:
        pid, sym, qty, avg_cost_c, side, opt_type, opened_at, alloc_id, bot, ac = r
        # Convert to consistent dollar figures
        entry_price_usd = float(avg_cost_c or 0) / 100.0
        live_price_usd = float(live.get(sym) or 0)
        # Notional at cost (position size)
        if opt_type is not None:
            notional_usd = float(entry_price_usd) * float(qty or 0) * 100
        else:
            notional_usd = float(entry_price_usd) * float(qty or 0)
        # Unrealized P&L
        unreal = 0.0
        if live_price_usd > 0 and opt_type is None:
            is_short = (side or "long") == "short"
            if is_short:
                unreal = (entry_price_usd - live_price_usd) * float(qty or 0)
            else:
                unreal = (live_price_usd - entry_price_usd) * float(qty or 0)
        # SQLite returns TEXT for DateTime columns via raw text() — handle both.
        opened_iso: Any = None
        if opened_at is not None:
            if hasattr(opened_at, "isoformat"):
                opened_iso = opened_at.isoformat()
            else:
                opened_iso = str(opened_at)
        out.append({
            "position_id": int(pid),
            "symbol": sym,
            "side": side or "long",
            "qty": float(qty or 0),
            "entry_price_usd": entry_price_usd,
            "live_price_usd": live_price_usd,
            "notional_usd": notional_usd,
            "unrealized_usd": unreal,
            "bot": bot,
            "asset_class": ac,
            "allocation_id": int(alloc_id),
            "opened_at": opened_iso,
            "is_option": opt_type is not None,
        })
    return out


def _max_drawdown_from_snapshots(db: Session, user_id: int, days: int = 60) -> dict:
    """Compute peak-to-trough drawdown from bot_daily_pnl snapshots."""
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = db.execute(text(
        "SELECT date, SUM(portfolio_value_eod_cents) "
        "FROM bot_daily_pnl "
        "WHERE date >= :cut "
        "  AND portfolio_value_eod_cents IS NOT NULL "
        "  AND allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = :uid) "
        "GROUP BY date "
        "ORDER BY date ASC"
    ), {"cut": cutoff, "uid": user_id}).fetchall()

    equity_curve = [(r[0], int(r[1] or 0)) for r in rows]
    if not equity_curve:
        return {"max_drawdown_pct": 0.0, "max_drawdown_cents": 0, "days_of_data": 0}

    peak = equity_curve[0][1]
    max_dd_cents = 0
    max_dd_pct = 0.0
    peak_date = equity_curve[0][0]
    trough_date = equity_curve[0][0]
    for d, v in equity_curve:
        if v > peak:
            peak = v
            peak_date = d
        dd = peak - v
        if peak > 0 and dd > max_dd_cents:
            max_dd_cents = dd
            max_dd_pct = dd / peak
            trough_date = d
    return {
        "max_drawdown_pct": round(max_dd_pct, 6),
        "max_drawdown_cents": int(max_dd_cents),
        "peak_date": str(peak_date),
        "trough_date": str(trough_date),
        "days_of_data": len(equity_curve),
        "equity_curve": [{"date": str(d), "value_cents": v} for d, v in equity_curve],
    }


def _historical_var(db: Session, user_id: int, days: int = 30, confidence: float = 0.95) -> dict:
    """Simple historical VaR from daily fund P&L.

    Returns a 1-day 95% VaR (dollar amount you should not lose more than
    on 95% of days, based on the last N days of realized daily P&L).
    """
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = db.execute(text(
        "SELECT date, SUM(COALESCE(realized_cents, 0) + COALESCE(unrealized_cents, 0)) "
        "FROM bot_daily_pnl "
        "WHERE date >= :cut "
        "  AND allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = :uid) "
        "GROUP BY date "
        "ORDER BY date ASC"
    ), {"cut": cutoff, "uid": user_id}).fetchall()

    daily_pnl_cents = [int(r[1] or 0) for r in rows]
    if len(daily_pnl_cents) < 5:
        return {"var_95_1d_cents": 0, "days_of_data": len(daily_pnl_cents), "note": "insufficient history"}

    # Sort ascending — the (1 - confidence) percentile is our VaR
    sorted_pnl = sorted(daily_pnl_cents)
    idx = int((1 - confidence) * len(sorted_pnl))
    var_cents = -sorted_pnl[idx]  # loss is a positive number
    return {
        "var_95_1d_cents": max(0, int(var_cents)),
        "days_of_data": len(daily_pnl_cents),
        "min_daily_cents": min(sorted_pnl),
        "max_daily_cents": max(sorted_pnl),
    }


def _bot_return_correlation(db: Session, user_id: int, days: int = 30) -> dict:
    """Pairwise correlation between bot daily returns.

    Returns list of {bot_a, bot_b, corr, n_days} sorted by |corr| desc.
    Only includes pairs where both bots have >= 5 days of data.
    """
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = db.execute(text(
        "SELECT p.name, dp.date, "
        "       CAST(COALESCE(dp.realized_cents,0) + COALESCE(dp.unrealized_cents,0) AS FLOAT) / "
        "       NULLIF(a.starting_capital_cents, 0) AS daily_ret "
        "FROM bot_daily_pnl dp "
        "JOIN bot_allocations a ON a.id = dp.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid AND dp.date >= :cut "
        "  AND a.starting_capital_cents > 0"
    ), {"uid": user_id, "cut": cutoff}).fetchall()

    # Build {bot: {date: ret}}
    by_bot: dict[str, dict[str, float]] = defaultdict(dict)
    for name, d, ret in rows:
        if ret is not None:
            by_bot[name][str(d)] = float(ret)

    bots = sorted(by_bot.keys())
    pairs = []
    for i in range(len(bots)):
        for j in range(i + 1, len(bots)):
            a, b = bots[i], bots[j]
            common = set(by_bot[a].keys()) & set(by_bot[b].keys())
            if len(common) < 5:
                continue
            xs = [by_bot[a][d] for d in common]
            ys = [by_bot[b][d] for d in common]
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((xs[k] - mx) * (ys[k] - my) for k in range(n)) / n
            varx = sum((xs[k] - mx) ** 2 for k in range(n)) / n
            vary = sum((ys[k] - my) ** 2 for k in range(n)) / n
            if varx <= 0 or vary <= 0:
                continue
            corr = cov / math.sqrt(varx * vary)
            pairs.append({"bot_a": a, "bot_b": b, "corr": round(corr, 3), "n_days": n})

    pairs.sort(key=lambda x: -abs(x["corr"]))
    return {
        "bot_count": len(bots),
        "pairs_computed": len(pairs),
        "top_correlated": pairs[:15],
    }


@router.get("/console")
def get_risk_console(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Composite risk snapshot."""
    from app.core.canonical import compute_strategy_lab_aggregate

    uid = current_user.id
    agg = compute_strategy_lab_aggregate(uid, db) or {}
    pv_cents = int(agg.get("total_value_cents") or 0)
    pnl = agg.get("pnl", {})

    positions = _open_positions_with_live_price(db, uid)
    deployed_usd = sum(p["notional_usd"] for p in positions)
    unrealized_usd = sum(p["unrealized_usd"] for p in positions)
    starting_cents = int(agg.get("return_30d_value_cents", 0)) + int(pv_cents) - int(pv_cents)  # placeholder
    # Compute starting via allocations
    row = db.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": uid}).fetchone()
    starting_cents = int(row[0] or 0) if row else _FUND_INCEPTION_CENTS

    # 2026-07-06: include portfolio-rank bot capital in the fund starting
    # total AND in the per-sleeve pie. Note: pv_cents ALREADY includes
    # portfolio-rank capital (canonical.py rolls it into total_value_cents
    # as of this same PR). We only need to add here for numbers that come
    # from local queries: starting_cents (from bot_allocations only) and
    # sleeve_totals (from bot_positions only).
    pr_starting_cents = 0
    pr_pv_cents = 0
    pr_deployed_usd = 0.0
    try:
        pr_rows = db.execute(text(
            "SELECT id, starting_capital_cents FROM portfolio_rank_bots"
        )).fetchall()
        for _r in pr_rows:
            _bid = int(_r[0])
            _sc = int(_r[1] or 0)
            pr_starting_cents += _sc
            _pnl_row = db.execute(text(
                "SELECT COALESCE(SUM(current_pnl_cents), 0) "
                "FROM portfolio_rank_holdings WHERE bot_id = :bid"
            ), {"bid": _bid}).fetchone()
            _bot_pnl = int(_pnl_row[0] or 0) if _pnl_row else 0
            pr_pv_cents += _sc + _bot_pnl
        # Deployed for portfolio-rank = sum of holdings notional at entry.
        _dep_row = db.execute(text(
            "SELECT COALESCE(SUM("
            "  CASE WHEN entry_price_cents IS NOT NULL AND actual_weight IS NOT NULL "
            "       THEN entry_price_cents * actual_weight "
            "       ELSE 0 END"
            "), 0) FROM portfolio_rank_holdings"
        )).fetchone()
        _pr_dep_cents = int(_dep_row[0] or 0) if _dep_row else 0
        pr_deployed_usd = _pr_dep_cents / 100.0
    except Exception as _pr_exc:
        logger.warning("[risk-console] portfolio_rank rollup failed: %s", _pr_exc)

    # Roll portfolio-rank capital into starting + deployed. Do NOT add to
    # pv_cents — canonical already included it. Local alias for readability.
    starting_cents += pr_starting_cents
    pv_cents_adj = pv_cents
    deployed_usd += pr_deployed_usd
    deployment_pct = (deployed_usd * 100) / (starting_cents / 100) if starting_cents else 0

    # Net exposure by symbol (sum across bots)
    by_symbol = defaultdict(lambda: {"symbol": "", "notional_usd": 0.0, "unrealized_usd": 0.0,
                                     "bots": [], "positions_count": 0, "is_option": False})
    for p in positions:
        b = by_symbol[p["symbol"]]
        b["symbol"] = p["symbol"]
        b["notional_usd"] += p["notional_usd"]
        b["unrealized_usd"] += p["unrealized_usd"]
        b["positions_count"] += 1
        if p["bot"] not in b["bots"]:
            b["bots"].append(p["bot"])
        if p["is_option"]:
            b["is_option"] = True
    net_exposure = sorted(by_symbol.values(), key=lambda x: -x["notional_usd"])

    # Concentration: top-5 symbols as % of PV (uses portfolio-rank-inclusive PV
    # so the denominator matches the fund invariant).
    top5 = sum(x["notional_usd"] for x in net_exposure[:5])
    pv_usd = pv_cents_adj / 100.0
    top5_concentration_pct = (top5 / pv_usd * 100) if pv_usd else 0

    dd = _max_drawdown_from_snapshots(db, uid, days=60)
    var = _historical_var(db, uid, days=30)
    corr = _bot_return_correlation(db, uid, days=30)

    # Sleeve exposures
    sleeve_totals = defaultdict(float)
    for p in positions:
        sleeve_totals[p["asset_class"] or "unknown"] += p["notional_usd"]
    # Portfolio-rank capital surfaces as its own sleeve. Even before the
    # runner places holdings, we surface starting_capital here so the pie
    # includes the $100K and the LP-facing narrative stays consistent.
    if pr_pv_cents > 0:
        sleeve_totals["portfolio_rank"] = pr_pv_cents / 100.0

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "user_id": uid,
        "fund": {
            "pv_cents": pv_cents_adj,
            "starting_cents": starting_cents,
            "all_time_pnl_cents": pv_cents_adj - starting_cents,
            "pnl_windows": pnl,
        },
        "deployment": {
            "deployed_usd": round(deployed_usd, 2),
            "unrealized_usd": round(unrealized_usd, 2),
            "deployment_pct": round(deployment_pct, 2),
            # 2026-07-05 fix: real deployment can exceed 100% when either
            # (a) ghost positions inflate the notional sum, or (b) a bot
            # opened positions beyond its stated cap. LP-facing pie fills
            # to the capped value; overexposed=True triggers the warning
            # badge so the number isn't silently truthy.
            "deployment_pct_capped": round(min(100.0, deployment_pct), 2),
            "deployment_overexposed": deployment_pct > 100.0,
            "cash_reserve_pct": round(max(0.0, 100 - deployment_pct), 2),
            "open_positions_count": len(positions),
            "top5_concentration_pct": round(top5_concentration_pct, 2),
            "sleeve_notional_usd": {k: round(v, 2) for k, v in sleeve_totals.items()},
        },
        "drawdown": dd,
        "var": var,
        "correlation": corr,
        "net_exposure_by_symbol": [
            {**x, "notional_usd": round(x["notional_usd"], 2),
             "unrealized_usd": round(x["unrealized_usd"], 2)}
            for x in net_exposure[:25]  # top 25 symbols
        ],
    }


@router.post("/flatten-all")
def flatten_all_positions(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """HARD KILL: Close every open position for the current user.

    Requires `confirm: "FLATTEN_ALL"` in JSON body to prevent accidental
    liquidation. Uses the position_monitor._close_position helper so
    exit trades + realized P&L land in the standard tables.

    Returns per-position outcome.
    """
    confirm = str(payload.get("confirm", "")).strip()
    if confirm != "FLATTEN_ALL":
        raise HTTPException(
            status_code=400,
            detail="Missing or invalid confirm token. Send {\"confirm\": \"FLATTEN_ALL\"}",
        )

    reason = str(payload.get("reason", "manual_flatten")).strip()[:80] or "manual_flatten"

    from app.db.models.bots import BotPosition, BotAllocation, BotProfile
    from app.core.canonical import _cached_live_prices
    from strategy_lab.core.position_monitor import _close_position

    # Fetch open positions
    positions = db.execute(text(
        "SELECT p.id FROM bot_positions p "
        "JOIN bot_allocations a ON a.id = p.allocation_id "
        "WHERE a.user_id = :uid AND p.closed_at IS NULL AND p.quarantined_at IS NULL"
    ), {"uid": current_user.id}).fetchall()
    pos_ids = [int(r[0]) for r in positions]

    if not pos_ids:
        return {"closed": 0, "results": [], "note": "no open positions"}

    now = datetime.now(timezone.utc)

    # Bulk fetch objects
    pos_rows = db.query(BotPosition).filter(BotPosition.id.in_(pos_ids)).all()
    alloc_ids = {p.allocation_id for p in pos_rows}
    allocs = {a.id: a for a in db.query(BotAllocation).filter(BotAllocation.id.in_(alloc_ids)).all()}
    symbols_needed = list({p.symbol for p in pos_rows if p.option_type is None})
    live = _cached_live_prices(symbols_needed)

    results = []
    closed_count = 0
    for pos in pos_rows:
        alloc = allocs.get(pos.allocation_id)
        if not alloc:
            results.append({"position_id": pos.id, "symbol": pos.symbol, "status": "no_alloc"})
            continue
        # Get an exit price. For options, use avg_cost as a placeholder (unrealized = 0).
        if pos.option_type is not None:
            exit_price = float(pos.avg_cost_cents or 0) / 100.0
        else:
            exit_price = float(live.get(pos.symbol) or 0)
            if exit_price <= 0:
                # Fallback to entry to close at breakeven if no live price
                exit_price = float(pos.avg_cost_cents or 0) / 100.0
        try:
            _close_position(db, pos, alloc, exit_price, reason, now)
            closed_count += 1
            results.append({
                "position_id": pos.id,
                "symbol": pos.symbol,
                "bot": None,  # avoid extra query
                "exit_price_usd": exit_price,
                "status": "closed",
            })
        except Exception as exc:
            db.rollback()
            logger.error("[risk/flatten-all] close failed for pos_id=%d: %s", pos.id, exc)
            results.append({"position_id": pos.id, "symbol": pos.symbol, "status": "error",
                            "error": str(exc)[:200]})

    logger.warning(
        "[risk/flatten-all] user=%d closed=%d/%d reason=%s",
        current_user.id, closed_count, len(pos_ids), reason,
    )

    # Ops alert
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="⚠️ FLATTEN ALL executed",
            message=(
                f"user_id={current_user.id} closed {closed_count}/{len(pos_ids)} "
                f"positions · reason={reason}"
            ),
            severity="critical",
            source="risk/flatten-all",
        )
    except Exception:
        pass

    return {"closed": closed_count, "attempted": len(pos_ids), "reason": reason, "results": results}
