"""Portfolio-rank runtime.

Sits parallel to the signal-trigger runtime (`scan_and_execute.py`).
Loads a `portfolio_rank_bots` row, computes the factor for its
universe, produces a target basket (top decile long, optionally
bottom decile short), then rebalances `portfolio_rank_holdings` to
match. Rebalance is a diff: adds and removes only, no churn on
constant names.

Phase 2 (2026-07-05) adds:
  - Dry-run vs live-orders split. Two flags must both be true to
    place real broker orders:
        BMG_PORTFOLIO_RANK_BOTS_ENABLED  = master gate (also gates
                                           the manual endpoint)
        BMG_PORTFOLIO_RANK_LIVE_ORDERS   = live orders on
                                           (default false)
    In dry-run the runner sets actual_weight = target_weight and
    logs the basket. No Alpaca calls happen. This lets us watch a
    clean rebalance before flipping the second flag Monday morning.
  - Discord digest to the ops webhook (routes to #dev-updates)
    after every rebalance so Brock sees the basket without
    curling the endpoint.
  - Nightly runner that iterates all enabled bots and triggers
    rebalance for any whose schedule matches today.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


def _live_orders_enabled() -> bool:
    return _env_flag("BMG_PORTFOLIO_RANK_LIVE_ORDERS", "false")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_bot(db: Session, bot_id: int) -> Optional[dict]:
    row = db.execute(text("""
        SELECT id, name, description, factor_definition, universe,
               rebalance_schedule, long_decile, short_decile,
               position_sizing, starting_capital_cents, enabled,
               paper_citation, ssrn_id
        FROM portfolio_rank_bots WHERE id = :bid
    """), {"bid": bot_id}).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "name": row[1],
        "description": row[2],
        "factor_definition": json.loads(row[3] or "{}"),
        "universe": json.loads(row[4] or "{}"),
        "rebalance_schedule": row[5],
        "long_decile": int(row[6] or 10),
        "short_decile": int(row[7] or 0),
        "position_sizing": row[8],
        "starting_capital_cents": int(row[9] or 0),
        "enabled": bool(row[10]),
        "paper_citation": row[11],
        "ssrn_id": row[12],
    }


def _target_basket(
    ranking: dict[str, float],
    long_decile: int,
    short_decile: int,
    position_sizing: str,
) -> dict[str, dict[str, float]]:
    """Given a ranking, return {symbol: {"side": "long"|"short", "weight": w}}.

    Only equal_weight is implemented in Phase 1. value_weight requires
    market-cap data — added when the first real anomaly bot ships.
    """
    if not ranking:
        return {}
    n = len(ranking)
    long_n = max(1, math.ceil(n * long_decile / 100)) if long_decile > 0 else 0
    short_n = max(1, math.ceil(n * short_decile / 100)) if short_decile > 0 else 0

    sorted_desc = sorted(ranking.items(), key=lambda kv: -kv[1])
    long_syms = [s for s, _ in sorted_desc[:long_n]]
    short_syms = [s for s, _ in sorted_desc[-short_n:]] if short_n else []

    basket: dict[str, dict[str, float]] = {}
    if position_sizing != "equal_weight":
        logger.warning(
            "[portfolio-rank] sizing=%s not implemented; falling back to equal_weight",
            position_sizing,
        )
    if long_syms:
        w = round(1.0 / len(long_syms), 6)
        for s in long_syms:
            basket[s] = {"side": "long", "weight": w}
    if short_syms:
        w = round(-1.0 / len(short_syms), 6)
        for s in short_syms:
            basket[s] = {"side": "short", "weight": w}
    return basket


def _current_holdings(db: Session, bot_id: int) -> dict[str, dict[str, Any]]:
    rows = db.execute(text(
        "SELECT symbol, side, target_weight, actual_weight, entry_price_cents "
        "FROM portfolio_rank_holdings WHERE bot_id = :bid"
    ), {"bid": bot_id}).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r[0]] = {
            "side": r[1],
            "target_weight": float(r[2] or 0),
            "actual_weight": float(r[3] or 0),
            "entry_price_cents": int(r[4] or 0) if r[4] is not None else None,
        }
    return out


def _entry_price_cents(db: Session, symbol: str) -> Optional[int]:
    """Best-effort last close in cents. Returns None if unavailable.

    Phase 1 does not place real orders, so this cost basis is only for
    P&L attribution when Phase 2 wires the broker. Uses the canonical
    live-price cache when possible.
    """
    try:
        from app.core.canonical import _cached_live_prices
        prices = _cached_live_prices([symbol])
        px = prices.get(symbol)
        if px and px > 0:
            return int(round(float(px) * 100))
    except Exception:
        pass
    return None


# Alpaca fractional dollar-notional minimum. Rebalance names below this
# get skipped with [DROP:notional_below_minimum] rather than submitted
# to a guaranteed reject.
_ALPACA_MIN_NOTIONAL_USD = 1.00


def _submit_broker_orders_for_rebalance(
    bot: dict,
    adds: list[dict],
    removes: list[str],
) -> dict:
    """Phase 2 broker path — submit real Alpaca market DAY orders.

    Called from rebalance() when BMG_PORTFOLIO_RANK_LIVE_ORDERS=true AND
    there's a diff. Long-only (every PR bot has short_decile=0 as of
    2026-07-08). Skips crypto symbols since crypto adapter has a different
    order shape — logged for follow-up.

    Order sequence: REMOVES first (frees buying power), then ADDS.
    Sizing: dollar_target = starting_capital × abs(target_weight).
    Notional < $1 skipped (Alpaca fractional minimum).

    Returns {"orders_placed": [...], "orders_failed": [...],
             "orders_skipped": [...]} per-symbol result rows. Callers
    should merge order_ids into the adds dict for rebalance_log.
    """
    from strategy_lab.core.execution import get_broker

    results = {"orders_placed": [], "orders_failed": [], "orders_skipped": []}
    starting_dollars = int(bot.get("starting_capital_cents") or 0) / 100.0
    if starting_dollars <= 0:
        logger.warning(
            "[portfolio-rank] %s starting_capital=0 — skipping broker submission",
            bot["name"],
        )
        return results

    try:
        broker = get_broker("stock")
    except Exception as _bexc:
        logger.error(
            "[portfolio-rank] %s get_broker('stock') failed: %s",
            bot["name"], _bexc,
        )
        return results

    # ── 2026-07-14 · Per-name notional cap tied to REAL fund NAV ────────────
    # Prior sizing formula was starting_dollars * target_weight. When
    # starting_capital was $150K-ish (funded assuming $1M NAV) and basket
    # was 6 equal-weight names, each name got sized at $25K on a $97K
    # actual NAV — total gross ~$150K on $97K NAV consumed all buying
    # power and silenced the whole crypto+options fleet for 3 weeks.
    #
    # Cap: MAX_PCT_PER_NAME_OF_NAV (default 6%) × current Alpaca
    # portfolio_value. Ensures single-name exposure stays proportional to
    # what the fund actually has, not what the bot was funded assuming.
    _MAX_PCT_PER_NAME_OF_NAV = 0.06
    _fund_nav_dollars: float | None = None
    try:
        _acct = broker.get_account() or {}
        _pv_str = _acct.get("portfolio_value") or _acct.get("equity") or "0"
        _fund_nav_dollars = float(_pv_str)
        if _fund_nav_dollars <= 0:
            _fund_nav_dollars = None
    except Exception as _acct_exc:
        logger.warning(
            "[portfolio-rank] %s NAV cap disabled — get_account failed: %s",
            bot["name"], _acct_exc,
        )

    # Look up owned qty at broker once for the sell loop.
    owned_by_sym: dict[str, float] = {}
    try:
        for p in broker.get_positions():
            owned_by_sym[str(p.get("symbol") or "").upper()] = float(p.get("qty") or 0)
    except Exception as _pexc:
        logger.warning(
            "[portfolio-rank] %s get_positions failed (proceeding without qty lookup): %s",
            bot["name"], _pexc,
        )

    # ── SELLS (removes) — frees buying power for buys ──────────────────────
    for sym in removes:
        sym_u = sym.upper()
        if "/" in sym_u:
            results["orders_skipped"].append({
                "symbol": sym, "side": "sell",
                "reason": "crypto_route_not_wired",
            })
            logger.warning(
                "[portfolio-rank] %s SKIP sell %s — crypto broker path not wired",
                bot["name"], sym,
            )
            continue
        owned = owned_by_sym.get(sym_u, 0.0)
        if owned <= 0:
            results["orders_skipped"].append({
                "symbol": sym, "side": "sell",
                "reason": "no_position_at_broker",
            })
            continue
        try:
            resp = broker.submit_order(symbol=sym_u, qty=owned, side="sell")
            oid = (resp or {}).get("order_id")
            results["orders_placed"].append({
                "symbol": sym, "side": "sell", "qty": owned, "order_id": oid,
            })
            logger.warning(
                "[PR-ALPACA-FILL] %s SELL %s qty=%.6f → order_id=%s",
                bot["name"], sym_u, owned, oid,
            )
        except Exception as _sexc:
            results["orders_failed"].append({
                "symbol": sym, "side": "sell",
                "error": f"{type(_sexc).__name__}: {_sexc}",
            })
            logger.error(
                "[PR-ALPACA-REJECT] %s SELL %s qty=%.6f: %s",
                bot["name"], sym_u, owned, _sexc,
            )

    # ── BUYS (adds) ────────────────────────────────────────────────────────
    for add in adds:
        sym = str(add.get("symbol") or "").strip()
        if not sym:
            continue
        sym_u = sym.upper()
        if "/" in sym_u:
            results["orders_skipped"].append({
                "symbol": sym, "side": "buy",
                "reason": "crypto_route_not_wired",
            })
            logger.warning(
                "[portfolio-rank] %s SKIP buy %s — crypto broker path not wired",
                bot["name"], sym,
            )
            continue

        weight = abs(float(add.get("target_weight") or 0))
        dollar_target = starting_dollars * weight
        # Apply per-name cap if we have a live NAV read.
        if _fund_nav_dollars is not None:
            per_name_cap = _fund_nav_dollars * _MAX_PCT_PER_NAME_OF_NAV
            if dollar_target > per_name_cap:
                logger.warning(
                    "[portfolio-rank] %s %s notional capped $%.0f → $%.0f "
                    "(%.1f%% of $%.0f NAV)",
                    bot["name"], sym_u, dollar_target, per_name_cap,
                    _MAX_PCT_PER_NAME_OF_NAV * 100, _fund_nav_dollars,
                )
                dollar_target = per_name_cap
        if dollar_target < _ALPACA_MIN_NOTIONAL_USD:
            results["orders_skipped"].append({
                "symbol": sym, "side": "buy",
                "reason": f"notional_below_minimum ({dollar_target:.4f} < {_ALPACA_MIN_NOTIONAL_USD})",
            })
            continue

        entry_px_c = int(add.get("entry_price_cents") or 0)
        entry_px = entry_px_c / 100.0
        if entry_px <= 0:
            results["orders_skipped"].append({
                "symbol": sym, "side": "buy",
                "reason": "no_entry_price",
            })
            continue

        qty = round(dollar_target / entry_px, 6)
        if qty <= 0:
            results["orders_skipped"].append({
                "symbol": sym, "side": "buy",
                "reason": f"qty_rounded_to_zero (target=${dollar_target:.4f} px=${entry_px:.4f})",
            })
            continue

        try:
            resp = broker.submit_order(symbol=sym_u, qty=qty, side="buy")
            oid = (resp or {}).get("order_id")
            add["alpaca_order_id"] = oid  # merged into rebalance_log adds JSON
            results["orders_placed"].append({
                "symbol": sym, "side": "buy", "qty": qty, "order_id": oid,
                "notional_usd": dollar_target,
            })
            logger.warning(
                "[PR-ALPACA-FILL] %s BUY %s qty=%.6f notional=$%.2f → order_id=%s",
                bot["name"], sym_u, qty, dollar_target, oid,
            )
        except Exception as _bexc:
            results["orders_failed"].append({
                "symbol": sym, "side": "buy",
                "error": f"{type(_bexc).__name__}: {_bexc}",
            })
            logger.error(
                "[PR-ALPACA-REJECT] %s BUY %s qty=%.6f notional=$%.2f: %s",
                bot["name"], sym_u, qty, dollar_target, _bexc,
            )

    return results


def rebalance(
    db: Session,
    bot_id: int,
    triggered_by: str = "manual",
) -> dict[str, Any]:
    """Run one rebalance cycle for the named bot.

    Returns a dict with counts + a snippet of adds / removes. Never
    raises; errors are logged to portfolio_rank_rebalance_log.
    """
    t0 = time.monotonic()
    bot = _load_bot(db, bot_id)
    if not bot:
        return {"error": f"bot {bot_id} not found"}
    if not bot["enabled"]:
        return {"error": f"bot {bot['name']} disabled"}

    from strategy_lab.universes import get_universe
    from strategy_lab.factors import compute_factor

    error: Optional[str] = None
    ranking: dict[str, float] = {}
    basket: dict[str, dict[str, float]] = {}
    try:
        # Universe supports two JSON schemas:
        #   Phase 1 dummy:  {"type": "sp500_partial"} or {"type": "custom", "symbols": [...]}
        #   Phase 2 real:   {"kind": "alpaca_universe_by_ticker_list", "list_name": "sp500"}
        uni = bot["universe"]
        uni_type = str(uni.get("type", ""))
        uni_kind = str(uni.get("kind", ""))
        if uni_type == "custom":
            symbols = list(uni.get("symbols", []))
        elif uni_kind == "alpaca_universe_by_ticker_list":
            symbols = get_universe(str(uni.get("list_name", "")))
        elif uni_type:
            symbols = get_universe(uni_type)
        else:
            raise ValueError(f"universe schema unrecognized: {uni}")
        if not symbols:
            raise ValueError(f"empty universe: {uni}")

        # Factor supports two schemas too:
        #   Phase 1 dummy:  {"type": "alphabetical"}
        #   Phase 2 real:   {"kind": "return_lookback", "months_back": 12, ...}
        fdef = bot["factor_definition"]
        factor_type = str(fdef.get("kind") or fdef.get("type") or "")
        factor_params = {k: v for k, v in fdef.items() if k not in ("type", "kind")}
        ranking = compute_factor(factor_type, symbols, db, factor_params)
        basket = _target_basket(
            ranking, bot["long_decile"], bot["short_decile"],
            bot["position_sizing"],
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error("[portfolio-rank] %s rebalance failed: %s",
                     bot["name"], error, exc_info=True)

    adds: list[dict[str, Any]] = []
    removes: list[str] = []
    if error is None:
        current = _current_holdings(db, bot_id)
        target_syms = set(basket.keys())
        current_syms = set(current.keys())

        # Removes: in current but not in target.
        for sym in sorted(current_syms - target_syms):
            db.execute(text(
                "DELETE FROM portfolio_rank_holdings "
                "WHERE bot_id = :bid AND symbol = :sym"
            ), {"bid": bot_id, "sym": sym})
            removes.append(sym)

        # Upserts: in target. Insert new rows or update target_weight
        # for existing ones. Phase 1 sets actual_weight = target_weight
        # since we are not placing real orders.
        for sym, meta in basket.items():
            side = meta["side"]
            weight = float(meta["weight"])
            existing = current.get(sym)
            if existing:
                db.execute(text("""
                    UPDATE portfolio_rank_holdings
                    SET target_weight = :tw, actual_weight = :aw,
                        side = :side, last_marked_at = :ts
                    WHERE bot_id = :bid AND symbol = :sym
                """), {
                    "tw": weight, "aw": weight, "side": side,
                    "ts": _now_iso(), "bid": bot_id, "sym": sym,
                })
            else:
                px_c = _entry_price_cents(db, sym)
                db.execute(text("""
                    INSERT INTO portfolio_rank_holdings
                      (bot_id, symbol, target_weight, actual_weight,
                       side, entry_price_cents, current_price_cents,
                       entry_ts, last_marked_at, current_pnl_cents)
                    VALUES
                      (:bid, :sym, :tw, :aw, :side, :ec, :ec, :ts, :ts, 0)
                """), {
                    "bid": bot_id, "sym": sym, "tw": weight,
                    "aw": weight, "side": side, "ec": px_c,
                    "ts": _now_iso(),
                })
                adds.append({"symbol": sym, "side": side,
                             "target_weight": weight,
                             "entry_price_cents": px_c})

    latency_ms = int((time.monotonic() - t0) * 1000)
    db.execute(text("""
        INSERT INTO portfolio_rank_rebalance_log
          (bot_id, triggered_by, ranking_output, target_basket,
           adds, removes, latency_ms, error, created_at)
        VALUES
          (:bid, :tb, :ro, :tar, :ad, :rm, :lat, :err, :ts)
    """), {
        "bid": bot_id,
        "tb": triggered_by,
        "ro": json.dumps({k: round(v, 4) for k, v in
                          list(ranking.items())[:60]}),
        "tar": json.dumps(basket),
        "ad": json.dumps(adds),
        "rm": json.dumps(removes),
        "lat": latency_ms,
        "err": error,
        "ts": _now_iso(),
    })

    if error is None:
        db.execute(text("""
            UPDATE portfolio_rank_bots
            SET last_rebalanced_at = :ts
            WHERE id = :bid
        """), {"ts": _now_iso(), "bid": bot_id})

    db.commit()

    # Phase 2: live-orders path. When BMG_PORTFOLIO_RANK_LIVE_ORDERS is
    # true AND the basket differs from current holdings, submit real
    # Alpaca market DAY orders. Long-only (every PR bot has short_decile=0).
    # Result rows saved into rebalance_log via the adds/removes JSON.
    order_mode = "dry_run"
    broker_results: dict = {}
    if _live_orders_enabled() and error is None and (adds or removes):
        broker_results = _submit_broker_orders_for_rebalance(bot, adds, removes)
        placed = len(broker_results.get("orders_placed", []))
        failed = len(broker_results.get("orders_failed", []))
        skipped = len(broker_results.get("orders_skipped", []))
        if placed > 0:
            order_mode = "live"
        elif failed > 0 and placed == 0:
            order_mode = "live_all_rejected"
        elif skipped > 0 and placed == 0 and failed == 0:
            order_mode = "live_all_skipped"
        else:
            order_mode = "live"
        logger.warning(
            "[portfolio-rank] %s live orders: placed=%d failed=%d skipped=%d",
            bot["name"], placed, failed, skipped,
        )
        # Persist broker outcome into rebalance_log by rewriting the adds JSON.
        # We already inserted the log row above with the initial adds shape;
        # update in place so the alpaca_order_ids merged into `adds` items
        # by _submit_broker_orders_for_rebalance make it into the record.
        try:
            db.execute(text("""
                UPDATE portfolio_rank_rebalance_log
                SET adds = :ad,
                    ranking_output = :ro
                WHERE bot_id = :bid AND triggered_by = :tb
                  AND created_at = (SELECT MAX(created_at)
                                    FROM portfolio_rank_rebalance_log
                                    WHERE bot_id = :bid AND triggered_by = :tb)
            """), {
                "ad": json.dumps({"adds": adds, "broker_results": broker_results}),
                "ro": json.dumps({k: round(v, 4) for k, v in
                                  list(ranking.items())[:60]}),
                "bid": bot_id, "tb": triggered_by,
            })
            db.commit()
        except Exception as _lexc:
            logger.warning("[portfolio-rank] rebalance_log broker update failed: %s", _lexc)

    # Discord digest — routes via ops webhook to #dev-updates. Fire-and-
    # forget; a webhook 500 must not block the DB write we just committed.
    try:
        _post_rebalance_digest(bot, ranking, basket, adds, removes,
                               order_mode, latency_ms, error, triggered_by)
    except Exception as _dexc:
        logger.warning("[portfolio-rank] digest post failed: %s", _dexc)

    return {
        "bot_id": bot_id,
        "bot_name": bot["name"],
        "triggered_by": triggered_by,
        "universe_size": len(ranking),
        "target_basket_size": len(basket),
        "adds": len(adds),
        "removes": len(removes),
        "latency_ms": latency_ms,
        "order_mode": order_mode,
        "error": error,
    }


# ── Discord digest ────────────────────────────────────────────────────────────

def _post_rebalance_digest(
    bot: dict[str, Any],
    ranking: dict[str, float],
    basket: dict[str, dict[str, float]],
    adds: list[dict[str, Any]],
    removes: list[str],
    order_mode: str,
    latency_ms: int,
    error: Optional[str],
    triggered_by: str,
) -> None:
    """Post a compact rebalance summary to the ops Discord webhook."""
    from app.services.discord import send_ops_alert
    if error:
        send_ops_alert(
            title=f"Portfolio-Rank rebalance FAILED — {bot['name']}",
            message=f"Trigger: {triggered_by}\nError: {error}\n"
                    f"Universe attempt size: {len(ranking)}\n"
                    f"Latency: {latency_ms}ms",
            severity="critical",
            source="portfolio_rank_runner",
        )
        return
    add_syms = [a.get("symbol", "?") for a in adds]
    add_preview = ", ".join(add_syms[:15]) + (
        f" (+{len(add_syms) - 15} more)" if len(add_syms) > 15 else ""
    )
    remove_preview = ", ".join(removes[:15]) + (
        f" (+{len(removes) - 15} more)" if len(removes) > 15 else ""
    )
    citation = bot.get("paper_citation") or "no citation"
    ssrn = bot.get("ssrn_id")
    if ssrn:
        citation = f"{citation} — https://ssrn.com/abstract={ssrn}"
    fields = [
        {"name": "universe_size", "value": str(len(ranking)), "inline": True},
        {"name": "basket_size", "value": str(len(basket)), "inline": True},
        {"name": "adds", "value": str(len(adds)), "inline": True},
        {"name": "removes", "value": str(len(removes)), "inline": True},
        {"name": "mode", "value": order_mode, "inline": True},
        {"name": "latency_ms", "value": str(latency_ms), "inline": True},
    ]
    if add_syms:
        fields.append({"name": "adds detail", "value": add_preview[:1000]})
    if removes:
        fields.append({"name": "removes detail", "value": remove_preview[:1000]})
    fields.append({"name": "vault reference", "value": citation[:1000]})
    send_ops_alert(
        title=f"Portfolio-Rank rebalance — {bot['name']}",
        message=f"Trigger: {triggered_by}. Mode: **{order_mode}**. "
                f"No broker orders were placed.",
        severity="info",
        source="portfolio_rank_runner",
        fields=fields,
    )


# ── Nightly runner ────────────────────────────────────────────────────────────

def _is_rebalance_day(schedule: str, today: date) -> bool:
    """Return True if `today` matches this bot's rebalance cadence.

    - "monthly"    → first Monday of the month
    - "quarterly"  → first Monday of Jan / Apr / Jul / Oct
    - "weekly"     → every Monday
    - "daily"      → every day (used by dummy_alpha_rank for verification)
    """
    schedule = (schedule or "").strip().lower()
    if schedule == "daily":
        return True
    if today.weekday() != 0:  # Monday only for weekly / monthly / quarterly
        return schedule == ""
    if schedule == "weekly":
        return True
    if schedule == "monthly":
        return today.day <= 7  # first Monday of the month
    if schedule == "quarterly":
        return today.day <= 7 and today.month in (1, 4, 7, 10)
    return False


def nightly_run(db: Session, triggered_by: str = "cron") -> dict[str, Any]:
    """Iterate every enabled bot; rebalance those whose schedule matches today.

    Feature-flag gated on BMG_PORTFOLIO_RANK_BOTS_ENABLED. When off, returns
    a no-op result so a stray cron fire cannot side-effect.
    """
    if not _env_flag("BMG_PORTFOLIO_RANK_BOTS_ENABLED", "false"):
        return {"skipped": "BMG_PORTFOLIO_RANK_BOTS_ENABLED=false"}

    from datetime import date as _date
    today = _date.today()
    rows = db.execute(text(
        "SELECT id, name, rebalance_schedule FROM portfolio_rank_bots "
        "WHERE enabled = 1"
    )).fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        bot_id = int(r[0])
        name = r[1]
        schedule = r[2]
        if not _is_rebalance_day(schedule, today):
            results.append({"bot_id": bot_id, "name": name,
                            "skipped": f"not a {schedule} rebalance day"})
            continue
        try:
            res = rebalance(db, bot_id, triggered_by=triggered_by)
            results.append(res)
        except Exception as exc:
            logger.error("[portfolio-rank] nightly rebalance %s raised: %s",
                         name, exc, exc_info=True)
            results.append({"bot_id": bot_id, "name": name,
                            "error": f"{type(exc).__name__}: {exc}"})
    return {"triggered_by": triggered_by, "date": today.isoformat(),
            "count": len(results), "results": results}


# ── Scheduler wiring ──────────────────────────────────────────────────────────

def setup_portfolio_rank_scheduler(scheduler) -> None:
    """Register the nightly cron job. Called from main.py startup.

    Fires at 03:00 America/Chicago every day. Job body checks each bot's
    schedule and only runs those whose cadence matches today. Runs
    unconditionally (no env-flag gate at register time) so we do not have
    to redeploy when the master flag flips — the gate lives inside
    nightly_run().
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[portfolio-rank] apscheduler unavailable, cron not wired: %s", exc)
        return

    def _job() -> None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            res = nightly_run(db, triggered_by="cron_0300ct")
            logger.warning("[portfolio-rank] nightly_run result: %s", res)
        finally:
            db.close()

    # Fire 5 minutes AFTER US equity market open so market DAY orders
    # submitted by the broker path are accepted. Alpaca rejects market
    # orders received outside regular trading hours ("market is closed").
    # 09:35 America/New_York = post-open buffer, always right regardless
    # of DST. Rebalance days themselves are still gated inside nightly_run
    # via _is_rebalance_day (weekly=Mon, monthly=first Mon, etc).
    scheduler.add_job(
        _job,
        CronTrigger(hour=9, minute=35, timezone="America/New_York"),
        id="portfolio_rank_nightly",
        replace_existing=True,
    )
    logger.warning(
        "[portfolio-rank] rebalance cron registered: 09:35 America/New_York "
        "(post-market-open, so broker DAY orders accept)"
    )
