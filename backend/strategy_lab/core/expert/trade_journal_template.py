"""R8 — Deterministic trade journal template for strategy_lab (replaces Haiku LLM call).

No LLM required. Accepts simple flat arguments for easy use in tests and production.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def render_lab_entry_journal(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    strategy: str,
    reason: str,
) -> str:
    """Return a human-readable string journal entry for a trade open (no LLM)."""
    direction = side.upper()
    value = qty * price
    return (
        f"{direction} {qty} {symbol} @ ${price:.2f} (${value:,.2f} notional). "
        f"Strategy: {strategy}. Reason: {reason}. "
        f"Logged at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}."
    )


def render_lab_exit_journal(
    symbol: str,
    side: str,
    qty: float,
    entry_price: float,
    exit_price: float,
    pnl: float,
    reason: str,
) -> str:
    """Return a human-readable string journal entry for a trade close (no LLM)."""
    direction = side.upper()
    pnl_sign = "+" if pnl >= 0 else ""
    return (
        f"{direction} {qty} {symbol} — entry ${entry_price:.2f} → exit ${exit_price:.2f}. "
        f"P&L: {pnl_sign}${pnl:.2f}. Exit reason: {reason}. "
        f"Logged at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}."
    )
