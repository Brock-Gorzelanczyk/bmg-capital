"""One-shot IWM 240C ×2 trim scheduled for 2026-08-11 09:31 ET.

Brock pre-authorized 2026-08-10 overnight: sell 2× IWM260828C00240000,
LIMIT at mid, day. If unfilled +15 min after open, reprice toward bid
one tick at a time, floor at bid. Log as admin remediation.

Runs regardless of scans resume state — reduces risk either way.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_ALPACA_BASE = "https://paper-api.alpaca.markets"
_DATA_BASE = "https://data.alpaca.markets"
_SYMBOL = "IWM260828C00240000"
_QTY = 2
_REASON = "iwm_240c_trim_sunday_approved_scheduled_2026_08_11"


def _creds() -> dict:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec}


def _get_nbbo() -> tuple[float, float]:
    """Return (bid, ask). Returns (0, 0) on failure."""
    try:
        snap = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"{_DATA_BASE}/v1beta1/options/snapshots?symbols={_SYMBOL}",
            headers=_creds(),
        ), timeout=10).read())
        q = snap.get("snapshots", {}).get(_SYMBOL, {}).get("latestQuote", {})
        return float(q.get("bp") or 0), float(q.get("ap") or 0)
    except Exception as exc:
        logger.error("[iwm-trim] NBBO fetch failed: %s", exc)
        return 0.0, 0.0


def _submit_limit(limit_price: float) -> dict:
    payload = json.dumps({
        "symbol": _SYMBOL,
        "qty": str(_QTY),
        "side": "sell",
        "type": "limit",
        "limit_price": str(round(limit_price, 2)),
        "time_in_force": "day",
        "position_intent": "sell_to_close",
    }).encode()
    req = urllib.request.Request(
        f"{_ALPACA_BASE}/v2/orders",
        data=payload,
        headers={**_creds(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as httpe:
        return {"error": "http", "status": httpe.code, "body": httpe.read().decode("utf-8", errors="replace")[:500]}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _get_order(order_id: str) -> dict:
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(
            f"{_ALPACA_BASE}/v2/orders/{order_id}",
            headers=_creds(),
        ), timeout=10).read())
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _cancel_order(order_id: str) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{_ALPACA_BASE}/v2/orders/{order_id}",
            headers=_creds(), method="DELETE",
        ), timeout=10)
        return True
    except Exception as exc:
        logger.warning("[iwm-trim] cancel %s failed: %s", order_id, exc)
        return False


def _log_bmg_trade(alpaca_order_id: str, limit_price: float, note: str) -> None:
    """Log to BMG with origin=BACKFILL (admin remediation, not bot-attributed)."""
    try:
        from app.db.session import SessionLocal
        from app.db.models.bots import BotPosition, BotTrade
        _db = SessionLocal()
        try:
            pos = (
                _db.query(BotPosition)
                .filter(BotPosition.symbol == _SYMBOL)
                .filter(BotPosition.closed_at.is_(None))
                .filter(BotPosition.quarantined_at.is_(None))
                .order_by(BotPosition.opened_at.desc())
                .first()
            )
            if not pos:
                logger.error("[iwm-trim] no open BMG position for %s — trade not logged", _SYMBOL)
                return
            row = BotTrade(
                allocation_id=pos.allocation_id,
                symbol=_SYMBOL,
                side="sell",
                qty=_QTY,
                fill_price_cents=int(round(limit_price * 100)),
                fees_cents=0,
                ts=datetime.now(timezone.utc),
                position_id=pos.id,
                is_paper=True,
                alpaca_order_id=alpaca_order_id,
                origin="BACKFILL",
                strategy=f"admin_remediation:{_REASON}:{note}",
            )
            _db.add(row)
            _db.commit()
            logger.warning("[iwm-trim] BMG trade logged id=%s", row.id)
        finally:
            _db.close()
    except Exception as exc:
        logger.error("[iwm-trim] BMG log failed: %s", exc)


def _alert(title: str, message: str) -> None:
    try:
        from app.services.critical_alert import send_critical
        send_critical(category="MANUAL_TEST", title=title, message=message,
                      source="jobs.iwm_trim_2026_08_11")
    except Exception as exc:
        logger.warning("[iwm-trim] alert failed: %s", exc)


def run_trim() -> dict:
    """Orchestrator: submit at mid → poll → reprice toward bid every 5 min
    after +15 min unfilled → floor at bid → alert on outcome.

    Runs synchronously in whichever thread APScheduler assigns. Total
    max runtime ~30 min bounded by MAX_REPRICES loop below.
    """
    logger.warning("[iwm-trim] START (Brock pre-authorized 2026-08-10)")
    submit_ts = datetime.now(timezone.utc)

    bid, ask = _get_nbbo()
    if bid <= 0 or ask <= 0:
        _alert("IWM trim ABORT — no NBBO", f"bid={bid} ask={ask}")
        return {"error": "no_nbbo", "bid": bid, "ask": ask}
    mid_raw = (bid + ask) / 2
    initial_mid = round(mid_raw + 0.005, 2)  # round to nearest cent (bias up on sell)
    logger.warning("[iwm-trim] initial NBBO bid=%s ask=%s mid=%s", bid, ask, initial_mid)

    order = _submit_limit(initial_mid)
    if order.get("error"):
        _alert("IWM trim SUBMIT FAILED", f"initial submit @ ${initial_mid}: {order}")
        return {"error": "submit_failed", "detail": order}
    order_id = order.get("id")
    if not order_id:
        _alert("IWM trim SUBMIT FAILED — no order_id", f"response: {order}")
        return {"error": "no_order_id", "response": order}
    logger.warning("[iwm-trim] submitted %s @ $%s", order_id, initial_mid)
    _log_bmg_trade(order_id, initial_mid, "initial_submit_at_mid")
    _alert(f"IWM trim submitted @ $%s" % initial_mid,
           f"order_id={order_id} qty={_QTY} limit=${initial_mid} bid=${bid} ask=${ask}")

    # Wait 15 min, then reprice one tick every 5 min until filled or floor
    TICK = 0.01
    POLL_INTERVAL = 60  # 1 min polls
    WAIT_BEFORE_REPRICE = 15 * 60
    REPRICE_INTERVAL = 5 * 60
    MAX_REPRICES = 20  # safety cap

    def _poll_until_filled_or(timeout_seconds: int, current_order_id: str) -> tuple[str, dict]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            info = _get_order(current_order_id)
            status = info.get("status")
            if status == "filled":
                return "filled", info
            if status in ("canceled", "expired", "rejected"):
                return status, info
            time.sleep(POLL_INTERVAL)
        return "still_unfilled", _get_order(current_order_id)

    outcome, info = _poll_until_filled_or(WAIT_BEFORE_REPRICE, order_id)
    if outcome == "filled":
        fill_price = float(info.get("filled_avg_price") or 0)
        savings = round((fill_price - bid) * _QTY * 100, 2)  # vs. worst-case bid
        _alert("IWM trim FILLED at initial mid",
               f"order={order_id} filled @ ${fill_price} (initial mid ${initial_mid}, savings vs bid=${savings})")
        return {"ok": True, "outcome": "filled_initial", "fill_price": fill_price,
                "initial_mid": initial_mid, "bid_at_submit": bid, "savings_vs_bid_usd": savings}

    current_limit = initial_mid
    current_id = order_id
    for reprice_i in range(1, MAX_REPRICES + 1):
        # Fetch fresh bid to compute floor
        fresh_bid, fresh_ask = _get_nbbo()
        if fresh_bid <= 0:
            _alert("IWM trim ABORT — lost NBBO during reprice", f"after {reprice_i-1} reprices")
            return {"error": "lost_nbbo_during_reprice", "last_limit": current_limit,
                    "reprices_done": reprice_i - 1}
        new_limit = round(current_limit - TICK, 2)
        floored = False
        if new_limit < fresh_bid:
            new_limit = fresh_bid
            floored = True
        # Cancel + resubmit
        if not _cancel_order(current_id):
            info = _get_order(current_id)
            if info.get("status") == "filled":
                fill_price = float(info.get("filled_avg_price") or 0)
                _alert("IWM trim FILLED during cancel", f"filled @ ${fill_price}")
                return {"ok": True, "outcome": "filled_during_cancel", "fill_price": fill_price}
        new_order = _submit_limit(new_limit)
        if new_order.get("error"):
            _alert("IWM trim RESUBMIT FAILED",
                   f"prev order {current_id} cancelled, resubmit @ ${new_limit} failed: {new_order}")
            return {"error": "resubmit_failed", "cancelled_order": current_id,
                    "reprices_done": reprice_i - 1}
        current_id = new_order.get("id")
        current_limit = new_limit
        logger.warning("[iwm-trim] reprice #%d @ $%s (bid $%s, floored=%s) → new order %s",
                       reprice_i, current_limit, fresh_bid, floored, current_id)
        _log_bmg_trade(current_id, current_limit, f"reprice_{reprice_i}_at_${current_limit}")
        outcome, info = _poll_until_filled_or(REPRICE_INTERVAL, current_id)
        if outcome == "filled":
            fill_price = float(info.get("filled_avg_price") or 0)
            _alert(f"IWM trim FILLED after {reprice_i} reprice(s)",
                   f"filled @ ${fill_price} (initial mid ${initial_mid}, final limit ${current_limit})")
            return {"ok": True, "outcome": f"filled_after_reprice_{reprice_i}",
                    "fill_price": fill_price, "initial_mid": initial_mid,
                    "reprices_done": reprice_i, "floored_at_bid": floored}
        if outcome in ("canceled", "expired", "rejected"):
            _alert(f"IWM trim {outcome.upper()}", f"order {current_id} status={outcome}")
            return {"error": outcome, "order_id": current_id, "reprices_done": reprice_i}
        if floored:
            # At bid and still unfilled — one more cycle then abort
            _alert(f"IWM trim STUCK AT BID after {reprice_i} reprices",
                   f"limit is bid (${fresh_bid}) but still unfilled — human decides")
            return {"error": "stuck_at_bid", "reprices_done": reprice_i,
                    "current_limit": current_limit, "bid": fresh_bid, "order_id": current_id}

    _alert(f"IWM trim UNFILLED after {MAX_REPRICES} reprices — MAX cap hit",
           f"final limit ${current_limit}, order {current_id}")
    return {"error": "max_reprices_hit", "reprices_done": MAX_REPRICES,
            "current_limit": current_limit, "order_id": current_id}


def register_iwm_trim_job(scheduler) -> None:
    """Register the one-shot trim for 2026-08-11 09:31 ET (13:31 UTC)."""
    try:
        from apscheduler.triggers.date import DateTrigger
        from datetime import datetime as _dt, timezone as _tz
        fire_at = _dt(2026, 8, 11, 13, 31, 0, tzinfo=_tz.utc)
        if fire_at < _dt.now(_tz.utc):
            logger.warning("[iwm-trim] scheduled fire time %s is in the past — skipping registration", fire_at)
            return
        scheduler.add_job(
            run_trim,
            DateTrigger(run_date=fire_at),
            id="iwm_trim_2026_08_11_0931et",
            replace_existing=True,
            misfire_grace_time=300,  # 5 min grace if scheduler is late
        )
        logger.warning("[iwm-trim] scheduled ONE-SHOT for %s (13:31 UTC / 9:31 ET)", fire_at.isoformat())
    except Exception as exc:
        logger.error("[iwm-trim] registration failed: %s", exc, exc_info=True)
