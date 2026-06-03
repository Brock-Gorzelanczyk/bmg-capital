"""Bot execution runner.

run_bot_profile() is the single entry point called by APScheduler for each
of the six bot profiles.  It:
  1. Loads the YAML profile config.
  2. Fetches all enabled paper-mode allocations for the profile.
  3. Generates mock signals (stub — real data fetch wired in next phase).
  4. Audits non-hold signals to bot_signals.
  5. Returns a summary dict.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def run_bot_profile(profile_name: str) -> dict:
    """Execute one bot profile: fetch bars, run strategies, risk check, paper execute, audit.

    Args:
        profile_name: One of stock_swing, stock_day, stock_lt,
                      crypto_swing, crypto_day, crypto_lt.

    Returns:
        Summary dict with keys: profile, allocations, signals, ts.
        On skip: {"skipped": True, "reason": str}.
        On error: {"error": str}.
    """
    try:
        # 1. Load profile YAML
        from strategy_lab.seeds import load_profile
        profile = load_profile(profile_name)

        # 2. Get all enabled allocations for this profile
        from app.db.session import SessionLocal
        from app.db.models.bots import BotProfile, BotAllocation

        db = SessionLocal()
        try:
            bp = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
            if not bp or not bp.enabled:
                return {"skipped": True, "reason": "profile disabled or not found"}

            allocations = (
                db.query(BotAllocation)
                .filter(
                    BotAllocation.profile_id == bp.id,
                    BotAllocation.enabled.is_(True),
                    BotAllocation.paper_mode.is_(True),
                )
                .all()
            )
            if not allocations:
                return {"skipped": True, "reason": "no enabled paper allocations"}

            # 3. Generate signals
            # Stub: produces a single hold signal per run.
            # Real bar-fetch + strategy dispatch wired in the data-feed phase.
            from strategy_lab.core.signals import Signal

            default_symbol = _default_symbol_for_profile(profile_name, profile)
            signals = [
                Signal(
                    symbol=default_symbol,
                    side="hold",
                    confidence=0.5,
                    size_hint=1.0,
                    reason="Market hours signal evaluation (stub)",
                    strategy=_primary_strategy(profile_name),
                )
            ]

            # 4. Audit non-hold signals
            from strategy_lab.core.audit import log_signal

            actionable = [s for s in signals if s.side != "hold"]
            for alloc in allocations:
                for sig in actionable:
                    log_signal(db, alloc.id, sig)

            return {
                "profile": profile_name,
                "allocations": len(allocations),
                "signals": len(actionable),
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        finally:
            db.close()

    except Exception as exc:
        logger.error("Bot runner failed for %s: %s", profile_name, exc, exc_info=True)
        return {"error": str(exc)}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _default_symbol_for_profile(profile_name: str, profile: dict) -> str:
    """Pick a default symbol from the profile config, or a sensible fallback."""
    symbols = profile.get("symbols") or profile.get("universe") or []
    if symbols:
        return symbols[0]
    # Fallback map
    _defaults = {
        "stock_swing": "SPY",
        "stock_day": "SPY",
        "stock_lt": "VTI",
        "crypto_swing": "BTCUSD",
        "crypto_day": "ETHUSD",
        "crypto_lt": "BTCUSD",
    }
    return _defaults.get(profile_name, "SPY")


def _primary_strategy(profile_name: str) -> str:
    """Map profile name to its primary strategy name."""
    _map = {
        "stock_swing": "mean_reversion",
        "stock_day": "opening_range",
        "stock_lt": "factor_blend",
        "crypto_swing": "momentum_breakout",
        "crypto_day": "vwap_reversion",
        "crypto_lt": "dca",
    }
    return _map.get(profile_name, "mean_reversion")
