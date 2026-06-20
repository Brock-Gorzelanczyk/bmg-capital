"""
Quarantine trade #9084 — legacy misrouted share order.

This trade was executed by the options bot before the options-execution
fix (commit 17aa7f3). It bought AMD shares instead of an options contract
(the broker API returned a share fill when an options order was intended).
It has no option_type, strike, or expiry and should not appear in options
P&L or the trade detail UI.

Run:
  railway ssh --service disciplined-intuition -i ~/.ssh/id_ed25519 -- \
    "cd /app && python scripts/quarantine_trade_9084.py [--dry-run]"
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

TRADE_ID = 9084
REASON = "legacy_misrouted_share_order_pre_options_fix"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from app.db.session import SessionLocal
    from app.db.models.bots import BotTrade, BotPosition

    db = SessionLocal()
    try:
        trade = db.get(BotTrade, TRADE_ID)
        if not trade:
            logger.error("Trade #%d not found", TRADE_ID)
            return

        logger.info(
            "Trade #%d: symbol=%s side=%s qty=%s option_type=%s quarantined_at=%s quarantine_reason=%s",
            trade.id, trade.symbol, trade.side, trade.qty,
            trade.option_type, trade.quarantined_at, trade.quarantine_reason,
        )

        if trade.quarantined_at:
            logger.info("Already quarantined — nothing to do.")
            return

        if args.dry_run:
            logger.info("[DRY RUN] Would quarantine trade #%d with reason: %s", TRADE_ID, REASON)
            return

        now = datetime.now(timezone.utc)
        trade.quarantined_at = now
        trade.quarantine_reason = REASON

        # Also quarantine the linked position if present
        if trade.position_id:
            pos = db.get(BotPosition, trade.position_id)
            if pos and not pos.quarantined_at:
                pos.quarantined_at = now
                pos.quarantine_reason = REASON
                logger.info("Quarantined linked BotPosition #%d", trade.position_id)

        db.commit()
        logger.info("Quarantined trade #%d successfully.", TRADE_ID)

    except Exception as exc:
        db.rollback()
        logger.error("Failed: %s", exc, exc_info=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
