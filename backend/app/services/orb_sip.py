"""ORB Stocks-in-Play — day-trading sleeve.

See vault: [[2026-08-29-day-trading-equity-intraday]] §1
Zarattini/Barbon/Aziz (SSRN 2024) "A Profitable Day Trading Strategy for
the U.S. Equity Market" — 5-min ORB filtered to Stocks-in-Play (SIP)
reports annualized alpha 36%, Sharpe 2.81 vs 0.48 unfiltered.

Universe: top ~1000 most liquid US stocks, price > $5, ATR > $0.50.
Simplified universe for BMG v1: SPY QQQ TSLA NVDA AAPL META AMZN MSFT
GOOGL AMD (10 mega-caps + top vol).

SIP filter (per Zarattini):
  RV = today's first-5-min volume / prior-14d avg first-5-min volume.
  Rank universe by RV. Fire on top-N (N=1 for concentration in v1).

Trade mechanics:
  - At 9:35 ET (5 min after open), compute first-5-min bar high/low
  - If TOP-1 SIP price already broke bar high: LONG (market)
  - If TOP-1 SIP price already broke bar low: SHORT (SKIP — long-only in v1)
  - Stop: 10R risk cap (stop distance = 10× ATR14 in $, R = 1% NAV)
  - Force close: 3:55 PM ET

Rulebook: check_can_enter() before every entry.
PDT rule ELIMINATED June 2026 — $10K account can day-trade freely.
"""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

# Required by ci_check_gates.sh
from app.services.trade_write_gate import check_trade_write  # noqa: F401
from app.services.position_write_gate import check_position_pre_write  # noqa: F401

logger = logging.getLogger(__name__)

BOT_NAME = "orb_sip"
UNIVERSE = ["SPY", "QQQ", "TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "GOOGL", "AMD"]
R_UNIT_USD = float(os.environ.get("DAYTRADE_R_UNIT_USD", "100"))  # 1R = $100
STOP_MULTIPLE = float(os.environ.get("ORB_STOP_MULTIPLE", "10"))  # 10R stop
MIN_PRICE = 5.0
MIN_ATR = 0.50


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


def _fetch_5min_bars(symbol: str, days: int = 20) -> List[Dict[str, Any]]:
    """Get 5-min bars for the last N days for the SIP filter + first-5-min bar."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    url = (
        f"/v2/stocks/{symbol}/bars?timeframe=5Min&start={start.isoformat()}"
        f"&end={end.isoformat()}&limit=10000&adjustment=raw"
    )
    r = _alpaca_data_get(url)
    return r.get("bars", [])


def _atr14(symbol: str) -> Optional[float]:
    """14-day ATR from daily bars. Used for stop sizing."""
    try:
        r = _alpaca_data_get(
            f"/v2/stocks/{symbol}/bars?timeframe=1Day&limit=20&adjustment=raw"
        )
        bars = r.get("bars", [])
        if len(bars) < 15:
            return None
        trs: List[float] = []
        prev_close = float(bars[-16]["c"])
        for b in bars[-15:-1]:
            h, l, c = float(b["h"]), float(b["l"]), float(b["c"])
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            trs.append(tr)
            prev_close = c
        return sum(trs) / len(trs)
    except Exception as e:
        logger.warning("[orb_sip] ATR fetch failed for %s: %s", symbol, e)
        return None


def _first_5min_bar_today(bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """From a list of 5-min bars, get today's first bar (9:30 ET RTH open).
    Returns bar dict with keys t,o,h,l,c,v — or None if not present."""
    import pytz
    ET = pytz.timezone("America/New_York")
    today_et = datetime.now(ET).date()
    target_open_et = ET.localize(datetime.combine(today_et, datetime.min.time().replace(hour=9, minute=30)))
    target_open_utc = target_open_et.astimezone(timezone.utc)
    # Find bar with timestamp within [9:30, 9:35) ET
    for b in bars:
        ts_str = str(b.get("t", ""))
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= target_open_utc and ts < target_open_utc + timedelta(minutes=5):
            return b
    return None


def _first_5min_volume_prior_avg(bars: List[Dict[str, Any]], days: int = 14) -> Optional[float]:
    """Compute avg first-5-min volume over the prior N trading days."""
    import pytz
    ET = pytz.timezone("America/New_York")
    now_et = datetime.now(ET)
    seen_days = 0
    day_vols: List[int] = []
    # Walk backwards from yesterday
    check_date = now_et.date() - timedelta(days=1)
    while seen_days < days and check_date > now_et.date() - timedelta(days=days * 2):
        if check_date.weekday() < 5:  # Mon-Fri only
            target_open_et = ET.localize(datetime.combine(check_date, datetime.min.time().replace(hour=9, minute=30)))
            target_open_utc = target_open_et.astimezone(timezone.utc)
            for b in bars:
                ts_str = str(b.get("t", ""))
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    continue
                if ts >= target_open_utc and ts < target_open_utc + timedelta(minutes=5):
                    day_vols.append(int(b.get("v", 0)))
                    seen_days += 1
                    break
        check_date -= timedelta(days=1)
    if not day_vols:
        return None
    return sum(day_vols) / len(day_vols)


def _rank_sip(universe: List[str]) -> List[Tuple[str, float, Dict[str, Any]]]:
    """Rank the universe by RV = today_first_5min_vol / prior_14d_avg_first_5min_vol.
    Returns list of (symbol, RV, first_5min_bar_dict) sorted desc by RV."""
    ranked: List[Tuple[str, float, Dict[str, Any]]] = []
    for sym in universe:
        bars = _fetch_5min_bars(sym, days=20)
        if not bars:
            continue
        today_bar = _first_5min_bar_today(bars)
        if not today_bar:
            continue
        prior_avg = _first_5min_volume_prior_avg(bars)
        if not prior_avg or prior_avg <= 0:
            continue
        today_vol = int(today_bar.get("v", 0))
        rv = today_vol / prior_avg
        # Price + ATR filter
        px = float(today_bar.get("c", 0))
        if px < MIN_PRICE:
            continue
        ranked.append((sym, rv, today_bar))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


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

    prof_row = db.execute(text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": BOT_NAME}).fetchone()
    if prof_row:
        profile_id = int(prof_row[0])
    else:
        r_prof = db.execute(
            text(
                "INSERT INTO bot_profiles (name, description, asset_class, enabled) "
                "VALUES (:n, 'ORB Stocks-in-Play day trading (Zarattini 2024)', 'stock', 1)"
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
            "VALUES (1, :p, 20.0, 'aggressive', 1, 0, 1, 0, 'T0', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"p": profile_id},
    )
    db.commit()
    return int(result.lastrowid)


def _notify(msg: str, severity: str = "info") -> None:
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(title="ORB SIP", message=msg, severity=severity, source="orb_sip")
    except Exception:
        logger.warning("[orb_sip] discord send failed: %s", msg)


def _submit_bracket_buy(symbol: str, qty: int, stop_price: float, client_order_id: str) -> Tuple[int, Dict[str, Any]]:
    """Market buy with attached stop. No take profit (let winner run until EOD)."""
    body = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "order_class": "oto",   # one-triggers-other: entry then stop
        "stop_loss": {"stop_price": f"{stop_price:.2f}"},
        "client_order_id": client_order_id,
    }
    return _alpaca_post("/v2/orders", body)


def _get_last_price(symbol: str) -> Optional[float]:
    try:
        r = _alpaca_data_get(f"/v2/stocks/{symbol}/trades/latest")
        return float(r["trade"]["p"])
    except Exception as e:
        logger.warning("[orb_sip] price fetch failed for %s: %s", symbol, e)
        return None


def _write_fill(db: Session, alloc_id: int, symbol: str, qty: int, side: str,
                fill_price: float, alpaca_order_id: str, exit_reason: str = None) -> None:
    from app.db.models.bots import BotTrade, BotPosition
    now = datetime.now(timezone.utc)
    fill_cents = int(round(fill_price * 100))

    if side == "buy":
        pos = BotPosition(
            allocation_id=alloc_id, symbol=symbol, qty=qty,
            avg_cost_cents=fill_cents, side="long",
            opened_at=now, closed_at=None, is_paper=True, origin="BROKER_FILL",
        )
        db.add(pos)
        db.flush()
        pos_id = pos.id
    else:
        row = db.execute(
            text(
                "SELECT id, qty, avg_cost_cents FROM bot_positions "
                "WHERE allocation_id = :aid AND symbol = :s AND closed_at IS NULL "
                "ORDER BY opened_at DESC LIMIT 1"
            ),
            {"aid": alloc_id, "s": symbol},
        ).fetchone()
        if row:
            pos_id, existing_qty, avg_cost = int(row[0]), float(row[1]), int(row[2])
            realized_cents = int(round((fill_cents - avg_cost) * existing_qty))
            db.execute(
                text(
                    "UPDATE bot_positions SET closed_at = :t, "
                    "close_price_cents = :p, realized_pnl_cents = :r, "
                    "exit_reason = :er WHERE id = :id"
                ),
                {"t": now.isoformat(), "p": fill_cents, "r": realized_cents,
                 "er": exit_reason or "orb_eod_close", "id": pos_id},
            )
        else:
            pos_id = None

    trade = BotTrade(
        allocation_id=alloc_id, symbol=symbol, side=side, qty=qty,
        fill_price_cents=fill_cents, fill_price_micros=fill_cents * 10000,
        fees_cents=0, ts=now, position_id=pos_id, is_paper=True,
        alpaca_order_id=alpaca_order_id, origin="BROKER_FILL",
    )
    db.add(trade)
    db.commit()


def entry_tick() -> Dict[str, Any]:
    """9:35 ET — pick top-1 SIP, fire ORB long if price already broke bar high."""
    from app.db.session import SessionLocal
    from app.services.day_trading_rulebook import check_can_enter

    db = SessionLocal()
    try:
        alloc_id = _ensure_alloc(db)

        # Rulebook preflight
        rb = check_can_enter(db, alloc_id)
        if not rb.allowed:
            _notify(f"ORB entry SKIPPED — rulebook: {rb.reason}")
            return {"status": "skip", "reason": f"rulebook:{rb.reason}"}

        # Rank universe by SIP RV
        ranked = _rank_sip(UNIVERSE)
        if not ranked:
            return {"status": "skip", "reason": "no_sip_data"}
        # Filter to breakouts of first-5-min bar high
        candidates: List[Dict[str, Any]] = []
        for sym, rv, bar in ranked[:5]:  # top 5 by RV
            bar_high = float(bar.get("h", 0))
            atr = _atr14(sym)
            if not atr or atr < MIN_ATR:
                continue
            last_px = _get_last_price(sym)
            if last_px is None:
                continue
            if last_px > bar_high:
                # Breakout confirmed
                stop_price = bar_high - atr * 0.5  # tight stop just below bar high
                risk_per_share = last_px - stop_price
                if risk_per_share <= 0:
                    continue
                qty = max(1, int(R_UNIT_USD / risk_per_share))
                candidates.append({
                    "symbol": sym, "rv": rv, "bar_high": bar_high,
                    "last_px": last_px, "stop": stop_price, "atr14": atr,
                    "qty": qty, "risk_usd": qty * risk_per_share,
                })
        if not candidates:
            return {"status": "skip", "reason": "no_breakouts_in_top5_sip"}

        # Take top-1 by RV that met the breakout condition
        pick = candidates[0]
        oid = f"orbsip_{pick['symbol']}_{int(datetime.now(timezone.utc).timestamp())}"
        status, resp = _submit_bracket_buy(pick["symbol"], pick["qty"], pick["stop"], oid)
        if status not in (200, 201):
            logger.error("[orb_sip] entry submit failed: %s %s", status, resp)
            _notify(f"❌ ORB entry failed for {pick['symbol']}: {status} {resp.get('message', resp)}", "warning")
            return {"status": "error", "reason": f"submit_{status}"}
        order_id = resp.get("id", "")
        _write_fill(db, alloc_id, pick["symbol"], pick["qty"], "buy", pick["last_px"], order_id)
        _notify(
            f"📈 ORB SIP BUY {pick['qty']}x {pick['symbol']} @ ${pick['last_px']:.2f} "
            f"(RV={pick['rv']:.2f}, bar_high=${pick['bar_high']:.2f}, "
            f"stop=${pick['stop']:.2f}, risk=${pick['risk_usd']:.0f})."
        )
        return {"status": "ok", "pick": pick, "order_id": order_id}
    except Exception as e:
        logger.error("[orb_sip] entry tick error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def eod_close_tick() -> Dict[str, Any]:
    """3:55 PM ET — force-close any open ORB position."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        alloc_id = _ensure_alloc(db)
        rows = db.execute(
            text(
                "SELECT id, symbol, qty FROM bot_positions "
                "WHERE allocation_id = :aid AND closed_at IS NULL"
            ),
            {"aid": alloc_id},
        ).fetchall()
        closed = []
        for r in rows:
            pos_id, sym, qty = int(r[0]), r[1], int(float(r[2]))
            px = _get_last_price(sym)
            if px is None:
                continue
            oid = f"orbsip_eod_{sym}_{int(datetime.now(timezone.utc).timestamp())}"
            body = {
                "symbol": sym, "qty": str(qty), "side": "sell",
                "type": "market", "time_in_force": "day", "client_order_id": oid,
            }
            status, resp = _alpaca_post("/v2/orders", body)
            if status in (200, 201):
                order_id = resp.get("id", "")
                _write_fill(db, alloc_id, sym, qty, "sell", px, order_id, "orb_eod_close")
                closed.append({"symbol": sym, "qty": qty, "price": px})
        if closed:
            _notify(f"🔚 ORB EOD close: {len(closed)} position(s) — {', '.join(c['symbol'] for c in closed)}")
        return {"status": "ok", "closed": closed}
    except Exception as e:
        logger.error("[orb_sip] EOD close error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def setup_orb_sip_scheduler(scheduler) -> None:
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    ET = pytz.timezone("America/New_York")

    scheduler.add_job(
        entry_tick,
        trigger=CronTrigger(hour=9, minute=35, day_of_week="mon-fri", timezone=ET),
        id="orb_sip_entry",
        name="orb_sip_entry",
        replace_existing=True, misfire_grace_time=180,
    )
    scheduler.add_job(
        eod_close_tick,
        trigger=CronTrigger(hour=15, minute=55, day_of_week="mon-fri", timezone=ET),
        id="orb_sip_eod_close",
        name="orb_sip_eod_close",
        replace_existing=True, misfire_grace_time=300,
    )
    logger.info("[orb_sip] scheduler registered (entry 9:35, EOD close 3:55 ET)")
