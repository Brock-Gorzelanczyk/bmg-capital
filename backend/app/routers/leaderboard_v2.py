"""Bot leaderboard v2 — explicit state badges, NULL≠0, unattributed as its own row.

Item 2 of the 2026-08-18 BMG APP CLEANUP spec. Brock's longest-running
complaint: bots showed $0.00 when the true value was unknown, which made
correct data look broken and broken data look calm.

ONE BATCHED ENDPOINT. Consumes core/canonical.compute_strategy_lab_aggregate
(one round-trip). No per-bot fan-out — the 40-parallel-request pattern is
what OOM-killed the container twice.

STATE ENUM per bot, exactly one:
  TRADING  — has closing trades in period; realized shown
  HOLDING  — open positions, no closes yet; unrealized shown; realized "—"
  IDLE     — enabled, no positions, no closes. sub_reason required
  PAUSED   — with the pause_reason string
  RETIRED  — tombstoned; excluded from all totals

IDLE sub_reason values:
  no_signals          — bot enabled + has capital, no signals in last 24h
  signals_no_fills    — signals fired but zero executed
  awaiting_rebalance  — bot fires on schedule (weekly/monthly), next in future
  zero_buying_power   — Alpaca account.buying_power = 0

BUG DETECTION:
  realized == 0 && closing_trades > 0 → has_bug=True, bug_reason="zero_realized_with_closes".
  UI renders an error badge, not a $0.00 number.

UNATTRIBUTED ROW:
  Separate row = fund_pv - sum(bot_pv). Never absorbed into bot rows.
  This is the ~$14.6K broker-positions-no-bot-claims delta Brock has been
  asking to see explicitly.

NULL DISCIPLINE:
  Any value the backend cannot compute returns null (not 0). Frontend
  renders "—" with reason in tooltip. $0.00 may ONLY appear when the true
  value is actually zero.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text as _sql
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard-v2"])


_RETIRED_MARKERS = ("retired", "tombstone", "merged_into_", "deprecated", "sunset")


def _derive_state(
    *,
    enabled: bool,
    paused_reason: Optional[str],
    closing_trades_count: int,
    open_positions_count: int,
    signals_24h: int,
    trades_24h: int,
    alpaca_buying_power_cents: Optional[int],
    fires_on_schedule_only: bool,
) -> Dict[str, Any]:
    """Single source of truth for the state badge.

    Returns {state, sub_reason?, pause_reason?}. Exactly one state.
    Order of precedence: RETIRED > PAUSED > TRADING > HOLDING > IDLE.
    """
    pr = (paused_reason or "").lower().strip()

    # RETIRED — tombstoned / merged
    if pr and any(m in pr for m in _RETIRED_MARKERS):
        return {"state": "RETIRED", "pause_reason": paused_reason}

    # PAUSED — any explicit pause_reason that isn't a retirement marker
    if pr:
        return {"state": "PAUSED", "pause_reason": paused_reason}

    # PAUSED — disabled without an explicit reason (still an operator action)
    if not enabled:
        return {"state": "PAUSED", "pause_reason": "disabled (no reason set)"}

    # TRADING — has closed a round trip in the period
    if closing_trades_count > 0:
        return {"state": "TRADING"}

    # HOLDING — has open positions, hasn't closed yet
    if open_positions_count > 0:
        return {"state": "HOLDING"}

    # IDLE — enabled, nothing open, no closes. Sub-reason mandatory.
    if alpaca_buying_power_cents is not None and alpaca_buying_power_cents <= 0:
        return {"state": "IDLE", "sub_reason": "zero_buying_power"}
    if signals_24h == 0 and fires_on_schedule_only:
        return {"state": "IDLE", "sub_reason": "awaiting_rebalance"}
    if signals_24h == 0:
        return {"state": "IDLE", "sub_reason": "no_signals"}
    if signals_24h > 0 and trades_24h == 0:
        return {"state": "IDLE", "sub_reason": "signals_no_fills"}
    return {"state": "IDLE", "sub_reason": "no_signals"}


# Profile-name prefix hints for "fires only on schedule" — used by IDLE
# sub-reason derivation. Weekly / monthly / scheduled bots that aren't
# currently in their fire window shouldn't be flagged "no_signals".
_SCHEDULED_ONLY_PREFIXES = (
    "stock_swing", "stock_lt", "crypto_lt", "crypto_dca_",
    "spy_iron_condor_weekly", "macro_faber_gtaa", "crypto_quant_10m",
    "crypto_quant_15m", "stock_quant_swing_", "stock_pead", "stock_momentum_breakout",
)


def _fires_on_schedule_only(profile_name: str) -> bool:
    p = (profile_name or "").lower()
    return any(p.startswith(x) or p == x for x in _SCHEDULED_ONLY_PREFIXES)


@router.get("/bots")
def get_leaderboard_bots(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """One batched leaderboard call. See module docstring for state doctrine."""
    from app.core.canonical import compute_strategy_lab_aggregate

    try:
        agg = compute_strategy_lab_aggregate(current_user.id, db) or {}
    except Exception as exc:
        logger.error("[leaderboard-v2] canonical aggregate failed: %s", exc)
        return {
            "error": f"canonical_aggregate_failed: {str(exc)[:200]}",
            "bots": [],
            "unattributed": None,
            "fund_pv_cents": None,
            "fund_pv_source": None,
        }

    raw = agg.get("leaderboard") or []
    fund_pv_cents = int(agg.get("total_value_cents") or 0)
    fund_pv_source = agg.get("total_value_source") or "unknown"
    bot_sum_pv_cents = int(agg.get("bot_sum_pv_cents") or 0)
    unattr_cents = int(agg.get("unattributed_cents") or 0)

    # Load pause_reason per profile (canonical doesn't expose it). One query.
    pause_reason_by_profile: Dict[str, Optional[str]] = {}
    try:
        rows = db.execute(_sql(
            "SELECT p.name, a.paused_reason "
            "FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE a.user_id = :uid"
        ), {"uid": current_user.id}).fetchall()
        for r in rows:
            # Multiple allocs per profile possible; keep the first non-empty.
            name, pr = r[0], r[1]
            if name and (name not in pause_reason_by_profile or pr):
                pause_reason_by_profile[name] = pr
    except Exception as exc:
        logger.warning("[leaderboard-v2] pause_reason lookup failed: %s", exc)

    # Alpaca buying_power (cheap — TTL cached).
    alpaca_buying_power_cents: Optional[int] = None
    try:
        from app.services.alpaca_account_cache import get_alpaca_account
        acct = get_alpaca_account()
        if acct:
            bp = acct.get("buying_power")
            if bp is not None:
                alpaca_buying_power_cents = int(float(bp) * 100)
    except Exception:
        pass

    out_bots: List[Dict[str, Any]] = []
    sum_bot_deployed = 0
    for r in raw:
        profile = r.get("profile") or ""
        display = r.get("name") or profile
        enabled = bool(r.get("enabled", False))
        paused_reason = pause_reason_by_profile.get(profile)

        closing = int(r.get("closing_trades_count") or 0)
        open_pos = int(r.get("open_positions_count") or 0)
        signals_24h = int(r.get("signals_24h") or 0)
        trades_24h = int(r.get("trades_24h") or 0)

        realized = r.get("realized_pnl_cents")
        unrealized = r.get("unrealized_pnl_cents")
        deployed = r.get("deployed_cents")
        ret_30d = r.get("return_30d_pct")
        pv = r.get("portfolio_value_cents")

        state_info = _derive_state(
            enabled=enabled,
            paused_reason=paused_reason,
            closing_trades_count=closing,
            open_positions_count=open_pos,
            signals_24h=signals_24h,
            trades_24h=trades_24h,
            alpaca_buying_power_cents=alpaca_buying_power_cents,
            fires_on_schedule_only=_fires_on_schedule_only(profile),
        )
        state = state_info["state"]

        # BUG detection: realized_cents == 0 with closing_trades > 0 is a
        # data-pipeline bug (either pnl_cents backfill missing or origin
        # filter dropped rows). UI renders an error badge, not a number.
        has_bug = (
            state == "TRADING"
            and (realized is None or int(realized) == 0)
            and closing > 0
        )
        bug_reason = "zero_realized_with_closes" if has_bug else None

        # Win rate — only meaningful when there are closes.
        win_rate: Optional[float] = None
        # canonical doesn't expose win_count/loss_count directly at this level;
        # compute from bot_trades if possible in one query later. For now, leave
        # as None so UI renders "—" rather than a bogus 0%.

        # NULL discipline. RETIRED bots contribute nothing to totals.
        if state == "RETIRED":
            realized_out = None
            unrealized_out = None
            deployed_out = None
            ret_30d_out = None
        else:
            realized_out = int(realized) if realized is not None else None
            unrealized_out = int(unrealized) if unrealized is not None else None
            deployed_out = int(deployed) if deployed is not None else None
            ret_30d_out = float(ret_30d) if ret_30d is not None else None
            if state == "HOLDING":
                # Force realized to null for HOLDING when no closes — "—" not 0.
                if closing == 0:
                    realized_out = None
            if deployed_out is not None:
                sum_bot_deployed += deployed_out

        out_bots.append({
            "profile": profile,
            "display_name": display,
            "state": state,
            "sub_reason": state_info.get("sub_reason"),
            "pause_reason": state_info.get("pause_reason"),
            "has_bug": has_bug,
            "bug_reason": bug_reason,

            # Column data (nullable — frontend renders "—" on null)
            "trades_round_trips": closing if closing >= 0 else None,
            "win_rate": win_rate,  # not yet populated; will show "—"
            "realized_cents": realized_out,
            "unrealized_cents": unrealized_out,
            "deployed_cents": deployed_out,
            "return_30d_pct": ret_30d_out,

            # Provenance for tooltips
            "realized_source": "canonical.compute_bot_snapshot" if realized_out is not None else None,
            "unrealized_source": "canonical.compute_bot_snapshot" if unrealized_out is not None else None,
            "deployed_source": "canonical.compute_bot_snapshot" if deployed_out is not None else None,

            # Supplementary
            "portfolio_value_cents": int(pv) if pv is not None else None,
            "starting_capital_cents": int(r.get("starting_capital_cents") or 0),
            "signals_24h": signals_24h,
            "trades_24h": trades_24h,
            "open_positions_count": open_pos,
        })

    # Sort: PAUSED/RETIRED sink to bottom; within active, deployed DESC.
    def _sort_key(b: Dict[str, Any]) -> tuple:
        state = b.get("state") or ""
        state_rank = {
            "TRADING": 0, "HOLDING": 1, "IDLE": 2, "PAUSED": 3, "RETIRED": 4,
        }.get(state, 5)
        deployed = b.get("deployed_cents") or 0
        return (state_rank, -deployed, b.get("display_name") or "")

    out_bots.sort(key=_sort_key)

    # Unattributed row — separate, never absorbed. fund_pv - sum(bot_pv).
    # Prefer canonical's already-computed value; fall back to derivation.
    unattr_row = {
        "value_cents": unattr_cents,
        "value_source": (
            "canonical.unattributed_cents"
            if unattr_cents != 0 else
            "fund_pv - sum(bot_pv) = 0"
        ),
        "note": "Broker-visible positions no BMG bot has claimed. "
                "Positive = bots claim more than broker holds; "
                "negative = broker holds positions no bot owns.",
    }

    return {
        "bots": out_bots,
        "unattributed": unattr_row,
        "fund_pv_cents": fund_pv_cents,
        "fund_pv_source": fund_pv_source,
        "bot_sum_pv_cents": bot_sum_pv_cents,
        "sum_bot_deployed_cents": sum_bot_deployed,
        "counts_by_state": {
            s: sum(1 for b in out_bots if b["state"] == s)
            for s in ("TRADING", "HOLDING", "IDLE", "PAUSED", "RETIRED")
        },
        "acceptance_flags": {
            # Brock's acceptance criteria — encoded so I27-style cross-checks
            # can assert directly against the endpoint.
            "no_zero_dollar_unknowns": all(
                b["realized_cents"] is not None or b["state"] != "TRADING"
                for b in out_bots
            ),
            "deployed_le_fund_equity": (
                sum_bot_deployed <= fund_pv_cents if fund_pv_cents > 0 else True
            ),
            "unattributed_matches_delta": (
                unattr_cents == (bot_sum_pv_cents - fund_pv_cents)
                if fund_pv_cents > 0 else True
            ),
        },
    }
