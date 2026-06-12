"""
Daily 7 AM ET standup — all agents contribute, Queen synthesizes into a daily plan.
Posted to #daily-plan channel. Plan stored in daily_plan table.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Agent metadata: id → (display_name, emoji)
_AGENT_META = {
    "researcher":           ("Equity Researcher",   "🔬"),
    "risk_sentinel":        ("Dick (CRO)",           "🛡️"),
    "data_quality_watcher": ("Data Quality",        "📊"),
    "execution_auditor":    ("Execution Auditor",   "⚡"),
    "operations":           ("Operations",          "🏦"),
}

_STATUS_COLOR = {
    "green":  0x16A34A,
    "yellow": 0xF59E0B,
    "red":    0xDC2626,
}

_STANDUP_ORDER = [
    "researcher",
    "risk_sentinel",
    "data_quality_watcher",
    "execution_auditor",
    "operations",
]

# Channel mapping: agent → (bus channel constant name, fallback channel name)
_AGENT_CHANNEL_MAP = {
    "researcher":           "researcher.findings",
    "risk_sentinel":        "sentinel.health",
    "data_quality_watcher": "dq.alert",
    "execution_auditor":    "exec.audit",
    "operations":           "ops.report",
}


def _get_discord_token() -> str:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token


def _get_standup_channel_id() -> str:
    return (
        os.getenv("DISCORD_CH_DAILY_PLAN", "")
        or os.getenv("DISCORD_CH_QUEEN_BRIEFINGS", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )


def _discord_post(channel_id: str, token: str, payload: dict) -> bool:
    """Post a message to Discord. Returns True on success."""
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
            json=payload,
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[standup] Discord post failed: %s", exc)
        return False


def get_standup_contribution(db: Session, agent_id: str) -> dict:
    """
    Read each agent's most recent bus output and memory to produce a short contribution dict.

    Returns: {"agent": agent_id, "status": "green/yellow/red", "summary": "one line", "details": {...}}
    """
    channel = _AGENT_CHANNEL_MAP.get(agent_id, "")
    status = "green"
    summary = "No recent activity"
    details: dict = {}

    try:
        row = db.execute(
            text("""
                SELECT payload, subject, created_at
                FROM agent_messages
                WHERE from_agent = :a AND channel = :c
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"a": agent_id, "c": channel},
        ).fetchone()

        if row:
            raw_payload = row[0]
            subject = row[1] or ""
            created_at = str(row[2])

            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
            except Exception:
                payload = {}

            details = {"subject": subject, "created_at": created_at, "payload": payload}

            # Infer status from payload
            if agent_id == "researcher":
                # Read memory for richer context
                regime_name = "unknown"
                degrading: list = []
                strong: list = []
                try:
                    from agents.memory import get_memories
                    mems = get_memories(db, agent_id="researcher", limit=20)
                    for m in mems:
                        if m.get("memory_type") == "regime_observation":
                            val = m.get("value", {})
                            if isinstance(val, dict):
                                regime_name = val.get("name", regime_name)
                        elif m.get("key") == "degrading_bots":
                            degrading = m.get("value", []) or []
                        elif m.get("key") == "strong_bots":
                            strong = m.get("value", []) or []
                except Exception:
                    pass
                # Also pull from bus payload
                regime_name = payload.get("regime", {}).get("name", regime_name) if isinstance(payload.get("regime"), dict) else regime_name
                degrading = payload.get("degrading_bots", degrading) or degrading
                strong = payload.get("strong_bots", strong) or strong
                status = "yellow" if degrading else "green"
                summary = f"Regime: {regime_name} | Degrading: {len(degrading)} | Strong: {len(strong)}"
                details.update({"regime_name": regime_name, "degrading_bots": degrading, "strong_bots": strong})

            elif agent_id == "risk_sentinel":
                level = payload.get("level", payload.get("status", "GREEN")).upper()
                status = level.lower() if level in ("GREEN", "YELLOW", "RED") else "green"
                summary = subject or f"Risk level: {level}"

            elif agent_id == "data_quality_watcher":
                issues = payload.get("issues", [])
                if issues:
                    status = "yellow"
                    summary = f"{len(issues)} data issue(s) detected"
                else:
                    status = "green"
                    summary = "All data feeds healthy"
                details.update({"issues": issues})

            elif agent_id == "execution_auditor":
                level = payload.get("level", "GREEN").upper()
                stats = payload.get("stats", {})
                status = level.lower() if level in ("GREEN", "YELLOW", "RED") else "green"
                avg_slip = stats.get("avg_slippage_bps")
                summary = f"Exec: {level} | Trades: {stats.get('trade_count', 0)} | Avg slip: {f'{avg_slip:.1f} bps' if avg_slip else 'N/A'}"

            elif agent_id == "operations":
                level = payload.get("level", payload.get("status", "GREEN")).upper()
                status = level.lower() if level in ("GREEN", "YELLOW", "RED") else "green"
                summary = subject or f"Ops status: {level}"

        else:
            # No recent message — check if it's a DQ alert absence (means GREEN)
            if agent_id == "data_quality_watcher":
                summary = "GREEN — no recent alert"
            elif agent_id == "operations":
                summary = "No recent ops report"
            details = {}

    except Exception as exc:
        logger.warning("[standup] contribution failed for %s: %s", agent_id, exc)
        summary = f"Error reading contribution: {exc}"

    return {
        "agent":   agent_id,
        "status":  status,
        "summary": summary,
        "details": details,
    }


def _post_contribution(channel_id: str, token: str, agent_id: str, contribution: dict) -> bool:
    """Post agent standup message to Discord as an embed."""
    display_name, emoji = _AGENT_META.get(agent_id, (agent_id, "🤖"))
    status = contribution.get("status", "green").lower()
    color = _STATUS_COLOR.get(status, _STATUS_COLOR["green"])
    summary = contribution.get("summary", "No summary available")
    status_label = status.upper()

    embed = {
        "author":      {"name": f"{emoji} {display_name}"},
        "description": summary,
        "color":       color,
        "fields":      [
            {"name": "Status", "value": status_label, "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return _discord_post(channel_id, token, {"embeds": [embed]})


def _synthesize_plan(contributions: list[dict], db: Session) -> dict:
    """Call Claude API to synthesize agent contributions into a daily plan."""
    # Build structured text of contributions
    lines = []
    for c in contributions:
        display_name, emoji = _AGENT_META.get(c["agent"], (c["agent"], ""))
        lines.append(f"[{emoji} {display_name}] Status: {c['status'].upper()} — {c['summary']}")

    contributions_text = "\n".join(lines)

    try:
        from app.config import settings
        api_key = settings.anthropic_api_key
    except Exception:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key:
        logger.warning("[standup] No Anthropic API key — using fallback plan")
        return _fallback_plan(contributions)

    try:
        import httpx
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1200,
                "system": (
                    "You are the Queen, portfolio manager at BMG Capital. "
                    "Based on your agents' morning standup contributions, write today's trading plan. "
                    "Respond ONLY with a valid JSON object with these keys: "
                    "focus_areas (list of 3 strings), bots_to_watch (list of strings), "
                    "risks (list of strings), proposed_actions (list of strings), summary (string)."
                ),
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Morning standup contributions:\n\n{contributions_text}\n\n"
                            "Write today's trading plan as JSON."
                        ),
                    }
                ],
            },
            timeout=30,
        )

        if response.is_success:
            data = response.json()
            raw_text = data["content"][0]["text"]
            # Extract JSON from the response
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()
            plan = json.loads(raw_text)
            # Ensure all expected keys exist
            plan.setdefault("focus_areas", [])
            plan.setdefault("bots_to_watch", [])
            plan.setdefault("risks", [])
            plan.setdefault("proposed_actions", [])
            plan.setdefault("summary", "")
            return plan
        else:
            logger.warning("[standup] Claude API returned %d — using fallback", response.status_code)
            return _fallback_plan(contributions)

    except Exception as exc:
        logger.warning("[standup] Claude synthesis failed: %s", exc)
        return _fallback_plan(contributions)


def _fallback_plan(contributions: list[dict]) -> dict:
    """Build a structured fallback plan from raw contribution data."""
    red_agents   = [c["agent"] for c in contributions if c.get("status") == "red"]
    yellow_agents = [c["agent"] for c in contributions if c.get("status") == "yellow"]
    green_agents  = [c["agent"] for c in contributions if c.get("status") == "green"]

    focus_areas: list[str] = []
    risks: list[str] = []

    if red_agents:
        focus_areas.append(f"Investigate RED alerts: {', '.join(red_agents)}")
        risks.append(f"Active RED alerts from: {', '.join(red_agents)}")
    if yellow_agents:
        focus_areas.append(f"Monitor YELLOW warnings: {', '.join(yellow_agents)}")
        risks.append(f"YELLOW warnings from: {', '.join(yellow_agents)}")
    if green_agents:
        focus_areas.append("Continue standard operations — all green agents nominal")

    # Pull bots to watch from researcher contribution
    bots_to_watch: list[str] = []
    for c in contributions:
        if c["agent"] == "researcher":
            degrading = c.get("details", {}).get("degrading_bots", [])
            if degrading:
                bots_to_watch.extend(degrading[:3])

    summary_parts = [f"{c['agent']}: {c['status'].upper()}" for c in contributions]
    summary = "Daily plan synthesized from standup. " + " | ".join(summary_parts)

    return {
        "focus_areas":      focus_areas or ["Maintain current allocations"],
        "bots_to_watch":    bots_to_watch or [],
        "risks":            risks or ["No active risk alerts"],
        "proposed_actions": ["Review agent outputs", "Monitor open positions"],
        "summary":          summary,
    }


def _post_plan(channel_id: str, token: str, plan: dict, contributions: list[dict]) -> bool:
    """Post Queen's synthesized plan to Discord as a rich embed."""
    now_et = datetime.now(timezone.utc)
    today_str = now_et.strftime("%Y-%m-%d")
    time_str = now_et.strftime("%H:%M UTC")
    n = len(contributions)

    focus_areas   = plan.get("focus_areas", [])
    bots_to_watch = plan.get("bots_to_watch", [])
    risks         = plan.get("risks", [])
    actions       = plan.get("proposed_actions", [])

    def _bullets(items: list, max_items: int = 5) -> str:
        return "\n".join(f"• {item}" for item in items[:max_items]) or "• None"

    embed = {
        "author":    {"name": "👑 Queen — BMG Capital"},
        "title":     f"📋 BMG Capital — Daily Plan · {today_str}",
        "color":     0x6366F1,
        "description": plan.get("summary", ""),
        "fields":    [
            {"name": "TODAY'S FOCUS",       "value": _bullets(focus_areas, 3),  "inline": False},
            {"name": "BOTS TO WATCH",       "value": _bullets(bots_to_watch),   "inline": True},
            {"name": "RISKS TO MONITOR",    "value": _bullets(risks),           "inline": True},
            {"name": "PROPOSED ACTIONS",    "value": _bullets(actions),         "inline": False},
        ],
        "footer":    {"text": f"Synthesized from {n} agent contributions · Generated {time_str} ET"},
        "timestamp": now_et.isoformat(),
    }

    return _discord_post(channel_id, token, {"embeds": [embed]})


def _save_plan(db: Session, plan: dict, contributions: list[dict]) -> None:
    """Save the daily plan and contributions to the daily_plan table."""
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        now_ts = datetime.now(timezone.utc).isoformat()
        plan_json = json.dumps(plan)
        contributions_json = json.dumps(contributions)

        db.execute(
            text("""
                INSERT INTO daily_plan (plan_date, plan_json, contributions_json, generated_ts)
                VALUES (:date, :plan, :contrib, :ts)
                ON CONFLICT (plan_date) DO UPDATE
                SET plan_json = :plan,
                    contributions_json = :contrib,
                    generated_ts = :ts
            """),
            {"date": today, "plan": plan_json, "contrib": contributions_json, "ts": now_ts},
        )
        db.commit()
        logger.info("[standup] daily_plan saved for %s", today)
    except Exception as exc:
        logger.warning("[standup] _save_plan failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def run_daily_standup(db: Session) -> dict:
    """
    Main entry point — called daily at 7 AM ET.

    1. Posts opening message
    2. Collects contributions from all agents
    3. Synthesizes plan with Claude
    4. Posts plan to Discord
    5. Saves to DB
    6. Publishes to bus

    Returns {"ok": True, "agents_contributed": n, "plan": plan}
    """
    # Heartbeat for queen
    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="queen")
    except Exception:
        pass

    token = _get_discord_token()
    channel_id = _get_standup_channel_id()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Post opening message
    _discord_post(channel_id, token, {
        "content": f"🗓️ **Morning Standup — {today_str}**\nAgents reporting in..."
    })

    # Collect contributions
    contributions: list[dict] = []
    for agent_id in _STANDUP_ORDER:
        contribution = get_standup_contribution(db, agent_id)
        contributions.append(contribution)
        _post_contribution(channel_id, token, agent_id, contribution)
        time.sleep(0.5)  # rate limit between posts

    # Synthesize plan
    plan = _synthesize_plan(contributions, db)

    # Post plan
    _post_plan(channel_id, token, plan, contributions)

    # Save to DB
    _save_plan(db, plan, contributions)

    # Publish to bus
    try:
        from agents.bus import publish as _pub
        from agents.channels import STANDUP
        _pub(
            db,
            channel=STANDUP,
            from_agent="queen",
            msg_type="standup_summary",
            subject=f"Daily standup — {today_str}",
            payload={
                "agents_contributed": len(contributions),
                "statuses": {c["agent"]: c["status"] for c in contributions},
                "plan_summary": plan.get("summary", ""),
            },
            priority=5,
        )
    except Exception as exc:
        logger.debug("[standup] bus publish skipped: %s", exc)

    logger.info("[standup] complete — %d contributions", len(contributions))
    return {"ok": True, "agents_contributed": len(contributions), "plan": plan}
