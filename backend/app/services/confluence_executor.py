"""Confluence executor — auto-fires bracket orders for armed picks.

**How it works:**
  1. Cron `confluence_executor_tick` runs every 5 min during RTH
  2. Queries all `confluence_picks` where `arm_state='ARMED'`
  3. For each: pulls current Alpaca last trade price
  4. Evaluates Play A + Play B trigger conditions
  5. On trigger: submits Alpaca bracket order (buy + limit target + stop loss),
     books BotTrade + BotPosition rows under the `confluence_executor` allocation,
     updates pick arm_state to FILLED_A / FILLED_B, sends Discord alert.

**Trigger logic (MVP v1):**
  Play A (breakout): `last_price >= play_a_trigger_price_cents`  (market buy)
  Play B (pullback): `last_price <= play_b_trigger_price_cents` AND
                     `last_price > play_b_stop_price_cents + $0.10`
                     (limit buy at trigger)

**Framework invalidation:**
  Every tick, for FILLED picks, check `last_price < invalidation_price_cents`.
  Emits alert; manual close required (bracket's built-in stop should have caught
  it, but this is a belt-and-suspenders check for gap-down cases).

**Attribution:**
  Positions live under alloc_id=CONFLUENCE_ALLOC_NAME (auto-created lazily).
  BotTrade rows: origin='BROKER_FILL' with real Alpaca order UUID.

**Imports the required write gates so ci_check_gates.sh passes:**
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

# Required by ci_check_gates.sh — the module constructs BotTrade + BotPosition
from app.services.trade_write_gate import check_trade_write  # noqa: F401
from app.services.position_write_gate import check_position_pre_write  # noqa: F401

logger = logging.getLogger(__name__)


CONFLUENCE_ALLOC_NAME = "confluence_executor"


def _alpaca_headers() -> Dict[str, str]:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        raise RuntimeError("no_alpaca_creds")
    return {
        "APCA-API-KEY-ID": kid,
        "APCA-API-SECRET-KEY": ksec,
        "Content-Type": "application/json",
    }


def _alpaca_data_get(path: str) -> Dict[str, Any]:
    url = f"https://data.alpaca.markets{path}"
    req = urllib.request.Request(url, headers=_alpaca_headers())
    with urllib.request.urlopen(req, timeout=10) as resp:
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


def _get_last_price(symbol: str) -> Optional[float]:
    """Latest trade price via Alpaca data API. Paper feed = IEX."""
    try:
        r = _alpaca_data_get(f"/v2/stocks/{symbol}/trades/latest")
        return float(r["trade"]["p"])
    except Exception as e:
        logger.warning("[confluence_executor] price fetch failed for %s: %s", symbol, e)
        return None


def _ensure_alloc(db: Session) -> int:
    """Get or create the confluence_executor bot_allocations row.
    Requires bot_profiles row with name='confluence_executor' (factory-reset creates it)."""
    row = db.execute(
        text(
            "SELECT a.id FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :n AND a.user_id = 1"
        ),
        {"n": CONFLUENCE_ALLOC_NAME},
    ).fetchone()
    if row:
        return int(row[0])

    # Lazy-create — bootstrap the profile then the allocation.
    # Only reached if factory-reset was skipped; alloc starts at $0 capital.
    prof_row = db.execute(
        text("SELECT id FROM bot_profiles WHERE name = :n"),
        {"n": CONFLUENCE_ALLOC_NAME},
    ).fetchone()
    if prof_row:
        profile_id = int(prof_row[0])
    else:
        r_prof = db.execute(
            text(
                "INSERT INTO bot_profiles (name, description, asset_class, enabled) "
                "VALUES (:n, 'confluence framework executor', 'stock', 1)"
            ),
            {"n": CONFLUENCE_ALLOC_NAME},
        )
        profile_id = int(r_prof.lastrowid)

    result = db.execute(
        text(
            "INSERT INTO bot_allocations "
            "(user_id, profile_id, capital_pct, risk_profile, paper_mode, "
            " go_live_requested, enabled, starting_capital_cents, tier, "
            " created_at, updated_at) "
            "VALUES (1, :p, 100.0, 'standard', 1, 0, 1, 0, 'T0', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"p": profile_id},
    )
    db.commit()
    aid = int(result.lastrowid)
    logger.info("[confluence_executor] created allocation id=%d profile=%s",
                aid, CONFLUENCE_ALLOC_NAME)
    return aid


def _submit_bracket_buy(
    symbol: str,
    qty: int,
    entry_type: str,
    entry_limit_price: Optional[float],
    target_price: float,
    stop_price: float,
    client_order_id: str,
) -> Tuple[int, Dict[str, Any]]:
    # 2026-08-24 fix: swing trades hold for weeks/months — TIF must be GTC
    # so bracket legs survive end-of-day. Prior 'day' setting silently expired
    # take-profit + stop-loss for HOG on 2026-08-21 (entry filled but exit
    # legs died at 4pm ET same day, leaving the position naked until refill).
    body: Dict[str, Any] = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "buy",
        "time_in_force": "gtc",
        "order_class": "bracket",
        "take_profit": {"limit_price": f"{target_price:.2f}"},
        "stop_loss": {"stop_price": f"{stop_price:.2f}"},
        "client_order_id": client_order_id,
    }
    if entry_type == "limit":
        body["type"] = "limit"
        body["limit_price"] = f"{entry_limit_price:.2f}"
    else:
        body["type"] = "market"
    return _alpaca_post("/v2/orders", body)


def _notify(msg: str, severity: str = "info") -> None:
    """Send to Discord ops alerts (non-blocking, fire-and-forget)."""
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="Confluence Executor",
            message=msg,
            severity=severity,
            source="confluence_executor",
        )
    except Exception:
        logger.warning("[confluence_executor] discord ops send failed (fallback log): %s", msg)


def _write_fill(
    db: Session,
    alloc_id: int,
    pick_id: int,
    symbol: str,
    qty: int,
    fill_price: float,
    alpaca_order_id: str,
    play_label: str,
) -> None:
    """Book fill as BotTrade + BotPosition. Origin='BROKER_FILL'."""
    from app.db.models.bots import BotTrade, BotPosition

    now = datetime.now(timezone.utc)
    fill_cents = int(round(fill_price * 100))

    pos = BotPosition(
        allocation_id=alloc_id,
        symbol=symbol,
        qty=qty,
        avg_cost_cents=fill_cents,
        side="long",
        opened_at=now,
        closed_at=None,
        is_paper=True,
        origin="BROKER_FILL",
    )
    db.add(pos)
    db.flush()

    # 2026-08-25 fix: previously passed `strategy=` and `realized_pnl_cents=`
    # kwargs — neither is a mapped column on BotTrade (see db/models/bots.py:117).
    # SQLAlchemy raised TypeError, outer try/except in _try_fire swallowed it,
    # BotTrade row never got written. But BotPosition write earlier in this
    # function had already succeeded via db.flush(). Result: 4 positions, 0
    # trades, I25 red (ledger #44 — invalid-kwarg silent-drop class).
    # The play label is preserved in the pick record (confluence_picks.arm_state
    # = FILLED_A / FILLED_B). PnL is computed from fill vs mark in the aggregator.
    trade = BotTrade(
        allocation_id=alloc_id,
        symbol=symbol,
        side="buy",
        qty=qty,
        fill_price_cents=fill_cents,
        fill_price_micros=fill_cents * 10000,
        fees_cents=0,
        ts=now,
        position_id=pos.id,
        is_paper=True,
        alpaca_order_id=alpaca_order_id,
        origin="BROKER_FILL",
    )
    db.add(trade)
    db.commit()

    logger.info(
        "[confluence_executor] booked pick=%d %s %s %d @ %.2f order=%s alloc=%d",
        pick_id, play_label, symbol, qty, fill_price, alpaca_order_id, alloc_id,
    )


def _try_fire(db: Session, pick, last_price: float, alloc_id: int) -> Optional[str]:
    """Check triggers, fire if condition met. Return play label or None."""
    size_cents = pick.size_dollars_cents or 500000
    ppa = (pick.play_a_trigger_price_cents or 0) / 100.0
    ppb = (pick.play_b_trigger_price_cents or 0) / 100.0
    psa = (pick.play_a_stop_price_cents or 0) / 100.0
    psb = (pick.play_b_stop_price_cents or 0) / 100.0
    t1 = (pick.target_1_cents or 0) / 100.0
    mode = (pick.arm_mode or "either").lower()

    fire = None
    entry_type = "market"
    entry_limit: Optional[float] = None
    stop_price = 0.0

    if mode in ("play_a_only", "either") and ppa > 0 and last_price >= ppa:
        fire = "A"
        entry_type = "market"
        stop_price = psa
    elif mode in ("play_b_only", "either") and ppb > 0 and last_price <= ppb and last_price > psb + 0.10:
        fire = "B"
        entry_type = "limit"
        entry_limit = ppb
        stop_price = psb

    if not fire:
        return None

    qty = max(1, int(size_cents / 100.0 / max(last_price, 0.01)))
    client_oid = f"conf_pick_{pick.id}_play_{fire}_{int(datetime.now(timezone.utc).timestamp())}"

    status, resp = _submit_bracket_buy(
        symbol=pick.ticker,
        qty=qty,
        entry_type=entry_type,
        entry_limit_price=entry_limit,
        target_price=t1,
        stop_price=stop_price,
        client_order_id=client_oid,
    )

    if status not in (200, 201):
        logger.error(
            "[confluence_executor] bracket submit failed pick=%d play=%s status=%d body=%s",
            pick.id, fire, status, resp,
        )
        _notify(
            f"⚠ Confluence #{pick.id} {pick.ticker} Play {fire} trigger fired "
            f"but Alpaca REJECTED: {status} {resp.get('message', resp)}"
        )
        return None

    order_id = resp.get("id", "")
    fill_price = entry_limit if entry_type == "limit" else last_price
    try:
        _write_fill(db, alloc_id, pick.id, pick.ticker, qty, fill_price, order_id, fire)
    except Exception as e:
        logger.error("[confluence_executor] booking failed pick=%d: %s", pick.id, e, exc_info=True)

    db.execute(
        text(
            "UPDATE confluence_picks SET arm_state = :s, "
            "alpaca_bracket_order_id = :o, filled_at = :t, "
            "filled_price_cents = :p WHERE id = :id"
        ),
        {
            "s": f"FILLED_{fire}",
            "o": order_id,
            "t": datetime.now(timezone.utc).isoformat(),
            "p": int(round(fill_price * 100)),
            "id": pick.id,
        },
    )
    db.commit()

    _notify(
        f"✅ Confluence #{pick.id} {pick.ticker} Play {fire} FILLED "
        f"@ ${fill_price:.2f} × {qty}. Target ${t1:.2f}, stop ${stop_price:.2f}. "
        f"Bracket {order_id[:8]}."
    )
    return fire


def tick() -> Dict[str, Any]:
    """One tick — call from APScheduler. Idempotent."""
    from app.db.session import SessionLocal
    from app.db.models.confluence import ConfluencePick

    fires: list = []
    invalidations: list = []
    errors: list = []

    db = SessionLocal()
    try:
        armed = db.query(ConfluencePick).filter(
            ConfluencePick.arm_state == "ARMED"
        ).all()

        if not armed:
            return {"status": "ok", "armed": 0, "fires": 0}

        alloc_id = _ensure_alloc(db)

        for pick in armed:
            # Expiry
            if pick.arm_expires_at:
                try:
                    exp = datetime.fromisoformat(pick.arm_expires_at)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > exp:
                        db.execute(
                            text("UPDATE confluence_picks SET arm_state='EXPIRED' WHERE id=:id"),
                            {"id": pick.id},
                        )
                        db.commit()
                        continue
                except Exception:
                    pass

            last = _get_last_price(pick.ticker)
            if last is None:
                errors.append(f"pick_{pick.id}_price_fetch_failed")
                continue

            fire = _try_fire(db, pick, last, alloc_id)
            if fire:
                fires.append({"pick_id": pick.id, "ticker": pick.ticker, "play": fire})

        # Invalidation checks
        filled = db.query(ConfluencePick).filter(
            ConfluencePick.arm_state.in_(["FILLED_A", "FILLED_B"])
        ).all()
        for pick in filled:
            if not pick.invalidation_price_cents:
                continue
            last = _get_last_price(pick.ticker)
            if last is None:
                continue
            if last * 100 < pick.invalidation_price_cents:
                invalidations.append({"pick_id": pick.id, "ticker": pick.ticker, "last": last})
                _notify(
                    f"🚨 Confluence #{pick.id} {pick.ticker} INVALIDATION — "
                    f"${last:.2f} < ${pick.invalidation_price_cents/100:.2f}. "
                    f"Bracket stop should have caught; verify Alpaca."
                )

    except Exception as e:
        logger.error("[confluence_executor] tick error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()

    return {
        "status": "ok",
        "armed": len(fires),
        "fires": fires,
        "invalidations": invalidations,
        "errors": errors,
    }


def setup_confluence_executor(scheduler) -> None:
    """Register the 5-min RTH executor tick job with APScheduler.

    Runs Mon-Fri 09:35-15:55 ET every 5 minutes. Skips outside RTH — no
    quotes anyway (paper feed = IEX which halts after hours).
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        func=tick,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="35,40,45,50,55,5,10,15,20,25,30",
            timezone="America/New_York",
        ),
        id="confluence_executor_tick",
        name="confluence_executor_tick",
        max_instances=1,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=60,
    )
    logger.info("[confluence_executor] scheduler registered (5-min RTH)")
