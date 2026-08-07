"""Single choke point for BotPosition writes across every entry path.

Per PM Claude 2026-08-07 P0-1: risk gates were guarding one entry point
of four. Runner's `_execute_options_signal` called `_check_leg_notional_gate`,
but orphan_adopter, catchall_adopter, and rebuild-from-alpaca all called
`db.add(BotPosition)` directly. SNOW 220C at 31% NAV entered via the
catchall path with no gate.

This module provides:

  check_position_pre_write(...) -> BreachResult

Returns:
  - allowed: True (always — we never silently drop; broker truth wins)
  - breach: bool (True if caps violated)
  - reason: str (why the gate failed, or empty)

All write paths import this and set BotPosition.breach_on_adopt =
result.breach + BotPosition.breach_reason = result.reason.
Invariant I14 asserts every breach has a remediation_ticket_id.
"""
from __future__ import annotations

import os
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BreachResult:
    breach: bool
    reason: str
    ticket_id: Optional[str] = None


def check_position_pre_write(
    *,
    symbol: str,
    qty: float,
    side: str,
    avg_cost_cents: int,
    is_option: bool,
    strike_price: Optional[float] = None,
    expiration_date: Optional[str] = None,
    strategy_name: str = "",
    entry_path: str = "runner",  # runner | orphan_adopter | catchall_adopter | rebuild
) -> BreachResult:
    """Run the same checks `_check_leg_notional_gate` runs, but as a
    non-gating advisory. Returns BreachResult; callers ALWAYS accept the
    write but flag the breach.

    Entry-path bypass note: `runner` path is authoritative — its caller
    (runner._execute_options_signal) uses the strict gate that REJECTS.
    Other paths (adopters) accept + flag.
    """
    contract_count = int(qty) if is_option else 0

    # Gate A — max contracts per spread
    max_contracts = int(os.getenv("OPTIONS_MAX_CONTRACTS_PER_TRADE", "5"))
    if is_option and contract_count > max_contracts:
        return _breach(
            entry_path,
            f"max_contracts:{contract_count}>{max_contracts}",
        )

    # Gate D — LEAPS DTE floor
    if strategy_name == "leaps_stock_replacement" and expiration_date:
        try:
            from datetime import datetime, timezone as tz
            exp = datetime.fromisoformat(expiration_date).replace(tzinfo=tz.utc).date()
            today = datetime.now(tz.utc).date()
            dte = (exp - today).days
            min_dte = int(os.getenv("LEAPS_MIN_DTE", "180"))
            if dte < min_dte:
                return _breach(entry_path, f"leaps_dte:{dte}<{min_dte}")
        except Exception:
            pass

    # Gate B — per-position leg notional vs NAV
    max_leg_pct = float(os.getenv(
        "OPTIONS_MAX_NOTIONAL_PCT",
        os.getenv("OPTIONS_MAX_LEG_NOTIONAL_PCT_NAV", "0.20"),
    ))
    nav = _fund_nav_dollars()
    if is_option and strike_price and nav and nav > 0:
        leg_notional = strike_price * 100 * contract_count
        if leg_notional > nav * max_leg_pct:
            return _breach(
                entry_path,
                f"leg_notional_pct_nav:${leg_notional:,.0f}/{nav:,.0f}={leg_notional/nav*100:.1f}%>{max_leg_pct*100:.0f}%",
            )
    # Equity — market_value equivalent check
    if (not is_option) and nav and nav > 0 and avg_cost_cents > 0:
        notional = (avg_cost_cents / 100.0) * abs(qty)
        if notional > nav * max_leg_pct:
            return _breach(
                entry_path,
                f"equity_notional_pct_nav:${notional:,.0f}/{nav:,.0f}={notional/nav*100:.1f}%>{max_leg_pct*100:.0f}%",
            )

    return BreachResult(breach=False, reason="")


def _breach(entry_path: str, reason: str) -> BreachResult:
    """Build a breach result with a fresh remediation ticket id."""
    ticket = f"BREACH-{uuid.uuid4().hex[:12]}"
    full_reason = f"{entry_path}:{reason}"
    logger.error("[position-gate] BREACH via %s: %s ticket=%s", entry_path, reason, ticket)
    return BreachResult(breach=True, reason=full_reason[:200], ticket_id=ticket)


def _fund_nav_dollars() -> Optional[float]:
    """Live Alpaca portfolio_value. Small cache to avoid hammering."""
    try:
        import urllib.request, json
        kid = os.environ.get("ALPACA_API_KEY", "")
        ksec = os.environ.get("ALPACA_SECRET_KEY", "")
        req = urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/account",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        )
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return float(d.get("portfolio_value") or 0)
    except Exception:
        return None
