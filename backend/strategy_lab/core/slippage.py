"""Slippage haircut model for paper-trading fills.

Paper trading fills happen at the quoted price. Real broker fills carry slippage
(your buy fills above the ask, your sell fills below the bid). Without simulating
slippage, paper P&L is unrealistic and the live transition will surprise.

This module applies a configurable per-side haircut (bps) so the paper book
carries realistic friction. Symmetric on entry and exit, so a round-trip on a
flat trade nets to -2 * haircut_bps of notional cost (not zero).

Configure via env: SLIPPAGE_HAIRCUT_BPS (default 8 bps per side, i.e. 16 bps round trip).

Python 3.9 compatible.
"""
from typing import Optional  # noqa: F401  (kept for type-hint extensibility)
import os


def haircut_bps() -> float:
    """Return the configured per-side haircut in basis points (default 8)."""
    try:
        return float(os.environ.get("SLIPPAGE_HAIRCUT_BPS", "8"))
    except Exception:
        return 8.0


def apply_entry_haircut(quote_price_cents: int, side: str) -> int:
    """Worsen the entry fill price by haircut_bps.

    side='buy'  -> fill HIGHER than quote (you pay more)
    side='sell' -> fill LOWER than quote (you receive less)

    Returns adjusted fill price in cents (rounded to nearest int cent).
    Unknown sides pass through unchanged.
    """
    bps = haircut_bps()
    factor = bps / 10_000
    if side == "buy":
        return int(round(quote_price_cents * (1 + factor)))
    elif side == "sell":
        return int(round(quote_price_cents * (1 - factor)))
    return quote_price_cents


def apply_exit_haircut(quote_price_cents: int, side: str) -> int:
    """Worsen the exit fill price by haircut_bps. Same convention as entry.

    For an exit, side is the action being taken to close (e.g. 'sell' to close a
    long, 'buy' to close a short / 'cover'). Callers should map 'cover' -> 'buy'
    before calling.
    """
    return apply_entry_haircut(quote_price_cents, side)
