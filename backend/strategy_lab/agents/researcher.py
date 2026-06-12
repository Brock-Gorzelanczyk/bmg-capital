"""
Researcher Agent — daily market research and strategy analysis for BMG Capital.

Responsibilities:
  1. Detect current market regime from DB snapshots
  2. Compute rolling 63-day Information Coefficient (IC) per bot
  3. Score strategy candidates in the WFA pipeline
  4. Produce actionable research directives

Called by Queen Agent at 7 AM ET. Returns a structured research dict.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

IC_WARN_THRESHOLD = 0.02   # IC below this → signal degrading
IC_GOOD_THRESHOLD = 0.05   # IC above this → strong signal

ACTIVE_BOTS = [
    "stock_swing", "stock_day", "stock_lt",
    "crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain",
    "options_income", "options_directional",
    "crypto_quant_aggressive", "crypto_quant_scalper", "crypto_quant_mean_reversion",
    "crypto_meanrev_2163",
]

_REGIME_BEST_BOTS = {
    "bull_trending":  ["stock_swing", "stock_lt", "crypto_swing"],
    "bear_trending":  ["crypto_swing", "options_directional"],
    "choppy":         ["options_income", "crypto_quant_mean_reversion"],
    "crisis":         ["options_directional", "crypto_quant_mean_reversion"],
    "complacency":    ["options_income", "crypto_quant_aggressive"],
    "neutral":        ["stock_swing", "crypto_swing", "options_income"],
    "unknown":        [],
}


def _regime_from_db(db: Session) -> dict:
    """Load latest regime snapshot and classify into a human-readable regime name."""
    try:
        from app.db.models.bots import RegimeSnapshot
        snap = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).first()
        if not snap:
            return {"name": "unknown", "vix": None, "trend": "unknown", "btc_dom": None}

        vix = snap.vix_value
        trend = (snap.trend_regime or "unknown").lower()
        vix_regime = (snap.vix_regime or "unknown").lower()
        btc_dom = snap.btc_dominance

        if vix and vix > 30:
            regime_name = "crisis"
        elif vix and vix < 12:
            regime_name = "complacency"
        elif "bull" in trend:
            regime_name = "bull_trending"
        elif "bear" in trend:
            regime_name = "bear_trending"
        elif "chop" in vix_regime or "sideways" in trend:
            regime_name = "choppy"
        else:
            regime_name = "neutral"

        return {
            "name": regime_name,
            "vix": vix,
            "trend": snap.trend_regime or "unknown",
            "vix_regime": snap.vix_regime or "unknown",
            "btc_dom": btc_dom,
            "ts": snap.ts.isoformat() if snap.ts else None,
        }
    except Exception as exc:
        logger.warning("[researcher] regime query failed: %s", exc)
        return {"name": "unknown", "vix": None, "trend": "unknown", "btc_dom": None}


def _compute_bot_ic(db: Session, bot_name: str, lookback_days: int = 63) -> Optional[float]:
    """
    Rolling Information Coefficient for a bot (63-day window).

    IC = 2 * win_rate - 1, derived from closed trades with realized P&L.
    Returns None when fewer than 10 trades exist (insufficient data).
    """
    try:
        from app.db.models.bots import BotProfile, BotAllocation, BotTrade
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
        if not prof:
            return None

        alloc_ids = [
            a.id for a in db.query(BotAllocation).filter(
                BotAllocation.profile_id == prof.id,
                BotAllocation.enabled.is_(True),
            ).all()
        ]
        if not alloc_ids:
            return None

        trades = db.query(BotTrade).filter(
            BotTrade.allocation_id.in_(alloc_ids),
            BotTrade.side == "sell",
            BotTrade.created_at >= cutoff,
            BotTrade.pnl_cents.isnot(None),
        ).all()

        if len(trades) < 10:
            return None

        wins = sum(1 for t in trades if (t.pnl_cents or 0) > 0)
        ic = 2 * (wins / len(trades)) - 1
        return round(ic, 4)
    except Exception as exc:
        logger.warning("[researcher] IC compute failed for %s: %s", bot_name, exc)
        return None


def _score_candidates(db: Session) -> list[dict]:
    """Pull WFA results for top candidates. Gracefully returns [] if table absent."""
    try:
        from sqlalchemy import text
        rows = db.execute(text("""
            SELECT strategy, wfe, oos_sharpe, pbo, dsr, promotion_status, updated_at
            FROM strategy_wfa_results
            ORDER BY oos_sharpe DESC
            LIMIT 10
        """)).fetchall()

        return [
            {
                "strategy":   row[0],
                "wfe":        round(row[1], 3) if row[1] is not None else None,
                "oos_sharpe": round(row[2], 3) if row[2] is not None else None,
                "pbo":        round(row[3], 3) if row[3] is not None else None,
                "dsr":        round(row[4], 3) if row[4] is not None else None,
                "status":     row[5],
                "updated_at": str(row[6])[:10] if row[6] else None,
            }
            for row in rows
        ]
    except Exception:
        return []


def _build_recommendations(regime: dict, bot_ics: dict[str, Optional[float]]) -> list[str]:
    """Actionable research directives based on regime + IC data."""
    recs: list[str] = []
    regime_name = regime.get("name", "unknown")

    preferred = _REGIME_BEST_BOTS.get(regime_name, [])
    if preferred:
        recs.append(f"Regime {regime_name} — prioritize {', '.join(preferred[:2])}")

    vix = regime.get("vix")
    if vix and vix > 25:
        recs.append(f"VIX={vix:.1f} elevated — reduce options income; favor directional/flat")
    elif vix and vix < 13:
        recs.append(f"VIX={vix:.1f} low — premium selling window open; check IVR > 30")

    btc_dom = regime.get("btc_dom")
    if btc_dom and btc_dom > 55:
        recs.append(f"BTC dominance={btc_dom:.1f}% — altcoins underperforming; stick to BTC/ETH")
    elif btc_dom and btc_dom < 45:
        recs.append(f"BTC dominance={btc_dom:.1f}% low — altcoin season; cross-sectional momentum active")

    for bot, ic in bot_ics.items():
        if ic is not None and ic < IC_WARN_THRESHOLD:
            recs.append(f"SIGNAL DECAY: {bot} IC={ic:.3f} — review strategy logic or reduce weight")
        elif ic is not None and ic > IC_GOOD_THRESHOLD:
            recs.append(f"STRONG IC: {bot} IC={ic:.3f} — consider increasing allocation weight")

    if not recs:
        recs.append("No regime-specific directives — maintain current allocations")

    return recs[:6]


def run_daily_research(db: Session) -> dict:
    """
    Main entry point called by Queen Agent at 7 AM ET.

    Returns dict with keys: regime, signal_ic, candidates, recommendations.
    """
    regime = _regime_from_db(db)

    bot_ics: dict[str, Optional[float]] = {b: _compute_bot_ic(db, b) for b in ACTIVE_BOTS}

    ic_summary = [
        {
            "bot": b,
            "ic": ic,
            "status": (
                "degrading"        if ic is not None and ic < IC_WARN_THRESHOLD else
                "strong"           if ic is not None and ic > IC_GOOD_THRESHOLD else
                "healthy"          if ic is not None else
                "insufficient_data"
            ),
        }
        for b, ic in bot_ics.items()
    ]

    candidates = _score_candidates(db)
    recommendations = _build_recommendations(regime, bot_ics)

    logger.info(
        "[researcher] regime=%s ic_bots=%d candidates=%d recs=%d",
        regime["name"], len([i for i in ic_summary if i["ic"] is not None]),
        len(candidates), len(recommendations),
    )

    return {
        "regime":          regime,
        "signal_ic":       ic_summary,
        "candidates":      candidates,
        "recommendations": recommendations,
    }
