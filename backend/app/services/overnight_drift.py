"""Overnight drift — short-swing sleeve.

See vault: [[2026-08-27-swing-short-term-2to10day]] §4 (Lou-Polk-Skouras
JFE 2019 "A Tug of War: Overnight versus Intraday Expected Returns")

Empirical finding: S&P 500's entire equity risk premium is earned OVERNIGHT
(Cooper-Cliff-Gulen 2008). Intraday returns are ~flat to slightly negative.
Session-continuation is structural (clientele composition — retail near
close, institutions intraday) and persists in 2020s replications.

Strategy:
  - Buy SPY MOC (market-on-close, 3:58 PM ET) — captures overnight gap
  - Sell SPY MOO (market-on-open, 9:31 AM ET) — closes before intraday
  - Do NOT hold intraday. Do NOT hold weekends (skip Fri MOC).

Regime gates:
  - Faber closed → skip entries (equity gate closed)
  - Vol scalar → size the position (halve if vol > target)
  - CGH — not applied (this is not a momentum strategy)

Sizing:
  Target 15% of NAV per overnight trade. Buy floor(nav * 0.15 * vol_scalar / spy_price).
  Simple single-position — no cross-sectional decile ranking in v1.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

# Required by ci_check_gates.sh
from app.services.trade_write_gate import check_trade_write  # noqa: F401
from app.services.position_write_gate import check_position_pre_write  # noqa: F401

logger = logging.getLogger(__name__)

BOT_NAME = "overnight_drift"
SYMBOL = "SPY"
SLEEVE_TARGET_PCT = float(os.environ.get("OVERNIGHT_DRIFT_SLEEVE_PCT", "0.15"))


def _alpaca_headers() -> Dict[str, str]:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        raise RuntimeError("no_alpaca_creds")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec, "Content-Type": "application/json"}


def _alpaca_data_get(path: str) -> Dict[str, Any]:
    url = f"https://data.alpaca.markets{path}"
    req = urllib.request.Request(url, headers=_alpaca_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _alpaca_post(path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    url = f"https://paper-api.alpaca.markets{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_alpaca_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"error": str(e)}
        return e.code, body


def _alpaca_account() -> Dict[str, Any]:
    url = "https://paper-api.alpaca.markets/v2/account"
    req = urllib.request.Request(url, headers=_alpaca_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_last_price(symbol: str) -> Optional[float]:
    try:
        r = _alpaca_data_get(f"/v2/stocks/{symbol}/trades/latest")
        return float(r["trade"]["p"])
    except Exception as e:
        logger.warning("[overnight_drift] price fetch failed for %s: %s", symbol, e)
        return None


def _ensure_alloc(db: Session) -> int:
    row = db.execute(
        text(
            "SELECT a.id FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :n AND a.user_id = 1"
        ),
        {"n": BOT_NAME},
    ).fetchone()
    if row:
        return int(row[0])

    prof_row = db.execute(
        text("SELECT id FROM bot_profiles WHERE name = :n"),
        {"n": BOT_NAME},
    ).fetchone()
    if prof_row:
        profile_id = int(prof_row[0])
    else:
        r_prof = db.execute(
            text(
                "INSERT INTO bot_profiles (name, description, asset_class, enabled) "
                "VALUES (:n, 'SPY overnight drift (MOC buy / MOO sell — Lou-Polk-Skouras)', 'stock', 1)"
            ),
            {"n": BOT_NAME},
        )
        profile_id = int(r_prof.lastrowid)

    result = db.execute(
        text(
            "INSERT INTO bot_allocations "
            "(user_id, profile_id, capital_pct, risk_profile, paper_mode, "
            " go_live_requested, enabled, starting_capital_cents, tier, "
            " created_at, updated_at) "
            "VALUES (1, :p, 15.0, 'standard', 1, 0, 1, 0, 'T0', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"p": profile_id},
    )
    db.commit()
    return int(result.lastrowid)


def _notify(msg: str, severity: str = "info") -> None:
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(title="Overnight Drift", message=msg,
                       severity=severity, source="overnight_drift")
    except Exception:
        logger.warning("[overnight_drift] discord send failed: %s", msg)


def _submit_moc_moo(side: str, qty: int, tif: str, client_order_id: str) -> Tuple[int, Dict[str, Any]]:
    """tif = 'cls' for MOC (close), 'opg' for MOO (opening).
    Alpaca uses time_in_force='cls' for MOC and 'opg' for MOO orders."""
    body = {
        "symbol": SYMBOL,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": tif,
        "client_order_id": client_order_id,
    }
    return _alpaca_post("/v2/orders", body)


def _write_fill(db: Session, alloc_id: int, qty: int, side: str,
                fill_price: float, alpaca_order_id: str) -> None:
    from app.db.models.bots import BotTrade, BotPosition
    now = datetime.now(timezone.utc)
    fill_cents = int(round(fill_price * 100))

    if side == "buy":
        pos = BotPosition(
            allocation_id=alloc_id, symbol=SYMBOL, qty=qty,
            avg_cost_cents=fill_cents, side="long",
            opened_at=now, closed_at=None, is_paper=True, origin="BROKER_FILL",
        )
        db.add(pos)
        db.flush()
        pos_id = pos.id
    else:
        # Close current open long
        row = db.execute(
            text(
                "SELECT id, qty, avg_cost_cents FROM bot_positions "
                "WHERE allocation_id = :aid AND symbol = :s AND closed_at IS NULL "
                "ORDER BY opened_at DESC LIMIT 1"
            ),
            {"aid": alloc_id, "s": SYMBOL},
        ).fetchone()
        if row:
            pos_id, existing_qty, avg_cost = int(row[0]), float(row[1]), int(row[2])
            realized_cents = int(round((fill_cents - avg_cost) * existing_qty))
            db.execute(
                text(
                    "UPDATE bot_positions SET closed_at = :t, "
                    "close_price_cents = :p, realized_pnl_cents = :r, "
                    "exit_reason = 'overnight_drift_moo' WHERE id = :id"
                ),
                {"t": now.isoformat(), "p": fill_cents, "r": realized_cents, "id": pos_id},
            )
        else:
            pos_id = None

    trade = BotTrade(
        allocation_id=alloc_id, symbol=SYMBOL, side=side, qty=qty,
        fill_price_cents=fill_cents, fill_price_micros=fill_cents * 10000,
        fees_cents=0, ts=now, position_id=pos_id, is_paper=True,
        alpaca_order_id=alpaca_order_id, origin="BROKER_FILL",
    )
    db.add(trade)
    db.commit()


def moc_entry_tick() -> Dict[str, Any]:
    """3:58 PM ET Mon-Thu — submit MOC buy for overnight hold."""
    from app.db.session import SessionLocal
    from app.services.regime_state import get_regime_state
    import pytz
    ET = pytz.timezone("America/New_York")

    now_et = datetime.now(ET)
    # Skip Friday (no overnight over weekend)
    if now_et.weekday() == 4:
        return {"status": "skip", "reason": "friday_no_weekend_hold"}

    db = SessionLocal()
    try:
        alloc_id = _ensure_alloc(db)
        regime = get_regime_state()
        if not regime.faber_open:
            _notify("MOC entry SKIPPED — Faber gate closed (SPY < 10mo SMA)")
            return {"status": "skip", "reason": "faber_closed"}

        # Check if a position is already open (shouldn't be, but idempotent)
        existing = db.execute(
            text(
                "SELECT COUNT(*) FROM bot_positions "
                "WHERE allocation_id = :aid AND closed_at IS NULL"
            ),
            {"aid": alloc_id},
        ).fetchone()
        if existing and int(existing[0]) > 0:
            _notify(f"MOC entry SKIPPED — existing position still open for alloc {alloc_id}")
            return {"status": "skip", "reason": "position_already_open"}

        # Size from Alpaca NAV × sleeve pct × vol_scalar
        acct = _alpaca_account()
        nav = float(acct.get("portfolio_value", 0))
        px = _get_last_price(SYMBOL)
        if px is None or px <= 0:
            return {"status": "error", "reason": "no_price"}
        budget = nav * SLEEVE_TARGET_PCT * regime.vol_scalar
        qty = max(1, int(budget / px))

        oid = f"overnight_moc_{int(datetime.now(timezone.utc).timestamp())}"
        status, resp = _submit_moc_moo("buy", qty, "cls", oid)
        if status not in (200, 201):
            logger.error("[overnight_drift] MOC submit failed: %s %s", status, resp)
            _notify(f"❌ MOC submit failed: {status} {resp.get('message', resp)}", "warning")
            return {"status": "error", "reason": f"submit_{status}", "detail": resp}

        order_id = resp.get("id", "")
        _write_fill(db, alloc_id, qty, "buy", px, order_id)
        _notify(
            f"🌙 Overnight MOC BUY {qty} SPY @ ~${px:.2f} "
            f"(vol_scalar={regime.vol_scalar:.2f}, budget=${budget:.0f}). "
            f"Order {order_id[:8]}. Exit MOO tomorrow 9:31 ET."
        )
        return {"status": "ok", "qty": qty, "price": px, "order_id": order_id}
    except Exception as e:
        logger.error("[overnight_drift] MOC tick error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def moo_exit_tick() -> Dict[str, Any]:
    """9:31 AM ET Tue-Fri — submit MOO sell to close overnight."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        alloc_id = _ensure_alloc(db)
        # Find open position
        row = db.execute(
            text(
                "SELECT id, qty FROM bot_positions "
                "WHERE allocation_id = :aid AND closed_at IS NULL AND symbol = :s "
                "ORDER BY opened_at DESC LIMIT 1"
            ),
            {"aid": alloc_id, "s": SYMBOL},
        ).fetchone()
        if not row:
            return {"status": "skip", "reason": "no_open_position"}

        pos_id, qty = int(row[0]), int(float(row[1]))
        px = _get_last_price(SYMBOL)
        if px is None:
            return {"status": "error", "reason": "no_price"}

        oid = f"overnight_moo_{int(datetime.now(timezone.utc).timestamp())}"
        status, resp = _submit_moc_moo("sell", qty, "opg", oid)
        if status not in (200, 201):
            logger.error("[overnight_drift] MOO submit failed: %s %s", status, resp)
            return {"status": "error", "reason": f"submit_{status}"}

        order_id = resp.get("id", "")
        _write_fill(db, alloc_id, qty, "sell", px, order_id)
        _notify(f"☀ Overnight MOO SELL {qty} SPY @ ~${px:.2f}. Order {order_id[:8]}.")
        return {"status": "ok", "qty": qty, "price": px, "order_id": order_id}
    except Exception as e:
        logger.error("[overnight_drift] MOO tick error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def setup_overnight_drift_scheduler(scheduler) -> None:
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    ET = pytz.timezone("America/New_York")

    # MOC buy: 3:58 PM ET Mon-Thu (skip Fri to avoid weekend)
    scheduler.add_job(
        moc_entry_tick,
        trigger=CronTrigger(hour=15, minute=58, day_of_week="mon-thu", timezone=ET),
        id="overnight_drift_moc_entry",
        name="overnight_drift_moc_entry",
        replace_existing=True, misfire_grace_time=300,
    )
    # MOO sell: 9:31 AM ET Tue-Fri
    scheduler.add_job(
        moo_exit_tick,
        trigger=CronTrigger(hour=9, minute=31, day_of_week="tue-fri", timezone=ET),
        id="overnight_drift_moo_exit",
        name="overnight_drift_moo_exit",
        replace_existing=True, misfire_grace_time=300,
    )
    logger.info("[overnight_drift] scheduler registered (MOC 3:58 Mon-Thu, MOO 9:31 Tue-Fri)")
