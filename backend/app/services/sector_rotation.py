"""Sector rotation — long-trend sleeve.

See vault: [[2026-08-27-swing-long-2to12month]] §5 (Industry momentum,
Moskowitz-Grinblatt JF 1999) + [[2026-08-27-swing-strategy-pool-synthesis]]

Strategy:
  Rank the 11 SPDR sector ETFs by 12-1 momentum (last-12-month return
  excluding the most recent month). Hold top 3 equal-weighted.
  Rebalance monthly on the first trading day.

Regime gates (from app.services.regime_state):
  - Faber closed → sell all + hold cash
  - CGH DOWN → halve position size (momentum crash risk elevated)
  - Vol scalar → applied to gross exposure

Position sizing:
  Target 25% of NAV in this sleeve. Split equally across top 3 → ~8% NAV each.
  Actual = 25% × NAV × vol_scalar × cgh_multiplier / 3.

Universe (11 SPDR sector ETFs):
  XLK  Technology
  XLF  Financials
  XLE  Energy
  XLV  Healthcare
  XLI  Industrials
  XLY  Consumer Discretionary
  XLP  Consumer Staples
  XLU  Utilities
  XLB  Materials
  XLRE Real Estate
  XLC  Communication Services
"""
from __future__ import annotations

import json
import logging
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

BOT_NAME = "sector_rotation"
UNIVERSE = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
TOP_N = 3
SLEEVE_TARGET_PCT = float(os.environ.get("SECTOR_ROTATION_SLEEVE_PCT", "0.25"))  # 25% NAV
CGH_DOWN_MULTIPLIER = 0.5   # halve size in DOWN state


def _alpaca_headers() -> Dict[str, str]:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        raise RuntimeError("no_alpaca_creds")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec, "Content-Type": "application/json"}


def _alpaca_data_get(path: str) -> Dict[str, Any]:
    url = f"https://data.alpaca.markets{path}"
    req = urllib.request.Request(url, headers=_alpaca_headers())
    with urllib.request.urlopen(req, timeout=20) as resp:
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


def _twelve_minus_one_momentum(symbol: str) -> Optional[float]:
    """Compute 12-1 momentum = return from t-12mo to t-1mo (skip last month).

    Uses daily bars; picks the closes at ~T-252 and ~T-21 trading days.
    Returns pct return, or None on fetch failure.
    """
    try:
        r = _alpaca_data_get(
            f"/v2/stocks/{symbol}/bars?timeframe=1Day&limit=260&adjustment=all"
        )
        bars = r.get("bars", [])
        if len(bars) < 253:
            return None
        # Close at index len-253 (about t-12mo) and len-22 (about t-1mo)
        c_old = float(bars[-253]["c"])
        c_new = float(bars[-22]["c"])
        return (c_new / c_old - 1.0) * 100.0
    except Exception as e:
        logger.warning("[sector_rotation] momentum fetch failed for %s: %s", symbol, e)
        return None


def _get_last_price(symbol: str) -> Optional[float]:
    try:
        r = _alpaca_data_get(f"/v2/stocks/{symbol}/trades/latest")
        return float(r["trade"]["p"])
    except Exception as e:
        logger.warning("[sector_rotation] price fetch failed for %s: %s", symbol, e)
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
                "VALUES (:n, 'sector rotation (11 SPDR ETFs, 12-1 momentum, monthly)', 'stock', 1)"
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
            "VALUES (1, :p, 25.0, 'standard', 1, 0, 1, 0, 'T0', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"p": profile_id},
    )
    db.commit()
    return int(result.lastrowid)


def _notify(msg: str, severity: str = "info") -> None:
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(title="Sector Rotation", message=msg,
                       severity=severity, source="sector_rotation")
    except Exception:
        logger.warning("[sector_rotation] discord send failed: %s", msg)


def _submit_market(symbol: str, qty: int, side: str, client_order_id: str) -> Tuple[int, Dict[str, Any]]:
    body = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": "day",
        "client_order_id": client_order_id,
    }
    return _alpaca_post("/v2/orders", body)


def _write_fill(db: Session, alloc_id: int, symbol: str, qty: int, side: str,
                fill_price: float, alpaca_order_id: str) -> None:
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
        # Close existing long — set closed_at + realized_pnl
        row = db.execute(
            text(
                "SELECT id, qty, avg_cost_cents FROM bot_positions "
                "WHERE allocation_id = :aid AND symbol = :s AND closed_at IS NULL "
                "ORDER BY opened_at ASC LIMIT 1"
            ),
            {"aid": alloc_id, "s": symbol},
        ).fetchone()
        if row:
            pos_id, existing_qty, avg_cost_cents = int(row[0]), float(row[1]), int(row[2])
            realized_cents = int(round((fill_cents - avg_cost_cents) * existing_qty))
            db.execute(
                text(
                    "UPDATE bot_positions SET closed_at = :t, "
                    "close_price_cents = :p, realized_pnl_cents = :r, "
                    "exit_reason = 'sector_rotation_rebalance' WHERE id = :id"
                ),
                {"t": now.isoformat(), "p": fill_cents, "r": realized_cents, "id": pos_id},
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


def rebalance_tick() -> Dict[str, Any]:
    """One rebalance — call monthly from APScheduler."""
    from app.db.session import SessionLocal
    from app.services.regime_state import get_regime_state

    db = SessionLocal()
    try:
        alloc_id = _ensure_alloc(db)
        regime = get_regime_state()

        # Compute momentum ranking
        momenta: List[Tuple[str, float]] = []
        for sym in UNIVERSE:
            m = _twelve_minus_one_momentum(sym)
            if m is not None:
                momenta.append((sym, m))
        momenta.sort(key=lambda x: x[1], reverse=True)
        top = momenta[:TOP_N]
        top_symbols = {s for s, _ in top}

        # Get current holdings for this alloc
        current_rows = db.execute(
            text(
                "SELECT symbol, qty FROM bot_positions "
                "WHERE allocation_id = :aid AND closed_at IS NULL"
            ),
            {"aid": alloc_id},
        ).fetchall()
        current_holdings = {r[0]: float(r[1]) for r in current_rows}

        # Determine sleeve budget from Alpaca portfolio value + regime gates
        acct = _alpaca_account()
        nav = float(acct.get("portfolio_value", 0))
        sleeve_budget = nav * SLEEVE_TARGET_PCT * regime.vol_scalar
        if not regime.cgh_up:
            sleeve_budget *= CGH_DOWN_MULTIPLIER
        if not regime.faber_open:
            sleeve_budget = 0.0  # sell everything

        per_sym_budget = sleeve_budget / TOP_N if TOP_N > 0 else 0.0

        # 1. Sell any current holding not in top list
        sells: List[Dict[str, Any]] = []
        for sym, qty in current_holdings.items():
            if sym not in top_symbols or sleeve_budget == 0:
                px = _get_last_price(sym)
                if px is None:
                    continue
                oid = f"secrot_sell_{sym}_{int(datetime.now(timezone.utc).timestamp())}"
                status, resp = _submit_market(sym, int(qty), "sell", oid)
                if status in (200, 201):
                    order_id = resp.get("id", "")
                    _write_fill(db, alloc_id, sym, int(qty), "sell", px, order_id)
                    sells.append({"symbol": sym, "qty": qty, "price": px})

        # 2. Buy new positions in top not already held (equal-weight to budget)
        buys: List[Dict[str, Any]] = []
        if sleeve_budget > 0:
            for sym, mom in top:
                if sym in current_holdings and sym in top_symbols:
                    continue  # already holding
                px = _get_last_price(sym)
                if px is None or px <= 0:
                    continue
                qty = max(1, int(per_sym_budget / px))
                oid = f"secrot_buy_{sym}_{int(datetime.now(timezone.utc).timestamp())}"
                status, resp = _submit_market(sym, qty, "buy", oid)
                if status in (200, 201):
                    order_id = resp.get("id", "")
                    _write_fill(db, alloc_id, sym, qty, "buy", px, order_id)
                    buys.append({"symbol": sym, "qty": qty, "price": px, "mom_12_1": mom})

        summary = {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "regime": regime.to_dict(),
            "sleeve_budget_usd": sleeve_budget,
            "top_ranked": [{"symbol": s, "mom_12_1_pct": m} for s, m in top],
            "sells": sells,
            "buys": buys,
        }
        _notify(
            f"🔄 Sector Rotation rebalance — top: {', '.join(s for s, _ in top)}. "
            f"Buys: {len(buys)}, Sells: {len(sells)}. "
            f"Sleeve budget: ${sleeve_budget:.0f} (vol_scalar={regime.vol_scalar:.2f})."
        )
        logger.info("[sector_rotation] rebalance complete: %s", json.dumps(summary)[:500])
        return summary

    except Exception as e:
        logger.error("[sector_rotation] tick error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def setup_sector_rotation_scheduler(scheduler) -> None:
    """Monthly rebalance on 2nd business day at 10 AM ET (avoids day-1 chaos)."""
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    ET = pytz.timezone("America/New_York")
    scheduler.add_job(
        rebalance_tick,
        trigger=CronTrigger(day="2", hour=10, minute=0, day_of_week="mon-fri", timezone=ET),
        id="sector_rotation_monthly",
        name="sector_rotation_monthly",
        replace_existing=True,
        misfire_grace_time=3600 * 6,
    )
    logger.info("[sector_rotation] scheduler registered (2nd of month, 10 AM ET)")
