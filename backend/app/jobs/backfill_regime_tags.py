"""backfill_regime_tags.py — one-shot backfill of regime tags on historical bot_trades.

For each bot_trades row where regime_vix IS NULL, finds the closest
regime_snapshots row by ts within ±window_hours. Maps raw snapshot fields
through the same _VIX_MAP / _TREND_MAP / btc_dom_band helpers as the live
regime_snapshot.snapshot() service. If no snapshot is within the window,
stamps all 3 columns "UNKNOWN" (never leaves NULL — NULL means "pre-m049",
UNKNOWN means "we tried").

Gated via _gate.already_ran("backfill_regime_tags_2026_06") — wired in
main.py AFTER m049 to guarantee columns exist before this runs.

Standing decisions honored:
  - UPDATE only on bot_trades — no DELETE, no INSERT.
  - Does not touch regime_snapshots (read-only).
  - Does not touch bot_allocations / bot_profiles / bot_daily_pnl.
  - No user_id filter — bot_trades has no user_id column; backfill is global.
  - One commit per batch (not one giant transaction).
  - Gate NOT recorded if verify_null_after > 0 (retry behavior preserved).
  - Timezone-aware throughout (UTC).
"""
from __future__ import annotations

import logging
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Import maps from regime_snapshot — single source of truth.
from app.services.regime_snapshot import _VIX_MAP, _TREND_MAP, btc_dom_band as _btc_dom_band_fn


def run_backfill(
    db: Session,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
    window_hours: int = 2,
) -> dict:
    """Backfill regime_vix / regime_trend / regime_btc_dom_band on every
    bot_trades row where regime_vix IS NULL.

    For each NULL row, find the closest regime_snapshots row by ts within
    ±window_hours. If found, map raw fields via the same _VIX_MAP / _TREND_MAP
    / btc_dom_band helpers. If no snapshot within window, stamp all 3 columns
    'UNKNOWN' (never leave NULL — NULL means 'pre-m049', UNKNOWN means 'we tried').

    Returns:
      {
        "rows_scanned": int,
        "rows_tagged_real": int,
        "rows_tagged_unknown": int,
        "batches_committed": int,
        "dry_run": bool,
        "verify_null_after": int,   # 0 == fully backfilled
      }
    """
    from app.db.models.bots import BotTrade, RegimeSnapshot

    # ── 1. Pre-load all regime_snapshots into memory sorted by ts ─────────────
    try:
        snaps = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.asc()).all()
    except Exception as exc:
        logger.error("[backfill_regime] failed to load regime_snapshots: %s", exc)
        snaps = []

    # Build parallel arrays for bisect (tz-aware UTC datetimes)
    snap_ts_list: list[datetime] = []
    snap_rows: list = []
    for s in snaps:
        ts = s.ts
        if ts is None:
            continue
        if isinstance(ts, str):
            # SQLite may return string; parse it
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        snap_ts_list.append(ts)
        snap_rows.append(s)

    logger.warning(
        "[backfill_regime] pre-loaded %d regime_snapshots into memory (window=±%dh, dry_run=%s)",
        len(snap_rows), window_hours, dry_run,
    )

    window_delta = timedelta(hours=window_hours)
    rows_scanned = 0
    rows_tagged_real = 0
    rows_tagged_unknown = 0
    batches_committed = 0

    # ── 2. Batched UPDATE loop ─────────────────────────────────────────────────
    while True:
        batch = (
            db.query(BotTrade)
            .filter(BotTrade.regime_vix.is_(None))
            .order_by(BotTrade.ts.asc())
            .limit(batch_size)
            .all()
        )
        if not batch:
            break

        for trade in batch:
            rows_scanned += 1

            # Coerce trade.ts to tz-aware UTC
            trade_ts = trade.ts
            if trade_ts is None:
                vix, trend, btc = ("UNKNOWN", "UNKNOWN", "UNKNOWN")
                rows_tagged_unknown += 1
            elif not snap_ts_list:
                vix, trend, btc = ("UNKNOWN", "UNKNOWN", "UNKNOWN")
                rows_tagged_unknown += 1
            else:
                if isinstance(trade_ts, str):
                    try:
                        trade_ts = datetime.fromisoformat(trade_ts)
                    except ValueError:
                        vix, trend, btc = ("UNKNOWN", "UNKNOWN", "UNKNOWN")
                        rows_tagged_unknown += 1
                        trade.regime_vix = vix
                        trade.regime_trend = trend
                        trade.regime_btc_dom_band = btc
                        continue
                if trade_ts.tzinfo is None:
                    trade_ts = trade_ts.replace(tzinfo=timezone.utc)

                # bisect to find insertion point in sorted snap_ts_list
                idx = bisect_left(snap_ts_list, trade_ts)

                # Check candidates idx-1 and idx for closest within window
                best = None
                best_delta = None
                for candidate_idx in (idx - 1, idx):
                    if 0 <= candidate_idx < len(snap_ts_list):
                        delta = abs(trade_ts - snap_ts_list[candidate_idx])
                        if delta <= window_delta:
                            if best_delta is None or delta < best_delta:
                                best = snap_rows[candidate_idx]
                                best_delta = delta

                if best is None:
                    vix, trend, btc = ("UNKNOWN", "UNKNOWN", "UNKNOWN")
                    rows_tagged_unknown += 1
                else:
                    vix_raw = (best.vix_regime or "").lower().strip()
                    vix = _VIX_MAP.get(vix_raw, "UNKNOWN")

                    trend_raw = (best.trend_regime or "").lower().strip()
                    trend = _TREND_MAP.get(trend_raw, "UNKNOWN")

                    if best.btc_dominance is not None:
                        try:
                            btc = _btc_dom_band_fn(float(best.btc_dominance))
                        except (TypeError, ValueError):
                            btc = "UNKNOWN"
                    else:
                        btc = "UNKNOWN"

                    rows_tagged_real += 1

            trade.regime_vix = vix
            trade.regime_trend = trend
            trade.regime_btc_dom_band = btc

        if not dry_run:
            db.commit()
            batches_committed += 1
        else:
            db.rollback()

        logger.warning(
            "[backfill_regime] batch done — scanned=%d real=%d unknown=%d committed=%d",
            rows_scanned, rows_tagged_real, rows_tagged_unknown, batches_committed,
        )

    # ── 3. Final verify ────────────────────────────────────────────────────────
    null_after = (
        db.query(BotTrade)
        .filter(BotTrade.regime_vix.is_(None))
        .count()
    )
    if null_after > 0:
        logger.critical(
            "[backfill_regime] %d NULL regime_vix rows remain after backfill — gate will NOT be recorded",
            null_after,
        )
    else:
        logger.warning("[backfill_regime] backfill complete — verify_null_after=0 (fully backfilled)")

    return {
        "rows_scanned": rows_scanned,
        "rows_tagged_real": rows_tagged_real,
        "rows_tagged_unknown": rows_tagged_unknown,
        "batches_committed": batches_committed,
        "dry_run": dry_run,
        "verify_null_after": null_after,
    }
