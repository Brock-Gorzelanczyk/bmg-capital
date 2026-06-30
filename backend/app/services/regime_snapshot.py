"""regime_snapshot.py — read latest RegimeSnapshot and map to journal-friendly bands.

Pure read, no writes. Returns "UNKNOWN" for each key when the table is empty
or the row is stale (>2 hours old) — so data gaps are visible rather than
silently masked.

Mapping rules (from spec + discipline.py precedent):
  vix_regime:   low  → LOW | mid → MID | high → HIGH | panic → HIGH
  trend_regime: bull → UP  | chop → CHOP | bear → DOWN
  btc_dominance (0-1 float, or 0-100 — coerced to 0-1):
    <0.50   → "<50"
    0.50-0.55 → "50-55"
    0.55-0.60 → "55-60"
    0.60-0.65 → "60-65"
    >0.65   → ">65"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_STALE_THRESHOLD_HOURS = 2

_VIX_MAP = {
    "low": "LOW",
    "mid": "MID",
    "high": "HIGH",
    "panic": "HIGH",
}

_TREND_MAP = {
    "bull": "UP",
    "chop": "CHOP",
    "bear": "DOWN",
}


def _btc_dom_band(btc: float) -> str:
    """Map btc_dominance float to a band string.

    Accepts either 0-1 (proportion) or 0-100 (percent) — coerces to 0-1.
    """
    if btc > 1.0:
        btc = btc / 100.0
    if btc < 0.50:
        return "<50"
    elif btc < 0.55:
        return "50-55"
    elif btc < 0.60:
        return "55-60"
    elif btc < 0.65:
        return "60-65"
    else:
        return ">65"


def snapshot(db: Session) -> dict:
    """Return {vix_band, trend, btc_dom_band} from the latest RegimeSnapshot row.

    All values are "UNKNOWN" when:
      - regime_snapshots table is empty (fresh deploy), OR
      - the most recent row is older than _STALE_THRESHOLD_HOURS (2h).

    Pure read — no writes to any table.
    """
    from app.db.models.bots import RegimeSnapshot

    try:
        row = (
            db.query(RegimeSnapshot)
            .order_by(RegimeSnapshot.ts.desc())
            .first()
        )
    except Exception as exc:
        logger.warning("[regime_snapshot] DB query failed: %s", exc)
        return {"vix_band": "UNKNOWN", "trend": "UNKNOWN", "btc_dom_band": "UNKNOWN"}

    if row is None:
        logger.info("[regime_snapshot] regime_snapshots table is empty — returning UNKNOWN")
        return {"vix_band": "UNKNOWN", "trend": "UNKNOWN", "btc_dom_band": "UNKNOWN"}

    # Staleness check
    now_utc = datetime.now(timezone.utc)
    ts = row.ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = now_utc - ts
    if age > timedelta(hours=_STALE_THRESHOLD_HOURS):
        logger.warning(
            "[regime_snapshot] latest row is %.1f hours old (stale >%dh) — returning UNKNOWN",
            age.total_seconds() / 3600,
            _STALE_THRESHOLD_HOURS,
        )
        return {"vix_band": "UNKNOWN", "trend": "UNKNOWN", "btc_dom_band": "UNKNOWN"}

    # Map vix_band
    vix_raw = (row.vix_regime or "").lower().strip()
    vix_band = _VIX_MAP.get(vix_raw, "UNKNOWN")
    if vix_band == "UNKNOWN":
        logger.warning("[regime_snapshot] unknown vix_regime=%r — returning UNKNOWN for vix_band", vix_raw)

    # Map trend
    trend_raw = (row.trend_regime or "").lower().strip()
    trend = _TREND_MAP.get(trend_raw, "UNKNOWN")
    if trend == "UNKNOWN":
        logger.warning("[regime_snapshot] unknown trend_regime=%r — returning UNKNOWN for trend", trend_raw)

    # Map btc_dom_band
    btc_raw = row.btc_dominance
    if btc_raw is None:
        btc_dom_band = "UNKNOWN"
    else:
        try:
            btc_dom_band = _btc_dom_band(float(btc_raw))
        except (TypeError, ValueError):
            logger.warning("[regime_snapshot] invalid btc_dominance=%r", btc_raw)
            btc_dom_band = "UNKNOWN"

    return {
        "vix_band": vix_band,
        "trend": trend,
        "btc_dom_band": btc_dom_band,
    }
