"""regime_tag.py — DRY helper for stamping BotTrade rows with the current regime.

Used at every BotTrade insert site (10 live sites) so the snapshot fetch is
never duplicated and failure is never trade-blocking.

Usage at each insert site:
    from app.services.regime_tag import regime_tag_dict
    _rt = regime_tag_dict(db, source="runner._execute_signal")
    trade = BotTrade(
        allocation_id=alloc.id,
        ...,
        **_rt,
    )
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_UNKNOWN_REGIME = {
    "regime_vix": "UNKNOWN",
    "regime_trend": "UNKNOWN",
    "regime_btc_dom_band": "UNKNOWN",
}


def regime_tag_dict(db: Session, *, source: str = "unknown") -> dict:
    """Fetch current regime, return dict ready to splat into BotTrade(...).

    Returns kwargs:
        {"regime_vix": ..., "regime_trend": ..., "regime_btc_dom_band": ...}

    Never raises — if snapshot() fails for any reason, all 3 keys default to
    "UNKNOWN" (not NULL). Trade insert is never blocked by regime fetch failure.

    Args:
        db:     Active SQLAlchemy session.
        source: Caller identifier for log messages (e.g. "runner._execute_signal").
    """
    try:
        from app.services.regime_snapshot import snapshot as _snap
        r = _snap(db)
        return {
            "regime_vix": r["vix_band"],
            "regime_trend": r["trend"],
            "regime_btc_dom_band": r["btc_dom_band"],
        }
    except Exception as exc:
        logger.warning("[regime_tag:%s] snapshot failed: %s", source, exc)
        return dict(_UNKNOWN_REGIME)
