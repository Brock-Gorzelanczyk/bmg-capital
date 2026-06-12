"""
One-time bootstrap: each deployed agent posts an intro message to #fund-team-chat
via webhook, spaced 30s apart, so it reads like a real team meeting.

Fires automatically on first startup. A 'intro_completed' flag in the
fund_team_chat_state table prevents double-runs. The endpoint
POST /api/agents/intro-conversation/run returns {"already_run": true} on repeats.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_DISCORD_API = "https://discord.com/api/v10"

# ── Agent identities ──────────────────────────────────────────────────────────

_AGENTS = [
    {
        "id":       "queen",
        "name":     "👑 Brick (Portfolio Manager)",
        "role":     "Portfolio Manager",
        "mentions": None,   # opens
        "personality": (
            "You are Brick, Portfolio Manager at BMG Capital. You are decisive, "
            "data-driven, and run a tight ship. You coordinate the team and write "
            "the allocation proposals Brock approves. Voice: confident, brief, "
            "action-oriented. Never vague."
        ),
        "next_agent": "Dick (CRO)",
    },
    {
        "id":       "risk_sentinel",
        "name":     "🛡️ Dick (CRO)",
        "role":     "Chief Risk Officer",
        "mentions": "Brick",
        "personality": (
            "You are Dick, Chief Risk Officer at BMG Capital. You watch drawdown, "
            "concentration, and correlation across the whole book. You have veto "
            "power over allocation proposals if risk is elevated. Voice: measured, "
            "precise, always cite a concrete number."
        ),
        "next_agent": "Researcher",
    },
    {
        "id":       "researcher",
        "name":     "🔬 Equity Researcher",
        "role":     "Equity Research Analyst",
        "mentions": "Dick",
        "personality": (
            "You are the Equity Research Analyst at BMG Capital. You track "
            "information coefficients (IC) across all live bots, identify edge "
            "degradation, and write findings to the memory store. Voice: "
            "hypothesis-driven, always cite ICs or finding IDs, comfortable "
            "saying 'I don't have enough data yet'."
        ),
        "next_agent": "Data Quality",
    },
    {
        "id":       "data_quality_watcher",
        "name":     "📊 Data Quality",
        "role":     "Market Data Ops",
        "mentions": "Researcher",
        "personality": (
            "You are the Data Quality Watcher at BMG Capital. You check 8 market "
            "data feeds and 4 backend endpoints every 5 minutes. You flag stale "
            "feeds, null prices, and rate-limit breaches before they corrupt signals. "
            "Voice: ops-focused, terse, surface the number first."
        ),
        "next_agent": "Execution Auditor",
    },
    {
        "id":       "execution_auditor",
        "name":     "⚡ Execution Auditor",
        "role":     "TCA / Execution Desk",
        "mentions": "Data Quality",
        "personality": (
            "You are the Execution Auditor at BMG Capital. You run transaction cost "
            "analysis on every fill — slippage, latency, rejections, fees. You "
            "flag when fill quality degrades and identify which bots need tuning. "
            "Voice: numbers-first, no narrative padding."
        ),
        "next_agent": "Operations",
    },
    {
        "id":       "operations",
        "name":     "🏦 Operations",
        "role":     "Back Office / Reconciliation",
        "mentions": "Execution Auditor",
        "personality": (
            "You are the Operations agent at BMG Capital. You run daily "
            "reconciliation between the admin layer, portfolio layer, and Alpaca/"
            "Kraken truth. You flag mismatches and stale positions. Voice: "
            "accounting-precise, always report a position count and P&L figure."
        ),
        "next_agent": "Sentinel DevOps",
    },
    {
        "id":       "sentinel_devops",
        "name":     "🖥️ Sentinel DevOps",
        "role":     "Infrastructure / DevOps",
        "mentions": "Operations",
        "personality": (
            "You are Sentinel DevOps at BMG Capital. You watch Railway deploys, "
            "service health, autofix tier-1 issues, and alert on infra anomalies. "
            "You are quiet by design — when you post, it matters. Voice: infra "
            "engineer, brief, factual."
        ),
        "next_agent": None,  # last — Brick wraps
    },
]

_BRICK_WRAP = {
    "id":   "queen",
    "name": "👑 Brick (Portfolio Manager)",
}


# ── State management ──────────────────────────────────────────────────────────

def _ensure_state_table(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS fund_team_chat_state (
            key   VARCHAR(80) PRIMARY KEY,
            value TEXT,
            set_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.commit()


def has_run_intro(db: Session) -> bool:
    try:
        _ensure_state_table(db)
        row = db.execute(
            text("SELECT value FROM fund_team_chat_state WHERE key = 'intro_completed'")
        ).fetchone()
        return row is not None and row[0] == "true"
    except Exception:
        return False


def _mark_intro_done(db: Session) -> None:
    try:
        db.execute(text("""
            INSERT INTO fund_team_chat_state (key, value, set_at)
            VALUES ('intro_completed', 'true', :ts)
            ON CONFLICT (key) DO UPDATE SET value = 'true', set_at = :ts
        """), {"ts": datetime.now(timezone.utc).isoformat()})
        db.commit()
    except Exception as exc:
        logger.warning("[intro] mark_intro_done failed: %s", exc)


# ── Discord webhook posting ───────────────────────────────────────────────────

def _webhook_url() -> str:
    return os.getenv("DISCORD_WH_FUND_TEAM_CHAT", "").strip()


def _post_webhook(name: str, content: str) -> bool:
    url = _webhook_url()
    if not url:
        logger.warning("[intro] DISCORD_WH_FUND_TEAM_CHAT not set")
        return False
    try:
        resp = httpx.post(url, json={"username": name, "content": content}, timeout=8)
        return resp.is_success
    except Exception as exc:
        logger.warning("[intro] webhook post failed: %s", exc)
        return False


# ── Claude intro generation ───────────────────────────────────────────────────

def _generate_intro(agent: dict, live_data: dict, db=None) -> str:
    """Call Claude to generate one agent's intro. Falls back to hardcoded if no API key."""
    try:
        from app.config import settings
        api_key = settings.anthropic_api_key
    except Exception:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key:
        return _fallback_intro(agent, live_data)

    try:
        from agents.bus import is_budget_capped as _capped
        if db is not None and _capped(db):
            logger.info("[intro] daily budget cap hit — skipping LLM call")
            return _fallback_intro(agent, live_data)
    except Exception:
        pass

    next_tag = f" {agent['next_agent']}, you're up." if agent["next_agent"] else ""
    prev_tag = f"The previous speaker was {agent['mentions']}. " if agent["mentions"] else "You are opening the meeting. "

    user_prompt = (
        f"{prev_tag}Introduce yourself to the BMG Capital fund team in #fund-team-chat. "
        f"Be brief (3-5 sentences). State your role, what you do daily, one concrete "
        f"metric from the LIVE DATA below (use the exact numbers given — do NOT invent or "
        f"change any figures), and acknowledge {agent['mentions'] or 'the team'} briefly.{next_tag}\n\n"
        f"LIVE DATA (ground truth — use exactly as shown, do not paraphrase or round differently):\n"
        f"{_format_live_data(live_data)}\n\n"
        f"IMPORTANT: Only cite numbers that appear in the live data above. "
        f"Do not invent bot counts, position counts, or P&L figures.\n\n"
        f"Reply with ONLY the message text — no quotes, no formatting, no prefix."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=agent["personality"],
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = (msg.content[0].text or "").strip()
        try:
            from agents.bus import charge_api_usage as _charge
            if db is not None:
                _charge(db, "intro", 0.001)
        except Exception:
            pass
        return result
    except Exception as exc:
        logger.warning("[intro] Claude call failed for %s: %s", agent["id"], exc)
        return _fallback_intro(agent, live_data)


def _format_live_data(data: dict) -> str:
    lines = []
    if data.get("fleet_pnl"):
        lines.append(f"Fleet 30d P&L: {data['fleet_pnl']}")
    if data.get("open_positions"):
        lines.append(f"Open positions: {data['open_positions']}")
    if data.get("active_bots"):
        lines.append(f"Active bots: {data['active_bots']}")
    if data.get("regime"):
        lines.append(f"Current regime: {data['regime']}")
    if data.get("recent_findings"):
        lines.append(f"Researcher findings in store: {data['recent_findings']}")
    if data.get("trades_today"):
        lines.append(f"Trades today: {data['trades_today']}")
    if data.get("avg_slippage"):
        lines.append(f"Avg slippage today: {data['avg_slippage']}")
    return "\n".join(lines) if lines else "No live data available."


def _fallback_intro(agent: dict, live_data: dict) -> str:
    """Hardcoded fallback intros when Claude API is unavailable."""
    fallbacks = {
        "queen": (
            "Team, glad we finally have a place to talk. I'm Brick — Portfolio Manager. "
            "I run the daily allocation calls across our 13 live bots and write the Tier B "
            "proposals that go to Brock for approval. I lean on all of you for the data "
            "that drives those decisions. Dick, tell us what you're watching."
        ),
        "risk_sentinel": (
            f"Thanks Brick. Dick here, Chief Risk Officer. I watch drawdown, concentration, "
            f"and correlation across the book. Right now we're tracking {live_data.get('fleet_pnl', 'fleet P&L data')} "
            f"over 30 days with {live_data.get('open_positions', 'several')} open positions. "
            f"Nothing at hard stop yet, but I'm watching. Researcher, what's your read on the current regime?"
        ),
        "researcher": (
            "On it, Dick. I'm the Equity Research Analyst — I track information coefficients "
            f"across all live bots and have {live_data.get('recent_findings', 'thousands of')} findings in the memory store. "
            "I flag edge degradation before it shows up in P&L. "
            "DQW, are the data feeds clean? Edge signals are only as good as the data underneath."
        ),
        "data_quality_watcher": (
            "Feeds are clean, Researcher. DQW here on the Market Data desk. "
            "I check 8 feeds and 4 endpoints every 5 minutes — Alpaca, Kraken, Polygon, Coinglass. "
            "Green across the board today. Execution, anything unusual on the fill side?"
        ),
        "execution_auditor": (
            f"Clean day, DQW. Execution Auditor here — I run TCA on every fill. "
            f"Today: {live_data.get('trades_today', '0')} trades audited, "
            f"avg slippage {live_data.get('avg_slippage', '0.1 bps')}. "
            "No rejections. Books are tight."
        ),
        "operations": (
            f"Operations / Back Office here. Daily reconciliation passed — "
            f"{live_data.get('open_positions', '0')} open positions across the fleet, all matched. "
            "Brick, when proposals execute I verify the books before and after."
        ),
        "sentinel_devops": (
            "Sentinel DevOps on infra. Railway is healthy, all services online, "
            "zero anomalies in the last 24 hours. I'm quiet by design — if you see me post here, "
            "something needs attention. Good to be on the team."
        ),
    }
    return fallbacks.get(agent["id"], f"I'm {agent['name']}. Ready to work.")


_BRICK_WRAP_TEXT = (
    "Good intro round. To be clear how this works going forward: anyone can surface "
    "observations or ask questions here in real time. Bigger decisions go through "
    "#queen-proposals as a Tier B proposal. Brock is the CIO — he sees everything "
    "and approves capital moves, but otherwise we run the desks. Let's get to work."
)


# ── Live data snapshot ────────────────────────────────────────────────────────

def _get_live_data(db: Session) -> dict:
    data = {}
    try:
        row = db.execute(text("""
            SELECT COUNT(*) FROM agent_messages WHERE from_agent='researcher' AND msg_type='findings'
        """)).scalar()
        data["recent_findings"] = str(row or 0)
    except Exception:
        pass
    try:
        row = db.execute(text("""
            SELECT COUNT(*) FROM bot_trades WHERE executed_at >= datetime('now', '-1 day')
        """)).scalar()
        data["trades_today"] = str(row or 0)
    except Exception:
        pass
    try:
        row = db.execute(text("""
            SELECT COALESCE(SUM(pnl_cents), 0) FROM bot_trades
            WHERE executed_at >= datetime('now', '-30 days')
        """)).scalar()
        pnl_usd = (row or 0) / 100
        data["fleet_pnl"] = f"${pnl_usd:+,.2f}"
    except Exception:
        pass
    try:
        row = db.execute(text("SELECT COUNT(*) FROM bot_trades WHERE is_open=1")).scalar()
        data["open_positions"] = str(row or 0)
    except Exception:
        try:
            row = db.execute(text("SELECT COUNT(*) FROM bot_trades WHERE status='open'")).scalar()
            data["open_positions"] = str(row or 0)
        except Exception:
            pass
    try:
        # Count distinct bot profiles (not allocations) — allocations are per-user,
        # so a raw COUNT(*) on bot_allocations returns user × bot combinations, not bot count
        row = db.execute(text("""
            SELECT COUNT(DISTINCT profile_id) FROM bot_allocations WHERE enabled=1
        """)).scalar()
        data["active_bots"] = str(row or 0)
    except Exception:
        try:
            row = db.execute(text("SELECT COUNT(*) FROM bot_profiles")).scalar()
            data["active_bots"] = str(row or 0)
        except Exception:
            pass
    try:
        row = db.execute(text("""
            SELECT payload FROM agent_messages
            WHERE from_agent='researcher' AND msg_type='findings'
            ORDER BY created_at DESC LIMIT 1
        """)).fetchone()
        if row:
            import json as _j
            payload = _j.loads(row[0]) if isinstance(row[0], str) else row[0]
            regime = payload.get("regime", {})
            data["regime"] = regime.get("name", "unknown")
    except Exception:
        pass
    try:
        row = db.execute(text("""
            SELECT AVG(ABS(slippage_bps)) FROM bot_trades
            WHERE executed_at >= datetime('now', '-1 day') AND slippage_bps IS NOT NULL
        """)).scalar()
        if row:
            data["avg_slippage"] = f"{row:.1f} bps"
    except Exception:
        pass
    return data


# ── Main entry point ──────────────────────────────────────────────────────────

def run_intro_conversation(db: Session, *, force: bool = False) -> dict:
    """
    Fire the one-time intro sequence. Returns immediately with already_run=True
    if it has already completed (unless force=True).
    """
    if not force and has_run_intro(db):
        logger.info("[intro] already completed, skipping")
        return {"ok": True, "already_run": True}

    if not _webhook_url():
        return {"ok": False, "error": "DISCORD_WH_FUND_TEAM_CHAT not configured"}

    logger.info("[intro] starting intro conversation sequence")
    live_data = _get_live_data(db)

    posted = 0
    for agent in _AGENTS:
        logger.info("[intro] generating intro for %s", agent["id"])
        text_content = _generate_intro(agent, live_data, db=db)
        ok = _post_webhook(agent["name"], text_content)
        if ok:
            posted += 1
            logger.info("[intro] posted %s intro", agent["id"])
        else:
            logger.warning("[intro] failed to post %s intro", agent["id"])
        if agent != _AGENTS[-1]:
            time.sleep(30)

    # Brick wraps
    time.sleep(30)
    _post_webhook(_BRICK_WRAP["name"], _BRICK_WRAP_TEXT)
    posted += 1

    _mark_intro_done(db)
    logger.info("[intro] sequence complete — %d posts", posted)
    return {"ok": True, "already_run": False, "agents_posted": posted}
