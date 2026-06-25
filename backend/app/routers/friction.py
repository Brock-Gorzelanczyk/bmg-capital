"""
/api/admin/friction/* — apply COMMIT 12's V1 friction model retroactively
to historical bot_trades, writing to bot_trades.modeled_fees_cents (added
in migration m019). DOES NOT touch the live fees_cents column.

POST /friction/backfill?batch=1000  — applies friction to up to <batch>
                                       trades with modeled_fees_cents IS NULL.
                                       Returns count processed.
GET  /friction/summary               — total modeled friction across all
                                       bot_trades, broken down by asset_class.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/friction", tags=["admin"])


@router.post("/backfill")
def backfill_friction(
    batch: int = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Apply V1 friction model to historical bot_trades. Batched."""
    from app.services.friction import model_friction_cents

    # Join to bot_allocations + bot_profiles to recover asset_class per trade.
    # Trades with NULL modeled_fees_cents are the unprocessed set.
    rows = db.execute(sql_text("""
        SELECT bt.id, bt.qty, bt.fill_price_cents, COALESCE(p.asset_class, 'stock') AS ac,
               bp.contract_count
          FROM bot_trades bt
          JOIN bot_allocations a ON a.id = bt.allocation_id
          JOIN bot_profiles p ON p.id = a.profile_id
          LEFT JOIN bot_positions bp ON bp.id = bt.position_id
         WHERE bt.modeled_fees_cents IS NULL
         ORDER BY bt.id ASC
         LIMIT :n
    """), {"n": batch}).fetchall()

    processed = 0
    for trade_id, qty, fill_cents, ac, contracts in rows:
        if qty is None or fill_cents is None:
            # Edge case — still mark as zero so we don't keep re-trying.
            db.execute(sql_text(
                "UPDATE bot_trades SET modeled_fees_cents = 0 WHERE id = :id"
            ), {"id": trade_id})
            processed += 1
            continue
        friction = model_friction_cents(
            asset_class=ac,
            qty=float(qty),
            fill_price_dollars=float(fill_cents) / 100.0,
            contracts=float(contracts or 0),
        )
        db.execute(sql_text(
            "UPDATE bot_trades SET modeled_fees_cents = :f WHERE id = :id"
        ), {"f": int(friction), "id": trade_id})
        processed += 1

    db.commit()

    # Remaining count after this batch
    remaining = db.execute(sql_text(
        "SELECT COUNT(*) FROM bot_trades WHERE modeled_fees_cents IS NULL"
    )).scalar() or 0

    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[friction.backfill] batch complete",
            message=(
                f"Processed {processed} trades, {remaining} remaining.\n"
                f"Run POST /api/admin/friction/backfill again to continue."
            ),
            severity="info",
            source="friction.backfill",
        )
    except Exception:
        pass

    return {
        "processed": processed,
        "remaining": int(remaining),
        "batch_size": batch,
        "more": int(remaining) > 0,
    }


@router.get("/summary")
def friction_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Aggregate modeled friction by asset_class."""
    try:
        rows = db.execute(sql_text("""
            SELECT COALESCE(p.asset_class, 'stock') AS ac,
                   COUNT(bt.id) AS trade_count,
                   COALESCE(SUM(bt.modeled_fees_cents), 0) AS modeled_fees_cents,
                   COALESCE(SUM(bt.fees_cents), 0) AS recorded_fees_cents
              FROM bot_trades bt
              JOIN bot_allocations a ON a.id = bt.allocation_id
              JOIN bot_profiles p ON p.id = a.profile_id
             GROUP BY ac
             ORDER BY modeled_fees_cents DESC
        """)).fetchall()
    except Exception as exc:
        return {"error": str(exc), "by_asset_class": []}

    total_modeled = sum(int(r[2] or 0) for r in rows)
    total_recorded = sum(int(r[3] or 0) for r in rows)
    backfill_remaining = db.execute(sql_text(
        "SELECT COUNT(*) FROM bot_trades WHERE modeled_fees_cents IS NULL"
    )).scalar() or 0

    return {
        "by_asset_class": [
            {
                "asset_class": r[0],
                "trade_count": int(r[1] or 0),
                "modeled_fees_cents": int(r[2] or 0),
                "recorded_fees_cents": int(r[3] or 0),
            }
            for r in rows
        ],
        "total_modeled_fees_cents": total_modeled,
        "total_recorded_fees_cents": total_recorded,
        "backfill_remaining_trades": int(backfill_remaining),
    }
