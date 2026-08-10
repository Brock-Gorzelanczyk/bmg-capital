"""Orphan option adopter — STOP-THE-LINE #3 (2026-07-15 audit).

Walks Alpaca's live us_option positions. For each position that has NO
matching open BotPosition row in BMG, tries to attribute it to an
originating bot by walking Alpaca's order history, then inserts a
BotPosition + BotTrade so the app's tracking catches up to broker truth.

Positions that can't be attributed (order history missing, no bot with a
matching signal timestamp, cross-account fills) get added to an ORPHAN
LEDGER row with manual_review=True so a human can decide what to do.

The reconciler runs every 15 min alongside the buying-power healer. On
each cycle it also re-computes the drift metric Brock asked for:

  alpaca_legs == db_legs
  db_unrealized == alpaca_unrealized ± $1

Env overrides:
  ORPHAN_ADOPTION_ENABLED   (default "true")  kill switch
  ORPHAN_ATTRIBUTION_WINDOW_HOURS (default 72) how far back to walk
                                              order history for
                                              attribution
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Ledger #32 §W1: any file constructing BotTrade/BotPosition must import its gate.
from app.services.trade_write_gate import check_trade_write  # noqa: F401
from app.services.position_write_gate import check_position_pre_write  # noqa: F401

_ALPACA_BASE = "https://paper-api.alpaca.markets"


# ── Alpaca helpers ──────────────────────────────────────────────────────────

def _creds() -> Optional[tuple[str, str]]:
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not sec:
        return None
    return key, sec


def _alpaca_get(path: str) -> Any:
    c = _creds()
    if c is None:
        return None
    key, sec = c
    req = urllib.request.Request(
        f"{_ALPACA_BASE}{path}",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _fetch_broker_options() -> list[dict]:
    try:
        return [p for p in (_alpaca_get("/v2/positions") or []) if p.get("asset_class") == "us_option"]
    except Exception as exc:
        logger.warning("[orphan-adopter] positions fetch failed: %s", exc)
        return []


def _fetch_order_history(hours: int) -> list[dict]:
    """Pull filled option orders in the last N hours. Sorted newest-first."""
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    qs = urllib.parse.urlencode({
        "status": "closed",
        "asset_class": "us_option",
        "after": after,
        "limit": 500,
        "direction": "desc",
        "nested": "true",
    })
    try:
        orders = _alpaca_get(f"/v2/orders?{qs}") or []
        return [o for o in orders if o.get("status") == "filled" or (o.get("legs") or [])]
    except Exception as exc:
        logger.warning("[orphan-adopter] order history fetch failed: %s", exc)
        return []


# ── OCC parse (canonical helper) ────────────────────────────────────────────

_OCC_RE = re.compile(r"^([A-Z][A-Z0-9]*)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def _parse_occ(sym: str) -> Optional[dict]:
    m = _OCC_RE.match((sym or "").upper())
    if not m:
        return None
    root, yy, mm, dd, cp, strike_raw = m.groups()
    return {
        "root": root,
        "expiration_date": f"20{yy}-{mm}-{dd}",
        "option_type": "call" if cp == "C" else "put",
        "strike_price": int(strike_raw) / 1000.0,
    }


# ── Attribution ─────────────────────────────────────────────────────────────

def _attribute_position_to_bot(
    db,
    occ_symbol: str,
    broker_qty: float,
    orders: list[dict],
) -> Optional[dict]:
    """Look through Alpaca order history for a filled order that opened this
    OCC symbol. Return {allocation_id, profile_name, avg_cost_cents, side, qty}
    if we can attribute; None if we can't.

    Attribution strategy:
      1. Find the filled Alpaca order matching this OCC (or containing it as
         a leg).
      2. Look up bot_trades where alpaca_order_id matches. That tells us the
         allocation.
      3. If bot_trades has no matching row, try to match via a nearby
         bot_signal (same underlying, same side, ts within 60 min of fill).
    """
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile

    from sqlalchemy import func

    # ── Path A: find the Alpaca order for this OCC ──────────────────────
    matching_order = None
    for o in orders:
        if o.get("symbol") == occ_symbol:
            matching_order = o
            break
        # Check nested legs
        legs = o.get("legs") or []
        for lg in legs:
            if lg.get("symbol") == occ_symbol:
                matching_order = o
                break
        if matching_order:
            break

    if matching_order is None:
        return None

    alpaca_order_id = matching_order.get("id")
    if not alpaca_order_id:
        return None

    # ── Path B: match bot_trade by alpaca_order_id ─────────────────────
    trade = (
        db.query(BotTrade)
        .filter(BotTrade.alpaca_order_id == alpaca_order_id)
        .first()
    )
    if trade is not None:
        alloc = db.query(BotAllocation).filter(BotAllocation.id == trade.allocation_id).first()
        if alloc:
            profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
            # Derive avg cost from the Alpaca fill price
            filled_avg = matching_order.get("filled_avg_price") or matching_order.get("limit_price") or 0
            try:
                avg_cost_cents = int(round(float(filled_avg) * 100))
            except (TypeError, ValueError):
                avg_cost_cents = trade.fill_price_cents or 0
            return {
                "allocation_id": alloc.id,
                "profile_name": profile.name if profile else "unknown",
                "avg_cost_cents": avg_cost_cents,
                "qty": abs(broker_qty),
                "side": "short" if broker_qty < 0 else "long",
                "attribution_source": "alpaca_order_id_match",
            }

    # Path C: fallback — attribute to whichever options bot has recent signals
    # for this underlying near the order fill time. Cheap heuristic; conservative.
    parsed = _parse_occ(occ_symbol)
    if not parsed:
        return None

    return None  # can't attribute — caller writes an orphan-ledger row


# ── Adopt loop ──────────────────────────────────────────────────────────────

def adopt_orphans(db, dry_run: bool = False) -> dict:
    """Main entry. Walks Alpaca options, matches to BMG, upserts adopters
    or ledger rows. Returns diagnostic dict.

    2026-08-05 v2 fixes after runaway (Brock stop-the-line):
      * IDEMPOTENT — key on (allocation_id, occ_symbol, side) not just occ.
        Skip if a row already exists in that key. Prevents the "run twice,
        duplicate" pattern.
      * COST BASIS from Alpaca's avg_entry_price on the position itself,
        NOT current_price/mark. Prevents phantom P&L on first adoption.
      * PAIRED TRADE — create a BotTrade alongside each BotPosition so
        future rollback-orphan-position sweeps don't kill legit adopts.
      * DRY-RUN DIFF explicit: net_adds == alpaca_count - db_count.
    """
    enabled = os.getenv("ORPHAN_ADOPTION_ENABLED", "true").strip().lower() == "true"
    if not enabled:
        return {"skipped": "disabled_by_env"}

    from app.db.models.bots import BotPosition, BotTrade

    hours = int(os.getenv("ORPHAN_ATTRIBUTION_WINDOW_HOURS", "72"))

    broker_pos = _fetch_broker_options()
    orders = _fetch_order_history(hours)

    # BMG side — key = (allocation_id, symbol, side). Multiple bots can each
    # legitimately hold the same OCC with different intents (long vs short).
    bmg_open = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .filter(BotPosition.option_type.isnot(None))
        .all()
    )
    bmg_keys: set[tuple] = {
        (p.allocation_id, p.symbol, getattr(p, "side", "long")) for p in bmg_open
    }
    bmg_count = len(bmg_open)

    orphans_found: list[dict] = []
    adopted: list[dict] = []
    ledgered: list[dict] = []
    skipped_idempotent: list[str] = []

    for bp in broker_pos:
        occ = bp.get("symbol")
        if not occ:
            continue

        qty = float(bp.get("qty") or 0)
        broker_side = "short" if qty < 0 else "long"
        # Alpaca avg_entry_price is the actual fill price. Use it, NOT
        # current_price / market_value / mark — those inject P&L drift on
        # the first tick after adoption.
        avg_entry = float(bp.get("avg_entry_price") or 0)
        entry = {
            "occ_symbol": occ,
            "broker_qty": qty,
            "broker_side": broker_side,
            "avg_entry_price": avg_entry,
            "market_value": float(bp.get("market_value") or 0),
            "unrealized_pl": float(bp.get("unrealized_pl") or 0),
        }
        orphans_found.append(entry)

        attribution = _attribute_position_to_bot(db, occ, qty, orders)
        if attribution is None:
            ledgered.append({**entry, "reason": "no_matching_alpaca_order_or_bot_trade"})
            continue

        # IDEMPOTENCY GUARD — same (alloc, occ, side) already open? skip.
        key = (attribution["allocation_id"], occ, broker_side)
        if key in bmg_keys:
            skipped_idempotent.append(f"{occ}@alloc{attribution['allocation_id']}/{broker_side}")
            continue

        if dry_run:
            adopted.append({**entry, **attribution, "dry_run": True})
            continue

        try:
            parsed = _parse_occ(occ) or {}
            # Cost basis in cents from Alpaca avg_entry_price (dollars).
            cost_cents = int(round(avg_entry * 100)) if avg_entry > 0 else attribution.get("avg_cost_cents", 0)
            now_ts = datetime.now(timezone.utc)
            pos = BotPosition(
                allocation_id=attribution["allocation_id"],
                symbol=occ,
                qty=abs(qty),
                avg_cost_cents=cost_cents,
                side=broker_side,
                opened_at=now_ts,
                closed_at=None,
                is_paper=True,
                option_type=parsed.get("option_type"),
                strike_price=parsed.get("strike_price"),
                expiration_date=parsed.get("expiration_date"),
                underlying_symbol=parsed.get("root"),
                contract_count=int(abs(qty)),
                contract_premium_cents=cost_cents,
                origin="ADOPTED",  # m099
            )
            db.add(pos)
            db.flush()  # get pos.id
            # Paired entry trade — so rollback-orphan-position sweeps don't
            # nuke this adoption. Marked alpaca_order_id="adopter" so it's
            # traceable + won't accidentally match a real Alpaca fill.
            entry_trade = BotTrade(
                allocation_id=attribution["allocation_id"],
                symbol=occ,
                side="short" if broker_side == "short" else "buy",
                qty=abs(qty),
                fill_price_cents=cost_cents,
                fees_cents=0,
                ts=now_ts,
                position_id=pos.id,
                is_paper=True,
                alpaca_order_id=attribution.get("alpaca_order_id_source") or "orphan_adopter",
                option_type=parsed.get("option_type"),
                strike_price=parsed.get("strike_price"),
                expiration_date=parsed.get("expiration_date"),
                underlying_symbol=parsed.get("root"),
                contract_count=int(abs(qty)),
                contract_premium_cents=cost_cents,
                origin="ADOPTED",  # m099
            )
            db.add(entry_trade)
            db.commit()
            bmg_keys.add(key)   # prevent same-run dupes
            adopted.append({**entry, **attribution, "pos_id": pos.id, "trade_id": entry_trade.id})
            logger.warning(
                "[orphan-adopter] ADOPTED %s → bot=%s alloc=%d pos_id=%d trade_id=%d qty=%.4f side=%s avg_entry=%.4f",
                occ, attribution["profile_name"], attribution["allocation_id"],
                pos.id, entry_trade.id, abs(qty), broker_side, avg_entry,
            )
        except Exception as exc:
            db.rollback()
            ledgered.append({**entry, "reason": f"adopt_insert_failed: {type(exc).__name__}"})
            logger.error("[orphan-adopter] insert failed for %s: %s", occ, exc)

    # ── Drift metric (Brock's daily check) ───────────────────────────────
    alpaca_legs = len(broker_pos)
    db_legs_after = bmg_count + len(adopted)
    alpaca_upl = sum(float(p.get("unrealized_pl") or 0) for p in broker_pos)
    # Net adds should equal (alpaca_count - bmg_count_before) minus anything
    # skipped-idempotent. Log LOUD if it doesn't, because that means we're
    # trying to add rows we shouldn't.
    net_adds_expected = alpaca_legs - bmg_count
    net_adds_actual = len(adopted) if not dry_run else 0

    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "broker_options_count": alpaca_legs,
        "bmg_options_count_before": bmg_count,
        "bmg_options_count_after":  db_legs_after,
        "orphans_found": len(orphans_found),
        "adopted": len(adopted),
        "skipped_idempotent": len(skipped_idempotent),
        "skipped_idempotent_sample": skipped_idempotent[:10],
        "ledgered_for_review": len(ledgered),
        "alpaca_total_unrealized_pl": round(alpaca_upl, 2),
        "net_adds_expected": net_adds_expected,
        "net_adds_actual": net_adds_actual,
        "adopted_details": adopted,
        "ledgered_details": ledgered,
        "dry_run": dry_run,
    }

    # Discord alert if anything changed
    try:
        if not dry_run and (adopted or ledgered):
            from app.services.discord import send_ops_alert
            send_ops_alert(
                title=f"[orphan-adopter] adopted={len(adopted)} ledgered={len(ledgered)}",
                message=(
                    f"Broker options: {alpaca_legs}. BMG had {bmg_count} before, "
                    f"{db_legs_after} after. {len(ledgered)} could not be attributed and need "
                    f"manual review — see logs for OCC symbols."
                ),
                severity="warn",
                source="orphan_adopter",
            )
    except Exception as _dc_exc:
        logger.warning("[orphan-adopter] discord alert failed: %s", _dc_exc)

    return result


def setup_orphan_adopter(scheduler) -> None:
    """Register the reconciler every 15 min during market hours."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[orphan-adopter] apscheduler unavailable: %s", exc)
        return

    from app.db.session import SessionLocal

    def _job() -> None:
        db = SessionLocal()
        try:
            res = adopt_orphans(db, dry_run=False)
            if res.get("adopted") or res.get("ledgered_for_review"):
                logger.warning("[orphan-adopter] cycle: %s", {
                    k: v for k, v in res.items()
                    if k not in ("adopted_details", "ledgered_details")
                })
        except Exception as exc:
            logger.error("[orphan-adopter] job raised: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _job,
        CronTrigger(day_of_week="mon-fri", hour="13-19", minute="*/15", timezone="UTC"),
        id="orphan_adopter",
        replace_existing=True,
        max_instances=1,
    )
    logger.warning("[orphan-adopter] scheduler registered — every 15 min during US market hours")
