"""m087 — Seed cw_vol_spread portfolio-rank bot.

Cremers-Weinbaum 2010 JFQA, SSRN 968237. OI-weighted (IV_call - IV_put)
across matched strike/expiry pairs as an informed-flow signal on the
underlying stock. Long top decile weekly.

Universe: use the existing options-liquid universe. yfinance option
chains are the data source. Weekly rebalance keeps the cycle fast.

Funding: $1,000 from the $2,920 m085 pool. Companion to m086/m088.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m087_cw_vol_spread_bot_2026_07_09"

_BOT = {
    "name": "cw_vol_spread",
    "description": (
        "Cremers-Weinbaum 2010 IV spread signal. For each name compute the "
        "OI-weighted mean(IV_call - IV_put) across matched strike/expiry "
        "pairs. Long top decile weekly. Reads informed-flow signal from "
        "options and trades the underlying stock — no options positions "
        "opened, so no options-BP consumption."
    ),
    "factor_definition": {"kind": "cw_vol_spread",
                          "dte_min": 15, "dte_max": 60,
                          "max_pairs": 12},
    "universe": {"kind": "alpaca_universe_by_ticker_list",
                 "list_name": "sp500"},
    "rebalance_schedule": "weekly",
    "long_decile": 10, "short_decile": 0,
    "position_sizing": "equal_weight",
    "starting_capital_cents": 100_000,  # $1,000
    "enabled": 1,
    "paper_citation": "Cremers & Weinbaum 2010 JFQA 45(2):335-367",
    "ssrn_id": "968237",
}


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(text(
        "SELECT id FROM portfolio_rank_bots WHERE name = :n"
    ), {"n": _BOT["name"]}).fetchone()
    if existing:
        record(conn, _MIGRATION_NAME)
        return {"executed": True, "action": "already_exists",
                "bot_id": int(existing[0])}

    conn.execute(text("""
        INSERT INTO portfolio_rank_bots
          (name, description, factor_definition, universe,
           rebalance_schedule, long_decile, short_decile,
           position_sizing, starting_capital_cents, enabled,
           paper_citation, ssrn_id, created_at)
        VALUES
          (:name, :desc, :fdef, :uni, :sched, :ld, :sd, :ps,
           :cap, :en, :cite, :ssrn, :ts)
    """), {
        "name": _BOT["name"], "desc": _BOT["description"],
        "fdef": json.dumps(_BOT["factor_definition"]),
        "uni":  json.dumps(_BOT["universe"]),
        "sched": _BOT["rebalance_schedule"],
        "ld": _BOT["long_decile"], "sd": _BOT["short_decile"],
        "ps": _BOT["position_sizing"],
        "cap": _BOT["starting_capital_cents"],
        "en":  _BOT["enabled"],
        "cite": _BOT["paper_citation"],
        "ssrn": _BOT["ssrn_id"],
        "ts": now_iso,
    })

    if hasattr(conn, "commit"):
        conn.commit()

    verify = conn.execute(text(
        "SELECT id, starting_capital_cents FROM portfolio_rank_bots WHERE name = :n"
    ), {"n": _BOT["name"]}).fetchone()
    if not verify or int(verify[1]) != _BOT["starting_capital_cents"]:
        logger.error("[m087] verify failed — not recording")
        return {"executed": False, "error": "verify_failed"}

    logger.warning(
        "[m087] seeded PR %s bot_id=%d cents=%d enabled=1",
        _BOT["name"], int(verify[0]), _BOT["starting_capital_cents"],
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "action": "seeded",
        "bot_id": int(verify[0]),
        "cents": _BOT["starting_capital_cents"],
    }
