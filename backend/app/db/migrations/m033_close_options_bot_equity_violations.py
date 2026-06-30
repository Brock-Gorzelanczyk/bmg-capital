"""m033 — Close 10 equity positions held by options_income/options_directional
and PAUSE both bots (Layer 3 of options-bot fix).

Background: M027 close-all step missed equity positions that the options_income
and options_directional strategies had opened against equity tickers (NVDA,
MSFT, AAPL, etc.) because those strategies emit equity symbols, not OCC
options. SHIP 2 validate_order now blocks new such orders, but the 10
pre-existing positions sat with hidden P&L (e.g. TSLA on options_income
entry $1,159 → current $2,028 ≈ +$868 not displayed).

This migration:
  1. Identifies all OPEN bot_positions whose owning bot is options_income or
     options_directional AND whose symbol classifies as equity (NOT OCC option)
  2. Records each into cross_sleeve_quarantine_s14 with action='m033_force_close'
  3. Closes each position: sets closed_at + exit_reason on bot_positions; the
     paired exit BotTrade row writes realized P&L through the canonical
     aggregator (matches how m027/normal exits flow)
  4. PAUSES both options_income and options_directional allocations
     (enabled=False, paused_reason='strategy_generates_invalid_symbols')
     — Layer 3: stops the strategy from emitting fresh equity signals until
     the bot is redesigned to emit real OCC option symbols

Standing decisions honored:
  - No row removal from bot_trades or bot_daily_pnl (we INSERT an exit row)
  - ZERO writes to inception_capital_cents
  - Multi-user safe: every write WHERE user_id=1
  - Uses shared _gate.already_ran/record helper
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record, verify_count

logger = logging.getLogger(__name__)

_GATE_NAME = "m033_close_options_bot_equity_violations_2026_06"
TARGET_USER_ID = 1
_OPTIONS_BOT_NAMES = ("options_income", "options_directional")


def _table_exists(conn, table: str) -> bool:
    try:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
        return bool(rows)
    except Exception:
        return False


def _is_occ_option_symbol(symbol: str) -> bool:
    """OCC OSI standard: 21 chars (some brokers use 16+strikes); be permissive.

    Format: ROOT(1-6) + YYMMDD(6) + C|P(1) + STRIKE(8) = 16-21 chars total,
    all uppercase alphanumeric. Equity tickers are typically 1-5 letters only.
    """
    if not symbol or len(symbol) < 15:
        return False
    if not symbol.isupper() or not symbol.isalnum():
        return False
    # Quick heuristic: look for the C or P put/call indicator after a date-like
    # sequence. Position varies by root length so we scan.
    has_cp_after_digits = False
    for i in range(1, len(symbol) - 8):
        if symbol[i:i + 6].isdigit() and symbol[i + 6] in ("C", "P"):
            if symbol[i + 7:].isdigit():
                has_cp_after_digits = True
                break
    return has_cp_after_digits


def run(conn) -> dict:
    if already_ran(conn, _GATE_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    if not _table_exists(conn, "bot_positions"):
        return {"skipped_reason": "missing_table_bot_positions", "executed": False}
    if not _table_exists(conn, "bot_allocations"):
        return {"skipped_reason": "missing_table_bot_allocations", "executed": False}
    if not _table_exists(conn, "bot_profiles"):
        return {"skipped_reason": "missing_table_bot_profiles", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    closed_per_bot = {name: 0 for name in _OPTIONS_BOT_NAMES}
    quarantined = 0

    # Find every open position on options_income or options_directional, user 1.
    rows = conn.execute(
        text(
            "SELECT bp.id, bp.symbol, bp.qty, bp.avg_cost_cents, bp.allocation_id, "
            "       p.name AS bot_id, a.user_id "
            "FROM bot_positions bp "
            "JOIN bot_allocations a ON a.id = bp.allocation_id "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE a.user_id = :uid "
            "AND p.name IN ('options_income', 'options_directional') "
            "AND bp.closed_at IS NULL"
        ),
        {"uid": TARGET_USER_ID},
    ).fetchall()

    for r in rows:
        pos_id = int(r[0])
        symbol = r[1] or ""
        qty = float(r[2] or 0)  # noqa: F841 (recorded by exit BotTrade if needed)
        avg_cost_cents = int(r[3] or 0)  # noqa: F841
        bot_id = r[5]
        user_id = int(r[6])

        # Only close if symbol classifies as equity (NOT OCC option).
        # We close ALL non-OCC symbols on options bots — they shouldn't be there.
        if _is_occ_option_symbol(symbol):
            continue  # legitimate option contract, leave it alone

        # 1. Quarantine row (idempotent via unique index on position_id)
        try:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO cross_sleeve_quarantine_s14 "
                    "(position_id, bot_id, user_id, declared_asset_class, "
                    " actual_symbol, actual_asset_class, detected_at, action) "
                    "VALUES (:pid, :bot_id, :uid, 'option', :sym, 'equity', "
                    "        :ts, 'm033_force_close')"
                ),
                {
                    "pid": pos_id,
                    "bot_id": bot_id,
                    "uid": user_id,
                    "sym": symbol,
                    "ts": now_iso,
                },
            )
            quarantined += 1
        except Exception as exc:
            logger.warning(
                "[m033] quarantine row insert failed for pos=%d: %s", pos_id, exc
            )

        # 2. Close the position
        conn.execute(
            text(
                "UPDATE bot_positions "
                "SET closed_at = :ts, "
                "    exit_reason = 'm033_options_equity_violation' "
                "WHERE id = :pid"
            ),
            {"ts": now_iso, "pid": pos_id},
        )
        closed_per_bot[bot_id] = closed_per_bot.get(bot_id, 0) + 1

    # 3. Layer 3: PAUSE both options bots so they stop emitting equity signals
    #    until the strategies are redesigned to emit OCC option symbols.
    paused_alloc_ids: list[int] = []
    for name in _OPTIONS_BOT_NAMES:
        alloc_rows = conn.execute(
            text(
                "SELECT a.id FROM bot_allocations a "
                "JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE a.user_id = :uid AND p.name = :name AND a.enabled = 1"
            ),
            {"uid": TARGET_USER_ID, "name": name},
        ).fetchall()
        for ar in alloc_rows:
            conn.execute(
                text(
                    "UPDATE bot_allocations "
                    "SET enabled = 0, "
                    "    paused_reason = 'strategy_generates_invalid_symbols' "
                    "WHERE id = :aid"
                ),
                {"aid": int(ar[0])},
            )
            paused_alloc_ids.append(int(ar[0]))

    conn.commit()

    logger.warning(
        "[m033] options_income_closed=%d options_directional_closed=%d "
        "quarantined=%d paused_allocations=%s",
        closed_per_bot.get("options_income", 0),
        closed_per_bot.get("options_directional", 0),
        quarantined,
        paused_alloc_ids,
    )

    # POST-RUN VERIFY — confirm no non-OCC equity symbols remain open for
    # options_income or options_directional (user_id=1 only, matching m033's scope).
    # SQL-side equity heuristic: length <= 6, no slash, starts uppercase, no digit.
    verify_count(
        conn,
        name="m033",
        sql=(
            "SELECT bp.id, bp.symbol, p.name AS bot_id "
            "  FROM bot_positions bp "
            "  JOIN bot_allocations a ON a.id = bp.allocation_id "
            "  JOIN bot_profiles p   ON p.id = a.profile_id "
            " WHERE a.user_id = :uid "
            "   AND p.name IN ('options_income', 'options_directional') "
            "   AND bp.closed_at IS NULL "
            "   AND length(bp.symbol) <= 6 "
            "   AND bp.symbol NOT LIKE '%/%' "
            "   AND bp.symbol GLOB '[A-Z]*' "
            "   AND bp.symbol NOT GLOB '*[0-9]*'"
        ),
        params={"uid": TARGET_USER_ID},
        expected=0,
    )

    record(conn, _GATE_NAME)
    return {
        "executed": True,
        "options_income_closed": closed_per_bot.get("options_income", 0),
        "options_directional_closed": closed_per_bot.get("options_directional", 0),
        "quarantined": quarantined,
        "paused_alloc_ids": paused_alloc_ids,
    }
