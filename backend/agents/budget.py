"""
Daily API budget enforcement for the BMG Capital agent fleet.
Hard cap: $3.00/day. Resets at midnight UTC.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, date as _date
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

DAILY_HARD_CAP_USD = 3.00
DAILY_WARN_THRESHOLD = 0.80   # warn at 80% ($2.40)

# Haiku pricing (approximate, per 1M tokens)
HAIKU_INPUT_PER_M  = 0.80
HAIKU_OUTPUT_PER_M = 4.00
# Default cost per call when exact token count not available
DEFAULT_CALL_COST_USD = 0.001   # ~1000 input + 300 output tokens typical


def _ensure_tables(db: Session) -> None:
    """CREATE TABLE IF NOT EXISTS for daily_budget_state and agent_api_spend."""
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_budget_state (
                date            DATE PRIMARY KEY,
                total_spent_usd DECIMAL(10,4) DEFAULT 0,
                cap_hit         BOOLEAN DEFAULT false,
                cap_hit_at      TIMESTAMP,
                warn_sent       BOOLEAN DEFAULT false,
                resumed_manual  BOOLEAN DEFAULT false
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_api_spend (
                date            DATE        NOT NULL,
                agent_id        VARCHAR(40) NOT NULL,
                total_spent_usd DECIMAL(10,4) DEFAULT 0,
                call_count      INTEGER DEFAULT 0,
                PRIMARY KEY (date, agent_id)
            )
        """))
        db.commit()
    except Exception as exc:
        logger.warning("[budget] _ensure_tables failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def get_today_state(db: Session) -> dict:
    """
    Return the row for today (UTC date).  Creates it if absent.
    Keys: date, total_spent_usd (float), cap_hit (bool), cap_hit_at,
          warn_sent (bool), resumed_manual (bool).
    """
    today = _date.today().isoformat()
    try:
        _ensure_tables(db)
        row = db.execute(
            text("SELECT date, total_spent_usd, cap_hit, cap_hit_at, warn_sent, resumed_manual "
                 "FROM daily_budget_state WHERE date = :d"),
            {"d": today},
        ).fetchone()

        if row is None:
            db.execute(
                text("""
                    INSERT INTO daily_budget_state (date, total_spent_usd, cap_hit, warn_sent, resumed_manual)
                    VALUES (:d, 0, false, false, false)
                """),
                {"d": today},
            )
            db.commit()
            return {
                "date": today,
                "total_spent_usd": 0.0,
                "cap_hit": False,
                "cap_hit_at": None,
                "warn_sent": False,
                "resumed_manual": False,
            }

        return {
            "date": str(row[0]),
            "total_spent_usd": float(row[1] or 0),
            "cap_hit": bool(row[2]),
            "cap_hit_at": row[3],
            "warn_sent": bool(row[4]),
            "resumed_manual": bool(row[5]),
        }
    except Exception as exc:
        logger.warning("[budget] get_today_state failed: %s", exc)
        return {
            "date": today,
            "total_spent_usd": 0.0,
            "cap_hit": False,
            "cap_hit_at": None,
            "warn_sent": False,
            "resumed_manual": False,
        }


def charge(db: Session, agent_id: str, cost_usd: float) -> bool:
    """
    Record an API spend charge and return True if the charge was accepted (under cap).
    Returns False if the daily cap is hit (callers must skip the LLM call).

    Side effects:
    - Increments total_spent_usd in daily_budget_state
    - Upserts agent_api_spend for per-agent tracking
    - Posts Discord notices at warn (80%) and cap thresholds
    """
    try:
        _ensure_tables(db)
        state = get_today_state(db)
        today = state["date"]

        # Cap is hit and not manually resumed — reject immediately
        if state["cap_hit"] and not state["resumed_manual"]:
            logger.info("[budget] cap active — rejecting charge for %s ($%.5f)", agent_id, cost_usd)
            return False

        new_total = state["total_spent_usd"] + cost_usd

        if new_total > DAILY_HARD_CAP_USD:
            # Hit the cap
            now_ts = datetime.now(timezone.utc).isoformat()
            try:
                db.execute(
                    text("""
                        UPDATE daily_budget_state
                        SET total_spent_usd = :t, cap_hit = true, cap_hit_at = :ts
                        WHERE date = :d
                    """),
                    {"t": new_total, "ts": now_ts, "d": today},
                )
                db.commit()
            except Exception as exc:
                logger.warning("[budget] failed to write cap_hit state: %s", exc)
                try:
                    db.rollback()
                except Exception:
                    pass

            _post_budget_notice(
                content=(
                    "\U0001f6d1 Daily API budget hit ($3.00). "
                    "Brick, Dick, Researcher pausing LLM work until midnight UTC. "
                    "Rule-based monitoring continues."
                ),
                color=0xFF0000,
                post_to_fund_team=True,
            )
            logger.warning("[budget] daily cap hit — total would be $%.4f", new_total)
            return False

        # Charge accepted — increment
        try:
            db.execute(
                text("""
                    UPDATE daily_budget_state
                    SET total_spent_usd = :t
                    WHERE date = :d
                """),
                {"t": new_total, "d": today},
            )
            db.commit()
        except Exception as exc:
            logger.warning("[budget] failed to increment total_spent_usd: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # Upsert agent_api_spend
        try:
            db.execute(
                text("""
                    INSERT INTO agent_api_spend (date, agent_id, total_spent_usd, call_count)
                    VALUES (:d, :a, :cost, 1)
                    ON CONFLICT (date, agent_id) DO UPDATE
                    SET total_spent_usd = agent_api_spend.total_spent_usd + :cost,
                        call_count      = agent_api_spend.call_count + 1
                """),
                {"d": today, "a": agent_id, "cost": cost_usd},
            )
            db.commit()
        except Exception as exc:
            logger.warning("[budget] agent_api_spend upsert failed (non-fatal): %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # Warn threshold check (80%)
        warn_threshold = DAILY_HARD_CAP_USD * DAILY_WARN_THRESHOLD
        if new_total >= warn_threshold and not state["warn_sent"]:
            try:
                db.execute(
                    text("UPDATE daily_budget_state SET warn_sent = true WHERE date = :d"),
                    {"d": today},
                )
                db.commit()
            except Exception as exc:
                logger.warning("[budget] failed to set warn_sent: %s", exc)
                try:
                    db.rollback()
                except Exception:
                    pass

            _post_budget_notice(
                content=(
                    f"⚠️ Daily API budget at 80% (${new_total:.2f} of $3.00). "
                    "LLM-dependent features will pause if cap is hit."
                ),
                color=0xFFA500,
                post_to_fund_team=False,
            )

        return True

    except Exception as exc:
        logger.warning("[budget] charge() unexpected error (fail-open): %s", exc)
        return True  # fail open — never crash an agent on budget accounting errors


def is_capped(db: Session) -> bool:
    """Quick check whether today's cap is hit (without incrementing spend)."""
    try:
        state = get_today_state(db)
        return state["cap_hit"] and not state["resumed_manual"]
    except Exception as exc:
        logger.warning("[budget] is_capped check failed (fail-open): %s", exc)
        return False


def reset_cap(db: Session) -> None:
    """Manually lift the cap for today (sets resumed_manual=True). LLM work resumes."""
    try:
        _ensure_tables(db)
        today = _date.today().isoformat()
        db.execute(
            text("UPDATE daily_budget_state SET resumed_manual = true WHERE date = :d"),
            {"d": today},
        )
        db.commit()
        logger.info("[budget] cap manually reset for %s", today)
    except Exception as exc:
        logger.warning("[budget] reset_cap failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def get_status(db: Session) -> dict:
    """
    Return a budget status summary dict.

    Example return value:
    {
        "cap_usd": 3.00,
        "spent_today_usd": 1.42,
        "remaining_usd": 1.58,
        "pct_used": 47.3,
        "cap_hit": False,
        "reset_at": "2026-06-13T00:00:00Z",
        "per_agent_spend": {}
    }
    """
    try:
        _ensure_tables(db)
        state = get_today_state(db)
        today = state["date"]
        spent = state["total_spent_usd"]
        remaining = max(0.0, DAILY_HARD_CAP_USD - spent)
        pct_used = round((spent / DAILY_HARD_CAP_USD) * 100, 1) if DAILY_HARD_CAP_USD > 0 else 0.0

        # Compute tomorrow midnight UTC as the reset time
        from datetime import timedelta
        today_dt = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        reset_at = (today_dt + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

        # Per-agent spend
        per_agent: dict[str, float] = {}
        try:
            rows = db.execute(
                text("SELECT agent_id, total_spent_usd FROM agent_api_spend WHERE date = :d"),
                {"d": today},
            ).fetchall()
            for row in rows:
                per_agent[str(row[0])] = float(row[1] or 0)
        except Exception as exc:
            logger.warning("[budget] get_status per_agent query failed: %s", exc)

        return {
            "cap_usd": DAILY_HARD_CAP_USD,
            "spent_today_usd": round(spent, 4),
            "remaining_usd": round(remaining, 4),
            "pct_used": pct_used,
            "cap_hit": state["cap_hit"] and not state["resumed_manual"],
            "reset_at": reset_at,
            "per_agent_spend": per_agent,
        }
    except Exception as exc:
        logger.warning("[budget] get_status failed: %s", exc)
        return {
            "cap_usd": DAILY_HARD_CAP_USD,
            "spent_today_usd": 0.0,
            "remaining_usd": DAILY_HARD_CAP_USD,
            "pct_used": 0.0,
            "cap_hit": False,
            "reset_at": "",
            "per_agent_spend": {},
        }


def _post_budget_notice(content: str, color: int, post_to_fund_team: bool = False) -> None:
    """
    Post a budget notice to Discord channels via the bot API.

    Always posts to #dev-log (DISCORD_CH_DEV_LOG env var).
    On cap-hit (post_to_fund_team=True), also posts to #fund-team-chat
    via webhook (DISCORD_WH_FUND_TEAM_CHAT env var).
    """
    bot_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    dev_log_channel_id = os.getenv("DISCORD_CH_DEV_LOG", "").strip()
    fund_team_webhook = os.getenv("DISCORD_WH_FUND_TEAM_CHAT", "").strip()

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
    }

    # Post to #dev-log via bot API
    if bot_token and dev_log_channel_id:
        try:
            import httpx
            url = f"https://discord.com/api/v10/channels/{dev_log_channel_id}/messages"
            httpx.post(
                url,
                json={"content": content},
                headers=headers,
                timeout=5,
            )
        except Exception as exc:
            logger.debug("[budget] dev-log Discord post failed: %s", exc)

    # On cap-hit: also post to #fund-team-chat webhook
    if post_to_fund_team and fund_team_webhook:
        try:
            import httpx
            httpx.post(
                fund_team_webhook,
                json={"content": content},
                timeout=5,
            )
        except Exception as exc:
            logger.debug("[budget] fund-team-chat webhook post failed: %s", exc)
