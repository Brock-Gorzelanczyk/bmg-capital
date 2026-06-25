"""
Vol-targeting capital allocator — DRY-RUN ONLY (V1).

Reads:
  - bot_allocations + bot_profiles for the universe
  - bot_daily_pnl for realized_vol_60d per bot
  - nav_history for fleet NAV (denominator)

Outputs a propose_rebalance JSON the operator reviews in the ops channel.
This module DOES NOT execute. Execute path lives in a separate gated
endpoint (COMMIT 18) that requires Brock's manual confirmation token.

V1 guardrails (per Brock's greenlight on 2026-06-24):
  - EXCLUSIONS:
      * options_directional / options_income → NAV contaminated by
        6/19-6/24 equity-fallback fills, re-enable after 30 clean
        trading days
      * any allocation with paused_reason LIKE '%incubat%' or '%retire%'
      * any orphan allocation (enabled=0, no clear paused_reason)
  - Target portfolio vol: 12% annualized (informational — V1 doesn't
    solve for it; uses risk-parity within sleeves at fixed sleeve
    weights, deployment-capped)
  - Per-sleeve floor 10%, cap 40%
  - Risk-parity within sleeves (weight ∝ 1/vol)
  - Per-name fleet cap 3% NAV (enforced separately at execution time
    by services.concentration — referenced in output not pre-computed)
  - Hard leverage cap 1.25x bot / 1.0x fleet
  - V1 deployment cap: 35% (NOT 85% single-shot)
  - Constraint violations are flagged, never silently relaxed.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# ── V1 constants (greenlit by Brock) ─────────────────────────────────────────
TARGET_VOL_ANN = 0.12                    # 12% target portfolio vol
PER_NAME_CAP = 0.03                      # 3% of NAV per ticker
PER_SLEEVE_FLOOR = 0.10                  # 10% min per sleeve
PER_SLEEVE_CAP = 0.40                    # 40% max per sleeve
BOT_LEVERAGE_CAP = 1.25                  # bot can't carry > 1.25x its weight
FLEET_LEVERAGE_CAP = 1.00                # fleet stays unleveraged
V1_DEPLOYMENT_CAP = 0.35                 # 35% of NAV deployed in V1
VOL_LOOKBACK_DAYS = 60                   # for realized_vol_60d

# Bots excluded from V1 (NAV contamination from B CRITICAL gate aftermath)
CONTAMINATED_PROFILES = {
    "options_directional",
    "options_income",
    "crypto_meanrev_2163",                # retired
}

# Sane realized-vol bands per asset class (for output annotation)
VOL_BANDS = {
    "stock":   (0.10, 0.30),
    "crypto":  (0.40, 0.90),
    "quant":   (0.20, 0.60),
    "options": (0.30, 0.80),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fleet_nav_cents(db: Session) -> Optional[int]:
    try:
        row = db.execute(sql_text(
            "SELECT nav_cents FROM nav_history ORDER BY date DESC LIMIT 1"
        )).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _realized_vol_60d(db: Session, allocation_id: int) -> tuple[Optional[float], int, str]:
    """Annualized realized vol from bot_daily_pnl returns over last 60 days.

    Returns (vol, sample_size, note). vol=None if insufficient data.
    note describes data status: "ok" / "thin" (<10 samples) / "empty".
    """
    try:
        cutoff = (date.today() - timedelta(days=VOL_LOOKBACK_DAYS)).isoformat()
        rows = db.execute(sql_text("""
            SELECT realized_cents, starting_capital_cents
              FROM bot_daily_pnl bdp
              JOIN bot_allocations a ON a.id = bdp.allocation_id
             WHERE bdp.allocation_id = :aid
               AND bdp.date >= :cutoff
             ORDER BY bdp.date ASC
        """), {"aid": allocation_id, "cutoff": cutoff}).fetchall()
    except Exception as exc:
        logger.warning("[allocator] vol lookup failed for alloc %d: %s", allocation_id, exc)
        return None, 0, "error"

    if not rows:
        return None, 0, "empty"

    # Daily return = realized_cents / starting_capital_cents
    returns = []
    for realized, start_cap in rows:
        if start_cap and start_cap > 0:
            returns.append(float(realized or 0) / float(start_cap))
    n = len(returns)
    if n < 2:
        return None, n, "empty" if n == 0 else "thin"
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    daily_vol = math.sqrt(variance)
    annualized = daily_vol * math.sqrt(252)
    note = "ok" if n >= 10 else "thin"
    return annualized, n, note


def _band_annotation(asset_class: str, vol: Optional[float]) -> str:
    if vol is None:
        return "no data"
    lo, hi = VOL_BANDS.get(asset_class, (0.05, 1.5))
    if vol < lo:
        return f"below {asset_class} band ({lo:.0%}-{hi:.0%}) — possibly stale"
    if vol > hi:
        return f"above {asset_class} band ({lo:.0%}-{hi:.0%}) — verify"
    return f"in normal {asset_class} band ({lo:.0%}-{hi:.0%})"


def _sleeve_of(asset_class: str, profile_name: str) -> str:
    """Map asset_class + profile_name → sleeve identifier."""
    if asset_class == "options":
        return "options"
    if asset_class == "quant" or profile_name.startswith("crypto_quant_"):
        return "quant"
    if asset_class == "crypto":
        return "crypto"
    return "stocks"


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def propose_rebalance(db: Session, user_id: int) -> dict[str, Any]:
    """V1 dry-run. Returns the propose_rebalance JSON. Does not write."""
    fleet_nav = _fleet_nav_cents(db)
    if fleet_nav is None or fleet_nav <= 0:
        return {
            "executed": False,
            "error": "fleet_nav_unavailable",
            "warning_banner": "Cannot propose rebalance — nav_history is empty.",
        }
    fleet_nav_usd = fleet_nav / 100.0

    # Pull every allocation for the user with its profile
    rows = db.execute(sql_text("""
        SELECT a.id, a.profile_id, a.enabled, a.starting_capital_cents,
               a.capital_cents_within_portfolio, a.paused_reason, a.tier,
               p.name AS profile_name, p.asset_class
          FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = :uid
         ORDER BY a.id
    """), {"uid": user_id}).fetchall()

    survivors: list[dict] = []   # {alloc_id, name, asset_class, sleeve, vol, vol_note, sample_size}
    excluded: list[dict] = []
    constraint_violations: list[str] = []

    for r in rows:
        aid, pid, enabled, start, within, paused, tier, name, asset_class = r
        sleeve = _sleeve_of(asset_class or "stock", name)

        # Exclusions
        exclusion_reason: Optional[str] = None
        if name in CONTAMINATED_PROFILES:
            exclusion_reason = (
                "NAV history contaminated by 6/19-6/24 equity-fallback fills, "
                "re-enable after 30 clean trading days"
            ) if name in ("options_directional", "options_income") else "retired"
        elif paused and any(k in (paused or "").lower() for k in ("incubat", "pending_data", "incubating")):
            exclusion_reason = f"paused: {paused}"
        elif paused and "retire" in (paused or "").lower():
            exclusion_reason = "retired"
        elif not enabled and not paused:
            exclusion_reason = "orphan_review_required"

        if exclusion_reason:
            excluded.append({
                "allocation_id": aid,
                "profile": name,
                "asset_class": asset_class,
                "sleeve": sleeve,
                "reason": exclusion_reason,
                "proposed_allocation_cents": 0,
            })
            continue

        vol, sample_n, vol_note = _realized_vol_60d(db, aid)
        survivors.append({
            "allocation_id": aid,
            "profile": name,
            "asset_class": asset_class,
            "sleeve": sleeve,
            "current_starting_cents": int(start or 0),
            "current_within_portfolio_cents": int(within or 0),
            "realized_vol_60d": vol,
            "vol_sample_size": sample_n,
            "vol_status": vol_note,
            "band_annotation": _band_annotation(asset_class or "stock", vol),
        })

    # ── Group by sleeve + apply risk-parity weights within each ──────────
    sleeves: dict[str, list[dict]] = {}
    for s in survivors:
        sleeves.setdefault(s["sleeve"], []).append(s)

    # V1 sleeve weights: equal across active sleeves, bounded by floor/cap.
    # Risk-parity within sleeve (weight ∝ 1/vol when vol available).
    active_sleeves = list(sleeves.keys())
    n_sleeves = len(active_sleeves)
    if n_sleeves == 0:
        return {
            "executed": False,
            "warning_banner": (
                "DATA INTEGRITY NOTE: every allocation excluded by V1 guardrails. "
                "Nothing to allocate."
            ),
            "fleet_nav_cents": fleet_nav,
            "excluded_bots": excluded,
            "survivor_bots": [],
            "propose_rebalance": {},
            "constraint_violations": constraint_violations,
        }

    raw_sleeve_w = 1.0 / n_sleeves
    sleeve_w_clamped: dict[str, float] = {}
    for sleeve_name in active_sleeves:
        w = max(PER_SLEEVE_FLOOR, min(PER_SLEEVE_CAP, raw_sleeve_w))
        sleeve_w_clamped[sleeve_name] = w
    # Renormalize to sum to V1_DEPLOYMENT_CAP
    total_w = sum(sleeve_w_clamped.values())
    scale = V1_DEPLOYMENT_CAP / total_w if total_w > 0 else 0
    sleeve_w_final = {s: w * scale for s, w in sleeve_w_clamped.items()}

    # Within sleeve: risk-parity if all vols available; else equal-weight.
    propose_per_alloc: dict[int, dict] = {}
    for sleeve_name, members in sleeves.items():
        sleeve_target_pct = sleeve_w_final[sleeve_name]
        sleeve_target_cents = int(round(fleet_nav * sleeve_target_pct))
        # Compute inverse-vol weights; fall back to equal weight if any vol missing
        vols = [m.get("realized_vol_60d") for m in members]
        usable = [v for v in vols if v is not None and v > 0.001]
        if len(usable) == len(members):
            inv = [1.0 / v for v in vols]  # type: ignore[arg-type]
            sw = sum(inv)
            weights = [i / sw for i in inv]
        else:
            weights = [1.0 / len(members)] * len(members)
            constraint_violations.append(
                f"sleeve {sleeve_name}: vol unavailable for {len(members) - len(usable)} of "
                f"{len(members)} members → fell back to equal-weight"
            )
        # Apply per-bot leverage cap: if any member would carry > 1.25/(n) share, clamp + redistribute.
        max_weight = BOT_LEVERAGE_CAP / len(members)
        weights = [min(w, max_weight) for w in weights]
        wsum = sum(weights)
        if wsum > 0:
            weights = [w / wsum for w in weights]
        for member, w in zip(members, weights):
            proposed_cents = int(round(sleeve_target_cents * w))
            current_cents = member["current_within_portfolio_cents"] or member["current_starting_cents"]
            propose_per_alloc[member["allocation_id"]] = {
                "allocation_id": member["allocation_id"],
                "profile": member["profile"],
                "sleeve": sleeve_name,
                "weight_in_sleeve": round(w, 6),
                "current_capital_cents": current_cents,
                "proposed_capital_cents": proposed_cents,
                "delta_cents": proposed_cents - current_cents,
                "vol_used": member["realized_vol_60d"],
                "vol_status": member["vol_status"],
            }

    # Per-sleeve summary
    per_sleeve_summary = []
    for sleeve_name in active_sleeves:
        members_proposed = [p for p in propose_per_alloc.values() if p["sleeve"] == sleeve_name]
        cur = sum(m["current_capital_cents"] for m in members_proposed)
        prop = sum(m["proposed_capital_cents"] for m in members_proposed)
        per_sleeve_summary.append({
            "sleeve": sleeve_name,
            "current_cents": cur,
            "proposed_cents": prop,
            "current_pct_of_fleet": round(cur / fleet_nav * 100, 3),
            "proposed_pct_of_fleet": round(prop / fleet_nav * 100, 3),
            "target_sleeve_weight": round(sleeve_w_final[sleeve_name], 6),
            "member_count": len(members_proposed),
        })

    total_current = sum(p["current_capital_cents"] for p in propose_per_alloc.values())
    total_proposed = sum(p["proposed_capital_cents"] for p in propose_per_alloc.values())
    current_deployment_pct = round(total_current / fleet_nav * 100, 3)
    proposed_deployment_pct = round(total_proposed / fleet_nav * 100, 3)

    # Aggregate vol (weighted by proposed allocation)
    weighted_vol_num = 0.0
    weighted_vol_den = 0
    for p in propose_per_alloc.values():
        if p["vol_used"] is not None and p["proposed_capital_cents"] > 0:
            weighted_vol_num += p["vol_used"] * p["proposed_capital_cents"]
            weighted_vol_den += p["proposed_capital_cents"]
    estimated_portfolio_vol = (weighted_vol_num / weighted_vol_den) if weighted_vol_den > 0 else None

    if estimated_portfolio_vol is not None and estimated_portfolio_vol > TARGET_VOL_ANN * 1.5:
        constraint_violations.append(
            f"estimated portfolio vol {estimated_portfolio_vol:.1%} > 1.5x target {TARGET_VOL_ANN:.0%}"
        )

    return {
        "executed": False,
        "warning_banner": (
            "DATA INTEGRITY NOTE: Options sleeve excluded due to post-gate cleanup. "
            "V1 deployment cap = 35%, not the long-run 85% target — staged ramp. "
            "Output is informational. Execute requires manual confirmation gate."
        ),
        "as_of": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "fleet_nav_cents": fleet_nav,
        "fleet_nav_usd": round(fleet_nav_usd, 2),
        "v1_guardrails": {
            "target_vol_annualized": TARGET_VOL_ANN,
            "per_name_cap_pct": PER_NAME_CAP * 100,
            "per_sleeve_floor_pct": PER_SLEEVE_FLOOR * 100,
            "per_sleeve_cap_pct": PER_SLEEVE_CAP * 100,
            "bot_leverage_cap": BOT_LEVERAGE_CAP,
            "fleet_leverage_cap": FLEET_LEVERAGE_CAP,
            "v1_deployment_cap_pct": V1_DEPLOYMENT_CAP * 100,
            "vol_lookback_days": VOL_LOOKBACK_DAYS,
        },
        "excluded_bots": excluded,
        "survivor_bots": survivors,
        "per_sleeve_summary": per_sleeve_summary,
        "current_deployment_pct": current_deployment_pct,
        "proposed_deployment_pct": proposed_deployment_pct,
        "estimated_portfolio_vol_annualized": estimated_portfolio_vol,
        "constraint_violations": constraint_violations,
        "propose_rebalance": list(propose_per_alloc.values()),
    }
