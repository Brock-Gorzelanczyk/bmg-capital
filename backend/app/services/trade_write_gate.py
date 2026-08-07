"""Single choke point for BotTrade writes across every entry path.

Per PM Claude 2026-08-07 4a directive: sim-leak was 9 fresh rows via
`bot_executor.py`. m078's real-only-mode fix (aa5ebb5f) patched
runner._execute_signal but never touched the other 10 BotTrade write
sites. Same shape as the risk-gate bug — one guarded entry point of many.

This module provides:

  check_trade_write(...) -> TradeWriteResult

Rule (Brock 2026-08-07): a BotTrade write is either:
  - REAL: has a non-empty alpaca_order_id sourced from a broker fill
  - EXPLICIT ADMIN: alpaca_order_id starts with an admin marker
    (adopter, rebuild, reconcile_close, catchall, etc) — traceable,
    intended, not a sim

Anything else (empty alpaca_order_id, random-fill simulator) is
BLOCKED unless the BOT_EXECUTOR_LEGACY_SIM_ENABLED env var is set to
opt in to sim behavior (dev/testing only).

All write paths should:
    from app.services.trade_write_gate import check_trade_write
    gate = check_trade_write(alpaca_order_id=..., source_path="runner")
    if gate.blocked:
        logger.error(...); return

The gate is a compile-time policy contract, not a runtime security
barrier — a determined coder can bypass by not calling it. But the
invariant (I3: 0 sim fills in 24h) reads bot_trades directly, so any
bypass gets caught the next scheduler tick.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Known-good admin markers — writes with these are traceable and intentional.
_ADMIN_MARKER_PREFIXES = (
    "adopter", "orphan_adopter", "catchall_adopter_",
    "rebuild_", "reconcile_close_", "adopt_missing_",
    "autoflatten_", "admin_", "catchall_double_count",
)


@dataclass
class TradeWriteResult:
    blocked: bool
    reason: str


def check_trade_write(
    *,
    alpaca_order_id: Optional[str],
    source_path: str,
) -> TradeWriteResult:
    """Returns TradeWriteResult; callers should check .blocked and
    refuse the write if true. Sim writes are allowed only when
    BOT_EXECUTOR_LEGACY_SIM_ENABLED=true (default false)."""
    if alpaca_order_id and str(alpaca_order_id).strip():
        oid = str(alpaca_order_id).strip()
        # Real Alpaca UUIDs are 36-char with 4 dashes
        if len(oid) == 36 and oid.count("-") == 4:
            return TradeWriteResult(blocked=False, reason="real_alpaca_uuid")
        # Admin markers are traceable
        if any(oid.startswith(p) for p in _ADMIN_MARKER_PREFIXES):
            return TradeWriteResult(blocked=False, reason=f"admin_marker:{source_path}")
        # Anything else with a non-empty string is suspicious but not blocked —
        # log for review.
        logger.warning("[trade-write-gate] unfamiliar alpaca_order_id shape from %s: %r", source_path, oid[:40])
        return TradeWriteResult(blocked=False, reason=f"unknown_shape:{source_path}")
    # Empty alpaca_order_id → sim leak candidate.
    sim_ok = os.getenv("BOT_EXECUTOR_LEGACY_SIM_ENABLED", "false").strip().lower() == "true"
    if sim_ok:
        return TradeWriteResult(blocked=False, reason=f"sim_allowed_by_env:{source_path}")
    logger.error("[trade-write-gate] BLOCK sim write from %s (alpaca_order_id empty; BOT_EXECUTOR_LEGACY_SIM_ENABLED=false)", source_path)
    return TradeWriteResult(blocked=True, reason=f"sim_blocked:{source_path}")
