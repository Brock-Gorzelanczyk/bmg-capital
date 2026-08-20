#!/usr/bin/env python3
"""factor_consolidation — retire redundant/decayed PR bots per Brock 2026-08-20 research.

Brock's PM research (queued behind DoD #1):
BMG has 13 factor bots but only ~5 independent bets. Four are provably
redundant or documented-decayed. Consolidating cuts turnover (bigger cost
saving at $93K than any signal-add would return per DeMiguel 2020).

RETIRE (disable, keep row for history):
  low_volatility       — Novy-Marx & Medhat NBER 2025: profitability subsumes
                         defensive/low-vol. Same exposure as quality_gross_
                         profitability, held twice.
  momentum_umd         — Ehsani-Linnainmaa JF 2022: factor momentum subsumes
                         individual stock momentum. residual_momentum
                         (Blitz-Huij-Martens) does it with ~2× Sharpe.
  short_term_momentum  — same family. residual_momentum captures the signal
                         without paying separate turnover.
  accruals             — Green-Hand-Soliman: decayed to non-positive in US.
                         Hou-Xue-Zhang replication fails since ~2010.

KEEP (5 sleeves per research spec):
  value_hml
  quality_gross_profitability  (absorbs low_volatility)
  residual_momentum            (absorbs momentum_umd + short_term_momentum)
  net_stock_issuance           (replaces accruals)
  insider_cluster_buys         (event sleeve)

UNTOUCHED (out of PM's explicit spec — leave alone):
  os_ratio, overnight_momentum, cw_vol_spread   (options-flow signals,
                                                  distinct asset)
  crypto_xs_momentum, tsm_12m, bab, idio_volatility,
  smart_money_13f, pead                          (either different asset
                                                  class or not on retire list)

USAGE (execution gated — will NOT run automatically):
  # Dry-run: show what would happen (safe)
  python3 scripts/factor_consolidation.py

  # Execute (writes DB; requires §V0 fresh backup)
  BMG_ENABLE_FACTOR_CONSOLIDATION=1 python3 scripts/factor_consolidation.py --live

  # Or via admin endpoint (see /admin/factor-consolidation, ships separately)

DO NOT RUN until DoD #1 is met (fund trades 5 consecutive days).
This is a strategic reallocation, not stability work.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Make backend importable when run from repo root
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("factor_consolidation")


_RETIRE_BOTS = [
    ("low_volatility",       "Novy-Marx & Medhat 2025: profitability subsumes defensive"),
    ("momentum_umd",         "Ehsani-Linnainmaa 2022: factor momentum subsumes stock momentum"),
    ("short_term_momentum",  "Same momentum family — residual_momentum captures the signal"),
    ("accruals",             "Green-Hand-Soliman: decayed to non-positive in US"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="Actually disable. Default dry-run.")
    args = parser.parse_args()

    # Extra safety gate
    if args.live and os.getenv("BMG_ENABLE_FACTOR_CONSOLIDATION") != "1":
        logger.error(
            "REFUSED --live without BMG_ENABLE_FACTOR_CONSOLIDATION=1 env var. "
            "This is queued behind DoD #1 (fund trades 5 consecutive days). "
            "If DoD #1 is met AND §V0 backup is fresh, set the env var + re-run."
        )
        return 2

    from app.db.session import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        actions = []
        for name, reason in _RETIRE_BOTS:
            row = db.execute(text(
                "SELECT id, enabled, starting_capital_cents FROM portfolio_rank_bots "
                "WHERE name = :n"
            ), {"n": name}).fetchone()
            if not row:
                actions.append({"bot": name, "action": "not_found"})
                continue
            bot_id, enabled, cents = row
            if not enabled:
                actions.append({"bot": name, "action": "already_disabled",
                                "capital_cents": cents})
                continue

            actions.append({
                "bot": name,
                "action": "would_disable" if not args.live else "disabling",
                "capital_cents": cents,
                "reason": reason,
            })

            if args.live:
                db.execute(text(
                    "UPDATE portfolio_rank_bots SET enabled = 0, "
                    "  description = COALESCE(description,'') || :append "
                    "WHERE id = :i"
                ), {
                    "i": bot_id,
                    "append": f" [RETIRED 2026-08-20: {reason}]",
                })

        if args.live:
            db.commit()
            logger.info("COMMITTED %d retire action(s)", len([a for a in actions if a['action'] == 'disabling']))
        else:
            logger.info("DRY-RUN (add --live to execute)")

        for a in actions:
            print(f"  {a['bot']:32}  {a['action']:20}  {a.get('reason','')}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
