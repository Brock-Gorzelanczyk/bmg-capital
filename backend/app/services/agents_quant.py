"""Conclave agent 3 — Quant.

The only non-LLM agent. Reads bot_signals + bot_trades history for the
same (bot, strategy) family and computes historical hit rate. Also
counts sample size so Master knows how much to trust the number.

No LLM call. Pure DB math. Runs in ~20ms.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def evaluate(db: Session, signal_dict: dict) -> dict[str, Any]:
    """Look up the historical fill+PnL rate for this bot+strategy pair.

    Returns:
        {
          "win_rate": float in [0,1] (or None if no data),
          "sample_size": int,
          "verdict": "approve" | "reject",
          "reasoning": short string
        }

    Verdict is approve if: sample_size >= 20 and win_rate >= 0.45
                        OR sample_size < 20 (not enough data, don't block)
    Reject otherwise.
    """
    bot = signal_dict.get("bot") or ""
    strategy = signal_dict.get("strategy") or ""
    if not bot:
        return {"win_rate": None, "sample_size": 0, "verdict": "approve",
                "reasoning": "no bot name; deferring to other agents"}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        # Round-trip PnL: match sell/cover trades against the entry position
        # for the same bot in the last 30 days. Optional strategy filter
        # routes through bot_signals (which owns the strategy column;
        # bot_positions/bot_trades do not).
        rows = db.execute(text("""
            SELECT
              t.fill_price_cents,
              pos.avg_cost_cents,
              pos.qty,
              pos.side
            FROM bot_trades t
            JOIN bot_positions pos ON pos.id = t.position_id
            JOIN bot_allocations a ON a.id = t.allocation_id
            JOIN bot_profiles p ON p.id = a.profile_id
            LEFT JOIN bot_signals s ON s.id = t.signal_id
            WHERE p.name = :bot
              AND (:strategy = '' OR s.strategy = :strategy)
              AND t.side IN ('sell', 'cover', 'close')
              AND t.quarantined_at IS NULL
              AND t.ts >= :cut
        """), {"bot": bot, "strategy": strategy, "cut": cutoff}).fetchall()
    except Exception as exc:
        logger.warning("[conclave.quant] history query failed for %s: %s", bot, exc)
        return {"win_rate": None, "sample_size": 0, "verdict": "approve",
                "reasoning": f"quant history query error: {exc}"}

    wins = 0
    losses = 0
    for r in rows:
        try:
            exit_c = float(r[0] or 0)
            entry_c = float(r[1] or 0)
            qty = float(r[2] or 0)
            side = (r[3] or "long").lower()
            if entry_c <= 0 or qty <= 0:
                continue
            if side in ("short", "sell"):
                pnl = (entry_c - exit_c) * qty
            else:
                pnl = (exit_c - entry_c) * qty
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        except (ValueError, TypeError):
            continue

    n = wins + losses
    if n == 0:
        return {"win_rate": None, "sample_size": 0, "verdict": "approve",
                "reasoning": "no closed round-trips in last 30d"}
    win_rate = round(wins / n, 4)
    if n < 20:
        return {"win_rate": win_rate, "sample_size": n, "verdict": "approve",
                "reasoning": f"n={n}<20; insufficient sample, defer"}
    if win_rate < 0.45:
        return {"win_rate": win_rate, "sample_size": n, "verdict": "reject",
                "reasoning": f"n={n} win_rate={win_rate:.2%} below 45% floor"}
    return {"win_rate": win_rate, "sample_size": n, "verdict": "approve",
            "reasoning": f"n={n} win_rate={win_rate:.2%} clears floor"}
