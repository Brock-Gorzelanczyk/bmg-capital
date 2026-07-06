"""m070 — Enable the 3 dormant SSRN factor bots (dry-run mode).

Brock's directive: get every strategy trading.

## What this does

Sets `enabled = 1` on the three portfolio_rank_bots seeded by m069:
  - low_volatility
  - value_hml
  - net_stock_issuance

They stay at $0 capital. Dry-run rebalance still exercises the full
pipeline (factor compute → basket build → holdings write → Discord
digest) — just with zero notional. That's fine for OBSERVING factor
behavior. When Brock decides a funding source, a follow-up migration
allocates real capital.

## Cadence reminder

The runner will only rebalance on the schedule matching the cron day:
  - low_volatility: monthly. Next fire = first Monday of next month.
  - value_hml + net_stock_issuance: quarterly. Next fire = first
    Monday of the next quarter start month.

For immediate observation, Brock can trigger a manual rebalance via:

  curl -X POST -H "Authorization: Bearer $TOK" \
    $HOST/api/admin/portfolio-rank/bots/{id}/rebalance

which bypasses the cron and runs the full pipeline right now.

## Fund invariant

No capital moved. $1,000,000 exact before and after.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m070_enable_ssrn_bots_2026_07"

_TARGETS = ("low_volatility", "value_hml", "net_stock_issuance")


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    actions: list[dict] = []
    for name in _TARGETS:
        row = conn.execute(text(
            "SELECT id, enabled FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": name}).fetchone()
        if not row:
            actions.append({"bot": name, "action": "not_found"})
            continue
        if bool(row[1]):
            actions.append({"bot": name, "action": "already_enabled"})
            continue
        conn.execute(text(
            "UPDATE portfolio_rank_bots SET enabled = 1 WHERE id = :bid"
        ), {"bid": int(row[0])})
        actions.append({"bot": name, "action": "enabled", "id": int(row[0])})
        logger.warning("[m070] enabled portfolio_rank_bot %s (id=%d)", name, int(row[0]))

    # Fund invariant unchanged (no capital moved). Assert anyway.
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM portfolio_rank_bots"
    )).fetchone()
    fund_total = int(ba_row[0] or 0) + int(pr_row[0] or 0)
    if fund_total != 100_000_000:
        raise RuntimeError(
            f"m070 invariant broken: fund_total={fund_total} != 100000000"
        )

    record(conn, _MIGRATION_NAME)
    return {"executed": True, "actions": actions, "fund_total_cents": fund_total}
