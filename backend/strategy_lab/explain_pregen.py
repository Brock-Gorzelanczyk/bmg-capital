"""Hourly background job: pre-generate AI explanations for the latest signal per active bot."""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _already_explained(conn, source: str, signal_id: int) -> bool:
    from sqlalchemy import text
    row = conn.execute(
        text("SELECT 1 FROM signal_explanations WHERE signal_source=:s AND signal_id=:i"),
        {"s": source, "i": signal_id},
    ).fetchone()
    return row is not None


def _save(conn, source: str, signal_id: int, explanation: str) -> None:
    from sqlalchemy import text
    from app.services.signal_explain import MODEL
    conn.execute(
        text("""
            INSERT INTO signal_explanations (signal_source, signal_id, explanation, model_used)
            VALUES (:s, :i, :e, :m)
            ON CONFLICT(signal_source, signal_id) DO NOTHING
        """),
        {"s": source, "i": signal_id, "e": explanation, "m": MODEL},
    )
    conn.commit()


async def _generate_one(signal: dict, source: str, signal_id: int) -> str | None:
    from app.services.signal_explain import _call_haiku
    try:
        return await _call_haiku(signal)
    except Exception as exc:
        logger.warning("[explain-pregen] haiku failed for %s #%d: %s", source, signal_id, exc)
        return None


def run_explain_pregen() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.debug("[explain-pregen] no ANTHROPIC_API_KEY, skipping")
        return

    from app.db.session import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    generated = 0
    skipped = 0

    try:
        # ── Bot signals: latest per allocation ────────────────────────────────
        bot_rows = db.execute(text("""
            SELECT bs.id, bs.symbol, bs.side, bs.confidence,
                   bs.entry_price, bs.stop_price, bs.target_price,
                   bs.reason, bs.strategy
            FROM bot_signals bs
            WHERE bs.id IN (
                SELECT MAX(id) FROM bot_signals GROUP BY allocation_id
            )
            ORDER BY bs.id DESC
            LIMIT 50
        """)).fetchall()

        for row in bot_rows:
            sig_id = row[0]
            if _already_explained(db, "bot", sig_id):
                skipped += 1
                continue
            signal = {
                "ticker": row[1], "side": row[2], "confidence": row[3],
                "entry_price": row[4], "stop_price": row[5], "target_price": row[6],
                "reason": row[7], "strategy": row[8],
            }
            explanation = asyncio.run(_generate_one(signal, "bot", sig_id))
            if explanation:
                _save(db, "bot", sig_id, explanation)
                generated += 1

        # ── Scout signals: latest per setup ──────────────────────────────────
        try:
            from app.db.models.scout import UserScoutSignal
            from sqlalchemy import func
            scout_rows = (
                db.query(UserScoutSignal)
                .order_by(UserScoutSignal.id.desc())
                .limit(30)
                .all()
            )
            for row in scout_rows:
                if _already_explained(db, "scout", row.id):
                    skipped += 1
                    continue
                signal = {
                    "ticker": row.ticker, "side": row.side, "confidence": row.confidence,
                    "entry_price": row.entry_price, "stop_price": row.stop_price,
                    "target_price": row.target_price, "reason": row.reason,
                    "strategy": row.display_name,
                }
                explanation = asyncio.run(_generate_one(signal, "scout", row.id))
                if explanation:
                    _save(db, "scout", row.id, explanation)
                    generated += 1
        except Exception as exc:
            logger.warning("[explain-pregen] scout pass failed: %s", exc)

        # ── Forge signals: latest per bot ─────────────────────────────────────
        try:
            from app.db.models.forge import UserForgeSignal
            forge_rows = (
                db.query(UserForgeSignal)
                .order_by(UserForgeSignal.id.desc())
                .limit(30)
                .all()
            )
            for row in forge_rows:
                if _already_explained(db, "forge", row.id):
                    skipped += 1
                    continue
                signal = {
                    "ticker": row.ticker, "side": row.side, "confidence": row.confidence,
                    "entry_price": row.entry_price, "stop_price": row.stop_price,
                    "target_price": row.target_price, "reason": row.reason,
                    "strategy": row.strategy_id,
                }
                explanation = asyncio.run(_generate_one(signal, "forge", row.id))
                if explanation:
                    _save(db, "forge", row.id, explanation)
                    generated += 1
        except Exception as exc:
            logger.warning("[explain-pregen] forge pass failed: %s", exc)

        logger.info("[explain-pregen] done — generated=%d skipped=%d", generated, skipped)

    except Exception as exc:
        logger.error("[explain-pregen] fatal: %s", exc, exc_info=True)
    finally:
        db.close()
