"""Pre-trade safety guard — checks BEFORE Alpaca order submission.

Brock 2026-08-18 resume-guard: fund resumes with I1 = 17 position drift.
Post-diagnosis, the drift is under-adoption (Alpaca holds positions BMG
doesn't track — e.g., JNJ 92 shares broker-side, 1.71 tracked in BMG).

Under-adoption creates one real risk on resume: a stock bot opens a
position in a symbol already held at Alpaca but untracked by BMG, producing
double exposure. This module blocks that specific case.

Called from broker adapters' submit_order() BEFORE the POST to /orders.
Fails OPEN (allows trade) on internal errors — a bug in the guard must not
halt trading. The guard's job is only to catch the specific untracked-
broker-position case; other risk checks live in the runner (§O1, I7, etc).
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def check_untracked_broker_position(
    *,
    symbol: str,
    side: str,
    user_id: int = 1,
) -> Tuple[bool, str]:
    """Return (allowed, reason).

    Denies iff ALL:
      - side is 'buy' (or 'long' — entries only; closes/sells are allowed
        even if untracked because closing an untracked position is safe)
      - Alpaca has an open position in symbol
      - NO active (open, non-quarantined) BotPosition for that symbol under
        any user_id allocation

    Fails OPEN on any exception — a broken guard cannot halt trading.
    """
    s = (side or "").lower()
    if s not in ("buy", "long"):
        return True, ""  # sells/covers/close paths not gated

    try:
        from app.services.alpaca_account_cache import get_alpaca_positions
        alp = get_alpaca_positions() or []
    except Exception as exc:
        logger.warning("[pre-trade-gate] alpaca fetch failed (fail-open): %s", exc)
        return True, f"gate_alpaca_unavailable:{type(exc).__name__}"

    if not any((p.get("symbol") or "") == symbol for p in alp):
        return True, ""  # Alpaca doesn't hold it — safe

    # Alpaca has it. Does ANY active BMG allocation track it?
    try:
        from sqlalchemy import text as _t
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            row = db.execute(
                _t(
                    "SELECT 1 FROM bot_positions bp "
                    "JOIN bot_allocations a ON a.id = bp.allocation_id "
                    "WHERE bp.closed_at IS NULL "
                    "  AND bp.quarantined_at IS NULL "
                    "  AND bp.symbol = :s "
                    "  AND a.user_id = :u "
                    "LIMIT 1"
                ),
                {"s": symbol, "u": user_id},
            ).first()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("[pre-trade-gate] BMG lookup failed (fail-open): %s", exc)
        return True, f"gate_bmg_unavailable:{type(exc).__name__}"

    if row:
        return True, ""  # BMG tracks it — safe to add / rebalance

    # Alpaca has it, BMG doesn't — REJECT.
    logger.error(
        "[pre-trade-gate] BLOCK entry %s %s — untracked broker position",
        side, symbol,
    )
    return False, "untracked_broker_position_blocks_entry"


class PreTradeGateBlocked(Exception):
    """Raised when submit_order is called for an entry that would create
    double exposure to a broker-only position. Caller should catch and log."""

    def __init__(self, symbol: str, side: str, reason: str):
        self.symbol = symbol
        self.side = side
        self.reason = reason
        super().__init__(f"pre-trade-gate BLOCK {side} {symbol}: {reason}")
