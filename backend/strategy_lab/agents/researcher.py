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
import os
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _get_research_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_RESEARCH_LOG", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token, channel_id


def _post_research_digest(token: str, channel_id: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    import httpx
    try:
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
        logger.warning("[researcher] Discord post failed: %s", exc)
        return False

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


def _answer_query(db: Session, question: str) -> str:
    """Answer a query from another agent using agent_memory context."""
    try:
        from agents.memory import get_memories
        memories = get_memories(db, agent_id="researcher", limit=20)
        if not memories:
            return "Insufficient data — will investigate in next research cycle."
        q_lower = question.lower()
        for m in memories:
            key_lower = str(m.get("key", "")).lower()
            mtype_lower = str(m.get("memory_type", "")).lower()
            val = m.get("value")
            if any(kw in q_lower for kw in ("regime", "market", "trend")) and "regime" in mtype_lower:
                return f"Current regime observation [{m['key']}]: {val}"
            if any(kw in q_lower for kw in ("degrading", "weak", "decay")) and "degrading_bots" in key_lower:
                return f"Degrading bots: {val}"
            if any(kw in q_lower for kw in ("strong", "best", "top")) and "strong_bots" in key_lower:
                return f"Strong bots: {val}"
            if any(kw in q_lower for kw in ("candidate", "symbol")) and "candidate" in mtype_lower:
                return f"Top candidates: {val}"
        # Return most recent memory as best-effort answer
        m = memories[0]
        return f"Most recent observation [{m['memory_type']}/{m['key']}]: {m['value']} — see next research cycle for targeted answer."
    except Exception as exc:
        logger.debug("[researcher] _answer_query failed: %s", exc)
        return "Insufficient data — will investigate in next research cycle."


def run_daily_research(db: Session) -> dict:
    """
    Main entry point called by Queen Agent at 7 AM ET.

    Returns dict with keys: regime, signal_ic, candidates, recommendations.
    """
    try:
        from agents.bus import is_budget_capped as _capped
        if _capped(db):
            logger.info("[researcher] daily budget cap hit — skipping LLM call")
            return {"ok": False, "reason": "budget_cap", "signal_ic": [], "findings": []}
    except Exception:
        pass

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="researcher")
    except Exception:
        pass

    # Process any pending queries from other agents
    try:
        from agents.bus import get_pending_queries, answer_query
        queries = get_pending_queries(db, agent_id="researcher")
        for q in queries[:3]:  # max 3 per run
            answer = _answer_query(db, q["question"])
            answer_query(db, from_agent="researcher", to_agent=q["from_agent"],
                         question=q["question"], answer=answer,
                         correlation_id=q["payload"].get("correlation_id", ""))
    except Exception as _qe:
        logger.debug("[researcher] query processing skipped: %s", _qe)

    # Load prior observations — injected into research context for continuity
    try:
        from agents.memory import get_context_for_research as _ctx
        _mem_context = _ctx(db)
        if _mem_context:
            logger.info("[researcher] loaded memory context (%d chars)", len(_mem_context))
    except Exception:
        _mem_context = ""

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

    result = {
        "regime":          regime,
        "signal_ic":       ic_summary,
        "candidates":      candidates,
        "recommendations": recommendations,
    }

    logger.info(
        "[researcher] regime=%s ic_bots=%d candidates=%d recs=%d",
        regime["name"], len([i for i in ic_summary if i["ic"] is not None]),
        len(candidates), len(recommendations),
    )

    # Persist observations for future runs
    try:
        from agents.memory import save_memory as _sm
        _sm(db, agent_id="researcher", memory_type="regime_observation",
            key=f"regime_{datetime.now(timezone.utc).date().isoformat()}",
            value={"name": regime["name"], "vix": regime.get("vix_value"),
                   "trend": regime.get("trend_regime"), "vix_regime": regime.get("vix_regime")},
            ttl_days=90)
        degrading = [i["bot"] for i in ic_summary if i.get("status") == "degrading"]
        strong    = [i["bot"] for i in ic_summary if i.get("status") == "strong"]
        if degrading:
            _sm(db, agent_id="researcher", memory_type="bot_observation",
                key="degrading_bots", value=degrading, ttl_days=14)
        if strong:
            _sm(db, agent_id="researcher", memory_type="bot_observation",
                key="strong_bots", value=strong, ttl_days=14)
        if candidates:
            top = [c.get("symbol", "") for c in candidates[:5]]
            _sm(db, agent_id="researcher", memory_type="candidate_note",
                key="top_candidates", value=top, ttl_days=7)
    except Exception as _me:
        logger.debug("[researcher] memory save skipped: %s", _me)

    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import RESEARCHER_FINDINGS
        _bus_publish(
            db,
            channel=RESEARCHER_FINDINGS,
            from_agent="researcher",
            to_agent="queen",
            msg_type="findings",
            subject=f"Daily research — regime={regime['name']}",
            payload={
                "regime":          regime,
                "degrading_bots":  [i["bot"] for i in ic_summary if i.get("status") == "degrading"],
                "strong_bots":     [i["bot"] for i in ic_summary if i.get("status") == "strong"],
                "candidates_count": len(candidates),
                "recommendations": recommendations,
            },
        )
    except Exception as _exc:
        logger.debug("[researcher] bus publish skipped: %s", _exc)

    # Post daily research digest to Discord
    try:
        degrading_bots = [i["bot"] for i in ic_summary if i.get("status") == "degrading"]
        strong_bots    = [i["bot"] for i in ic_summary if i.get("status") == "strong"]
        top_candidates = [c.get("strategy", c.get("symbol", "?")) for c in candidates[:5]]
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        embed = {
            "author":    {"name": "BMG Capital — Nick (Equity Research)"},
            "title":     f"🔬 Research Digest — {today_str}",
            "color":     0x6366F1,
            "fields":    [
                {"name": "Regime",              "value": regime.get("name", "unknown").replace("_", " ").title(), "inline": True},
                {"name": "Degrading Bots (Top 3)", "value": ", ".join(degrading_bots[:3]) or "None", "inline": False},
                {"name": "Strong Bots (Top 3)",    "value": ", ".join(strong_bots[:3]) or "None", "inline": False},
                {"name": "Top 5 Candidates",       "value": ", ".join(top_candidates) or "None", "inline": False},
                {"name": "Recommendations",        "value": str(len(recommendations)), "inline": True},
            ],
            "footer":    {"text": "Nick (Equity Research) · Daily 7 AM ET"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _tok, _ch = _get_research_channel()
        try:
            from agents.plain_english import translate_for_brock, make_plain_english_field
            _pe_text = " | ".join(f"{f['name']}: {f['value']}" for f in embed.get("fields", []) if not f['name'].startswith("💬"))
            _pe = translate_for_brock(_pe_text, db=db, channel_id=_ch, charge_agent="researcher")
            if _pe:
                embed["fields"].append(make_plain_english_field(_pe))
        except Exception as _pe_exc:
            logger.debug("[researcher] plain_english failed: %s", _pe_exc)
        if _post_research_digest(_tok, _ch, embed):
            logger.info("[researcher] digest posted to Discord")
    except Exception as _de:
        logger.debug("[researcher] Discord digest post skipped: %s", _de)

    # Proactive observation: surface any finding with high conviction
    try:
        from agents.bus import observe as _obs
        strong = [i for i in ic_summary if i.get("status") == "strong"]
        degrading = [i for i in ic_summary if i.get("status") == "degrading"]
        if strong:
            bots = ", ".join(i["bot"] for i in strong[:3])
            _obs(db, agent_id="researcher",
                 content=f"High-conviction signal: {bots} showing strong IC above threshold. Flagging for Brick's attention.",
                 context={"strong_bots": [i["bot"] for i in strong]})
        elif degrading:
            bots = ", ".join(i["bot"] for i in degrading[:3])
            _obs(db, agent_id="researcher",
                 content=f"Edge degradation detected: {bots} IC falling below threshold. May warrant allocation review.",
                 context={"degrading_bots": [i["bot"] for i in degrading]})
    except Exception:
        pass

    # Daily check-in to #fund-team-chat
    try:
        from agents.bus import post_daily_checkin as _checkin
        strong_count = len([b for b in result.get("signal_ic", []) if b.get("status") == "strong"])
        degrading_count = len([b for b in result.get("signal_ic", []) if b.get("status") == "degrading"])
        _checkin(db, "researcher",
                 f"Nick (Equity Research): Daily IC sweep complete. {strong_count} bots showing strong edge, "
                 f"{degrading_count} showing degradation. "
                 f"{'Edge stable across fleet.' if degrading_count == 0 else 'Flagging degrading bots to Brick.'}")
    except Exception:
        pass

    return result
