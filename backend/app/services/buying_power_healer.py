"""Auto-heal Alpaca paper account when buying_power hits zero.

Root cause pattern (2026-07-14): PR bots sized as if fund were $1M take
$23K/name positions on a $97K NAV. Six positions consume the whole account
plus margin. Alpaca then rejects every new BUY silently via
[DROP:no_broker_order_id] and the entire crypto + options fleet goes dark
for weeks before anyone notices.

The DURABLE fix — separate from surfacing the silent reject as a hold
signal — is to auto-trim the largest positions when buying_power falls
below a floor. This runs on a scheduled cron (every 15 minutes during
market hours) and:

  1. Reads /v2/account.buying_power from Alpaca.
  2. If < BUYING_POWER_FLOOR_USD ($10K default), identifies the 3 largest
     equity positions and market-sells enough of each to restore the floor.
  3. Posts a loud Discord alert so Brock knows what happened + why.

Env overrides:
  BUYING_POWER_FLOOR_USD   (default 10000)  trigger threshold
  BUYING_POWER_TARGET_USD  (default 25000)  what to trim back to
  BUYING_POWER_HEAL_ENABLED (default "true") kill switch — set "false" to disable

Safe by construction:
  - Only trims LONG equity positions (never touches options or shorts).
  - Never sells more than 60% of any single position in one cycle.
  - Silent no-op when buying_power is healthy.
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


def check_and_heal() -> dict:
    """Main entry point. Returns a diagnostic dict describing what happened."""
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

    if bp >= floor_usd:
        return {"ok": True, "buying_power": bp, "action": "no_trim_needed", "floor": floor_usd}

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
            if res.get("freed_usd", 0) > 0:
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
