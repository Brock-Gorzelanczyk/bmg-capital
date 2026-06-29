"""Track record reconstruction service.

SHIP 3: After m027 wiped bot_trades, honest reconstruction is limited.
- cash_floor (SPY/QQQ single-bot mapping) gets best-effort fill attribution.
- All other bots get a track_reset_marker row so leaderboard has an anchor.

HARD CONSTRAINTS:
- NEVER DELETE FROM bot_trades
- NEVER DELETE FROM bot_daily_pnl
- Reconstruction INSERTs into bot_daily_pnl are additive only
- NEVER UPDATE existing bot_daily_pnl rows

Per spec: DO NOT call reconstruct_for_user from anywhere except:
  (a) the admin POST endpoint
  (b) the lifespan boot block in main.py (once, after m030)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TRACK_RESET_MARKER_NOTE = "track_reset_marker"
M027_RESET_DATE = date(2026, 6, 28)

# Bots with single-unambiguous Alpaca mapping (symbol does not overlap other bots).
# cash_floor is the only one: SPY + QQQ, no other bot in that universe.
_SINGLE_BOT_MAPPING_BOTS = {"cash_floor"}


def _fetch_alpaca_fills(since: date) -> list[dict]:
    """Fetches /v2/account/activities/FILL paginated. Returns list of dicts.

    Returns empty list on 429/5xx/network error. Never raises.
    """
    try:
        from strategy_lab.brokers.alpaca_paper_stocks import PaperStocksAdapter
        adapter = PaperStocksAdapter()
        raw_fills = adapter.get_activities(
            activity_type="FILL",
            after=since.isoformat(),
            page_size=100,
        )
        result = []
        for f in raw_fills:
            try:
                result.append({
                    "transaction_time": f.get("transaction_time") or f.get("date"),
                    "symbol": f.get("symbol", ""),
                    "side": f.get("side", ""),
                    "qty": float(f.get("qty", 0)),
                    "price": float(f.get("price", 0)),
                })
            except (TypeError, ValueError) as exc:
                logger.warning("[reconstruction] fill parse error: %s — fill=%r", exc, f)
        return result
    except Exception as exc:
        logger.warning("[reconstruction] _fetch_alpaca_fills error: %s", exc)
        return []


def reconstruct_from_alpaca(
    allocation_id: int,
    db: Session,
    since: Optional[date] = None,
) -> dict:
    """Pull Alpaca paper fills, group by UTC date, compute realized P&L per
    day, INSERT into bot_daily_pnl ONLY when (allocation_id, date) row absent.

    Returns:
        {"alloc_id": int, "days_reconstructed": int, "fills_fetched": int,
         "earliest_fill_date": str | None,
         "status": "reconstructed" | "no_data" | "alpaca_error" | "not_eligible"}

    NEVER deletes existing rows. NEVER overwrites.
    For now (SHIP 3): attribution is best-effort for cash_floor (SPY/QQQ single-bot
    mapping) only. For other bots: returns status="no_data" because multi-bot
    symbol overlap blocks honest attribution post-m027 wipe.
    """
    if since is None:
        since = M027_RESET_DATE

    # Check which bot this allocation belongs to
    alloc_row = db.execute(
        text(
            "SELECT ba.id, bp.name AS bot_name "
            "FROM bot_allocations ba "
            "LEFT JOIN bot_profiles bp ON bp.id = ba.profile_id "
            "WHERE ba.id = :aid"
        ),
        {"aid": allocation_id},
    ).fetchone()

    if alloc_row is None:
        return {
            "alloc_id": allocation_id,
            "days_reconstructed": 0,
            "fills_fetched": 0,
            "earliest_fill_date": None,
            "status": "no_data",
        }

    bot_name = alloc_row[1] or ""

    # Only cash_floor gets Alpaca fill reconstruction (spec: honest beats clever)
    if bot_name not in _SINGLE_BOT_MAPPING_BOTS:
        return {
            "alloc_id": allocation_id,
            "days_reconstructed": 0,
            "fills_fetched": 0,
            "earliest_fill_date": None,
            "status": "not_eligible",
        }

    # Fetch fills from Alpaca
    fills = _fetch_alpaca_fills(since)
    if not fills:
        return {
            "alloc_id": allocation_id,
            "days_reconstructed": 0,
            "fills_fetched": 0,
            "earliest_fill_date": None,
            "status": "no_data",
        }

    # Group fills by UTC date, compute realized P&L per day
    # For paired buy/sell: realized = sell_proceeds - buy_cost (simplified)
    # We use fill-level realized: side='sell' contributes qty * price, 'buy' subtracts
    daily_realized: dict[str, int] = {}
    for fill in fills:
        ts_str = fill.get("transaction_time")
        if not ts_str:
            continue
        try:
            if "T" in str(ts_str):
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(str(ts_str), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            fill_date = dt.date().isoformat()
        except (ValueError, TypeError):
            continue

        qty = fill.get("qty", 0.0) or 0.0
        price = fill.get("price", 0.0) or 0.0
        side = (fill.get("side") or "").lower()

        realized_cents = int(qty * price * 100)
        if side in ("sell", "sell_short"):
            daily_realized[fill_date] = daily_realized.get(fill_date, 0) + realized_cents
        elif side in ("buy", "buy_to_cover"):
            daily_realized[fill_date] = daily_realized.get(fill_date, 0) - realized_cents

    if not daily_realized:
        return {
            "alloc_id": allocation_id,
            "days_reconstructed": 0,
            "fills_fetched": len(fills),
            "earliest_fill_date": None,
            "status": "no_data",
        }

    # Insert only where (allocation_id, date) does not already exist
    days_reconstructed = 0
    earliest_fill_date = None

    for fill_date_str, realized_cents in sorted(daily_realized.items()):
        existing = db.execute(
            text(
                "SELECT id FROM bot_daily_pnl "
                "WHERE allocation_id = :aid AND date = :d"
            ),
            {"aid": allocation_id, "d": fill_date_str},
        ).fetchone()

        if existing is not None:
            continue  # never overwrite

        # Get inception snapshot for this allocation
        snap_row = db.execute(
            text(
                "SELECT COALESCE(inception_capital_cents, starting_capital_cents, 0) "
                "FROM bot_allocations WHERE id = :aid"
            ),
            {"aid": allocation_id},
        ).fetchone()
        inception_snap = int(snap_row[0] or 0) if snap_row else 0

        db.execute(
            text(
                "INSERT INTO bot_daily_pnl "
                "(allocation_id, date, realized_cents, unrealized_cents, fees_cents, "
                " inception_capital_cents_snapshot) "
                "VALUES (:aid, :d, :r, 0, 0, :snap)"
            ),
            {
                "aid": allocation_id,
                "d": fill_date_str,
                "r": realized_cents,
                "snap": inception_snap,
            },
        )
        days_reconstructed += 1
        if earliest_fill_date is None or fill_date_str < earliest_fill_date:
            earliest_fill_date = fill_date_str

    db.commit()

    status = "reconstructed" if days_reconstructed > 0 else "no_data"
    logger.info(
        "[reconstruction] alloc=%d bot=%s fills=%d days_reconstructed=%d status=%s",
        allocation_id, bot_name, len(fills), days_reconstructed, status,
    )

    return {
        "alloc_id": allocation_id,
        "days_reconstructed": days_reconstructed,
        "fills_fetched": len(fills),
        "earliest_fill_date": earliest_fill_date,
        "status": status,
    }


def insert_track_reset_marker(
    allocation_id: int,
    db: Session,
    reset_date: date = M027_RESET_DATE,
    note: str = TRACK_RESET_MARKER_NOTE,
) -> dict:
    """Insert a single zero-PnL marker row into bot_daily_pnl per allocation
    so leaderboard logic has a row to anchor "since reset" context.

    INSERT is idempotent: skips if a marker row already exists for this allocation.
    Returns:
        {"alloc_id": int, "marker_inserted": bool,
         "existing_marker_date": str | None}
    """
    reset_date_str = reset_date.isoformat()

    # Check for existing marker
    existing = db.execute(
        text(
            "SELECT id, date FROM bot_daily_pnl "
            "WHERE allocation_id = :aid AND note = :note "
            "ORDER BY date ASC LIMIT 1"
        ),
        {"aid": allocation_id, "note": note},
    ).fetchone()

    if existing is not None:
        return {
            "alloc_id": allocation_id,
            "marker_inserted": False,
            "existing_marker_date": str(existing[1]),
        }

    # Get inception snapshot
    snap_row = db.execute(
        text(
            "SELECT COALESCE(inception_capital_cents, starting_capital_cents, 0) "
            "FROM bot_allocations WHERE id = :aid"
        ),
        {"aid": allocation_id},
    ).fetchone()
    inception_snap = int(snap_row[0] or 0) if snap_row else 0

    # Insert marker row (realized=0, the marker lives in the note column)
    try:
        db.execute(
            text(
                "INSERT INTO bot_daily_pnl "
                "(allocation_id, date, realized_cents, unrealized_cents, fees_cents, "
                " inception_capital_cents_snapshot, note) "
                "VALUES (:aid, :d, 0, 0, 0, :snap, :note)"
            ),
            {
                "aid": allocation_id,
                "d": reset_date_str,
                "snap": inception_snap,
                "note": note,
            },
        )
        db.commit()
        logger.info("[reconstruction] inserted track_reset_marker for alloc=%d date=%s", allocation_id, reset_date_str)
        return {
            "alloc_id": allocation_id,
            "marker_inserted": True,
            "existing_marker_date": None,
        }
    except Exception as exc:
        logger.warning("[reconstruction] insert_track_reset_marker failed alloc=%d: %s", allocation_id, exc)
        db.rollback()
        return {
            "alloc_id": allocation_id,
            "marker_inserted": False,
            "existing_marker_date": None,
        }


def reconstruct_for_user(user_id: int, db: Session) -> dict:
    """Top-level entry point. For each enabled allocation:
      1. Try reconstruct_from_alpaca. If days_reconstructed > 0, log success.
      2. Else insert_track_reset_marker.

    Returns:
        {"user_id": int,
         "per_alloc": [
            {"alloc_id": int, "bot_name": str,
             "days_reconstructed": int, "marker_inserted": bool,
             "status": str}
         ],
         "total_days_reconstructed": int,
         "total_markers_inserted": int}
    """
    allocs = db.execute(
        text(
            "SELECT ba.id, bp.name AS bot_name "
            "FROM bot_allocations ba "
            "LEFT JOIN bot_profiles bp ON bp.id = ba.profile_id "
            "WHERE ba.user_id = :uid AND ba.enabled = 1"
        ),
        {"uid": user_id},
    ).fetchall()

    per_alloc = []
    total_days_reconstructed = 0
    total_markers_inserted = 0

    for alloc_row in allocs:
        alloc_id = alloc_row[0]
        bot_name = alloc_row[1] or f"alloc_{alloc_id}"

        # Step 1: try Alpaca reconstruction
        recon_result = reconstruct_from_alpaca(alloc_id, db)
        days_reconstructed = recon_result.get("days_reconstructed", 0)
        status = recon_result.get("status", "no_data")

        # Step 2: if no days were reconstructed, insert marker
        marker_inserted = False
        if days_reconstructed == 0:
            marker_result = insert_track_reset_marker(alloc_id, db)
            marker_inserted = marker_result.get("marker_inserted", False)
            if marker_inserted:
                total_markers_inserted += 1

        total_days_reconstructed += days_reconstructed

        per_alloc.append({
            "alloc_id": alloc_id,
            "bot_name": bot_name,
            "days_reconstructed": days_reconstructed,
            "marker_inserted": marker_inserted,
            "status": status,
        })

    logger.info(
        "[reconstruction] user=%d allocs=%d total_days=%d total_markers=%d",
        user_id, len(allocs), total_days_reconstructed, total_markers_inserted,
    )

    return {
        "user_id": user_id,
        "per_alloc": per_alloc,
        "total_days_reconstructed": total_days_reconstructed,
        "total_markers_inserted": total_markers_inserted,
    }
