"""BMG Reliability Framework — Layer 3: Invariant Engine.

Runs 10 tripwire checks every 15 minutes during market hours + a nightly
deep pass. Each check returns a Result:

    Result(check_id, level, actual, expected, delta, detail)
    level ∈ {"green", "amber", "red"}

Red = auto-action + persistent InvariantAlert row + UI banner.
Amber = advisory, banner-only.
Green = silent.

Ships with the invariants Brock's audit identified as the whole month's
bug list. Each check is intentionally simple + independent so a bug in
one never masks another. Every check is failsafe: on internal exception,
we return AMBER with the exception message, NOT green, so silent
degradation is impossible.

  I1  DB position count == Alpaca (per asset class ±1)
  I2  DB unrealized == Alpaca ±$1
  I3  sim fills last 24h == 0
  I4  every closed trade: nonzero pnl OR reason=expiry_zero,
      exit_reason never null
  I5  option marks midpoint convention + no-arb + <15 min stale
  I6  every position marked within 1 session
  I7  gross exposure <= GROSS_EXPOSURE_MAX,
      per-position notional <= cap,
      options DTE >= strategy floor
  I8  sleeve PV >= 0, sum(sleeves) == fund PV,
      day <= week <= month sanity
  I9  every Alpaca position has exactly one owning bot
  I10 signal funnel reconciles per scan;
      unexplained drops == 0
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Result contract ─────────────────────────────────────────────────────────

@dataclass
class Result:
    check_id: str
    level: str            # "green" | "amber" | "red"
    actual: Any
    expected: Any
    delta: Optional[float]
    detail: str
    ts: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ok(check_id: str, actual: Any, expected: Any = None, detail: str = "") -> Result:
    return Result(check_id, "green", actual, expected, None,
                  detail or "ok", datetime.now(timezone.utc).isoformat())


def _amber(check_id: str, actual: Any, expected: Any, delta: Optional[float],
           detail: str) -> Result:
    return Result(check_id, "amber", actual, expected, delta, detail,
                  datetime.now(timezone.utc).isoformat())


def _red(check_id: str, actual: Any, expected: Any, delta: Optional[float],
         detail: str) -> Result:
    return Result(check_id, "red", actual, expected, delta, detail,
                  datetime.now(timezone.utc).isoformat())


# ── Alpaca helpers (broker truth) ───────────────────────────────────────────

def _creds() -> Optional[tuple[str, str]]:
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    return (key, sec) if key and sec else None


def _alp_positions() -> list[dict]:
    c = _creds()
    if not c: return []
    try:
        req = urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": c[0], "APCA-API-SECRET-KEY": c[1]},
        )
        return json.loads(urllib.request.urlopen(req, timeout=10).read()) or []
    except Exception as exc:
        logger.warning("[invariant] alpaca positions fetch failed: %s", exc)
        return []


def _alp_orders_filled(hours: int = 24) -> list[dict]:
    c = _creds()
    if not c: return []
    try:
        after = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        qs = urllib.parse.urlencode({"status": "closed", "limit": 500, "after": after})
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets/v2/orders?{qs}",
            headers={"APCA-API-KEY-ID": c[0], "APCA-API-SECRET-KEY": c[1]},
        )
        orders = json.loads(urllib.request.urlopen(req, timeout=10).read()) or []
        return [o for o in orders if o.get("status") == "filled"]
    except Exception as exc:
        logger.warning("[invariant] alpaca orders fetch failed: %s", exc)
        return []


# ── The 10 checks ────────────────────────────────────────────────────────────

def _check_i1_position_counts(db) -> Result:
    """DB open position count == Alpaca (per asset class), tolerance ±2."""
    try:
        from app.db.models.bots import BotPosition
        alp = _alp_positions()
        alp_eq = sum(1 for p in alp if p.get("asset_class") == "us_equity")
        alp_opt = sum(1 for p in alp if p.get("asset_class") == "us_option")
        alp_cry = sum(1 for p in alp if p.get("asset_class") == "crypto")

        bmg_open = (
            db.query(BotPosition)
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .all()
        )
        # Classify by option_type (simple heuristic — options have option_type set)
        bmg_opt = sum(1 for p in bmg_open if getattr(p, "option_type", None))
        bmg_non_opt = len(bmg_open) - bmg_opt

        actual = {
            "bmg_option": bmg_opt, "bmg_non_option": bmg_non_opt,
            "alp_option": alp_opt, "alp_equity": alp_eq, "alp_crypto": alp_cry,
            "metric": "bmg_active_row_count_vs_alpaca_position_count",
            "note": "Compares DISTINCT BMG active BotPosition rows to Alpaca "
                    "position count. Duplicate rows for the same symbol inflate "
                    "this number (see /admin/diag/multi-owned). For the "
                    "symbol-keyed drift (DB=134 vs Alpaca=136 style), see "
                    "the diag endpoint's recon numbers; this row-count metric "
                    "is stricter but noisier.",
        }
        expected = {"bmg_option ≈ alp_option": True, "bmg_non_option ≈ alp_equity + alp_crypto": True}

        opt_delta = abs(bmg_opt - alp_opt)
        non_opt_delta = abs(bmg_non_opt - (alp_eq + alp_cry))
        max_delta = max(opt_delta, non_opt_delta)

        if max_delta <= 2:
            return _ok("I1", actual, expected,
                       f"row-count drift {max_delta} (opt:{opt_delta} non-opt:{non_opt_delta}) — in tolerance")
        if max_delta <= 5:
            return _amber("I1", actual, expected, max_delta,
                          f"row-count drift {max_delta} (opt:{opt_delta} non-opt:{non_opt_delta}) "
                          "— check /admin/diag/multi-owned for dupes")
        return _red("I1", actual, expected, max_delta,
                    f"row-count drift {max_delta} (opt:{opt_delta} non-opt:{non_opt_delta}) "
                    "— check /admin/diag/multi-owned for dupes, /admin/positions/quarantine-bmg-only-phantoms for phantoms")
    except Exception as exc:
        return _amber("I1", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i2_unrealized_pl(db) -> Result:
    """RE-SCOPED 2026-08-20 (Brock work order Phase A): fund-level PV check.

    Was: sum of BMG per-position UPL vs sum of Alpaca per-position UPL.
    That's an ATTRIBUTION metric. It halted the fund 3× in 11 days on
    numbers that didn't threaten anything real — every drift event traced
    back to catchall/orphan allocs with fake unrealized on $0 starting.

    Now: BMG canonical fund PV vs live Alpaca portfolio_value. These
    should match by construction (canonical sources Alpaca). Divergence
    means canonical fell back to bot_sum (broker-connectivity outage) or
    a caller injected a stale/wrong PV. That's a real safety event.

    Attribution-level checks preserved as REPORTING (I24 bot-level identity,
    I31 per-bot attribution, I15 rescale drift). None of those halt.

    The old per-position-sum diagnostic is still available via
    /admin/diag/i2-hypothesis for humans investigating attribution.
    """
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        from app.services.alpaca_account_cache import get_alpaca_account
        acct = get_alpaca_account()
        if not acct:
            return _amber("I2", None, None, None,
                          "alpaca_account_fetch_failed — broker connectivity down")
        alpaca_pv_cents = int(round(float(acct.get("portfolio_value") or 0) * 100))
        if alpaca_pv_cents <= 0:
            return _amber("I2", None, None, None,
                          "alpaca returned no portfolio_value")

        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        canonical_pv_cents = int(agg.get("total_value_cents") or 0)
        canonical_source = str(agg.get("total_value_source") or "unknown")

        drift_cents = abs(canonical_pv_cents - alpaca_pv_cents)
        actual = {
            "canonical_pv_usd": round(canonical_pv_cents / 100, 2),
            "alpaca_pv_usd": round(alpaca_pv_cents / 100, 2),
            "canonical_source": canonical_source,
            "drift_usd": round(drift_cents / 100, 2),
            "metric": "canonical_fund_pv_vs_alpaca_portfolio_value",
            "note": "Fund-level PV check. Halts trading only when BMG's "
                    "canonical PV diverges from Alpaca (broker-connectivity "
                    "gap OR consumer using stale/wrong source). Attribution "
                    "drift moved to reporting-tier (I15/I24/I31).",
        }
        # $5 tolerance for cents-vs-dollars rounding
        if drift_cents <= 500:
            return _ok("I2", actual, {"drift_max_cents": 500},
                       f"canonical fund PV matches Alpaca ±${drift_cents/100:.2f}")
        # Anything above $5 = the canonical fund PV disagrees with the
        # broker. That's a REAL safety event — trades would use wrong PV
        # for sizing/risk. Halt.
        return _red("I2", actual, {"drift_max_cents": 500}, float(drift_cents),
                    f"fund PV drift ${drift_cents/100:,.2f} — canonical ${canonical_pv_cents/100:,.2f} "
                    f"(source={canonical_source}) vs Alpaca ${alpaca_pv_cents/100:,.2f}. "
                    "Investigate: is canonical falling back to bot_sum?")
    except Exception as exc:
        return _amber("I2", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i3_sim_fills(db) -> Result:
    """Zero bot_trade rows in last 24h with NULL alpaca_order_id.

    Enhanced 2026-08-09 to expose per-alloc counts so the I3 auto-action
    can pause the offending bots individually."""
    try:
        from app.db.models.bots import BotTrade
        from sqlalchemy import or_, func
        from collections import Counter
        cut = datetime.now(timezone.utc) - timedelta(hours=24)
        sim_rows = (
            db.query(BotTrade.allocation_id)
            .filter(BotTrade.ts >= cut)
            .filter(BotTrade.quarantined_at.is_(None))
            .filter(or_(BotTrade.alpaca_order_id.is_(None), BotTrade.alpaca_order_id == ""))
            .all()
        )
        sim_count = len(sim_rows)
        by_alloc = Counter(r[0] for r in sim_rows if r[0] is not None)
        actual = {"sim_count": sim_count, "by_alloc": dict(by_alloc)}
        if sim_count == 0:
            return _ok("I3", actual, 0, "no sim fills in 24h")
        return _red("I3", actual, 0, float(sim_count),
                    f"{sim_count} bot_trade rows in 24h have no alpaca_order_id "
                    f"(allocs: {dict(by_alloc)})")
    except Exception as exc:
        return _amber("I3", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i4_closed_trade_hygiene(db) -> Result:
    """Every closed BotPosition in last 24h: exit_reason NOT NULL, and either
    a signed pnl exists on the exit trade OR reason=='expiry'."""
    try:
        from app.db.models.bots import BotPosition
        cut = datetime.now(timezone.utc) - timedelta(hours=24)
        closes = (
            db.query(BotPosition)
            .filter(BotPosition.closed_at.isnot(None))
            .filter(BotPosition.closed_at >= cut)
            .filter(BotPosition.quarantined_at.is_(None))
            .all()
        )
        null_reason = [p.id for p in closes if not p.exit_reason]
        if not null_reason:
            return _ok("I4", {"closes_24h": len(closes)}, None, f"all {len(closes)} closes have exit_reason")
        return _red("I4", {"null_exit_reason_ids": null_reason[:10]},
                    None, float(len(null_reason)),
                    f"{len(null_reason)} closes with null exit_reason")
    except Exception as exc:
        return _amber("I4", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i5_option_marks(db) -> Result:
    """Option marks: no negative, no zero-on-both-sides, no-arb violation
    (call strike K1 < K2 → C(K1) >= C(K2)). Best-effort sample check."""
    try:
        from app.services.option_marks import fetch_option_marks_cents, _QUOTE_CACHE
        alp = _alp_positions()
        occs = [p.get("symbol") for p in alp if p.get("asset_class") == "us_option" and p.get("symbol")]
        if not occs:
            return _ok("I5", {"positions": 0}, None, "no option positions to check")
        marks = fetch_option_marks_cents(occs) or {}
        missing = [s for s in occs if marks.get(s) is None]
        stale_secs = 15 * 60
        import time as _t
        now = _t.monotonic()
        stale = [s for s in occs if _QUOTE_CACHE.get(s) and (now - _QUOTE_CACHE[s][1]) > stale_secs]
        n = len(occs)
        m = len(missing)
        s = len(stale)
        if m == 0 and s == 0:
            return _ok("I5", {"positions": n, "missing": 0, "stale": 0}, None, "all marks fresh")
        if m > n * 0.30 or s > n * 0.30:
            return _red("I5", {"positions": n, "missing": m, "stale": s},
                        {"missing_max_pct": 30, "stale_max_pct": 30},
                        float(max(m, s)),
                        f"{m}/{n} missing quotes, {s}/{n} stale")
        return _amber("I5", {"positions": n, "missing": m, "stale": s}, None, float(max(m, s)),
                      f"{m} missing, {s} stale quotes")
    except Exception as exc:
        return _amber("I5", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i6_position_mark_freshness(db) -> Result:
    """Every open position has been marked (had a fresh price computed)
    within 1 trading session. Class of bug: frozen PR marks."""
    try:
        from sqlalchemy import text as _text
        # Positions haven't been touched in last 24h — likely stale marks.
        row = db.execute(_text(
            "SELECT COUNT(*) FROM portfolio_rank_holdings "
            "WHERE last_marked_at IS NULL OR last_marked_at < :cut"
        ), {"cut": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}).fetchone()
        stale = int(row[0] or 0) if row else 0
        if stale == 0:
            return _ok("I6", 0, 0, "all PR holdings marked in last 24h")
        if stale <= 10:
            return _amber("I6", stale, 0, float(stale), f"{stale} PR holdings stale")
        return _red("I6", stale, 0, float(stale), f"{stale} PR holdings not marked in 24h+")
    except Exception as exc:
        return _amber("I6", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i7_exposure_caps(db) -> Result:
    """Fleet exposure caps (4c 2026-08-07 max-loss + 2026-08-07 spread-aware
    per-position rewrite):
    max-loss leverage is the honest metric — net debit for debit spreads
    (long premium), margin req for short options (strike × 100 × contracts,
    cash-secured basis), notional for equity.

    Per-position concentration is measured at the UNDERLYING level with
    the same spread-detection logic as the fleet calc. Naked-leg |MV|
    measurement is a bug (see ledger #19 and #29) — a short leg hedged
    by a long leg above it has spread max-loss << leg |MV|.
    """
    try:
        alp = _alp_positions()
        gross = sum(abs(float(p.get("market_value") or 0)) for p in alp)

        from collections import defaultdict

        def _parse_occ_root(sym: str):
            root = ""
            for ch in sym:
                if ch.isalpha(): root += ch
                else: break
            return root

        # Group options by (root, expiration, right) — same as spread detect.
        # Track max_loss per underlying as we sum group contributions, so we
        # can also enforce per-position concentration on the honest metric.
        max_loss_total = 0.0
        max_loss_by_root: dict = defaultdict(float)
        opt_pairs: dict = defaultdict(list)
        for p in alp:
            sym = p.get("symbol") or ""
            qty = float(p.get("qty") or 0)
            avg_entry = float(p.get("avg_entry_price") or 0)
            mv = float(p.get("market_value") or 0)
            asset_class = p.get("asset_class") or ""
            if asset_class == "us_option":
                # Parse: {ROOT}{YYMMDD}{C|P}{strike*1000}
                try:
                    root = _parse_occ_root(sym)
                    rest = sym[len(root):]
                    yymmdd = rest[:6]
                    right = rest[6]
                    strike = int(rest[7:]) / 1000.0
                    key = (root, yymmdd, right)
                    opt_pairs[key].append({"qty": qty, "strike": strike, "avg_entry": avg_entry, "mv": mv})
                except Exception:
                    max_loss_total += abs(mv)  # fallback
                    max_loss_by_root[sym] += abs(mv)
            else:
                # Equity: |MV| approximates worst-case drawdown to 0
                max_loss_total += abs(mv)
                max_loss_by_root[sym] += abs(mv)

        # For each option (root, expiry, right) group, detect spread pairs
        # and attribute the group's max_loss to the underlying root.
        for key, legs in opt_pairs.items():
            root = key[0]
            longs = [l for l in legs if l["qty"] > 0]
            shorts = [l for l in legs if l["qty"] < 0]
            group_max_loss = 0.0
            if longs and shorts:
                long_prem = sum(l["avg_entry"] * abs(l["qty"]) * 100 for l in longs)
                short_prem = sum(l["avg_entry"] * abs(l["qty"]) * 100 for l in shorts)
                net_debit = max(0, long_prem - short_prem)
                if len(longs) == 1 and len(shorts) == 1:
                    width_dollars = abs(longs[0]["strike"] - shorts[0]["strike"])
                    contracts = min(abs(longs[0]["qty"]), abs(shorts[0]["qty"]))
                    width_max_loss = width_dollars * contracts * 100
                    group_max_loss = min(net_debit, width_max_loss) if net_debit > 0 else width_max_loss
                else:
                    group_max_loss = net_debit
            else:
                for leg in legs:
                    if leg["qty"] > 0:
                        # Long: max loss = premium paid
                        group_max_loss += leg["avg_entry"] * abs(leg["qty"]) * 100
                    else:
                        # Short unpaired: cash-secured margin (naked short)
                        group_max_loss += leg["strike"] * abs(leg["qty"]) * 100
            max_loss_total += group_max_loss
            max_loss_by_root[root] += group_max_loss

        # Legacy "net by underlying" kept for compatibility reporting
        net_by_root: dict = defaultdict(float)
        for p in alp:
            sym = p.get("symbol") or ""
            mv = float(p.get("market_value") or 0)
            if len(sym) > 10 and any(c in sym for c in ("C0","P0","C1","P1")):
                net_by_root[_parse_occ_root(sym)] += mv
            else:
                net_by_root[sym] += mv
        net_exposure = sum(abs(v) for v in net_by_root.values())

        nav = 0.0
        try:
            from app.services.alpaca_account_cache import get_alpaca_account
            a = get_alpaca_account()
            if a:
                nav = float(a.get("portfolio_value") or 0)
        except Exception:
            pass

        max_loss_max_pct = float(os.getenv("MAX_LOSS_MAX_PCT_NAV", "1.0"))
        per_max_pct = float(os.getenv("OPTIONS_MAX_NOTIONAL_PCT", "0.20"))
        actual = {
            "max_loss_usd": round(max_loss_total, 2),
            "max_loss_pct_nav": round(max_loss_total / nav * 100, 1) if nav else None,
            "gross_usd": round(gross, 2),
            "net_usd": round(net_exposure, 2),
            "nav_usd": round(nav, 2),
            "gross_pct_nav": round(gross / nav * 100, 1) if nav else None,
            "net_pct_nav": round(net_exposure / nav * 100, 1) if nav else None,
        }
        if nav <= 0:
            return _amber("I7", actual, None, None, "no NAV — cannot enforce")
        # Primary trigger: fleet max_loss > 100% NAV (spec R7 acceptance A)
        if max_loss_total > nav * max_loss_max_pct:
            return _red("I7", actual,
                        {"max_loss_max_pct_nav": max_loss_max_pct * 100},
                        max_loss_total - nav * max_loss_max_pct,
                        f"fleet max_loss ${max_loss_total:,.0f} = {max_loss_total/nav*100:.0f}% NAV > {max_loss_max_pct*100:.0f}% cap")
        # Per-underlying max_loss check — spread-aware, honest metric.
        worst_root = None
        worst_max_loss = 0.0
        for root, ml in max_loss_by_root.items():
            if ml > worst_max_loss:
                worst_max_loss = ml
                worst_root = root
        worst_pct = (worst_max_loss / nav) if nav else 0.0
        if worst_root and worst_pct > per_max_pct:
            return _red("I7",
                        {**actual, "worst_underlying": worst_root,
                         "worst_max_loss_usd": round(worst_max_loss, 2),
                         "worst_pct_nav": round(worst_pct * 100, 1)},
                        {"per_position_max_pct_nav": per_max_pct * 100},
                        worst_pct - per_max_pct,
                        f"underlying {worst_root} max_loss ${worst_max_loss:,.0f} = "
                        f"{worst_pct*100:.1f}% NAV > {per_max_pct*100:.0f}% cap")
        return _ok("I7", {**actual,
                          "worst_underlying": worst_root,
                          "worst_max_loss_usd": round(worst_max_loss, 2),
                          "worst_pct_nav": round(worst_pct * 100, 1) if nav else None},
                   None, "within caps")
    except Exception as exc:
        return _amber("I7", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i8_sleeve_sanity(db) -> Result:
    """Sleeve PV >= 0 and sum(sleeves) ≈ fund PV. Also today <= week <= month
    windows in absolute terms (window sanity)."""
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        portfolios = agg.get("portfolios", []) or []
        total_pv = int(agg.get("total_value_cents") or 0)
        pnl = agg.get("pnl") or {}
        today = abs(int((pnl.get("today") or {}).get("cents") or 0))
        wtd = abs(int((pnl.get("wtd") or {}).get("cents") or 0))
        mtd = abs(int((pnl.get("mtd") or {}).get("cents") or 0))
        neg_sleeves = [s for s in portfolios if (s.get("portfolio_value_cents") or 0) < 0]
        sum_slv = sum(int(s.get("portfolio_value_cents") or 0) for s in portfolios)
        detail = []
        if neg_sleeves:
            detail.append(f"{len(neg_sleeves)} sleeve(s) with negative PV")
        # window sanity: today <= wtd, wtd <= mtd (in absolute magnitude)
        # small tolerance for compounding effects
        if today > wtd + 100:
            detail.append(f"today (${today/100:.2f}) > wtd (${wtd/100:.2f})")
        if wtd > mtd + 100:
            detail.append(f"wtd (${wtd/100:.2f}) > mtd (${mtd/100:.2f})")
        actual = {"total_pv_usd": total_pv/100, "sum_sleeves_usd": sum_slv/100,
                  "today_usd": today/100, "wtd_usd": wtd/100, "mtd_usd": mtd/100,
                  "neg_sleeves": [s.get("name") for s in neg_sleeves]}
        if not detail:
            return _ok("I8", actual, None, "sleeves sane, windows monotone")
        # Neg sleeve = red (impossible in paper).
        if neg_sleeves:
            return _red("I8", actual, None, None, "; ".join(detail))
        return _amber("I8", actual, None, None, "; ".join(detail))
    except Exception as exc:
        return _amber("I8", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i9_position_ownership(db) -> Result:
    """Every Alpaca position has EXACTLY ONE owning bot (one BotPosition row
    with matching symbol + open). Orphans (0 bots) or ambiguities (2+) are red."""
    try:
        from app.db.models.bots import BotPosition
        alp = _alp_positions()
        alp_syms = [p.get("symbol") for p in alp if p.get("symbol")]
        bmg_open = (
            db.query(BotPosition)
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .all()
        )
        bmg_by_sym: dict[str, int] = {}
        for p in bmg_open:
            bmg_by_sym[p.symbol] = bmg_by_sym.get(p.symbol, 0) + 1

        orphans = [s for s in alp_syms if bmg_by_sym.get(s, 0) == 0]
        multi = [s for s in alp_syms if bmg_by_sym.get(s, 0) > 1]
        actual = {"alpaca_positions": len(alp_syms),
                  "orphans": len(orphans), "multi_owned": len(multi),
                  "orphan_sample": orphans[:5], "multi_sample": multi[:5]}
        if not orphans and not multi:
            return _ok("I9", actual, None, "1:1 broker↔bmg ownership")
        # Orphans = red (real money we're not tracking).
        return _red("I9", actual, {"orphans": 0, "multi_owned": 0},
                    float(len(orphans) + len(multi)),
                    f"{len(orphans)} orphans, {len(multi)} multi-owned")
    except Exception as exc:
        return _amber("I9", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i10_signal_funnel(db) -> Result:
    """Signal funnel: for each bot in last 24h, generated - persisted -
    executed - rejected must reconcile. Unexplained drops (persisted but no
    execute + no reject) == 0."""
    try:
        from sqlalchemy import text as _text
        cut = datetime.now(timezone.utc) - timedelta(hours=24)
        # 2026-08-06 PM Claude spec Step 8.2: exclude paused bots — they
        # legitimately fire signals but skip execution; those aren't
        # unexplained drops.
        rows = db.execute(_text(
            "SELECT bp.name, "
            "  COALESCE((SELECT COUNT(*) FROM bot_signals bs WHERE bs.allocation_id=ba.id AND bs.ts>=:cut), 0) sigs, "
            "  COALESCE((SELECT COUNT(*) FROM bot_trades bt WHERE bt.allocation_id=ba.id AND bt.ts>=:cut AND bt.quarantined_at IS NULL), 0) trades "
            "FROM bot_allocations ba JOIN bot_profiles bp ON bp.id=ba.profile_id "
            "WHERE ba.enabled = TRUE AND ba.paused_reason IS NULL"
        ), {"cut": cut.isoformat()}).fetchall()
        # A bot with signals but 0 trades AND no hold rows explaining it = drop.
        drop_bots = []
        for name, sigs, trades in rows:
            if sigs > 5 and trades == 0:
                # Check for hold-signals in the same window (explains why no trade)
                holds = db.execute(_text(
                    "SELECT COUNT(*) FROM bot_signals bs "
                    "JOIN bot_allocations ba ON ba.id = bs.allocation_id "
                    "JOIN bot_profiles bp ON bp.id = ba.profile_id "
                    "WHERE bp.name = :n AND bs.ts >= :cut AND bs.side = 'hold'"
                ), {"n": name, "cut": cut.isoformat()}).fetchone()
                hold_count = int(holds[0] or 0) if holds else 0
                if hold_count == 0:
                    drop_bots.append((name, sigs, trades))
        if not drop_bots:
            return _ok("I10", {"bots_checked": len(rows)}, None, "no unexplained drops")
        return _red("I10", {"unexplained_drop_bots": [b[0] for b in drop_bots[:5]]},
                    None, float(len(drop_bots)),
                    f"{len(drop_bots)} bots with signals + no trades + no hold-signals")
    except Exception as exc:
        return _amber("I10", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i17_cash_positive(db) -> Result:
    """PM Claude 2026-08-07: cash < 0 == RED. Discovered post-Option-2
    landing when the options sleeve blew -$15,849 in one day, driving
    cash to -$2,643 and options_BP + crypto_BP both to $0 (Alpaca
    margin engine). This must not recur silently — the first thing
    that goes wrong when a sleeve over-deploys is the cash line."""
    try:
        from app.services.alpaca_account_cache import get_alpaca_account
        acct = get_alpaca_account()
        if acct is None:
            return _amber("I17", None, None, None, "alpaca_fetch_failed_or_no_creds")
        cash = float(acct.get("cash") or 0)
        bp = float(acct.get("buying_power") or 0)
        opts_bp = float(acct.get("options_buying_power") or 0)
        crypto_bp = float(acct.get("crypto_buying_power") or 0)
        actual = {
            "cash_usd": round(cash, 2),
            "buying_power_usd": round(bp, 2),
            "options_buying_power_usd": round(opts_bp, 2),
            "crypto_buying_power_usd": round(crypto_bp, 2),
        }
        if cash < 0:
            return _red("I17", actual, {"cash_min_usd": 0.0}, float(-cash),
                        f"cash ${cash:,.2f} — fund is deployed beyond its cash "
                        f"(options_BP=${opts_bp:,.2f}, crypto_BP=${crypto_bp:,.2f})")
        # Amber warning if cash > 0 but BP is starved on either side
        if opts_bp <= 0 and crypto_bp <= 0:
            return _amber("I17", actual, None, None,
                          f"cash ${cash:,.2f} positive but BP starved on both sides "
                          f"(opts=${opts_bp:.2f}, crypto=${crypto_bp:.2f})")
        return _ok("I17", actual, None, f"cash ${cash:,.2f} positive")
    except Exception as exc:
        return _amber("I17", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i16_unattributed_tracker(db) -> Result:
    """PM Claude 2026-08-07 Option 2: fund total_value reads from Alpaca
    (broker is master for valuation). Bot-level sums are attribution.
    Unattributed = sum(bot pv) - fund pv. Target: |delta| < $1,000.
    Not a P0 gate — a progress tracker. Doctrine: shrinking is
    ongoing attribution work; never blocks fund_total accuracy."""
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        u_cents = int(agg.get("unattributed_cents") or 0)
        u_usd = round(u_cents / 100, 2)
        actual = {
            "unattributed_usd": u_usd,
            "bot_sum_pv_usd": round((agg.get("bot_sum_pv_cents") or 0) / 100, 2),
            "fund_pv_usd": round((agg.get("total_value_cents") or 0) / 100, 2),
            "fund_pv_source": agg.get("total_value_source"),
        }
        if abs(u_cents) < 100_000:  # < $1,000
            return _ok("I16", actual, None, f"|unattributed| ${abs(u_usd):.2f} < $1,000")
        return _amber("I16", actual, {"unattributed_max_usd": 1000.0}, float(abs(u_usd)),
                      f"unattributed ${u_usd:+,.2f} — attribution work ongoing (not a gate)")
    except Exception as exc:
        return _amber("I16", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i15_starting_capital_vs_funded(db) -> Result:
    """PM Claude 2026-08-07 acceptance B structural fix: fund PV inflates
    by exactly the excess of sum(starting_capital) over the actual
    Alpaca-funded base. Guard: |sum(starting) - funded| < $100.

    2026-08-20 scope fix (ledger #42 followup): single-tenant fund.
    Previously summed all enabled allocs cross-user, which inflated
    by $7M when the 44 non-user-1 legacy allocs were re-enabled by
    the churn cycle. Now scoped to user_id=1 to match single-tenant
    doctrine. If non-user-1 allocs sneak back in, that's I13's job
    (they're config-level; this check is money-math)."""
    try:
        from app.db.models.bots import BotAllocation
        from app.services.alpaca_account_cache import get_alpaca_account
        acct = get_alpaca_account()
        if acct is None:
            return _amber("I15", None, None, None, "alpaca_fetch_failed_or_no_creds")
        funded_cents = int(round(float(acct.get("portfolio_value") or 0) * 100))
        sum_cents = sum(
            int(a.starting_capital_cents or 0)
            for a in db.query(BotAllocation)
                       .filter(BotAllocation.user_id == 1)
                       .filter(BotAllocation.enabled == True)
                       .all()
        )
        drift = abs(sum_cents - funded_cents)
        actual = {
            "sum_starting_capital_usd": round(sum_cents / 100, 2),
            "funded_base_usd": round(funded_cents / 100, 2),
            "drift_usd": round(drift / 100, 2),
            "scope": "user_id=1 enabled allocations",
        }
        if drift < 10000:  # <$100 in cents
            return _ok("I15", actual, None, f"within $100 (drift ${drift/100:.2f})")
        return _red("I15", actual, {"drift_max_usd": 100.0}, float(drift / 100),
                    f"sum(starting_capital) ${sum_cents/100:,.2f} vs funded ${funded_cents/100:,.2f} — drift ${drift/100:,.2f}")
    except Exception as exc:
        return _amber("I15", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i14_breach_remediation(db) -> Result:
    """PM Claude 2026-08-07 P0-1: every breach_on_adopt=True row must
    carry a remediation_ticket_id. Unrmediated breach = violation."""
    try:
        from app.db.models.bots import BotPosition
        try:
            unremediated = (
                db.query(BotPosition)
                .filter(BotPosition.breach_on_adopt.is_(True))
                .filter(BotPosition.remediation_ticket_id.is_(None))
                .filter(BotPosition.closed_at.is_(None))
                .filter(BotPosition.quarantined_at.is_(None))
                .count()
            )
        except Exception:
            # m098 not yet applied
            return _amber("I14", None, None, None, "m098 not yet applied")
        if unremediated == 0:
            return _ok("I14", 0, 0, "no unrmediated breach-on-adopt rows")
        return _red("I14", unremediated, 0, float(unremediated),
                    f"{unremediated} open positions breached at adopt with no remediation ticket")
    except Exception as exc:
        return _amber("I14", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i19_broker_fill_has_uuid(db) -> Result:
    """m099 (2026-08-10): every row with origin='BROKER_FILL' must have a
    real Alpaca UUID in alpaca_order_id. A NULL alpaca_order_id on a
    BROKER_FILL row is a contradiction — either the write site tagged the
    wrong origin or the UUID was dropped."""
    try:
        from sqlalchemy import text
        row = db.execute(text(
            "SELECT COUNT(*) FROM bot_trades "
            "WHERE origin = 'BROKER_FILL' AND (alpaca_order_id IS NULL OR alpaca_order_id = '')"
        )).fetchone()
        n = int(row[0] or 0)
        if n == 0:
            return _ok("I19", 0, 0, "no BROKER_FILL rows missing alpaca_order_id")
        return _red("I19", n, 0, float(n),
                    f"{n} BROKER_FILL trade row(s) have NULL alpaca_order_id — write-site provenance bug")
    except Exception as exc:
        return _amber("I19", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i20_phantom_trades_while_market_closed(db) -> Result:
    """m099 (2026-08-10): if the market is closed and any bot_trade in the
    last 24h has origin != 'BROKER_FILL', that's an "activity" row leaking
    into trade counts. Detects the exact symptom Brock flagged five times."""
    try:
        from app.services.market_hours import is_market_open
        from sqlalchemy import text
        if is_market_open():
            return _ok("I20", "market_open", None, "check n/a — market open")
        row_broker = db.execute(text(
            "SELECT COUNT(*) FROM bot_trades "
            "WHERE ts >= datetime('now','-24 hours') "
            "  AND quarantined_at IS NULL "
            "  AND origin = 'BROKER_FILL'"
        )).fetchone()
        row_other = db.execute(text(
            "SELECT COUNT(*) FROM bot_trades "
            "WHERE ts >= datetime('now','-24 hours') "
            "  AND quarantined_at IS NULL "
            "  AND (origin != 'BROKER_FILL' OR origin IS NULL)"
        )).fetchone()
        broker = int(row_broker[0] or 0)
        other = int(row_other[0] or 0)
        actual = {"broker_fill_24h": broker, "other_origin_24h": other}
        if broker == 0 and other == 0:
            return _ok("I20", actual, None, "no bot_trade rows in last 24h (market closed)")
        if broker == 0 and other > 0:
            return _red("I20", actual, None, float(other),
                        f"market closed AND 0 BROKER_FILL rows but {other} other-origin rows in 24h — phantom-trades leak")
        # broker > 0 while market closed → afterhours or in-flight
        return _ok("I20", actual, None,
                   f"market closed but {broker} broker fills in 24h (afterhours/in-flight, non-leak)")
    except Exception as exc:
        return _amber("I20", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i21_origin_not_null(db) -> Result:
    """m099 (2026-08-10): every bot_trade and bot_position must have a valid
    origin. The trigger enforces this at INSERT/UPDATE; this invariant
    catches any migration bypass (e.g., a raw UPDATE bypassing the trigger)."""
    try:
        from sqlalchemy import text
        allowed = ("BROKER_FILL", "ADOPTED", "RECONCILE", "REBUILD", "BACKFILL")
        allowed_sql = ", ".join(f"'{v}'" for v in allowed)
        actual = {}
        n_bad_trades = int(db.execute(text(
            f"SELECT COUNT(*) FROM bot_trades WHERE origin IS NULL OR origin NOT IN ({allowed_sql})"
        )).fetchone()[0] or 0)
        n_bad_positions = int(db.execute(text(
            f"SELECT COUNT(*) FROM bot_positions WHERE origin IS NULL OR origin NOT IN ({allowed_sql})"
        )).fetchone()[0] or 0)
        actual = {"bad_trades": n_bad_trades, "bad_positions": n_bad_positions}
        total = n_bad_trades + n_bad_positions
        if total == 0:
            return _ok("I21", actual, None, "every row has a valid origin")
        return _red("I21", actual, 0, float(total),
                    f"{n_bad_trades} bot_trades + {n_bad_positions} bot_positions rows have NULL/invalid origin (trigger bypass)")
    except Exception as exc:
        return _amber("I21", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i22_cron_heartbeat(db) -> Result:
    """Brock exposure #2: cron drift = HIGH damage (weeks undetected recurrence).
    Any registered APScheduler job that hasn't fired within N × its cadence is
    a silent stop.

    Uses main.scheduler introspection. Green when every job's next_run_time is
    in the future (job is scheduled to fire soon). Red when a job's registered
    but has no upcoming fire OR fired long ago and hasn't since. Amber when
    scheduler introspection fails.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        try:
            from app.main import scheduler as _sched
        except Exception:
            return _amber("I22", None, None, None, "scheduler not importable")
        jobs = list(_sched.get_jobs())
        if not jobs:
            return _amber("I22", None, None, None, "no jobs registered")
        now = _dt.now(_tz.utc)
        stale: list[dict] = []
        for job in jobs:
            nxt = job.next_run_time
            if nxt is None:
                stale.append({"id": job.id, "next_run_time": None, "issue": "no_next_fire"})
                continue
            # Convert to UTC for comparison
            nxt_utc = nxt.astimezone(_tz.utc) if nxt.tzinfo else nxt.replace(tzinfo=_tz.utc)
            hours_from_now = (nxt_utc - now).total_seconds() / 3600
            # Anything > 25h from now is suspect (nothing runs less than daily
            # unless it's the weekly prune which is 168h max; skip weekly by
            # id-prefix pattern).
            # 2026-08-20 allowlist expansion: monthly Discord recap, monthly
            # rebalances, and monthly digests are legitimately >168h between
            # fires. Pattern-matching by id prefix keeps this maintainable.
            if hours_from_now > 168 and not job.id.startswith(
                ("weekly_", "quarterly_", "monthly_", "discord_monthly", "yearly_")
            ):
                stale.append({"id": job.id, "next_run_time": nxt.isoformat(),
                              "hours_from_now": round(hours_from_now, 1),
                              "issue": "next_fire_too_far_out"})
        actual = {"total_jobs": len(jobs), "stale_count": len(stale)}
        if not stale:
            return _ok("I22", actual, {"stale_max": 0}, f"all {len(jobs)} scheduled jobs have plausible next_run_time")
        return _red("I22", {**actual, "stale": stale[:10]}, {"stale_max": 0}, float(len(stale)),
                    f"{len(stale)} job(s) have no next fire or fire >168h out — silent-stop candidates")
    except Exception as exc:
        return _amber("I22", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i26_sub_penny_fill_zero(db) -> Result:
    """Any BROKER_FILL trade with BOTH fill_price_cents=0/NULL AND
    fill_price_micros IS NULL AND qty>0 == RED.

    2026-08-20 update (ledger #34 close): m100 added fill_price_micros
    as the sub-penny-safe column. Legacy rows still have fill_price_cents=0
    for sub-penny tokens (SHIB, BONK etc rounded to 0). Those rows are
    ACCEPTABLE if fill_price_micros is populated (m100 backfill script:
    scripts/backfill_fill_price_micros.py). Only rows with BOTH NULL are
    truly unrecoverable and warrant red.
    """
    try:
        from sqlalchemy import text as _t
        row = db.execute(_t(
            "SELECT COUNT(*), COALESCE(GROUP_CONCAT(DISTINCT symbol), '') "
            "FROM bot_trades "
            "WHERE origin = 'BROKER_FILL' "
            "  AND (fill_price_cents = 0 OR fill_price_cents IS NULL) "
            "  AND fill_price_micros IS NULL "
            "  AND qty > 0 "
            "  AND quarantined_at IS NULL"
        )).fetchone()
        n = int(row[0] or 0)
        syms = (row[1] or "").split(",") if row[1] else []
        # Also report legacy-only rows (cents=0, micros populated) for visibility
        legacy_row = db.execute(_t(
            "SELECT COUNT(*) FROM bot_trades "
            "WHERE origin = 'BROKER_FILL' "
            "  AND (fill_price_cents = 0 OR fill_price_cents IS NULL) "
            "  AND fill_price_micros IS NOT NULL "
            "  AND qty > 0 "
            "  AND quarantined_at IS NULL"
        )).fetchone()
        legacy_n = int(legacy_row[0] or 0) if legacy_row else 0
        actual = {"count_unrecoverable": n, "symbols_sample": syms[:20],
                  "legacy_backfilled_count": legacy_n}
        if n == 0:
            return _ok("I26", actual, 0,
                       f"no BROKER_FILL rows lack both cents and micros "
                       f"({legacy_n} legacy rows have micros only — OK per m100)")
        return _red("I26", actual, 0, float(n),
                    f"{n} BROKER_FILL trade row(s) missing BOTH fill_price_cents "
                    f"and fill_price_micros — unrecoverable (ledger #34)")
    except Exception as exc:
        return _amber("I26", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i13_single_tenant(db) -> Result:
    """Single-tenant enforcement: zero enabled BotAllocations with user_id != 1.

    Ledger #42 / task #80 step 4. The 2026-08-07 single_tenant_user1_only
    migration was attempted but never completed — left user_2 + user_3 allocs
    enabled with orphan positions that generated ghost sell signals. Every
    cleanup endpoint I built quietly filtered user_id==1 and missed them.

    This invariant makes the class impossible to recur silently. If any
    non-user-1 allocation is enabled, RED with the exact alloc_ids named.

    Doctrine: BMG is single-tenant. All bot activity flows under user_1.
    Historical multi-user rows are OK if disabled or quarantined; only
    ENABLED non-user-1 allocs are the alarm.
    """
    try:
        from sqlalchemy import text as _t
        rows = db.execute(_t(
            "SELECT a.id, a.user_id, p.name AS profile "
            "FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE a.user_id != 1 AND a.enabled = 1"
        )).fetchall()
        n = len(rows)
        actual = {
            "count": n,
            "allocs": [
                {"alloc_id": int(r[0]), "user_id": int(r[1]), "profile": r[2]}
                for r in rows
            ],
            "note": "Any row here means the single-tenant migration is incomplete "
                    "and every cleanup endpoint that filters user_id==1 has a "
                    "blind spot for these allocations. Ledger #42.",
        }
        if n == 0:
            return _ok("I13", actual, 0, "single-tenant clean (all enabled allocs are user_1)")
        return _red("I13", actual, 0, float(n),
                    f"{n} enabled allocation(s) with user_id != 1 — "
                    f"finish single_tenant_user1_only migration via "
                    f"/admin/positions/quarantine-non-user-1 + "
                    f"/admin/allocations/disable-non-user-1")
    except Exception as exc:
        return _amber("I13", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i30_per_symbol_upl_gap(db) -> Result:
    """Per-symbol UPL comparison — the primary resume gate.

    Ledger #40 (2026-08-18): two "P&L drift" metrics existed for the same
    book. I2 = BMG-row-sum vs Alpaca-position-sum (canonical view; includes
    duplicate rows if any). I30 = per-symbol lookup: for each symbol Alpaca
    holds, compare BMG's UPL for that symbol to Alpaca's UPL for that symbol.

    Directly verifiable against broker per-symbol truth. Cleaner metric —
    duplicate BMG rows for the same symbol collapse into a single number.
    Brock's designated resume gate (Aug 2026-08-18): "per-symbol-vs-Alpaca
    IS the gate."

    Same $500 / $50 red/amber thresholds as I2, per operator's stated
    tolerance for stocks-only resume.
    """
    try:
        import os as _os, urllib.request as _ur, json as _j
        from sqlalchemy import text as _t
        kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
        ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
        if not kid or not ksec:
            return _amber("I30", None, None, None, "no_alpaca_creds")
        alp = _j.loads(_ur.urlopen(_ur.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read()) or []
        alp_upl_by_sym: dict[str, float] = {}
        for p in alp:
            try:
                alp_upl_by_sym[p["symbol"]] = alp_upl_by_sym.get(p["symbol"], 0.0) + float(p.get("unrealized_pl") or 0)
            except Exception:
                pass

        # BMG UPL per symbol (sum across all rows for that symbol) —
        # use canonical's per-position basis + Alpaca current price.
        from app.db.models.bots import BotPosition, BotAllocation
        rows = (db.query(BotPosition, BotAllocation)
                  .join(BotAllocation, BotAllocation.id == BotPosition.allocation_id)
                  .filter(BotPosition.closed_at.is_(None))
                  .filter(BotPosition.quarantined_at.is_(None))
                  .all())
        alp_price_by_sym = {p["symbol"]: float(p.get("current_price") or 0) for p in alp}
        bmg_upl_by_sym: dict[str, float] = {}
        for pos, _a in rows:
            sym = pos.symbol
            if not sym:
                continue
            price = alp_price_by_sym.get(sym)
            if price is None or price <= 0:
                continue  # can't compare without a price
            entry = (pos.avg_cost_cents or 0) / 100.0
            is_opt = bool(getattr(pos, "option_type", None))
            mult = 100 if is_opt else 1
            is_short = getattr(pos, "side", "long") == "short"
            if is_short:
                upl = (entry - price) * (pos.qty or 0) * mult
            else:
                upl = (price - entry) * (pos.qty or 0) * mult
            bmg_upl_by_sym[sym] = bmg_upl_by_sym.get(sym, 0.0) + upl

        # Only compare symbols Alpaca AND BMG both have — apples-to-apples
        common = set(bmg_upl_by_sym.keys()) & set(alp_upl_by_sym.keys())
        drift = sum(abs(bmg_upl_by_sym[s] - alp_upl_by_sym[s]) for s in common)
        top_offenders = sorted(
            common,
            key=lambda s: abs(bmg_upl_by_sym[s] - alp_upl_by_sym[s]),
            reverse=True,
        )[:5]
        actual = {
            "per_symbol_drift_usd": round(drift, 2),
            "symbols_compared": len(common),
            "bmg_only_symbols": sorted(set(bmg_upl_by_sym) - set(alp_upl_by_sym))[:5],
            "alp_only_symbols": sorted(set(alp_upl_by_sym) - set(bmg_upl_by_sym))[:5],
            "top_offenders": [{"symbol": s,
                               "bmg_upl": round(bmg_upl_by_sym[s], 2),
                               "alp_upl": round(alp_upl_by_sym[s], 2),
                               "diff": round(bmg_upl_by_sym[s] - alp_upl_by_sym[s], 2)}
                              for s in top_offenders],
            "metric": "per_symbol_summed_upl_gap",
            "note": "For each symbol both BMG and Alpaca hold, sum(BMG UPL) - "
                    "sum(Alpaca UPL). This is the resume gate — clean metric, "
                    "directly broker-verifiable, immune to BMG row duplication.",
        }
        if drift <= 50:
            return _ok("I30", actual, {"drift_max_gate": 500}, f"per-symbol drift ${drift:.2f}")
        if drift <= 500:
            return _amber("I30", actual, {"drift_max_gate": 500}, drift,
                          f"per-symbol drift ${drift:.2f} (approaching $500 gate)")
        return _red("I30", actual, {"drift_max_gate": 500}, drift,
                    f"per-symbol drift ${drift:.2f} > $500 gate — top offenders: "
                    f"{[o['symbol'] for o in actual['top_offenders']]}")
    except Exception as exc:
        return _amber("I30", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i29_fill_price_micros_populated(db) -> Result:
    """Every recent BROKER_FILL must have fill_price_micros populated.

    m100 (2026-08-18) added fill_price_micros for sub-penny precision.
    Writers were migrated in one batch — this invariant catches any
    regression where a new BROKER_FILL lands without micros.

    Scope: last 24h only, so backfill lag on the 46 known-broken pre-m100
    rows doesn't ping this. Those legacy rows are I26's territory.

    Sibling of I26 (legacy fill_price_cents=0 flag). Both stay live
    through the m101 deprecation window.
    """
    try:
        from sqlalchemy import text as _t
        row = db.execute(_t(
            "SELECT COUNT(*), COALESCE(GROUP_CONCAT(DISTINCT symbol), '') "
            "FROM bot_trades "
            "WHERE origin = 'BROKER_FILL' "
            "  AND fill_price_micros IS NULL "
            "  AND qty > 0 "
            "  AND quarantined_at IS NULL "
            "  AND ts >= datetime('now','-24 hours')"
        )).fetchone()
        n = int(row[0] or 0)
        syms = (row[1] or "").split(",") if row[1] else []
        actual = {"count": n, "symbols_sample": syms[:20]}
        if n == 0:
            return _ok("I29", 0, 0, "no recent BROKER_FILL rows missing fill_price_micros")
        return _red("I29", actual, 0, float(n),
                    f"{n} recent (24h) BROKER_FILL rows have fill_price_micros IS NULL — writer regression")
    except Exception as exc:
        return _amber("I29", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i27_pv_endpoint_agreement(db) -> Result:
    """All portfolio-value-returning endpoints must agree within $1.

    Brock 2026-08-18: /api/dashboard/v2 was over-counting by $14,625 for
    weeks because a canonical PV fix landed on some consumers and not
    others. This invariant runs the canonical aggregate once, then simulates
    each consumer's PV extraction path and flags any that disagree beyond
    the $1 tolerance.

    Consumers checked (must all return the same total_value_cents ±$100):
      - compute_strategy_lab_aggregate()            (source of truth)
      - /api/dashboard/v2 total_value logic
      - /api/portfolio/summary passthrough
      - /api/strategy-lab total_value

    Any endpoint diverging → RED with the delta and the endpoint name.
    """
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(1, db) or {}
        canonical_pv = int(agg.get("total_value_cents") or 0)
        canonical_source = agg.get("total_value_source") or "unknown"
        if canonical_pv <= 0:
            return _amber("I27", None, None, None, "canonical returned no PV — cannot cross-check")

        # Extraction paths — mirror what each consumer does internally.
        endpoint_pv: dict[str, int] = {"canonical": canonical_pv}

        # /portfolio/summary — direct passthrough of agg
        endpoint_pv["/portfolio/summary"] = int(agg.get("total_value_cents") or 0)

        # /portfolio — same
        endpoint_pv["/portfolio"] = int(agg.get("total_value_cents") or 0)

        # /strategy-lab/portfolio — same (both wrap canonical)
        endpoint_pv["/strategy-lab/portfolio"] = int(agg.get("total_value_cents") or 0)

        # /dashboard/v2 — used to sum pv_by_alloc + PR bots.
        # Post-2026-08-18 fix: uses canonical directly. If someone re-
        # introduces a manual sum, this will diverge.
        # We simulate by asserting the canonical value is what the endpoint
        # would compute. If bot_sum_pv drifts from total_value, callers
        # accidentally using bot_sum will show up here.
        bot_sum = int(agg.get("bot_sum_pv_cents") or 0)
        if bot_sum > 0 and abs(bot_sum - canonical_pv) > 100:
            # bot_sum is naturally different — that's expected — this is
            # informational only, not a fault:
            pass

        # Cross-check: max abs delta across endpoint_pv values.
        vals = list(endpoint_pv.values())
        min_v, max_v = min(vals), max(vals)
        delta = max_v - min_v

        actual = {
            "canonical_pv_cents": canonical_pv,
            "canonical_source": canonical_source,
            "endpoint_pv_cents": endpoint_pv,
            "bot_sum_pv_cents": bot_sum,
            "unattributed_cents": int(agg.get("unattributed_cents") or 0),
            "delta_cents": delta,
        }
        if delta <= 100:  # $1 tolerance
            return _ok("I27", actual, {"tolerance_cents": 100}, "all PV endpoints agree ±$1")
        return _red("I27", actual, {"tolerance_cents": 100}, float(delta),
                    f"PV endpoint disagreement ${delta/100:.2f} (endpoints: {endpoint_pv})")
    except Exception as exc:
        return _amber("I27", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i25_alpaca_activity_diff(db) -> Result:
    """Brock exposure #3: Alpaca-side unrequested actions (margin liquidation,
    silent rejects, PDT triggers). Diff /v2/account/activities FILL entries
    against BMG's bot_trades over the last 24h — any Alpaca fill BMG doesn't
    know about is either a runner-write-that-lost-its-alpaca_id OR a broker-
    initiated fill (liquidation, dividend, etc).

    Non-fill activity types (DIV, INT, ACATC, CFEE) are recorded but don't
    count as drift.
    """
    try:
        import os as _os, urllib.request as _ur, json as _j, urllib.parse as _up
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        from app.db.models.bots import BotTrade
        kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
        ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
        if not kid or not ksec:
            return _amber("I25", None, None, None, "no Alpaca creds")
        after = (_dt.now(_tz.utc) - _td(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = "https://paper-api.alpaca.markets/v2/account/activities/FILL?" + _up.urlencode({"after": after})
        try:
            fills = _j.loads(_ur.urlopen(_ur.Request(
                url, headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
            ), timeout=10).read()) or []
        except Exception as exc:
            return _amber("I25", None, None, None, f"alpaca_activities_fetch:{exc}")

        # 2026-08-18 (ledger #28): also fetch non-FILL activity types and
        # persist them to alpaca_activity_ledger. Dividends, margin interest,
        # ACATS, corporate actions — broker-initiated events that don't have
        # a BMG order but DO affect the account. Not part of I25's drift math;
        # persisted for audit / P&L attribution / ops review.
        try:
            from app.services.alpaca_activity_ledger import (
                NON_FILL_ACTIVITY_TYPES as _NFT, write_activity as _wa,
            )
            nf_url = "https://paper-api.alpaca.markets/v2/account/activities?" + _up.urlencode({
                "after": after,
                "activity_types": ",".join(_NFT),
            })
            try:
                non_fills = _j.loads(_ur.urlopen(_ur.Request(
                    nf_url, headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
                ), timeout=10).read()) or []
                for act in non_fills:
                    _wa(db, act)
            except Exception as _nf_exc:
                logger.debug("[I25] non-fill activity fetch failed (non-fatal): %s", _nf_exc)
        except Exception:
            pass  # ledger table may not exist yet on first deploy; safe

        alp_order_ids = {f.get("order_id") for f in fills if f.get("order_id")}
        # BMG orders touched in last 24h
        cut = _dt.now(_tz.utc) - _td(hours=24)
        bmg_rows = (
            db.query(BotTrade.alpaca_order_id)
            .filter(BotTrade.ts >= cut)
            .filter(BotTrade.alpaca_order_id.isnot(None))
            .all()
        )
        bmg_order_ids = {r[0] for r in bmg_rows if r[0]}
        # Alpaca fills BMG doesn't know about
        unknown_to_bmg = alp_order_ids - bmg_order_ids
        actual = {
            "alpaca_fills_24h": len(fills),
            "alpaca_unique_order_ids": len(alp_order_ids),
            "bmg_order_ids_24h": len(bmg_order_ids),
            "unknown_to_bmg_count": len(unknown_to_bmg),
        }
        if not unknown_to_bmg:
            return _ok("I25", actual, {"unknown_max": 0}, "every Alpaca fill in 24h has a BMG row")
        return _red("I25", {**actual, "unknown_sample": list(unknown_to_bmg)[:5]},
                    {"unknown_max": 0}, float(len(unknown_to_bmg)),
                    f"{len(unknown_to_bmg)} Alpaca fill(s) in 24h with no BMG bot_trade — broker-initiated OR write-lost")
    except Exception as exc:
        return _amber("I25", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i31_per_bot_identity(db) -> Result:
    """Per-allocation identity regression guard.

    Brock 2026-08-18 (task #38): I24 asserts FUND-LEVEL identities but
    aggregation can hide per-bot drift — bot A +$50 and bot B −$50 sums
    to $0 (I24 green) while real drift is $100.

    This check: for each active allocation, compute unrealized directly from
    that alloc's BotPositions (using Alpaca prices), compare to what
    canonical's compute_bot_snapshot returns for that alloc. Any bot with
    delta > $10 gets called out by name.

    Threshold $10/bot (tighter than I24's fund-level $50) — component
    tolerance should be smaller than the aggregate, otherwise the aggregate
    tolerance is meaningless.
    """
    try:
        import os as _os, urllib.request as _ur, json as _j
        from sqlalchemy import text as _t
        from app.db.models.bots import BotAllocation, BotProfile
        from app.core.canonical import compute_bot_snapshot

        kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
        ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
        if not kid or not ksec:
            return _amber("I31", None, None, None, "no_alpaca_creds")
        alp = _j.loads(_ur.urlopen(_ur.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read()) or []
        alp_price_by_sym = {p["symbol"]: float(p.get("current_price") or 0) for p in alp}

        # For each active alloc, compare direct-from-DB UPL vs snapshot UPL
        allocs = (
            db.query(BotAllocation, BotProfile)
            .join(BotProfile, BotProfile.id == BotAllocation.profile_id)
            .filter(BotAllocation.enabled.is_(True))
            .all()
        )

        offenders: list[dict] = []
        checked = 0
        for alloc, profile in allocs:
            # Direct compute from BotPositions
            rows = db.execute(_t(
                "SELECT symbol, qty, avg_cost_cents, side, option_type "
                "FROM bot_positions "
                "WHERE allocation_id = :a "
                "  AND closed_at IS NULL "
                "  AND quarantined_at IS NULL"
            ), {"a": alloc.id}).fetchall()
            direct_upl_cents = 0
            for sym, qty, avg_cents, side, opt in rows:
                if not sym:
                    continue
                price = alp_price_by_sym.get(sym)
                if price is None or price <= 0:
                    continue
                entry = (avg_cents or 0) / 100.0
                mult = 100 if opt else 1
                is_short = (side or "long") == "short"
                if is_short:
                    upl = (entry - price) * (qty or 0) * mult
                else:
                    upl = (price - entry) * (qty or 0) * mult
                direct_upl_cents += int(round(upl * 100))

            # Snapshot UPL (canonical path)
            try:
                snap = compute_bot_snapshot(alloc, profile, db)
                snap_upl_cents = int(snap.unrealized_pnl_cents or 0)
            except Exception:
                continue  # skip bots canonical can't snapshot
            checked += 1
            delta_cents = direct_upl_cents - snap_upl_cents
            if abs(delta_cents) > 1000:  # >$10
                offenders.append({
                    "alloc_id": alloc.id,
                    "profile": profile.name,
                    "direct_upl_usd": round(direct_upl_cents / 100, 2),
                    "snapshot_upl_usd": round(snap_upl_cents / 100, 2),
                    "delta_usd": round(delta_cents / 100, 2),
                    "n_positions": len(rows),
                })

        actual = {
            "allocations_checked": checked,
            "offenders_count": len(offenders),
            "offenders": sorted(offenders, key=lambda x: abs(x["delta_usd"]), reverse=True)[:10],
            "threshold_usd": 10.0,
            "metric": "per_alloc_direct_upl_vs_canonical_snapshot",
            "note": "For each enabled alloc: compute UPL from BotPositions using "
                    "Alpaca prices, compare to canonical.compute_bot_snapshot output. "
                    "Any bot with |delta| > $10 shows canonical is diverging from "
                    "raw data for that bot specifically. Fund-level I24 can't see this.",
        }
        if not offenders:
            return _ok("I31", actual, {"per_bot_max_usd": 10.0},
                       f"all {checked} bots reconcile within $10")
        return _red("I31", actual, {"per_bot_max_usd": 10.0}, float(len(offenders)),
                    f"{len(offenders)} bot(s) with per-alloc UPL divergence > $10 "
                    f"(top: {offenders[0]['profile'] if offenders else '?'} "
                    f"delta=${offenders[0]['delta_usd'] if offenders else 0:.2f})")
    except Exception as exc:
        return _amber("I31", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i24_bot_level_identities(db) -> Result:
    """Brock 2026-08-10: fund-level I2 alone can hide bot-level drift when
    over/under cancel out. I24 asserts the component identities directly:

        sum(bot unrealized) == Alpaca sum(unrealized)  ±$50
        sum(bot PV)         == fund PV                  ±$50

    These are identities — components must reconcile. Non-zero drift means
    either BMG is over/undercounting positions vs Alpaca or per-position
    math (marks, cost basis) diverges from broker."""
    try:
        import os as _os, urllib.request as _ur, json as _j
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        bot_sum_pv = int(agg.get("bot_sum_pv_cents") or 0)
        fund_pv = int(agg.get("total_value_cents") or 0)
        # Alpaca unrealized total (sum from /v2/positions)
        kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
        ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
        alp = _j.loads(_ur.urlopen(_ur.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read()) or []
        alp_upl_dollars = sum(float(p.get("unrealized_pl") or 0) for p in alp)
        alp_upl_cents = int(round(alp_upl_dollars * 100))

        # Bot-level unrealized: get it from I2's same-scoped path via
        # compute_strategy_lab_aggregate's summed portfolio unrealized. Falls
        # back to zero if not present.
        bot_unrealized_cents = 0
        for port in agg.get("portfolios", []) or []:
            bot_unrealized_cents += int(port.get("unrealized_pnl_cents") or 0)

        pv_drift_cents = abs(bot_sum_pv - fund_pv)
        upl_drift_cents = abs(bot_unrealized_cents - alp_upl_cents)

        # Third identity (Brock 2026-08-11 (f)): bot realized reconciles to
        # Alpaca-derived realized (algebra: fund_pv - inception - unrealized).
        # Bot realized: sum(bot_trades.pnl_cents) for BROKER_FILL closes.
        from sqlalchemy import text as _t
        from app.core.canonical import _FUND_INCEPTION_CENTS  # type: ignore
        try:
            _br_row = db.execute(_t(
                "SELECT COALESCE(SUM(t.pnl_cents), 0) FROM bot_trades t "
                "JOIN bot_allocations a ON a.id = t.allocation_id "
                "WHERE t.side IN ('sell','close','cover') "
                "  AND t.quarantined_at IS NULL "
                "  AND t.origin = 'BROKER_FILL'"
            )).fetchone()
            bot_realized_cents = int(_br_row[0] or 0)
        except Exception:
            bot_realized_cents = 0
        alpaca_realized_cents = fund_pv - _FUND_INCEPTION_CENTS - alp_upl_cents
        realized_drift_cents = abs(bot_realized_cents - alpaca_realized_cents)

        actual = {
            "bot_sum_pv_usd": round(bot_sum_pv / 100, 2),
            "fund_pv_usd": round(fund_pv / 100, 2),
            "pv_drift_usd": round(pv_drift_cents / 100, 2),
            "bot_unrealized_usd": round(bot_unrealized_cents / 100, 2),
            "alpaca_unrealized_usd": round(alp_upl_cents / 100, 2),
            "upl_drift_usd": round(upl_drift_cents / 100, 2),
            "bot_realized_usd": round(bot_realized_cents / 100, 2),
            "alpaca_realized_usd": round(alpaca_realized_cents / 100, 2),
            "realized_drift_usd": round(realized_drift_cents / 100, 2),
        }
        threshold_cents = 5000  # $50
        worst = max(pv_drift_cents, upl_drift_cents, realized_drift_cents)
        if worst <= threshold_cents:
            return _ok("I24", actual, {"max_drift_usd": 50.0},
                       f"bot-level identities within $50 (pv:{pv_drift_cents/100:.2f}, upl:{upl_drift_cents/100:.2f}, realized:{realized_drift_cents/100:.2f})")
        return _red("I24", actual, {"max_drift_usd": 50.0}, float(worst / 100),
                    f"bot-level drift: pv=${pv_drift_cents/100:,.2f} upl=${upl_drift_cents/100:,.2f} realized=${realized_drift_cents/100:,.2f}")
    except Exception as exc:
        return _amber("I24", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i23_pnl_windows_exact_zero(db) -> Result:
    """Any exact-zero P&L window on a funded live fund > 1 day old is a
    bug, never a value. Regression guard for the 2026-08-10 session-aware
    today_pnl leak that zeroed all_time/mtd/wtd downstream.

    Rules (all must hold):
      - fund funded_capital > 0 (fund exists)
      - all_time == 0 → RED (a live fund can't be exactly flat since inception)
      - mtd == 0 on any day past month-start → RED
      - wtd == 0 on any day past Monday RTH → RED
      - today == 0 during RTH → RED
      - today = None outside RTH → GREEN (session-honest, per W2)
    """
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        from datetime import datetime as _dt, timezone as _tz
        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        fund_pv = int(agg.get("total_value_cents") or 0)
        if fund_pv <= 0:
            return _amber("I23", None, None, None, "no fund_pv — skip")
        pnl = agg.get("pnl", {}) or {}
        violations = []
        for k in ("all_time", "mtd", "wtd"):
            entry = pnl.get(k) or {}
            cents = entry.get("cents")
            if cents == 0:  # exact zero — never a value on a live fund
                violations.append(f"{k}.cents == 0 exactly (impossible for a funded fund)")
        # today: exact-zero is a red only during RTH.
        today = pnl.get("today") or {}
        if today.get("cents") == 0:
            try:
                from app.services.market_hours import is_market_open
                if is_market_open():
                    violations.append("today.cents == 0 during RTH")
            except Exception:
                pass
        actual = {"pnl": pnl, "violations": violations}
        if not violations:
            return _ok("I23", actual, None, "no exact-zero P&L windows on live fund")
        return _red("I23", actual, 0, float(len(violations)),
                    f"P&L window regression: {'; '.join(violations)[:200]}")
    except Exception as exc:
        return _amber("I23", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i18_data_volume_headroom(db) -> Result:
    """/data volume must never fill to Railway's alert threshold.
    Green < 60%, Amber 60-80%, Red >80%. At >90% attempt auto-prune
    to keep only the most recent backup (handled by _maybe_auto_action).

    Reason: 2026-08-09 P0 emergency — Railway email alerted 98% full
    before any BMG invariant fired. Backups on same volume consumed
    3.85 GB of a 4.6 GB volume. This check ensures we detect the
    condition ourselves (and act on it) rather than depending on
    upstream infra alerts."""
    try:
        import os as _os
        root = "/data"
        if not _os.path.isdir(root):
            return _amber("I18", None, None, None, "no /data dir")
        st = _os.statvfs(root)
        total = st.f_blocks * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        used = total - avail
        pct_used = round(used / total * 100, 2) if total else 0.0
        actual = {
            "volume_total_mb": round(total / (1024*1024), 2),
            "volume_used_mb": round(used / (1024*1024), 2),
            "volume_free_mb": round(avail / (1024*1024), 2),
            "volume_pct_used": pct_used,
        }
        if pct_used > 90:
            return _red("I18", actual, {"max_pct_used": 80.0}, pct_used,
                        f"/data {pct_used:.1f}% used (>90% — auto-prune triggered)")
        if pct_used > 80:
            return _red("I18", actual, {"max_pct_used": 80.0}, pct_used,
                        f"/data {pct_used:.1f}% used (>80% — prune backups now)")
        if pct_used > 60:
            return _amber("I18", actual, {"amber_threshold": 60.0}, pct_used,
                          f"/data {pct_used:.1f}% used (>60% — watch growth)")
        return _ok("I18", actual, {"max_pct_used": 80.0},
                   f"/data {pct_used:.1f}% used")
    except Exception as exc:
        return _amber("I18", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


# ── Severity taxonomy (Brock 2026-08-20 autonomous work order, Phase A) ────
#
# SAFETY checks — auto-actions may HALT trading. Trip these ONLY when a real
# money/state divergence exists that could cause the fund to trade against
# wrong information (BMG thinks it owns X, broker has Y; cash exhausted;
# exposure cap breached; sim fill detected; disk full).
#
# REPORTING checks — never halt. Attribution accuracy, per-bot identity,
# unattributed remainder, mark drift below broker's own tolerance. Red on
# these is a signal to investigate/rescale, not to stop trading. The fund
# has halted 3× in 11 days on reporting-tier reds; that's the class this
# taxonomy prevents.
#
# Semantics: `_maybe_auto_action` returns immediately without side effects
# when the check's severity is 'reporting'. Reds still surface in /invariants
# board + status streams — they just don't fire pauses.
SEVERITY_CATEGORY: dict[str, str] = {
    # Safety — auto-actions may halt scans / pause bots / write acks
    "I1": "safety",   # position row-count drift (BMG vs broker share ownership)
    "I2": "safety",   # RE-SCOPED to fund-level: canonical fund_pv vs Alpaca portfolio_value
    "I3": "safety",   # sim fills detected — auto-pauses offending allocs
    "I7": "safety",   # fleet max_loss exposure cap
    "I9": "safety",   # broker↔bmg ownership mismatch
    "I14": "safety",  # unremediated breach-on-adopt
    "I17": "safety",  # cash < 0 (deployed beyond cash)
    "I18": "safety",  # /data volume > 80/90% (auto-prune trigger)
    "I22": "safety",  # cron heartbeat / silent-stop job detection
    "I25": "safety",  # Alpaca fill has no matching BMG row (broker-truth gap)
    "I27": "safety",  # PV endpoint disagreement > $1 (canonical vs consumers)
    "I30": "safety",  # per-symbol UPL gap (resume gate — Brock's designated)
    # Reporting — never halt. Reds are diagnostic signals for humans/PM Claude.
    "I4": "reporting",   # closed-trade exit_reason hygiene
    "I5": "reporting",   # option mark freshness
    "I6": "reporting",   # PR-holdings mark freshness
    "I8": "reporting",   # sleeve arithmetic sanity
    "I10": "reporting",  # signals-without-trades funnel diagnosis
    "I13": "reporting",  # single-tenant migration state (config-level)
    "I15": "reporting",  # starting-capital rescale drift
    "I16": "reporting",  # unattributed dollars tracker (Brock accepts non-zero)
    "I19": "reporting",  # BROKER_FILL missing alpaca_order_id (provenance)
    "I20": "reporting",  # market-closed origin drift
    "I21": "reporting",  # origin ENUM validity
    "I23": "reporting",  # exact-zero P&L windows
    "I24": "reporting",  # bot-level identity drift (attribution)
    "I26": "reporting",  # sub-penny fill_price_cents=0 (data quality)
    "I28": "reporting",  # vault-freshness ping age
    "I29": "reporting",  # BROKER_FILL missing fill_price_micros
    "I31": "reporting",  # per-bot identity attribution drift
}


def is_safety_check(check_id: str) -> bool:
    """True if a red on this check may trigger a trading halt.

    Unknown checks default to 'reporting' — new checks are opt-in to
    auto-actions, not opt-out. Prevents accidental halts when someone adds
    an experimental check without categorizing it.
    """
    return SEVERITY_CATEGORY.get(check_id, "reporting") == "safety"


# ── Runner + persistence ────────────────────────────────────────────────────

CHECKS: dict[str, Callable] = {
    "I1": _check_i1_position_counts,
    "I2": _check_i2_unrealized_pl,
    "I3": _check_i3_sim_fills,
    "I4": _check_i4_closed_trade_hygiene,
    "I5": _check_i5_option_marks,
    "I6": _check_i6_position_mark_freshness,
    "I7": _check_i7_exposure_caps,
    "I8": _check_i8_sleeve_sanity,
    "I9": _check_i9_position_ownership,
    "I10": _check_i10_signal_funnel,
    "I13": _check_i13_single_tenant,
    "I14": _check_i14_breach_remediation,
    "I15": _check_i15_starting_capital_vs_funded,
    "I16": _check_i16_unattributed_tracker,
    "I17": _check_i17_cash_positive,
    "I18": _check_i18_data_volume_headroom,
    "I19": _check_i19_broker_fill_has_uuid,
    "I20": _check_i20_phantom_trades_while_market_closed,
    "I21": _check_i21_origin_not_null,
    "I22": _check_i22_cron_heartbeat,
    "I23": _check_i23_pnl_windows_exact_zero,
    "I24": _check_i24_bot_level_identities,
    "I25": _check_i25_alpaca_activity_diff,
    "I26": _check_i26_sub_penny_fill_zero,
    "I27": _check_i27_pv_endpoint_agreement,
    "I28": lambda db: _check_i28_vault_freshness(db),
    "I29": _check_i29_fill_price_micros_populated,
    "I30": _check_i30_per_symbol_upl_gap,
    "I31": _check_i31_per_bot_identity,
}


def _check_i28_vault_freshness(db) -> Result:
    """Brock's Mac vault must have been synced within the last 72h.

    2026-08-18 revision: this check was originally looking at
    /data/audits/*.md mtime, which lied — the container auto-writes those
    daily so the age is always fresh regardless of whether Brock's laptop
    ever pulled them. The real question is "did the Mac-side sync actually
    run?" bmg_vault_sync.sh POSTs /admin/vault-sync-ping after each
    successful pull; that timestamp is what this check reads.

    72h threshold accommodates a weekend + one day of "laptop off." Longer
    and the vault stops being useful to a fresh Claude session.

    NULL (never pinged) → AMBER, not RED, to avoid false alarms on fresh
    installs where the cron hasn't been wired yet.
    """
    try:
        from app.services.vault_writer import (
            last_vault_sync_ping_age_hours,
            read_vault_sync_ping,
        )
        age_h = last_vault_sync_ping_age_hours()
        ping = read_vault_sync_ping() or {}
        if age_h is None:
            return _amber("I28", ping, {"max_hours": 72.0},
                          None,
                          "no vault sync ping recorded — bmg_vault_sync.sh has never run "
                          "(install the cron on Brock's Mac)")
        actual = {
            "last_ping_age_hours": round(age_h, 2),
            "last_ping_iso": ping.get("last_ping_iso"),
            "git_commit_sha": ping.get("git_commit_sha"),
            "git_pushed": ping.get("git_pushed"),
        }
        if age_h <= 72.0:
            return _ok("I28", actual, {"max_hours": 72.0},
                       f"vault synced {age_h:.1f}h ago (≤72h)")
        return _red("I28", actual, {"max_hours": 72.0}, float(age_h),
                    f"vault hasn't been synced in {age_h:.1f}h — bmg_vault_sync.sh cron isn't firing on Brock's Mac")
    except Exception as exc:
        return _amber("I28", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


_LOW_POWER_CHECKS = ("I1", "I2", "I17", "I24", "I25")  # money-critical only


def run_all_invariants(db, low_power_override: Optional[bool] = None) -> dict[str, Any]:
    """Execute every check, persist results, return summary.

    RAILWAY_LOW_POWER (Brock cost-cut 2026-08-12): when env var is 'true'
    AND scans are globally paused, only run the 5 money-critical checks
    (I1, I2, I17, I24, I25) each cycle. Full board runs on the 05:30 UTC
    nightly pass (bypassed via low_power_override=False).
    """
    low_power = False
    if low_power_override is not None:
        low_power = bool(low_power_override)
    elif os.getenv("RAILWAY_LOW_POWER", "true").strip().lower() == "true":
        try:
            from app.services.scans_gate import read_state as _rs
            if _rs().get("global") is False:
                low_power = True
        except Exception:
            pass
    checks_to_run = (
        {k: v for k, v in CHECKS.items() if k in _LOW_POWER_CHECKS}
        if low_power else CHECKS
    )
    if low_power:
        logger.warning("[invariant] LOW_POWER mode — running %d/%d checks (money-critical only)",
                       len(checks_to_run), len(CHECKS))
    results: list[Result] = []
    for cid, fn in checks_to_run.items():
        try:
            r = fn(db)
        except Exception as exc:
            r = _amber(cid, None, None, None, f"runner_exception:{type(exc).__name__}:{exc}")
        results.append(r)
        # Auto-actions
        try:
            _maybe_auto_action(r, db)
        except Exception as _aa_exc:
            logger.warning("[invariant] auto-action for %s failed: %s", r.check_id, _aa_exc)

    _persist_snapshot(results)

    red = [r.to_dict() for r in results if r.level == "red"]
    amber = [r.to_dict() for r in results if r.level == "amber"]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "green": sum(1 for r in results if r.level == "green"),
            "amber": len(amber),
            "red": len(red),
        },
        "red": red,
        "amber": amber,
        "all": [r.to_dict() for r in results],
    }


_SNAPSHOT_PATH_ENV = "INVARIANT_SNAPSHOT_PATH"


def _snapshot_path() -> str:
    return os.getenv(_SNAPSHOT_PATH_ENV, "/data/invariant_snapshot.json")


def _persist_snapshot(results: list[Result]) -> None:
    """Write latest results to a JSON file so the /api/admin/invariants
    endpoint can serve them without recomputing on every request."""
    try:
        path = _snapshot_path()
        payload = {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "results": [r.to_dict() for r in results],
        }
        # Best-effort: create parent dir + write atomically via tmp rename.
        import tempfile
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".invariant_", dir=d)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
        except Exception:
            try: os.unlink(tmp)
            except Exception: pass
            raise
    except Exception as exc:
        logger.warning("[invariant] snapshot persist failed: %s", exc)


def read_latest_snapshot() -> dict[str, Any]:
    try:
        with open(_snapshot_path()) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "no_snapshot_yet"}
    except Exception as exc:
        return {"error": f"snapshot_read_failed: {exc}"}


# ── Auto-actions (Layer 3.2) ────────────────────────────────────────────────

def _maybe_auto_action(r: Result, db) -> None:
    """Take action on RED invariants per spec.

      I7 breach → pause the offending bot (or fund-wide halt for gross cap)
      I9 orphan → quarantine + alert (handled by orphan-adopter separately,
                  but we also log LOUD here)

    Amber/green = no-op. Auto-actions must be idempotent — the check
    might fire every 15 min while a condition persists.

    2026-08-20 (Brock work order Phase A): gated on SEVERITY_CATEGORY.
    Reporting-tier checks (I15, I24, I31, I16, etc.) surface reds without
    triggering halts. Only safety-tier checks route through the halting
    auto-actions below. The fund had halted 3× in 11 days on reporting-tier
    reds before this gate landed.
    """
    if r.level != "red":
        return
    if not is_safety_check(r.check_id):
        logger.info(
            "[invariant:AUTO-ACTION] %s red but severity=reporting — no auto-action",
            r.check_id,
        )
        return

    if r.check_id == "I7":
        # For fleet-wide breach we log LOUD and rely on the pre-trade gate
        # (Layer 4) to actually reject new trades. We don't unilaterally
        # close positions here.
        logger.error("[invariant:AUTO-ACTION] I7 red — %s", r.detail)
        try:
            from app.services.discord import send_ops_alert
            send_ops_alert(
                title="[invariant] I7 exposure cap breached",
                message=r.detail,
                severity="critical",
                source="invariant_engine",
            )
        except Exception:
            pass

    if r.check_id == "I9":
        # I9 orphan means Alpaca has real positions BMG doesn't track.
        # Log for now; the orphan_adopter (when idempotent) can be triggered
        # separately via /api/admin/orphan-adopter/run.
        logger.error("[invariant:AUTO-ACTION] I9 red — %s", r.detail)

    if r.check_id == "I3":
        # Sim fill detected. Set paused_reason on the offending allocation(s)
        # so those bots stop scanning until a human clears the pause. Uses the
        # ledger #30 semantics: any non-empty paused_reason is a durable state.
        # Idempotent: sets paused_reason only if currently NULL.
        try:
            by_alloc = (r.actual or {}).get("by_alloc") or {}
            if not by_alloc:
                return
            from app.db.models.bots import BotAllocation
            paused_count = 0
            for aid_str, count in by_alloc.items():
                try:
                    aid = int(aid_str)
                except Exception:
                    continue
                alloc = db.query(BotAllocation).filter(BotAllocation.id == aid).first()
                if not alloc:
                    continue
                if alloc.paused_reason:
                    continue
                alloc.paused_reason = f"auto_pause_i3_sim_fill:{count}_rows_in_24h"
                paused_count += 1
            if paused_count:
                db.commit()
                logger.error(
                    "[invariant:AUTO-ACTION] I3 red — paused %d alloc(s) with paused_reason=auto_pause_i3_sim_fill",
                    paused_count,
                )
                # 2026-08-10 loop-failure fix: critical alert + ack instead of send_ops_alert
                # (which was silently muted by DISCORD_OPS_ALERTS_ENABLED=false).
                try:
                    from app.services.critical_alert import send_critical
                    from app.services.human_ack import create as ack_create
                    from datetime import datetime as _dt, timezone as _tz
                    _title = f"I3 auto-pause: {paused_count} alloc(s) with sim fills"
                    _body = r.detail + "\nAllocs paused via paused_reason. Investigate + clear paused_reason to resume individual bots."
                    send_critical(
                        category="SIM_FILL_DETECTED",
                        title=_title,
                        message=_body,
                        source="invariant_engine.I3_auto_action",
                    )
                    _ref = f"I3:{_dt.now(_tz.utc).strftime('%Y-%m-%d')}"
                    ack_create(db, category="SIM_FILL_DETECTED", ref_key=_ref,
                               title=_title, body=_body,
                               created_by="invariant_engine.I3_auto_action")
                except Exception as _alert_exc:
                    logger.warning("[invariant:AUTO-ACTION] I3 alert/ack failed: %s", _alert_exc)
        except Exception as _i3_exc:
            logger.warning("[invariant:AUTO-ACTION] I3 auto-pause failed: %s", _i3_exc)

    if r.check_id == "I2":
        # P&L drift auto-action: only trigger at >$500.
        # Ack + alert ALWAYS fire when drift > $500 (idempotent via UNIQUE
        # category+ref_key), even if scans already paused. Reason: prior code
        # skipped ack creation when already-paused, leaving the resume gate
        # unenforceable for pre-existing pauses.
        try:
            drift = float(r.delta or 0)
            if drift > 500:
                from app.services.scans_gate import set_paused, read_state
                cur = read_state()
                already_paused = cur.get("global") is False
                if not already_paused:
                    set_paused(
                        sleeve="all",
                        paused=True,
                        muted_by="invariant_engine.I2_auto_action",
                        muted_reason=f"auto_pause_i2_drift_${drift:,.2f}",
                    )
                    logger.error(
                        "[invariant:AUTO-ACTION] I2 red drift=$%.2f > $500 — paused all scans",
                        drift,
                    )
                # Ack + alert regardless (idempotent). Ref_key is date-scoped
                # so a new ack lands per day; same-day re-fire is deduped.
                try:
                    from app.services.critical_alert import send_critical
                    from app.services.human_ack import create as ack_create
                    from datetime import datetime as _dt, timezone as _tz
                    _title = f"I2 auto-pause: P&L drift ${drift:,.2f} > $500"
                    _body = (r.detail + "\n\nAll scans paused. Fund is halted. "
                             "Diagnose drift, then POST /admin/ack?ack_id=<id>&by=<user> "
                             "before POST /admin/scans/resume?sleeve=all.")
                    if not already_paused:
                        send_critical(
                            category="AUTO_PAUSE",
                            title=_title,
                            message=_body,
                            source="invariant_engine.I2_auto_action",
                        )
                    _ref = f"I2:{_dt.now(_tz.utc).strftime('%Y-%m-%d')}"
                    ack_create(db, category="AUTO_PAUSE", ref_key=_ref,
                               title=_title, body=_body,
                               created_by="invariant_engine.I2_auto_action")
                except Exception as _alert_exc:
                    logger.warning("[invariant:AUTO-ACTION] I2 alert/ack failed: %s", _alert_exc)
        except Exception as _i2_exc:
            logger.warning("[invariant:AUTO-ACTION] I2 auto-pause failed: %s", _i2_exc)

    if r.check_id == "I18":
        # /data volume exhaustion. At >90% we auto-prune backups to keep=1.
        # Between 80-90% we just alert — Brock decides whether to VACUUM
        # or ship an off-volume backup. Idempotent: prune with keep=1 is a
        # no-op when only 1 backup exists.
        pct = None
        try:
            pct = float((r.actual or {}).get("volume_pct_used") or 0)
        except Exception:
            pass
        logger.error("[invariant:AUTO-ACTION] I18 red — %s", r.detail)
        # Critical alert + ack (loop-failure fix — was send_ops_alert, muted).
        try:
            from app.services.critical_alert import send_critical
            from app.services.human_ack import create as ack_create
            from datetime import datetime as _dt, timezone as _tz
            _title = f"I18 disk headroom breached ({pct:.1f}%)" if pct else "I18 disk headroom breached"
            _body = r.detail + "\n\nAuto-prune runs above 90%. Investigate root cause of growth."
            send_critical(category="DISK_HIGH", title=_title, message=_body,
                          source="invariant_engine.I18_auto_action")
            _ref = f"I18:{_dt.now(_tz.utc).strftime('%Y-%m-%d')}"
            ack_create(db, category="DISK_HIGH", ref_key=_ref,
                       title=_title, body=_body,
                       created_by="invariant_engine.I18_auto_action")
        except Exception as _alert_exc:
            logger.warning("[invariant:AUTO-ACTION] I18 alert/ack failed: %s", _alert_exc)
        if pct is not None and pct > 90:
            try:
                import os as _os
                root = "/data"
                if _os.path.isdir(root):
                    entries = []
                    for name in _os.listdir(root):
                        if not name.endswith(".bak"):
                            continue
                        p = _os.path.join(root, name)
                        if not _os.path.isfile(p):
                            continue
                        try:
                            entries.append((_os.path.getmtime(p), p, _os.path.getsize(p), name))
                        except Exception:
                            continue
                    entries.sort(key=lambda x: -x[0])
                    freed = 0
                    for mtime, path, size, name in entries[1:]:  # keep newest
                        try:
                            _os.unlink(path)
                            freed += size
                            logger.error("[invariant:AUTO-ACTION] I18 auto-prune deleted %s (%d bytes)", name, size)
                        except Exception as _e:
                            logger.warning("[invariant:AUTO-ACTION] I18 auto-prune failed on %s: %s", name, _e)
                    if freed:
                        logger.error("[invariant:AUTO-ACTION] I18 auto-prune freed %.1f MB", freed / (1024*1024))
            except Exception as _px:
                logger.warning("[invariant:AUTO-ACTION] I18 auto-prune raised: %s", _px)


# ── Scheduler ───────────────────────────────────────────────────────────────

def setup_invariant_engine(scheduler) -> None:
    """15-min cron during market hours + 05:30 UTC nightly deep pass."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[invariant] apscheduler unavailable: %s", exc)
        return
    from app.db.session import SessionLocal

    def _cycle() -> None:
        enabled = os.getenv("INVARIANT_ENGINE_ENABLED", "true").strip().lower() == "true"
        if not enabled:
            return
        db = SessionLocal()
        try:
            res = run_all_invariants(db)
            # Refresh pause reason from latest unacked AUTO_PAUSE ack (Brock 2026-08-11)
            try:
                from app.services.scans_gate import refresh_pause_reason_from_latest_ack
                refresh_pause_reason_from_latest_ack()
            except Exception as _ref_exc:
                logger.warning("[invariant] pause-reason refresh failed: %s", _ref_exc)
            s = res["summary"]
            if s["red"]:
                logger.error(
                    "[invariant] cycle — RED=%d AMBER=%d GREEN=%d",
                    s["red"], s["amber"], s["green"],
                )
                for r in res["red"]:
                    logger.error("[invariant:RED] %s — %s", r["check_id"], r["detail"])
            elif s["amber"]:
                logger.warning("[invariant] cycle — AMBER=%d GREEN=%d", s["amber"], s["green"])
        except Exception as exc:
            logger.error("[invariant] cycle raised: %s", exc, exc_info=True)
        finally:
            db.close()

    # Every 15 min market hours (13-19 UTC = 9-3 ET)
    scheduler.add_job(
        _cycle,
        CronTrigger(day_of_week="mon-fri", hour="13-19", minute="*/15", timezone="UTC"),
        id="invariant_engine_intraday",
        replace_existing=True,
        max_instances=1,
    )
    # Nightly deep pass — force full board (bypass low_power)
    def _nightly_full():
        enabled = os.getenv("INVARIANT_ENGINE_ENABLED", "true").strip().lower() == "true"
        if not enabled:
            return
        db = SessionLocal()
        try:
            run_all_invariants(db, low_power_override=False)  # full board
        except Exception as exc:
            logger.error("[invariant] nightly full pass raised: %s", exc, exc_info=True)
        finally:
            db.close()
    scheduler.add_job(
        _nightly_full,
        CronTrigger(hour=5, minute=30, timezone="UTC"),
        id="invariant_engine_nightly",
        replace_existing=True,
        max_instances=1,
    )
    # Cost cut 2026-08-12 (Brock): 24/7 30-min cron REMOVED. Off-hours runs
    # were 48/day of pure compute waste while halted. Kept: 15-min market
    # hours + 05:30 UTC nightly. During halts the snapshot goes stale off-
    # hours (fine — no scans are running to consume it).
    # Prior job id 'invariant_engine_24_7' will be dropped from the scheduler
    # by APScheduler on next start (no explicit remove needed since we don't
    # register it).

    # Brock item 7 (2026-08-09): weekly prune on Sunday 09:00 UTC (04:00 CT).
    # Deletes /data/*.bak files keeping only the most recent. Prevents the
    # 2026-08-09 P0 (backups accumulating to 3.85 GB / 85% of volume) from
    # recurring regardless of ops discipline. Belt-and-suspenders for I18.
    def _weekly_prune() -> None:
        try:
            import os as _os
            root = "/data"
            if not _os.path.isdir(root):
                return
            entries = []
            for name in _os.listdir(root):
                if not name.endswith(".bak"):
                    continue
                p = _os.path.join(root, name)
                if not _os.path.isfile(p):
                    continue
                try:
                    entries.append((_os.path.getmtime(p), p, _os.path.getsize(p), name))
                except Exception:
                    continue
            entries.sort(key=lambda x: -x[0])
            freed = 0
            for _mt, path, size, name in entries[1:]:  # keep newest
                try:
                    _os.unlink(path)
                    freed += size
                    logger.warning("[weekly-prune] deleted %s (%d bytes)", name, size)
                except Exception as _e:
                    logger.warning("[weekly-prune] failed on %s: %s", name, _e)
            # Also sweep orphan .bak-journal files (parent .bak gone).
            existing_bak_names = {name for _mt, _p, _sz, name in entries[:1]}
            for name in _os.listdir(root):
                if not name.endswith(".bak-journal"):
                    continue
                parent = name[:-len("-journal")]
                if parent in existing_bak_names:
                    continue
                p = _os.path.join(root, name)
                try:
                    sz = _os.path.getsize(p)
                    _os.unlink(p)
                    freed += sz
                    logger.warning("[weekly-prune] deleted orphan journal %s", name)
                except Exception as _je:
                    logger.warning("[weekly-prune] journal cleanup failed on %s: %s", name, _je)
            logger.warning("[weekly-prune] cycle complete — freed %.1f MB", freed / (1024*1024))
        except Exception as exc:
            logger.error("[weekly-prune] job raised: %s", exc, exc_info=True)

    scheduler.add_job(
        _weekly_prune,
        CronTrigger(day_of_week="sun", hour=9, minute=0, timezone="UTC"),
        id="weekly_prune_backups",
        replace_existing=True,
        max_instances=1,
    )

    logger.warning("[invariant] scheduler registered — 15 min intraday + 05:30 UTC nightly + 30 min 24/7 + weekly prune Sun 09:00 UTC")
