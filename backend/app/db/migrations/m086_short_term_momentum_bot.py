"""m086 — Seed short_term_momentum portfolio-rank bot.

Medhat-Schmeling 2022 RFS, SSRN 3150525. 1-month momentum conditioned
on high turnover. Fills the month t-1 gap the standard 12-1 UMD skips.

Funding: $1,000 from the $2,920 pool m085 freed by halting
crypto_quant_scalp_1m + crypto_quant_meme_tier. Companion migrations
m087 (cw_vol_spread) and m088 (earnings_straddle) consume the rest.

Idempotent via _gate.record().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m086_short_term_momentum_bot_2026_07_09"

_BOT = {
    "name": "short_term_momentum",
    "description": (
        "Medhat-Schmeling 2022 RFS short-term momentum. Rank Russell 1000 "
        "by prior 1-month return, conditional on top-half turnover. Long "
        "top decile monthly rebal. Structurally low correlation to 12-1 "
        "UMD because month t-1 is exactly what UMD skips."
    ),
    "factor_definition": {"kind": "short_term_momentum",
                          "lookback_days": 21,
                          "turnover_cutoff": 0.5},
    "universe": {"kind": "alpaca_universe_by_ticker_list",
                 "list_name": "sp500"},
    "rebalance_schedule": "monthly",
    "long_decile": 10, "short_decile": 0,
    "position_sizing": "equal_weight",
    "starting_capital_cents": 100_000,  # $1,000
    "enabled": 1,
    "paper_citation": "Medhat & Schmeling 2022 RFS 35(3):1480-1526",
    "ssrn_id": "3150525",
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
        logger.error("[m086] verify failed — not recording")
        return {"executed": False, "error": "verify_failed"}

    logger.warning(
        "[m086] seeded PR %s bot_id=%d cents=%d enabled=1",
        _BOT["name"], int(verify[0]), _BOT["starting_capital_cents"],
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "action": "seeded",
        "bot_id": int(verify[0]),
        "cents": _BOT["starting_capital_cents"],
    }
