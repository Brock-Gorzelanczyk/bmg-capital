#!/usr/bin/env python3
"""Backfill fill_price_micros for pre-m100 sub-penny BROKER_FILL rows.

Ledger #34: BMG had ~46 BROKER_FILL rows with fill_price_cents=0 (sub-penny
tokens like SHIB/BONK/PEPE rounded to 0). m100 added fill_price_micros
BIGINT and left these rows NULL as the marker for this backfill.

This script:
  1. SELECTs BROKER_FILL rows where fill_price_micros IS NULL AND qty > 0
  2. For each, fetches the true fill price from Alpaca (either single-order
     endpoint or account activities FILL endpoint depending on
     alpaca_order_id shape)
  3. Computes micros = int(round(filled_price * 1_000_000))
  4. UPDATEs the row (only in --live mode)

§V0: verify off-volume backup fresh (<24h) BEFORE --live run.
§ADOPT-BOUND: dry_run default, --live required to write.

Usage:
  # From a machine that can talk to the BMG DB directly (Railway shell)
  # OR use POST /admin/backfill-fill-price-micros?dry_run=true endpoint (safer)

  python3 scripts/backfill_fill_price_micros.py           # dry-run
  python3 scripts/backfill_fill_price_micros.py --live    # execute

Idempotent: re-running skips rows already backfilled (WHERE micros IS NULL).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error

# Make backend importable when run from repo root
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_fill_price_micros")


def _alpaca_creds() -> tuple[str, str]:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        raise RuntimeError("Missing ALPACA_API_KEY / ALPACA_SECRET_KEY env vars")
    return kid, ksec


def _fetch_order(order_id: str) -> dict | None:
    kid, ksec = _alpaca_creds()
    try:
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets/v2/orders/{order_id}",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        )
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as e:
        logger.warning("[alpaca] order %s: HTTP %s", order_id, e.code)
        return None
    except Exception as e:
        logger.warning("[alpaca] order %s: %s", order_id, e)
        return None


def _fetch_activities_window(after_iso: str, until_iso: str) -> list[dict]:
    """Fetch FILL activities in a time window (used when order_id is an admin marker)."""
    kid, ksec = _alpaca_creds()
    try:
        url = (
            f"https://paper-api.alpaca.markets/v2/account/activities/FILL"
            f"?after={after_iso}&until={until_iso}"
        )
        req = urllib.request.Request(url, headers={
            "APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec,
        })
        return json.loads(urllib.request.urlopen(req, timeout=15).read()) or []
    except Exception as e:
        logger.warning("[alpaca] activities [%s..%s]: %s", after_iso, until_iso, e)
        return []


def _is_uuid(s: str) -> bool:
    return isinstance(s, str) and len(s) == 36 and s.count("-") == 4


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="Actually write. Default dry-run.")
    p.add_argument("--limit", type=int, default=100, help="Max rows to process per run.")
    args = p.parse_args()

    from app.db.session import SessionLocal
    from sqlalchemy import text as _t

    db = SessionLocal()
    try:
        rows = db.execute(_t(
            "SELECT id, alpaca_order_id, symbol, qty, ts "
            "FROM bot_trades "
            "WHERE fill_price_micros IS NULL "
            "  AND origin = 'BROKER_FILL' "
            "  AND qty > 0 "
            "ORDER BY ts DESC "
            "LIMIT :n"
        ), {"n": args.limit}).fetchall()
    finally:
        pass  # keep session open for writes below

    n_total = len(rows)
    logger.info("Found %d rows needing backfill (limit=%d)", n_total, args.limit)

    updated = 0
    skipped_no_match = 0
    skipped_no_price = 0
    errors = 0

    try:
        for r in rows:
            row_id, order_id, symbol, qty, ts = r
            price: float | None = None
            source = None

            if order_id and _is_uuid(order_id):
                data = _fetch_order(order_id)
                if data and data.get("filled_avg_price"):
                    try:
                        price = float(data["filled_avg_price"])
                        source = "order_by_id"
                    except (TypeError, ValueError):
                        pass
            else:
                # Admin marker — try to match by symbol+ts+qty in activities window
                try:
                    from datetime import datetime, timezone, timedelta
                    if isinstance(ts, str):
                        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        ts_dt = ts
                    after = (ts_dt - timedelta(hours=6)).isoformat()
                    until = (ts_dt + timedelta(hours=6)).isoformat()
                    acts = _fetch_activities_window(after, until)
                    for a in acts:
                        if (a.get("symbol") == symbol
                                and a.get("qty")
                                and abs(float(a["qty"]) - float(qty)) < 0.001):
                            try:
                                price = float(a.get("price") or 0)
                                source = "activities_by_time_symbol"
                                break
                            except (TypeError, ValueError):
                                pass
                except Exception as e:
                    logger.warning("row %d activities match failed: %s", row_id, e)

            if price is None or price <= 0:
                skipped_no_match += 1
                logger.info("  SKIP row %d %s qty=%s — no Alpaca match", row_id, symbol, qty)
                continue

            micros = int(round(price * 1_000_000))
            if micros <= 0:
                skipped_no_price += 1
                continue

            if args.live:
                try:
                    db.execute(_t(
                        "UPDATE bot_trades SET fill_price_micros = :m WHERE id = :i"
                    ), {"m": micros, "i": row_id})
                    updated += 1
                    logger.info("  UPDATED row %d %s qty=%s micros=%d src=%s",
                                row_id, symbol, qty, micros, source)
                except Exception as e:
                    errors += 1
                    logger.error("row %d UPDATE failed: %s", row_id, e)
            else:
                logger.info("  [dry] row %d %s qty=%s micros=%d src=%s",
                            row_id, symbol, qty, micros, source)

            # Rate limit — Alpaca 200 req/min = 3.3/sec. 250ms sleep = 4/sec ceiling.
            time.sleep(0.25)

        if args.live:
            db.commit()
    finally:
        db.close()

    logger.info(
        "DONE: total=%d updated=%d skipped_no_match=%d skipped_no_price=%d errors=%d live=%s",
        n_total, updated, skipped_no_match, skipped_no_price, errors, args.live,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
