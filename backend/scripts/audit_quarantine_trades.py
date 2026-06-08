"""
Audit all open BotPositions for stale entry prices.

For each open position, compare avg_cost_cents against the live ticker.
Positions where |entry - live| / live > 20% are quarantined:
  - BotPosition.quarantined_at set to now
  - BotPosition.quarantine_reason set to deviation description
  - All linked open-entry BotTrades quarantined the same way

Run on production:
  railway ssh --service disciplined-intuition -i ~/.ssh/id_ed25519 -- \
    "cd /app && python scripts/audit_quarantine_trades.py [--dry-run]"
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_THRESHOLD = 0.20  # 20%


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print findings without writing to DB")
    args = parser.parse_args()

    # ── DB connection ─────────────────────────────────────────────────────────
    db_url = os.environ.get("DATABASE_URL", "sqlite:////data/bmg_capital.db")
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {}

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url, connect_args=connect_args)
    Session = sessionmaker(bind=engine)
    db = Session()

    # ── Fetch all open positions ──────────────────────────────────────────────
    from app.db.models.bots import BotPosition, BotTrade, BotAllocation, BotProfile

    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .all()
    )

    logger.info("Open positions to audit: %d", len(open_positions))

    # ── Batch-fetch live prices ───────────────────────────────────────────────
    symbols = list({pos.symbol for pos in open_positions})
    logger.info("Fetching live prices for %d symbols: %s", len(symbols), symbols)

    live_prices: dict[str, float] = {}
    try:
        from app.services.live_prices import fetch_live_prices
        raw = fetch_live_prices(symbols)
        live_prices = {sym: float(raw[sym] or 0) for sym in symbols if raw.get(sym)}
        logger.info("Live prices received: %s", {k: round(v, 4) for k, v in live_prices.items()})
    except Exception as exc:
        logger.error("Failed to fetch live prices: %s", exc)
        sys.exit(1)

    # ── Audit each position ───────────────────────────────────────────────────
    dirty: list[dict] = []
    clean: list[dict] = []
    unavailable: list[str] = []

    now = datetime.now(timezone.utc)

    for pos in open_positions:
        live = live_prices.get(pos.symbol, 0)
        entry = pos.avg_cost_cents / 100.0

        if live <= 0:
            logger.warning("  SKIP %s (pos #%d) — live price unavailable", pos.symbol, pos.id)
            unavailable.append(pos.symbol)
            continue

        deviation = abs(entry - live) / live

        alloc = db.get(BotAllocation, pos.allocation_id)
        profile_name = "unknown"
        if alloc:
            prof = db.get(BotProfile, alloc.profile_id)
            if prof:
                profile_name = prof.name

        record = {
            "pos_id": pos.id,
            "bot": profile_name,
            "symbol": pos.symbol,
            "entry_usd": round(entry, 4),
            "live_usd": round(live, 4),
            "deviation_pct": round(deviation * 100, 2),
        }

        if deviation > _THRESHOLD:
            dirty.append(record)
        else:
            clean.append(record)

    # ── Report ────────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("═══ AUDIT RESULTS ═══")
    logger.info("  Clean positions  : %d", len(clean))
    logger.info("  Dirty positions  : %d", len(dirty))
    logger.info("  Unavailable price: %d", len(unavailable))
    logger.info("")

    if dirty:
        logger.info("DIRTY POSITIONS (will be quarantined):")
        for d in dirty:
            logger.info(
                "  pos#%d  bot=%-30s  %s  entry=$%-8.2f  live=$%-8.2f  deviation=%.1f%%",
                d["pos_id"], d["bot"], d["symbol"], d["entry_usd"], d["live_usd"], d["deviation_pct"],
            )
    else:
        logger.info("No dirty positions found.")

    if args.dry_run:
        logger.info("")
        logger.info("DRY RUN — no changes written.")
        return

    # ── Quarantine dirty positions + their trades ─────────────────────────────
    quarantined_positions = 0
    quarantined_trades = 0

    for d in dirty:
        pos = db.get(BotPosition, d["pos_id"])
        if not pos:
            continue

        reason = (
            f"SANITY_FAIL: entry=${d['entry_usd']:.4f} "
            f"deviates {d['deviation_pct']:.1f}% from live=${d['live_usd']:.4f} "
            f"(threshold={int(_THRESHOLD*100)}%) "
            f"audited {now.isoformat()}"
        )

        pos.quarantined_at = now
        pos.quarantine_reason = reason
        db.add(pos)
        quarantined_positions += 1

        # Quarantine the entry trade(s) linked to this position
        trades = (
            db.query(BotTrade)
            .filter(
                BotTrade.position_id == pos.id,
                BotTrade.side == "buy",
                BotTrade.quarantined_at.is_(None),
            )
            .all()
        )
        for trade in trades:
            trade.quarantined_at = now
            trade.quarantine_reason = reason
            db.add(trade)
            quarantined_trades += 1

    db.commit()

    logger.info("")
    logger.info("Quarantined: %d positions, %d trades", quarantined_positions, quarantined_trades)
    logger.info("Done.")


if __name__ == "__main__":
    main()
