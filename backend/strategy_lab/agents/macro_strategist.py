"""
Macro Strategist Agent — daily regime classification for BMG Capital.

Responsibilities:
  1. Pull latest market indicators (VIX, SPY trend, HY spread proxy, BTC dominance)
  2. Classify composite regime: bull_trending | bear_trending | choppy | crisis | complacency | neutral
  3. Detect regime transitions vs. prior day
  4. Store snapshot in regime_snapshots (regime_history model)
  5. Post summary to Discord #macro-view (falls back to dev-log if channel not set)
  6. Publish heartbeat to agent_messages bus

Called by: POST /api/agents/macro-strategist/run-classification
Also triggered by: Queen Agent daily standup at 7 AM ET
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_REGIME_EMOJI = {
    "bull_trending":  "🟢",
    "bear_trending":  "🔴",
    "choppy":         "🟡",
    "crisis":         "🔴",
    "complacency":    "🟠",
    "neutral":        "⚪",
    "unknown":        "❓",
}

_REGIME_LABEL = {
    "bull_trending":  "Bull Trending",
    "bear_trending":  "Bear Trending",
    "choppy":         "Choppy / Sideways",
    "crisis":         "Crisis / Risk-Off",
    "complacency":    "Complacency / Low-Vol",
    "neutral":        "Neutral",
    "unknown":        "Unknown",
}

_VIX_THRESHOLDS = {
    "crisis":      30,
    "elevated":    20,
    "normal":      15,
    "complacency": 12,
}


def _get_macro_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_MACRO_VIEW", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
        or os.getenv("DISCORD_CH_DAILY_DIGEST", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
        channel_id = (
            getattr(settings, "discord_ch_macro_view", "")
            or settings.discord_ch_dev_log
            or settings.discord_ch_daily_digest
            or channel_id
        )
    except Exception:
        pass
    return token, channel_id


def _post_discord(token: str, channel_id: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    try:
        import httpx
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json={"embeds": [embed]},
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[macro_strategist] Discord post failed: %s", exc)
        return False


def _read_live_indicators(db: Session) -> dict:
    """
    Read latest market indicators from existing DB tables.
    Primary source: bots.RegimeSnapshot (updated by risk_sentinel + strategy modules).
    Fallback: zeros.
    """
    try:
        from app.db.models.bots import RegimeSnapshot as LiveSnap
        snap = db.query(LiveSnap).order_by(LiveSnap.ts.desc()).first()
        if not snap:
            return {}
        return {
            "vix":          snap.vix_value,
            "vix_regime":   snap.vix_regime or "unknown",
            "trend_regime": snap.trend_regime or "unknown",
            "vol_pctile":   snap.vol_pctile,
            "btc_dom":      snap.btc_dominance,
            "btc_funding":  snap.btc_funding_rate,
            "spy_price":    snap.spy_price,
            "as_of":        snap.ts.isoformat() if snap.ts else None,
        }
    except Exception as exc:
        logger.warning("[macro_strategist] live indicators read failed: %s", exc)
        return {}


def _read_yesterday_regime(db: Session) -> Optional[str]:
    """Return the most recent stored regime label for transition detection."""
    try:
        from app.db.models.regime_history import RegimeSnapshot as HistSnap
        row = db.query(HistSnap).order_by(HistSnap.snapshot_date.desc()).first()
        return row.regime if row else None
    except Exception:
        return None


def _classify_regime(indicators: dict) -> tuple[str, float, dict]:
    """
    Classify composite market regime from raw indicators.
    Returns (regime_name, confidence_0_to_1, signals_dict).
    """
    vix    = indicators.get("vix")
    trend  = (indicators.get("trend_regime") or "unknown").lower()
    vix_r  = (indicators.get("vix_regime") or "unknown").lower()
    vol_p  = indicators.get("vol_pctile")

    signals: dict = {
        "vix":          vix,
        "trend_regime": trend,
        "vix_regime":   vix_r,
        "vol_pctile":   vol_p,
        "btc_dom":      indicators.get("btc_dom"),
        "btc_funding":  indicators.get("btc_funding"),
    }

    # Score-based classification
    confidence = 0.60  # baseline

    if vix is not None and vix > _VIX_THRESHOLDS["crisis"]:
        regime = "crisis"
        confidence = 0.90
    elif vix is not None and vix < _VIX_THRESHOLDS["complacency"]:
        regime = "complacency"
        confidence = 0.80
    elif "bull" in trend:
        regime = "bull_trending"
        confidence = 0.75 if (vol_p is None or vol_p < 0.60) else 0.65
    elif "bear" in trend:
        regime = "bear_trending"
        confidence = 0.75
    elif "chop" in vix_r or "sideways" in trend:
        regime = "choppy"
        confidence = 0.70
    elif vix is not None and vix > _VIX_THRESHOLDS["elevated"]:
        regime = "bear_trending"
        confidence = 0.55
    else:
        regime = "neutral"
        confidence = 0.50

    # Boost confidence when multiple signals agree
    if regime == "bull_trending" and "bull" in vix_r:
        confidence = min(confidence + 0.10, 0.95)
    if regime == "bear_trending" and "bear" in vix_r:
        confidence = min(confidence + 0.10, 0.95)

    signals["classified_regime"] = regime
    signals["confidence"] = round(confidence, 3)

    return regime, round(confidence, 3), signals


def _build_synthesis(regime: str, prev_regime: Optional[str], indicators: dict, confidence: float) -> str:
    label = _REGIME_LABEL.get(regime, regime)
    vix_str = f" (VIX {indicators['vix']:.1f})" if indicators.get("vix") else ""
    trans = ""
    if prev_regime and prev_regime != regime:
        prev_label = _REGIME_LABEL.get(prev_regime, prev_regime)
        trans = f" Transition from {prev_label}."
    conf_str = f"Confidence: {confidence * 100:.0f}%."
    return f"Regime: **{label}**{vix_str}.{trans} {conf_str}"


def _save_snapshot(
    db: Session,
    regime: str,
    raw_regime: str,
    confidence: float,
    indicators: dict,
    synthesis: str,
    transition_to: Optional[str],
) -> bool:
    """Store classification in regime_snapshots (regime_history model)."""
    try:
        from app.db.models.regime_history import RegimeSnapshot as HistSnap
        today = date.today()

        signals_payload = {
            **indicators,
            "synthesis": synthesis,
            "transition_to": transition_to,
            "classified_by": "macro_strategist",
        }

        existing = db.query(HistSnap).filter(HistSnap.snapshot_date == today).first()
        if existing:
            existing.regime = regime
            existing.raw_regime = raw_regime
            existing.confidence = confidence
            existing.vix_level = indicators.get("vix")
            existing.signals_json = json.dumps(signals_payload)
        else:
            snap = HistSnap(
                snapshot_date=today,
                regime=regime,
                raw_regime=raw_regime,
                confidence=confidence,
                vix_level=indicators.get("vix"),
                signals_json=json.dumps(signals_payload),
            )
            db.add(snap)

        db.commit()
        return True
    except Exception as exc:
        logger.warning("[macro_strategist] snapshot save failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _publish_heartbeat(db: Session, result: dict) -> None:
    try:
        db.execute(text("""
            INSERT INTO agent_messages (from_agent, channel, msg_type, subject, body, created_at)
            VALUES (:agent, :channel, :mtype, :subject, :body, :ts)
        """), {
            "agent":   "macro_strategist",
            "channel": "agent_heartbeats",
            "mtype":   "heartbeat",
            "subject": f"regime:{result.get('regime', 'unknown')}",
            "body":    json.dumps(result),
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        db.commit()
    except Exception as exc:
        logger.warning("[macro_strategist] heartbeat publish failed: %s", exc)


def run_macro_classification(db: Session) -> dict:
    """
    Main entry point. Returns classification result dict.
    """
    started = datetime.now(timezone.utc)
    logger.info("[macro_strategist] Running regime classification")

    indicators = _read_live_indicators(db)
    if not indicators:
        logger.warning("[macro_strategist] No live indicators available")

    prev_regime = _read_yesterday_regime(db)
    regime, confidence, signals = _classify_regime(indicators)
    is_transition = prev_regime is not None and prev_regime != regime

    synthesis = _build_synthesis(regime, prev_regime, indicators, confidence)

    saved = _save_snapshot(
        db,
        regime=regime,
        raw_regime=signals.get("trend_regime", "unknown"),
        confidence=confidence,
        indicators=indicators,
        synthesis=synthesis,
        transition_to=regime if is_transition else None,
    )

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    result = {
        "regime":         regime,
        "prev_regime":    prev_regime,
        "is_transition":  is_transition,
        "confidence":     confidence,
        "synthesis":      synthesis,
        "indicators":     indicators,
        "snapshot_saved": saved,
        "elapsed_ms":     elapsed_ms,
        "classified_at":  started.isoformat(),
    }

    _publish_heartbeat(db, result)

    # Discord post
    emoji = _REGIME_EMOJI.get(regime, "❓")
    label = _REGIME_LABEL.get(regime, regime)
    vix_str = f" · VIX {indicators['vix']:.1f}" if indicators.get("vix") else ""
    title = f"{emoji} Regime: {label}{vix_str}"
    description = synthesis
    if is_transition:
        prev_label = _REGIME_LABEL.get(prev_regime, prev_regime)
        description = f"⚡ **REGIME CHANGE** {prev_label} → {label}\n\n{synthesis}"

    color = {
        "bull_trending":  0x4ADE80,
        "bear_trending":  0xF87171,
        "crisis":         0xEF4444,
        "choppy":         0xFBBF24,
        "complacency":    0xFB923C,
        "neutral":        0x94A3B8,
    }.get(regime, 0x64748B)

    fields = []
    if indicators.get("btc_dom"):
        fields.append({"name": "BTC Dom", "value": f"{indicators['btc_dom']:.1f}%", "inline": True})
    if indicators.get("vol_pctile"):
        fields.append({"name": "Vol %ile", "value": f"{indicators['vol_pctile']:.0%}", "inline": True})

    embed = {
        "title":       title,
        "description": description,
        "color":       color,
        "fields":      fields,
        "footer":      {"text": f"Macro Strategist · {started.strftime('%Y-%m-%d %H:%M')} UTC · {elapsed_ms}ms"},
    }

    token, channel_id = _get_macro_channel()
    posted = _post_discord(token, channel_id, embed)
    result["discord_posted"] = posted

    logger.info(
        "[macro_strategist] Done — regime=%s confidence=%.2f transition=%s discord=%s",
        regime, confidence, is_transition, posted,
    )
    return result
