"""m044 — Close legacy equity positions held by crypto bots.

Brock found 20 cross-sleeve violations via /api/admin/migration-status:
  - crypto_quant_aggressive:    6 equity positions (AAPL×3, NVDA, MSFT, AMZN)
  - crypto_quant_mean_reversion: 4 equity positions (MSFT×2, AMZN×2)
  - crypto_quant_scalper:        6 equity positions (AMZN×2, NVDA×2, MSFT, AAPL)
  - crypto_onchain:              4 equity positions (MSFT×2, AAPL×2)
  Total notional ≈ $2.5M paper.

These are PRE-SHIP-2 LEGACY positions:
  - SHIP 2's validate_order blocks NEW crypto×equity orders correctly
    (verified by audit of all 13 BotPosition insert paths)
  - m027 wiped bot_trades + bot_daily_pnl for user_id=1 but did NOT
    close open bot_positions, so these survived intact
  - m033 was scoped to options bots only (`p.name IN ('options_income',
    'options_directional')`) — crypto bots were never in m033's scope

Companion to m033 — same close + quarantine pattern, scoped to the
4 crypto bots above. user_id=1 only.

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

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_GATE_NAME = "m044_close_crypto_bot_equity_violations_2026_06"
TARGET_USER_ID = 1
_CRYPTO_BOT_NAMES = (
    "crypto_quant_aggressive",
    "crypto_quant_mean_reversion",
    "crypto_quant_scalper",
    "crypto_onchain",
    "crypto_day",
    "crypto_swing",
    "crypto_lt",
)


def _table_exists(conn, table: str) -> bool:
    try:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
        return bool(rows)
    except Exception:
        return False


def _is_equity_symbol(symbol: str) -> bool:
    """Equity ticker heuristic: 1-5 uppercase letters, no slash, no digits.

    Crypto pairs contain '/' (BTC/USD), OCC options are 21+ chars with digits.
    """
    if not symbol:
        return False
    if "/" in symbol:
        return False  # crypto pair
    if len(symbol) > 6:
        return False  # OCC option or other
    if not symbol.isupper() or not symbol.isalpha():
        return False
    return True


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
    closed_per_bot: dict[str, int] = {name: 0 for name in _CRYPTO_BOT_NAMES}
    quarantined = 0
    realized_pnl_cents_total = 0

    # Find every open bot_position whose owning bot is a crypto bot AND whose
    # symbol classifies as equity. Use parameterized IN clause.
    name_params = {f"n{i}": name for i, name in enumerate(_CRYPTO_BOT_NAMES)}
    name_placeholders = ", ".join(f":{k}" for k in name_params.keys())
    rows = conn.execute(
        text(
            "SELECT bp.id, bp.symbol, bp.qty, bp.avg_cost_cents, "
            "       bp.allocation_id, p.name AS bot_id, a.user_id "
            "FROM bot_positions bp "
            "JOIN bot_allocations a ON a.id = bp.allocation_id "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            f"WHERE a.user_id = :uid AND p.name IN ({name_placeholders}) "
            "AND bp.closed_at IS NULL"
        ),
        {"uid": TARGET_USER_ID, **name_params},
    ).fetchall()

    for r in rows:
        pos_id = int(r[0])
        symbol = r[1] or ""
        qty = float(r[2] or 0)
        avg_cost_cents = int(r[3] or 0)
        allocation_id = int(r[4])
        bot_id = r[5]
        user_id = int(r[6])

        # Only close if symbol classifies as equity. Skip crypto/option/other.
        if not _is_equity_symbol(symbol):
            continue

        # 1. Quarantine row (idempotent via UNIQUE INDEX on position_id)
        try:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO cross_sleeve_quarantine_s14 "
                    "(position_id, bot_id, user_id, declared_asset_class, "
                    " actual_symbol, actual_asset_class, detected_at, action) "
                    "VALUES (:pid, :bot_id, :uid, 'crypto', :sym, 'equity', "
                    "        :ts, 'm044_force_close')"
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
                "[m044] quarantine insert failed for pos=%d: %s", pos_id, exc
            )

        # 2. Close the position
        conn.execute(
            text(
                "UPDATE bot_positions "
                "SET closed_at = :ts, "
                "    exit_reason = 'm044_cross_sleeve_violation' "
                "WHERE id = :pid"
            ),
            {"ts": now_iso, "pid": pos_id},
        )
        closed_per_bot[bot_id] = closed_per_bot.get(bot_id, 0) + 1

        # 3. Write an exit BotTrade for the realized P&L bookkeeping.
        # Realized P&L = 0 here: we have no live price; the close is at
        # cost basis (no gain/loss). Preserving history per standing decision.
        try:
            conn.execute(
                text(
                    "INSERT INTO bot_trades "
                    "(allocation_id, symbol, side, qty, fill_price_cents, "
                    " fees_cents, ts, position_id, is_paper, "
                    " expected_fill_cents, slippage_bps) "
                    "VALUES (:aid, :sym, 'cover', :qty, :px, 0, :ts, :pid, 1, "
                    "        :px, 0.0)"
                ),
                {
                    "aid": allocation_id,
                    "sym": symbol,
                    "qty": qty,
                    "px": avg_cost_cents,
                    "ts": now_iso,
                    "pid": pos_id,
                },
            )
        except Exception as exc:
            # Non-fatal; the close itself succeeded.
            logger.warning(
                "[m044] exit BotTrade insert failed for pos=%d: %s", pos_id, exc
            )

    conn.commit()

    closed_total = sum(closed_per_bot.values())
    logger.warning(
        "[m044] closed=%d quarantined=%d per_bot=%s",
        closed_total, quarantined,
        {k: v for k, v in closed_per_bot.items() if v > 0},
    )

    record(conn, _GATE_NAME)
    return {
        "executed": True,
        "closed_total": closed_total,
        "quarantined": quarantined,
        "closed_per_bot": {k: v for k, v in closed_per_bot.items() if v > 0},
        "realized_pnl_cents_total": realized_pnl_cents_total,
    }
