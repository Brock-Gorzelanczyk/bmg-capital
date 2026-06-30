"""m045 — Close the 20 remaining crypto-bot equity violations that m044 missed.

ROOT CAUSE of m044 silent no-op (Candidate A, highest probability):
  m044 filtered `WHERE a.user_id = :uid` with uid=1.
  The 20 violations are owned by user_id != 1 (likely user_id=3 from legacy
  test seeding). m044's WHERE clause excluded 100% of them; the for-loop ran
  zero times; record(gate) ran cleanly — no error, no rows changed.

HARDENING vs m044:
  1. SELECT does NOT filter by user_id — multi-user safe.
  2. Pre-scan SELECT logged at WARNING with row count + (id, bot, symbol, uid).
  3. Call site uses `engine.begin()` (explicit transaction) instead of
     `engine.connect()` (commit-as-you-go). Migration does NOT call
     conn.commit() itself.
  4. Post-loop VERIFY re-runs the SELECT; raises RuntimeError if any
     crypto-bot equity violations remain open.

Standing decisions honored:
  - NO writes to inception_capital_cents.
  - Never removes rows from bot_trades or bot_daily_pnl (INSERT exit cover trade only).
  - NO writes to bot_allocations.
  - NO auto-pause of crypto bots (strategies are fine; these are legacy positions).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record, verify_count

logger = logging.getLogger(__name__)

_GATE_NAME = "m045_close_remaining_crypto_equity_violations_2026_06"

TARGET_USER_ID = 1  # used ONLY for the "expected_user_id" log banner,
                    # NOT in the SELECT WHERE clause.

TARGET_BOT_NAMES = (
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
    """Equity ticker heuristic: 1-6 uppercase letters, no slash, no digit.

    AAPL, MSFT, NVDA, AMZN, TSLA, GOOGL, META, JPM, GLD, TLT, SPY, QQQ pass.
    Crypto pairs contain '/' (BTC/USD). OCC options are 21+ chars with digits.
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


def _fetch_open_violations(conn, name_params: dict) -> list:
    """Run the core SELECT — NO user_id filter (that was m044's bug)."""
    name_placeholders = ", ".join(f":{k}" for k in name_params.keys())
    return conn.execute(
        text(
            "SELECT bp.id, bp.symbol, bp.qty, bp.avg_cost_cents, "
            "       bp.allocation_id, p.name AS bot_id, a.user_id "
            "  FROM bot_positions bp "
            "  JOIN bot_allocations a ON a.id = bp.allocation_id "
            "  JOIN bot_profiles p   ON p.id = a.profile_id "
            f" WHERE p.name IN ({name_placeholders}) "
            "   AND bp.closed_at IS NULL"
        ),
        name_params,
    ).fetchall()


def run(conn) -> dict:
    """Close all open equity positions held by crypto bots, regardless of user_id.

    Returns one of:
      {"skipped_reason": "already_applied", "executed": False}
      {"skipped_reason": "missing_table_<name>", "executed": False}
      {"skipped_reason": "no_violations_found", "executed": True,
       "closed_total": 0, "quarantined": 0}
      {"executed": True, "closed_total": N, "quarantined": N,
       "closed_per_bot": {...}, "users_touched": [...]}

    Raises RuntimeError if post-run verify finds any remaining open
    crypto-bot equity violations.
    """
    if already_ran(conn, _GATE_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    for table in ("bot_positions", "bot_allocations", "bot_profiles",
                  "cross_sleeve_quarantine_s14", "bot_trades"):
        if not _table_exists(conn, table):
            return {"skipped_reason": f"missing_table_{table}", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    name_params = {f"n{i}": name for i, name in enumerate(TARGET_BOT_NAMES)}

    # Pre-scan: log everything we're about to act on so Railway logs are
    # auditable even if a later exception occurs.
    rows = _fetch_open_violations(conn, name_params)
    logger.warning(
        "[m045] candidate_rows=%d sample=%s users=%s "
        "(expected_user_id=%d; NOT filtering — m044 bug prevention)",
        len(rows),
        [(int(r[0]), r[5], r[1], int(r[6])) for r in rows[:5]],
        sorted({int(r[6]) for r in rows}),
        TARGET_USER_ID,
    )

    equity_rows = [r for r in rows if _is_equity_symbol(r[1] or "")]

    if not equity_rows:
        # No violations to close — record gate so this doesn't re-run on
        # every boot on clean/already-fixed databases.
        record(conn, _GATE_NAME)
        return {
            "skipped_reason": "no_violations_found",
            "executed": True,
            "closed_total": 0,
            "quarantined": 0,
        }

    closed_per_bot: dict[str, int] = {name: 0 for name in TARGET_BOT_NAMES}
    quarantined = 0
    users_touched: set[int] = set()

    for r in equity_rows:
        pos_id = int(r[0])
        symbol = r[1] or ""
        qty = float(r[2] or 0)
        avg_cost_cents = int(r[3] or 0)
        allocation_id = int(r[4])
        bot_id = r[5]
        user_id = int(r[6])

        users_touched.add(user_id)

        # 1. Quarantine row (idempotent via UNIQUE INDEX on position_id)
        try:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO cross_sleeve_quarantine_s14 "
                    "(position_id, bot_id, user_id, declared_asset_class, "
                    " actual_symbol, actual_asset_class, detected_at, action) "
                    "VALUES (:pid, :bot_id, :uid, 'crypto', :sym, 'equity', "
                    "        :ts, 'm045_force_close')"
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
                "[m045] quarantine insert failed for pos=%d user=%d: %s",
                pos_id, user_id, exc,
            )

        # 2. Close the position
        conn.execute(
            text(
                "UPDATE bot_positions "
                "   SET closed_at = :ts, "
                "       exit_reason = 'm045_cross_sleeve_violation' "
                " WHERE id = :pid"
            ),
            {"ts": now_iso, "pid": pos_id},
        )
        closed_per_bot[bot_id] = closed_per_bot.get(bot_id, 0) + 1

        # 3. Write an exit cover BotTrade at cost basis (no live price available).
        # History-preservation rule: INSERT only, never DELETE.
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
            # Non-fatal; the close itself succeeded. Log for Railway grep.
            logger.warning(
                "[m045] exit BotTrade insert failed for pos=%d user=%d: %s",
                pos_id, user_id, exc,
            )

    closed_total = sum(closed_per_bot.values())
    logger.warning(
        "[m045] closed_total=%d quarantined=%d closed_per_bot=%s users_touched=%s",
        closed_total,
        quarantined,
        {k: v for k, v in closed_per_bot.items() if v > 0},
        sorted(users_touched),
    )

    # POST-LOOP VERIFY — the critical safety net m044 lacked.
    # Use verify_count with a SQL-side equity symbol filter so the check is
    # independent of the Python _is_equity_symbol heuristic.
    name_placeholders_verify = ", ".join(f":{k}" for k in name_params.keys())
    verify_count(
        conn,
        name="m045",
        sql=(
            "SELECT bp.id, bp.symbol, p.name AS bot_id, a.user_id "
            "  FROM bot_positions bp "
            "  JOIN bot_allocations a ON a.id = bp.allocation_id "
            "  JOIN bot_profiles p   ON p.id = a.profile_id "
            f" WHERE p.name IN ({name_placeholders_verify}) "
            "   AND bp.closed_at IS NULL "
            "   AND length(bp.symbol) <= 6 "
            "   AND bp.symbol NOT LIKE '%/%' "
            "   AND bp.symbol GLOB '[A-Z]*' "
            "   AND bp.symbol NOT GLOB '*[0-9]*'"
        ),
        params=name_params,
        expected=0,
    )

    record(conn, _GATE_NAME)
    return {
        "executed": True,
        "closed_total": closed_total,
        "quarantined": quarantined,
        "closed_per_bot": {k: v for k, v in closed_per_bot.items() if v > 0},
        "users_touched": sorted(users_touched),
    }
