"""
Tier A autonomous executor — pauses a bot on hard drawdown breach.
DEFENSIVE ONLY: can ONLY pause (never disable, never increase exposure).
Max 3 auto-pauses per 24h. If 3 hit, escalates to RED and stops.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
DRAWDOWN_24H_PCT   = -5.0   # 24h P&L vs starting_capital_cents
DRAWDOWN_7D_PCT    = -10.0  # 7-day P&L vs starting_capital_cents
CONSEC_LOSS_N      = 5      # consecutive losing trades …
CONSEC_LOSS_DD_PCT = -3.0   # … AND drawdown > -3% to trigger

MAX_AUTO_PAUSES_PER_DAY = 3

_DISCORD_API = "https://discord.com/api/v10"

# URL-encoded ▶️ (U+25B6 + U+FE0F variation selector)
_PLAY_EMOJI_ENCODED = "%E2%96%B6%EF%B8%8F"
_PLAY_EMOJI = "▶️"


# ── Discord helpers ───────────────────────────────────────────────────────────

def _get_discord_creds() -> tuple[str, str]:
    """Return (token, channel_id) for risk alerts."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_RISK_ALERTS", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token, channel_id


def _get_cio_user_id() -> str | None:
    return os.getenv("CIO_DISCORD_USER_ID", "").strip() or None

def _get_mentions() -> str:
    cio_id = _get_cio_user_id()
    return os.getenv("DISCORD_CIO_MENTIONS", f"<@{cio_id}>" if cio_id else "").strip()


def _bot_headers(token: str) -> dict:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
    }


def _post_halt_alert(bot_name: str, trigger: str) -> str | None:
    """Post ⚠️ Auto-Defensive Halt embed to risk-alerts. Returns message_id or None."""
    token, channel_id = _get_discord_creds()
    if not token or not channel_id:
        logger.warning("[auto_defensive_halt] Discord not configured — skipping alert")
        return None

    mention = _get_mentions()

    embed = {
        "title": "⚠️ Auto-Defensive Halt",
        "color": 0xFF4444,
        "fields": [
            {"name": "Bot", "value": bot_name, "inline": True},
            {"name": "Trigger", "value": trigger, "inline": False},
        ],
        "footer": {"text": "React ▶️ to resume"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload: dict = {"embeds": [embed]}
    if mention:
        payload["content"] = mention

    try:
        resp = httpx.post(
            f"{_DISCORD_API}/channels/{channel_id}/messages",
            headers=_bot_headers(token),
            json=payload,
            timeout=10,
        )
        if resp.is_success:
            msg_id = resp.json().get("id")
            # Pre-add ▶️ reaction so the CIO only needs to click
            _add_bot_reaction(channel_id, msg_id, _PLAY_EMOJI_ENCODED, token)
            return msg_id
        logger.warning("[auto_defensive_halt] Discord post failed: %s", resp.status_code)
    except Exception as exc:
        logger.warning("[auto_defensive_halt] Discord post error: %s", exc)
    return None


def _post_critical_alert(reason: str) -> None:
    """Post CRITICAL escalation — daily auto-pause cap reached, halting further pauses."""
    token, channel_id = _get_discord_creds()
    if not token or not channel_id:
        return
    mention = _get_mentions()
    embed = {
        "title": "🚨 CRITICAL — Auto-Halt Cap Reached",
        "description": reason,
        "color": 0xFF0000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload: dict = {"embeds": [embed]}
    if mention:
        payload["content"] = mention
    try:
        httpx.post(
            f"{_DISCORD_API}/channels/{channel_id}/messages",
            headers=_bot_headers(token),
            json=payload,
            timeout=10,
        )
    except Exception as exc:
        logger.warning("[auto_defensive_halt] CRITICAL alert post error: %s", exc)


def _add_bot_reaction(channel_id: str, message_id: str, emoji_encoded: str, token: str) -> None:
    """Bot adds a reaction to its own message (PUT @me reaction)."""
    try:
        url = f"{_DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{emoji_encoded}/@me"
        httpx.put(url, headers=_bot_headers(token), timeout=8)
    except Exception as exc:
        logger.debug("[auto_defensive_halt] add_reaction failed: %s", exc)


def _get_reactions(channel_id: str, message_id: str, emoji_encoded: str, token: str) -> list[str]:
    """Return list of user IDs who reacted with this emoji."""
    try:
        url = f"{_DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{emoji_encoded}"
        resp = httpx.get(url, headers=_bot_headers(token), timeout=8)
        if resp.status_code == 404:
            return []
        if not resp.is_success:
            return []
        return [str(u["id"]) for u in resp.json()]
    except Exception as exc:
        logger.debug("[auto_defensive_halt] get_reactions error: %s", exc)
        return []


def _post_resume_reply(channel_id: str, bot_name: str, token: str) -> None:
    """Post a brief confirmation when the CIO resumes a halted bot."""
    try:
        httpx.post(
            f"{_DISCORD_API}/channels/{channel_id}/messages",
            headers=_bot_headers(token),
            json={"content": f"▶️ Bot **{bot_name}** resumed by CIO"},
            timeout=10,
        )
    except Exception as exc:
        logger.debug("[auto_defensive_halt] resume reply failed: %s", exc)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _count_pauses_today(db: Session) -> int:
    """How many autonomous pauses have been recorded today?"""
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        row = db.execute(
            text("""
                SELECT COUNT(*) FROM proposal_audit
                WHERE proposal_type = 'autonomous_decision'
                  AND decision = 'executed'
                  AND DATE(generated_ts) = :today
            """),
            {"today": today},
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _get_24h_pnl(db: Session, bot_name: str) -> int:
    """Sum pnl_cents for this bot over the last 24 hours (returns cents)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        row = db.execute(
            text("""
                SELECT COALESCE(SUM(pnl_cents), 0) as pnl_24h
                FROM bot_trades
                WHERE bot_name = :bot AND executed_at >= :cutoff_24h
            """),
            {"bot": bot_name, "cutoff_24h": cutoff},
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _get_7d_pnl(db: Session, bot_name: str) -> int:
    """Sum pnl_cents for this bot over the last 7 days (returns cents)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        row = db.execute(
            text("""
                SELECT COALESCE(SUM(pnl_cents), 0) as pnl_7d
                FROM bot_trades
                WHERE bot_name = :bot AND executed_at >= :cutoff_7d
            """),
            {"bot": bot_name, "cutoff_7d": cutoff},
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _get_last_n_trades(db: Session, bot_name: str, n: int = 5) -> list[int]:
    """Return pnl_cents for the last n trades (most recent first)."""
    try:
        rows = db.execute(
            text("""
                SELECT pnl_cents FROM bot_trades
                WHERE bot_name = :bot
                ORDER BY executed_at DESC
                LIMIT :n
            """),
            {"bot": bot_name, "n": n},
        ).fetchall()
        return [int(r[0]) for r in rows]
    except Exception:
        return []


def _pause_bot(db: Session, bot_name: str, reason: str) -> bool:
    """
    Pause the bot by setting status='PAUSED' on bot_profiles.
    Falls back gracefully if the status or reason_paused column doesn't exist.
    """
    try:
        # Try the full update with status + reason_paused
        db.execute(
            text("""
                UPDATE bot_profiles
                SET status = 'PAUSED', reason_paused = :reason
                WHERE name = :bot
            """),
            {"reason": reason, "bot": bot_name},
        )
        db.commit()
        return True
    except Exception:
        # reason_paused column may not exist — try without it
        try:
            db.rollback()
            db.execute(
                text("UPDATE bot_profiles SET status = 'PAUSED' WHERE name = :bot"),
                {"bot": bot_name},
            )
            db.commit()
            return True
        except Exception as exc2:
            logger.warning("[auto_defensive_halt] pause_bot failed for %s: %s", bot_name, exc2)
            db.rollback()
            return False


def _write_audit_record(
    db: Session,
    bot_name: str,
    reason: str,
    message_id: str | None,
    channel_id: str | None,
) -> str | None:
    """Write autonomous_decision record to proposal_audit. Returns proposal_id."""
    proposal_id = f"auto_halt_{bot_name}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    proposed_change = json.dumps({"bot": bot_name, "action": "pause", "trigger": reason})
    try:
        db.execute(
            text("""
                INSERT INTO proposal_audit (
                    proposal_id, proposal_type, generated_ts,
                    posted_message_id, posted_channel_id,
                    proposed_change, rationale, derived_from_finding_ids,
                    decision, decision_ts
                ) VALUES (
                    :pid, 'autonomous_decision', :ts,
                    :msg_id, :ch_id,
                    :proposed_change, :rationale, '[]',
                    'executed', :ts
                )
            """),
            {
                "pid": proposal_id,
                "ts": now,
                "msg_id": message_id,
                "ch_id": channel_id,
                "proposed_change": proposed_change,
                "rationale": reason,
            },
        )
        db.commit()
        return proposal_id
    except Exception as exc:
        logger.warning("[auto_defensive_halt] audit write failed: %s", exc)
        db.rollback()
        return None


# ── Main check ────────────────────────────────────────────────────────────────

def run_defensive_halt_check(db: Session) -> dict:
    """
    Runs every 15 minutes. Returns {"checked": n, "halted": n, "skipped_cap": bool}.

    For each enabled bot, evaluates three breach conditions:
      1. 24h drawdown > -5% of starting_capital_cents
      2. 7-day drawdown > -10% of starting_capital_cents
      3. 5+ consecutive losing trades AND drawdown > -3%

    DEFENSIVE ONLY — can ONLY pause (status='PAUSED').
    Max 3 auto-pauses per 24h; if the cap is hit, escalates to CRITICAL and stops.
    """
    checked = 0
    halted = 0
    skipped_cap = False

    # Fetch enabled bots that are not already paused
    try:
        rows = db.execute(
            text("""
                SELECT bp.name, bp.id, ba.capital_pct, ba.starting_capital_cents, bp.status
                FROM bot_profiles bp
                JOIN bot_allocations ba ON bp.id = ba.profile_id
                WHERE ba.enabled = 1 AND COALESCE(bp.status, '') != 'PAUSED'
            """),
        ).fetchall()
    except Exception as exc:
        logger.error("[auto_defensive_halt] failed to fetch enabled bots: %s", exc)
        return {"checked": 0, "halted": 0, "skipped_cap": False}

    token, channel_id = _get_discord_creds()

    for row in rows:
        bot_name = row[0]
        starting_capital = int(row[3]) if row[3] else 0
        checked += 1

        if starting_capital <= 0:
            continue

        breach_reason: str | None = None

        # ── Condition 1: 24h drawdown > -5% ──────────────────────────────────
        pnl_24h = _get_24h_pnl(db, bot_name)
        pct_24h = (pnl_24h / starting_capital) * 100.0
        if pct_24h <= DRAWDOWN_24H_PCT:
            breach_reason = (
                f"24h drawdown {pct_24h:.2f}% exceeds -{abs(DRAWDOWN_24H_PCT)}% threshold "
                f"(P&L: ${pnl_24h / 100:.2f})"
            )

        # ── Condition 2: 7-day drawdown > -10% ───────────────────────────────
        if breach_reason is None:
            pnl_7d = _get_7d_pnl(db, bot_name)
            pct_7d = (pnl_7d / starting_capital) * 100.0
            if pct_7d <= DRAWDOWN_7D_PCT:
                breach_reason = (
                    f"7-day drawdown {pct_7d:.2f}% exceeds -{abs(DRAWDOWN_7D_PCT)}% threshold "
                    f"(P&L: ${pnl_7d / 100:.2f})"
                )

        # ── Condition 3: 5+ consecutive losses AND drawdown > -3% ────────────
        if breach_reason is None:
            last_trades = _get_last_n_trades(db, bot_name, CONSEC_LOSS_N)
            if len(last_trades) >= CONSEC_LOSS_N and all(p < 0 for p in last_trades):
                pnl_24h_for_consec = _get_24h_pnl(db, bot_name)
                pct_consec = (pnl_24h_for_consec / starting_capital) * 100.0
                if pct_consec <= CONSEC_LOSS_DD_PCT:
                    breach_reason = (
                        f"{CONSEC_LOSS_N} consecutive losing trades with "
                        f"{pct_consec:.2f}% drawdown (exceeds -{abs(CONSEC_LOSS_DD_PCT)}% threshold)"
                    )

        if breach_reason is None:
            continue

        # ── Cap check: max 3 auto-pauses per 24h ─────────────────────────────
        pause_count = _count_pauses_today(db)
        if pause_count >= MAX_AUTO_PAUSES_PER_DAY:
            skipped_cap = True
            _post_critical_alert(
                f"Auto-pause cap ({MAX_AUTO_PAUSES_PER_DAY}/day) reached. "
                f"Bot {bot_name} breached: {breach_reason}. Manual intervention required."
            )
            logger.error(
                "[auto_defensive_halt] cap reached (%d/%d) — skipping pause for %s: %s",
                pause_count, MAX_AUTO_PAUSES_PER_DAY, bot_name, breach_reason,
            )
            return {"checked": checked, "halted": halted, "skipped_cap": True}

        # ── Pause the bot ─────────────────────────────────────────────────────
        paused = _pause_bot(db, bot_name, breach_reason)
        if not paused:
            logger.error("[auto_defensive_halt] failed to pause %s", bot_name)
            continue

        logger.warning(
            "[auto_defensive_halt] PAUSED bot=%s reason=%s", bot_name, breach_reason
        )

        # ── Post Discord alert + pre-add ▶️ reaction ──────────────────────────
        msg_id = _post_halt_alert(bot_name, breach_reason)

        # ── Write audit record ────────────────────────────────────────────────
        _write_audit_record(db, bot_name, breach_reason, msg_id, channel_id or None)

        halted += 1

    return {"checked": checked, "halted": halted, "skipped_cap": skipped_cap}


# ── Resume check ──────────────────────────────────────────────────────────────

def run_resume_check(db: Session) -> dict:
    """
    Runs every 2 minutes. Checks for ▶️ reactions on auto-halt messages.
    If CIO_DISCORD_USER_ID reacted, unpauses the bot and updates the audit record.

    Returns {"checked": n, "resumed": n}.
    """
    cio_id = _get_cio_user_id()
    if not cio_id:
        return {"checked": 0, "resumed": 0}

    token, _ = _get_discord_creds()
    if not token:
        return {"checked": 0, "resumed": 0}

    # Fetch unresolved autonomous halt records that have a message posted
    try:
        rows = db.execute(
            text("""
                SELECT id, proposal_id, posted_message_id, posted_channel_id, proposed_change
                FROM proposal_audit
                WHERE proposal_type = 'autonomous_decision'
                  AND decision = 'executed'
                  AND posted_message_id IS NOT NULL
                  AND posted_channel_id IS NOT NULL
            """),
        ).fetchall()
    except Exception as exc:
        logger.debug("[auto_defensive_halt] resume_check fetch failed: %s", exc)
        return {"checked": 0, "resumed": 0}

    checked = 0
    resumed = 0

    for row in rows:
        audit_id = row[0]
        proposal_id = row[1]
        message_id = row[2]
        channel_id_row = row[3]
        proposed_change_raw = row[4]
        checked += 1

        # Parse the bot name from the proposed_change JSON
        try:
            change = json.loads(proposed_change_raw) if isinstance(proposed_change_raw, str) else proposed_change_raw
            bot_name = change.get("bot", "")
        except Exception:
            continue

        if not bot_name:
            continue

        # Check if CIO reacted with ▶️
        reactors = _get_reactions(channel_id_row, message_id, _PLAY_EMOJI_ENCODED, token)
        if cio_id not in reactors:
            continue

        # ── Unpause the bot ───────────────────────────────────────────────────
        try:
            db.execute(
                text("""
                    UPDATE bot_profiles
                    SET status = 'ACTIVE', reason_paused = NULL
                    WHERE name = :bot
                """),
                {"bot": bot_name},
            )
        except Exception:
            # reason_paused column may not exist
            try:
                db.rollback()
                db.execute(
                    text("UPDATE bot_profiles SET status = 'ACTIVE' WHERE name = :bot"),
                    {"bot": bot_name},
                )
            except Exception as exc2:
                logger.warning("[auto_defensive_halt] unpause failed for %s: %s", bot_name, exc2)
                db.rollback()
                continue

        # ── Update audit record ───────────────────────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        try:
            db.execute(
                text("""
                    UPDATE proposal_audit
                    SET decision = 'manually_resumed', decision_ts = :now
                    WHERE id = :id
                """),
                {"now": now, "id": audit_id},
            )
        except Exception as exc:
            logger.warning("[auto_defensive_halt] audit update failed: %s", exc)

        try:
            db.commit()
        except Exception as exc:
            logger.warning("[auto_defensive_halt] commit failed: %s", exc)
            db.rollback()
            continue

        # ── Post reply confirmation ───────────────────────────────────────────
        _post_resume_reply(channel_id_row, bot_name, token)

        logger.warning(
            "[auto_defensive_halt] bot=%s resumed by CIO (proposal=%s)",
            bot_name, proposal_id,
        )
        resumed += 1

    return {"checked": checked, "resumed": resumed}
