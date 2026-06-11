"""Trading gate — global halt/reopen switch for all order submission.

Default state: OPEN (is_open=1).  Fail-open: any exception → allow.
"""
from __future__ import annotations

import logging
import os

import httpx

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _post_to_sentinel_ops(title: str, description: str, color: int) -> None:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel = os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")
    if not token or not channel:
        return
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    try:
        with httpx.Client(timeout=8) as client:
            client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"embeds": [{"title": title, "description": description, "color": color}]},
            )
    except Exception as exc:
        logger.warning("[trading_gate] Discord post failed: %s", exc)


class TradingGate:
    @staticmethod
    def is_open() -> bool:
        """Returns True if trading is allowed.  Fail-open on any exception."""
        try:
            db = SessionLocal()
            try:
                from sqlalchemy import text
                row = db.execute(
                    text("SELECT is_open FROM trading_gate_state ORDER BY id DESC LIMIT 1")
                ).fetchone()
                return row is None or row[0] == 1
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[trading_gate] is_open() failed, defaulting to OPEN: %s", exc)
            return True

    @staticmethod
    def halt(reason: str, halted_by: str) -> None:
        try:
            db = SessionLocal()
            try:
                from sqlalchemy import text
                db.execute(text(
                    "INSERT INTO trading_gate_state "
                    "(is_open, halt_reason, halted_at, halted_by) "
                    "VALUES (0, :reason, CURRENT_TIMESTAMP, :by)"
                ), {"reason": reason, "by": halted_by})
                db.execute(text(
                    "INSERT INTO trading_gate_audit (event, reason) VALUES ('halt', :reason)"
                ), {"reason": reason})
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.error("[trading_gate] halt() failed: %s", exc)
            return
        _post_to_sentinel_ops(
            title="🛑 TRADING HALTED",
            description=f"Reason: {reason}\nHalted by: {halted_by}",
            color=0xFF0000,
        )
        logger.warning("[trading_gate] HALTED — reason=%s by=%s", reason, halted_by)

    @staticmethod
    def reopen(reopened_by: str) -> None:
        try:
            db = SessionLocal()
            try:
                from sqlalchemy import text
                db.execute(text(
                    "UPDATE trading_gate_state "
                    "SET is_open=1, reopened_at=CURRENT_TIMESTAMP, reopened_by=:by "
                    "WHERE id=(SELECT id FROM trading_gate_state ORDER BY id DESC LIMIT 1)"
                ), {"by": reopened_by})
                db.execute(text(
                    "INSERT INTO trading_gate_audit (event, reason) VALUES ('reopen', :reason)"
                ), {"reason": f"reopened by {reopened_by}"})
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.error("[trading_gate] reopen() failed: %s", exc)
            return
        _post_to_sentinel_ops(
            title="✅ TRADING REOPENED",
            description=f"Reopened by: {reopened_by}",
            color=0x00FF00,
        )
        logger.info("[trading_gate] REOPENED — by=%s", reopened_by)


class TradingHaltedException(Exception):
    """Raised when an order is blocked by the trading gate."""
