"""Per-user concentration / correlation gates (Phase 5).

Three stacked checks, in order, fail-fast:

  1. SINGLE-NAME CAP — proposed + open-symbol notional across the user's
     allocations <= 8% of total user starting capital.
  2. SECTOR CAP     — same, by GICS-ish sector from `sector_map.get_sector`
     (capped at 25%). ETFs / unknown sectors skip the check.
  3. CLUSTER GATE   — for the proposed symbol's sector, if there are already
     3+ open positions and proposed + cluster > 15% of user starting capital,
     reject as "sector cluster concentration".

The gate is wired into runner._execute_signal / _execute_options_signal
right after position_dollars is computed, before qty / contract_count is
sized. A (False, reason) tuple causes the caller to:
  - log a warning
  - insert a bot_signals row with side="hold" reason="concentration: <r>"
  - return without writing BotPosition/BotTrade.

Env overrides (all default off):
  SINGLE_NAME_CAP_PCT       (default 8.0)
  SECTOR_CAP_PCT            (default 25.0)
  CLUSTER_MAX_POSITIONS     (default 3)
  CLUSTER_NOTIONAL_PCT      (default 15.0)
"""
from __future__ import annotations

import logging
import os
from typing import Tuple

from sqlalchemy import text as sql_text

from strategy_lab.core.sector_map import get_sector

logger = logging.getLogger(__name__)

# Defaults — overridable via env. Read at call time so test monkeypatching
# of os.environ takes effect without a reload.
_DEFAULT_SINGLE_NAME_CAP_PCT = 8.0
_DEFAULT_SECTOR_CAP_PCT = 25.0
_DEFAULT_CLUSTER_MAX_POSITIONS = 3
_DEFAULT_CLUSTER_NOTIONAL_PCT = 15.0


def _f(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except (ValueError, TypeError):
        return float(default)


def _i(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(raw)
    except (ValueError, TypeError):
        return int(default)


# ── Helpers (also used by scripts/check_concentration.py) ────────────────────

def user_total_capital(db, user_id: int) -> float:
    """Sum of starting_capital_cents across all of the user's allocations,
    returned in dollars. 0.0 if the user has no allocations.
    """
    row = db.execute(sql_text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "  FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": user_id}).fetchone()
    cents = int(row[0]) if row and row[0] is not None else 0
    return cents / 100.0


def _user_allocation_ids(db, user_id: int) -> list:
    rows = db.execute(sql_text(
        "SELECT id FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": user_id}).fetchall()
    return [int(r[0]) for r in rows]


def open_symbol_notional(db, user_id: int, symbol: str) -> float:
    """Sum of qty*avg_cost_cents/100 for OPEN positions in this symbol
    across all allocations owned by user_id. Dollars.
    """
    alloc_ids = _user_allocation_ids(db, user_id)
    if not alloc_ids:
        return 0.0
    # SQLAlchemy can't bind a list directly via :param for IN; expand
    # to a comma-list of named binds to stay sqlite/postgres portable.
    binds = {f"a{i}": v for i, v in enumerate(alloc_ids)}
    in_clause = ",".join(f":a{i}" for i in range(len(alloc_ids)))
    binds["sym"] = symbol
    row = db.execute(sql_text(
        f"SELECT COALESCE(SUM(qty * avg_cost_cents), 0) "
        f"  FROM bot_positions "
        f" WHERE allocation_id IN ({in_clause}) "
        f"   AND symbol = :sym "
        f"   AND closed_at IS NULL"
    ), binds).fetchone()
    cents = float(row[0]) if row and row[0] is not None else 0.0
    return cents / 100.0


def sector_open_positions(db, user_id: int, sector: str) -> list:
    """Return [(symbol, notional_dollars), ...] for all open positions
    in `sector` across the user's allocations.
    """
    alloc_ids = _user_allocation_ids(db, user_id)
    if not alloc_ids or not sector:
        return []
    binds = {f"a{i}": v for i, v in enumerate(alloc_ids)}
    in_clause = ",".join(f":a{i}" for i in range(len(alloc_ids)))
    rows = db.execute(sql_text(
        f"SELECT symbol, qty, avg_cost_cents "
        f"  FROM bot_positions "
        f" WHERE allocation_id IN ({in_clause}) "
        f"   AND closed_at IS NULL"
    ), binds).fetchall()
    out = []
    for r in rows:
        sym = r[0]
        sec = get_sector(sym)
        if sec == sector:
            notional = float(r[1] or 0) * float(r[2] or 0) / 100.0
            out.append((sym, notional))
    return out


# ── Main API ─────────────────────────────────────────────────────────────────

def check_concentration(
    db,
    user_id: int,
    allocation_id: int,
    symbol: str,
    proposed_notional: float,
    profile: dict,
) -> Tuple[bool, str]:
    """Returns (allowed, reason). reason is "" when allowed=True.

    Fail-safe: any internal error or missing-user condition returns
    (True, "") with a warning log, so a busted denominator never wedges
    the whole runner.
    """
    try:
        total_capital = user_total_capital(db, user_id)
    except Exception as exc:
        logger.warning("[concentration] user_total_capital failed for user_id=%s: %s",
                       user_id, exc)
        return True, ""

    if total_capital <= 0:
        logger.warning("[concentration] user_id=%s has zero starting capital — "
                       "allowing trade (safe default)", user_id)
        return True, ""

    proposed = float(proposed_notional or 0.0)
    if proposed <= 0:
        return True, ""

    single_name_cap_pct = _f("SINGLE_NAME_CAP_PCT", _DEFAULT_SINGLE_NAME_CAP_PCT)
    sector_cap_pct = _f("SECTOR_CAP_PCT", _DEFAULT_SECTOR_CAP_PCT)
    cluster_max_positions = _i("CLUSTER_MAX_POSITIONS", _DEFAULT_CLUSTER_MAX_POSITIONS)
    cluster_notional_pct = _f("CLUSTER_NOTIONAL_PCT", _DEFAULT_CLUSTER_NOTIONAL_PCT)

    # 1. SINGLE-NAME CAP
    try:
        existing = open_symbol_notional(db, user_id, symbol)
    except Exception as exc:
        logger.warning("[concentration] open_symbol_notional failed for %s: %s",
                       symbol, exc)
        existing = 0.0
    post_single = existing + proposed
    if (post_single / total_capital) * 100.0 > single_name_cap_pct:
        return False, (
            f"single-name cap: {symbol} would reach "
            f"{post_single/total_capital*100:.2f}% of user capital "
            f"(cap {single_name_cap_pct:.2f}%)"
        )

    # 2. SECTOR CAP — skip for ETFs / unknown sectors
    sector = None
    try:
        sector = get_sector(symbol)
    except Exception as exc:
        logger.warning("[concentration] get_sector raised for %s: %s", symbol, exc)
        sector = None

    # Treat "etf" as the same as None per spec (skip the check for ETFs).
    is_etf_or_unknown = sector is None or str(sector).lower() == "etf"
    if not is_etf_or_unknown:
        try:
            cluster_positions = sector_open_positions(db, user_id, sector)
        except Exception as exc:
            logger.warning("[concentration] sector_open_positions failed for %s: %s",
                           sector, exc)
            cluster_positions = []
        cluster_notional = sum(n for _s, n in cluster_positions)
        post_sector = cluster_notional + proposed
        if (post_sector / total_capital) * 100.0 > sector_cap_pct:
            return False, (
                f"sector cap: {sector} would reach "
                f"{post_sector/total_capital*100:.2f}% of user capital "
                f"(cap {sector_cap_pct:.2f}%)"
            )

        # 3. CLUSTER GATE
        n_positions = len(cluster_positions)
        if n_positions >= cluster_max_positions:
            cluster_post_pct = (cluster_notional + proposed) / total_capital * 100.0
            if cluster_post_pct > cluster_notional_pct:
                return False, (
                    f"sector cluster concentration: {sector} has "
                    f"{n_positions} open positions, cluster would reach "
                    f"{cluster_post_pct:.2f}% (cap {cluster_notional_pct:.2f}%)"
                )

    return True, ""
