"""Auto-heal Alpaca paper account when buying_power hits zero.

Root cause pattern (2026-07-14): PR bots sized as if fund were $1M take
$23K/name positions on a $97K NAV. Six positions consume the whole account
plus margin. Alpaca then rejects every new BUY silently via
[DROP:no_broker_order_id] and the entire crypto + options fleet goes dark
for weeks before anyone notices.

Two healers run together every 15 min during market hours:

  1. Equity BP healer — reads buying_power; if < BUYING_POWER_FLOOR_USD,
     market-sells up to 60% of the 3 largest LONG equity positions to
     restore BUYING_POWER_TARGET_USD.

  2. Options BP healer (2026-07-15) — reads options_buying_power; if <
     OPTIONS_BP_FLOOR_USD, sells-to-close the biggest bleeder LONG
     options positions (never touches short legs — closing one leg of a
     spread would leave the partner naked). Ordered by most-negative
     unrealized_pl so the healer sheds losers first, not winners.

Env overrides:
  BUYING_POWER_FLOOR_USD    (10000)  equity trigger
  BUYING_POWER_TARGET_USD   (25000)  equity restore target
  OPTIONS_BP_FLOOR_USD      (2000)   options trigger
  OPTIONS_BP_TARGET_USD     (5000)   options restore target
  BUYING_POWER_HEAL_ENABLED (true)   kill switch

Safe by construction:
  - Never touches SHORT options (spread partner naked risk).
  - Never touches equity SHORTS (currently there are none).
  - Silent no-op when both BPs are healthy.
  - All actions logged + Discord-alerted so nothing happens invisibly.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger(__name__)


def _get_creds() -> tuple[str, str] | None:
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not sec:
        return None
    return key, sec


def _alpaca_get(path: str) -> Any:
    creds = _get_creds()
    if creds is None:
        return None
    key, sec = creds
    req = urllib.request.Request(
        f"https://paper-api.alpaca.markets{path}",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _alpaca_post(path: str, body: dict) -> tuple[int, dict]:
    creds = _get_creds()
    if creds is None:
        return 0, {"error": "no_creds"}
    key, sec = creds
    req = urllib.request.Request(
        f"https://paper-api.alpaca.markets{path}",
        data=json.dumps(body).encode(),
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": sec,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


def _heal_options_bp(acct: dict) -> dict:
    """Sell-to-close biggest bleeder long options until options_bp restored.

    Only touches LONG options. Skips short legs (short_put/short_call) — closing
    one leg of a defined-risk spread would leave the hedge naked and require
    massive collateral. If the caller needs to close a short-leg position, do
    it as a coordinated pair (out of scope here).

    Returns a diagnostic dict.
    """
    floor  = float(os.getenv("OPTIONS_BP_FLOOR_USD",  "2000"))
    target = float(os.getenv("OPTIONS_BP_TARGET_USD", "5000"))
    opts_bp = float(acct.get("options_buying_power") or 0)

    if opts_bp >= floor:
        return {"ok": True, "options_bp": opts_bp, "action": "no_options_trim_needed", "floor": floor}

    logger.warning(
        "[bp-heal-options] options_bp=%.2f below floor=%.2f — closing bleeders",
        opts_bp, floor,
    )

    try:
        positions = _alpaca_get("/v2/positions") or []
    except Exception as exc:
        return {"error": f"positions_fetch_failed: {exc}"}

    # Only LONG options. Sort by most-negative unrealized_pl first (shed losers).
    trimable = [
        p for p in positions
        if p.get("asset_class") == "us_option"
        and p.get("side") == "long"
        and float(p.get("qty") or 0) > 0
    ]
    trimable.sort(key=lambda p: float(p.get("unrealized_pl") or 0))
    if not trimable:
        return {"ok": False, "reason": "no_long_options_to_trim", "options_bp": opts_bp}

    to_free = max(0.0, target - opts_bp)
    closes: list[dict] = []
    freed = 0.0

    # Close up to 3 bleeders in one cycle; each close frees roughly
    # (contracts × current_mid × 100) of options_bp. Order: worst pnl first.
    for p in trimable[:3]:
        if freed >= to_free:
            break
        symbol = p["symbol"]
        qty = int(float(p["qty"]))
        mv = float(p.get("market_value") or 0)
        upl = float(p.get("unrealized_pl") or 0)
        if qty <= 0:
            continue

        status, resp = _alpaca_post("/v2/orders", {
            "symbol": symbol,
            "qty": str(qty),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
        })
        closes.append({
            "symbol": symbol,
            "close_qty": qty,
            "market_value": round(mv, 2),
            "unrealized_pl": round(upl, 2),
            "status": status,
            "order_id": resp.get("id") if isinstance(resp, dict) else None,
            "error": resp.get("error") if isinstance(resp, dict) else None,
        })
        if status in (200, 201):
            freed += mv  # rough approximation — actual fill may differ

    # Mark corresponding BotPosition rows closed so DB stays consistent
    # (the reconciler would eventually catch this, but we can save a cycle).
    try:
        from app.db.session import SessionLocal
        from app.db.models.bots import BotPosition, BotAllocation
        from strategy_lab.core.position_monitor import _close_position
        from datetime import datetime, timezone
        db = SessionLocal()
        try:
            for c in closes:
                if c["status"] not in (200, 201): continue
                pos = (
                    db.query(BotPosition)
                    .filter(BotPosition.symbol == c["symbol"])
                    .filter(BotPosition.closed_at.is_(None))
                    .first()
                )
                if pos:
                    alloc = db.query(BotAllocation).filter(BotAllocation.id == pos.allocation_id).first()
                    if alloc:
                        try:
                            # rough exit price from market_value / qty (in dollars per contract)
                            exit_price = abs(c["market_value"]) / max(1, c["close_qty"]) / 100.0
                            _close_position(db, pos, alloc, exit_price, "healer_bleeder_cull", datetime.now(timezone.utc))
                        except Exception as _cp_exc:
                            logger.warning("[bp-heal-options] _close_position raised for %s: %s", c["symbol"], _cp_exc)
        finally:
            db.close()
    except Exception as _db_exc:
        logger.warning("[bp-heal-options] DB reconcile skipped: %s", _db_exc)

    # Discord alert
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[bp-heal-options] options_bp exhausted — closed bleeders",
            message=(
                f"options_buying_power was ${opts_bp:,.0f} (floor ${floor:,.0f}). "
                f"Closed {len(closes)} long-option bleeder{'s' if len(closes) != 1 else ''} "
                f"(~${freed:,.0f} freed). Never touches short legs — spread hedge would go naked."
            ),
            severity="warn",
            source="buying_power_healer.options",
            fields=[
                {"name": c["symbol"], "value": f"close {c['close_qty']} (mv=${c['market_value']:.0f} upnl=${c['unrealized_pl']:+.0f}) status={c['status']}"}
                for c in closes[:5]
            ],
        )
    except Exception as _dc_exc:
        logger.warning("[bp-heal-options] discord alert failed: %s", _dc_exc)

    return {
        "ok": True,
        "options_bp_before": opts_bp,
        "target": target,
        "freed_usd_approx": round(freed, 2),
        "closes": closes,
    }


def check_and_heal() -> dict:
    """Main entry point. Runs both equity and options healers. Returns combined
    diagnostic dict."""
    enabled = os.getenv("BUYING_POWER_HEAL_ENABLED", "true").strip().lower() == "true"
    if not enabled:
        return {"skipped": "disabled_by_env"}

    floor_usd = float(os.getenv("BUYING_POWER_FLOOR_USD", "10000"))
    target_usd = float(os.getenv("BUYING_POWER_TARGET_USD", "25000"))
    max_trim_pct = 0.60

    try:
        acct = _alpaca_get("/v2/account")
    except Exception as exc:
        logger.warning("[bp-heal] account fetch failed: %s", exc)
        return {"error": f"account_fetch_failed: {exc}"}

    if acct is None:
        return {"skipped": "no_creds"}

    bp = float(acct.get("buying_power") or 0)
    cash = float(acct.get("cash") or 0)
    pv = float(acct.get("portfolio_value") or 0)

    # Options BP healer runs unconditionally (independent from equity BP).
    options_result = None
    try:
        options_result = _heal_options_bp(acct)
    except Exception as _oh_exc:
        logger.warning("[bp-heal-options] raised: %s", _oh_exc, exc_info=True)
        options_result = {"error": str(_oh_exc)[:200]}

    if bp >= floor_usd:
        return {
            "ok": True,
            "buying_power": bp,
            "action": "no_equity_trim_needed",
            "floor": floor_usd,
            "options_healer": options_result,
        }

    logger.warning(
        "[bp-heal] buying_power=%.2f below floor=%.2f (cash=%.2f, pv=%.2f) — trimming",
        bp, floor_usd, cash, pv,
    )

    try:
        positions = _alpaca_get("/v2/positions") or []
    except Exception as exc:
        logger.warning("[bp-heal] positions fetch failed: %s", exc)
        return {"error": f"positions_fetch_failed: {exc}"}

    # Only long equity positions, sorted by market value desc
    trimable = [
        p for p in positions
        if p.get("asset_class") == "us_equity"
        and p.get("side") == "long"
        and float(p.get("market_value") or 0) > 500
    ]
    trimable.sort(key=lambda p: -float(p.get("market_value") or 0))
    if not trimable:
        return {"ok": False, "reason": "no_trimable_positions", "buying_power": bp}

    to_free = max(0.0, target_usd - bp)
    trims: list[dict] = []
    freed = 0.0

    # Trim up to 3 largest positions until we've freed enough
    for p in trimable[:3]:
        if freed >= to_free:
            break
        symbol = p["symbol"]
        qty = float(p["qty"])
        mv = float(p["market_value"])
        remaining_to_free = to_free - freed
        trim_dollars = min(mv * max_trim_pct, remaining_to_free)
        # convert to qty using current price (avg_entry_price is entry, not current)
        px = float(p.get("current_price") or 0)
        if px <= 0:
            continue
        trim_qty = round(trim_dollars / px, 4)
        if trim_qty <= 0:
            continue

        status, resp = _alpaca_post("/v2/orders", {
            "symbol": symbol,
            "qty": str(trim_qty),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
        })
        trims.append({
            "symbol": symbol,
            "trim_qty": trim_qty,
            "trim_dollars": round(trim_qty * px, 2),
            "status": status,
            "order_id": resp.get("id") if isinstance(resp, dict) else None,
            "error": resp.get("error") if isinstance(resp, dict) else None,
        })
        if status in (200, 201):
            freed += trim_qty * px

    # Discord alert
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[bp-heal] Alpaca buying_power exhausted — auto-trimmed positions",
            message=(
                f"buying_power was ${bp:,.0f} (floor ${floor_usd:,.0f}). "
                f"Freed ${freed:,.0f} across {len(trims)} positions to prevent silent "
                f"execution stall. This is the same failure mode that hid crypto+options "
                f"outages for 3 weeks in July 2026."
            ),
            severity="warn",
            source="buying_power_healer",
            fields=[
                {"name": t["symbol"], "value": f"trim {t['trim_qty']} (~${t['trim_dollars']:.0f}) status={t['status']}"}
                for t in trims[:5]
            ],
        )
    except Exception as _dc_exc:
        logger.warning("[bp-heal] discord alert failed: %s", _dc_exc)

    return {
        "ok": True,
        "buying_power_before": bp,
        "cash": cash,
        "portfolio_value": pv,
        "target": target_usd,
        "freed_usd": round(freed, 2),
        "trims": trims,
        "options_healer": options_result,
    }


def setup_buying_power_healer(scheduler) -> None:
    """Register the healer to run every 15 minutes during market hours (Mon-Fri
    9:35-15:55 ET) so it can react before the fleet stalls for more than one
    scan cycle."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[bp-heal] apscheduler unavailable: %s", exc)
        return

    def _job() -> None:
        try:
            res = check_and_heal()
            _eq_freed = res.get("freed_usd", 0) or 0
            _opt_res = res.get("options_healer") or {}
            _opt_freed = (_opt_res.get("freed_usd_approx", 0) if isinstance(_opt_res, dict) else 0) or 0
            if _eq_freed > 0 or _opt_freed > 0:
                logger.warning("[bp-heal] cycle: %s", res)
        except Exception as exc:
            logger.error("[bp-heal] job raised: %s", exc, exc_info=True)

    scheduler.add_job(
        _job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="13-19",
            minute="*/15",
            timezone="UTC",
        ),
        id="buying_power_healer",
        replace_existing=True,
        max_instances=1,
    )
    logger.warning("[bp-heal] scheduler registered — every 15 min during US market hours")
