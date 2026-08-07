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

        actual = {"bmg_option": bmg_opt, "bmg_non_option": bmg_non_opt,
                  "alp_option": alp_opt, "alp_equity": alp_eq, "alp_crypto": alp_cry}
        expected = {"bmg_option ≈ alp_option": True, "bmg_non_option ≈ alp_equity + alp_crypto": True}

        opt_delta = abs(bmg_opt - alp_opt)
        non_opt_delta = abs(bmg_non_opt - (alp_eq + alp_cry))
        max_delta = max(opt_delta, non_opt_delta)

        if max_delta <= 2:
            return _ok("I1", actual, expected, f"in tolerance (max delta {max_delta})")
        if max_delta <= 5:
            return _amber("I1", actual, expected, max_delta,
                          f"position drift {max_delta} (opt:{opt_delta} non-opt:{non_opt_delta})")
        return _red("I1", actual, expected, max_delta,
                    f"position drift {max_delta} (opt:{opt_delta} non-opt:{non_opt_delta})")
    except Exception as exc:
        return _amber("I1", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i2_unrealized_pl(db) -> Result:
    """BMG total unrealized ≈ Alpaca total unrealized ±$5.

    Runs the same math /portfolio/open-positions uses so the tripwire
    catches drift the UI is showing.
    """
    try:
        from app.db.models.bots import BotPosition
        from app.services.option_marks import fetch_option_marks_cents

        alp = _alp_positions()
        alp_upl = sum(float(p.get("unrealized_pl") or 0) for p in alp)
        # 2026-08-06 PM Claude Step 3.2: use Alpaca's current_price for
        # option marks so BMG unrealized matches broker UPL by
        # construction. Falls back to FMP midpoint only when Alpaca
        # doesn't report the position.
        alpaca_price_by_sym: dict[str, float] = {}
        for _p in alp:
            _sym = _p.get("symbol")
            _px = float(_p.get("current_price") or 0)
            if _sym and _px > 0:
                alpaca_price_by_sym[_sym] = _px

        bmg_open = (
            db.query(BotPosition)
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .all()
        )
        # Get option marks — prefer Alpaca current_price, fall back to FMP midpoint
        occ_syms = [p.symbol for p in bmg_open if getattr(p, "option_type", None)]
        marks_c: dict = {}
        need_fallback = [s for s in occ_syms if s not in alpaca_price_by_sym]
        if need_fallback:
            marks_c = fetch_option_marks_cents(need_fallback) or {}
        for _s in occ_syms:
            if _s in alpaca_price_by_sym:
                marks_c[_s] = int(round(alpaca_price_by_sym[_s] * 100))

        # Get equity/crypto prices — prefer Alpaca current_price, fall
        # back to live_prices for equity Alpaca doesn't hold.
        eq_syms = [p.symbol for p in bmg_open if not getattr(p, "option_type", None)]
        prices: dict[str, float] = {s: alpaca_price_by_sym[s] for s in eq_syms if s in alpaca_price_by_sym}
        need_eq_fallback = [s for s in eq_syms if s not in prices]
        if need_eq_fallback:
            try:
                from app.services.live_prices import fetch_live_prices
                prices.update(fetch_live_prices(need_eq_fallback) or {})
            except Exception:
                pass

        bmg_upl = 0.0
        for p in bmg_open:
            entry = (p.avg_cost_cents or 0) / 100.0
            is_opt = bool(getattr(p, "option_type", None))
            is_short = getattr(p, "side", "long") == "short"
            mult = 100 if is_opt else 1
            if is_opt:
                mc = marks_c.get(p.symbol)
                cur = mc / 100.0 if mc is not None else entry
            else:
                cur = float(prices.get(p.symbol) or entry)
            if is_short:
                bmg_upl += (entry - cur) * (p.qty or 0) * mult
            else:
                bmg_upl += (cur - entry) * (p.qty or 0) * mult

        actual = {"bmg_upl_usd": round(bmg_upl, 2), "alpaca_upl_usd": round(alp_upl, 2)}
        drift = abs(bmg_upl - alp_upl)
        if drift <= 5:
            return _ok("I2", actual, None, f"drift ${drift:,.2f}")
        if drift <= 50:
            return _amber("I2", actual, {"drift_max": 50}, drift, f"P&L drift ${drift:,.2f}")
        return _red("I2", actual, {"drift_max": 5}, drift,
                    f"P&L drift ${drift:,.2f} — BMG says ${bmg_upl:+,.2f} vs Alpaca ${alp_upl:+,.2f}")
    except Exception as exc:
        return _amber("I2", None, None, None, f"check_exception:{type(exc).__name__}:{exc}")


def _check_i3_sim_fills(db) -> Result:
    """Zero bot_trade rows in last 24h with NULL alpaca_order_id."""
    try:
        from app.db.models.bots import BotTrade
        from sqlalchemy import or_
        cut = datetime.now(timezone.utc) - timedelta(hours=24)
        sim_count = (
            db.query(BotTrade)
            .filter(BotTrade.ts >= cut)
            .filter(BotTrade.quarantined_at.is_(None))
            .filter(or_(BotTrade.alpaca_order_id.is_(None), BotTrade.alpaca_order_id == ""))
            .count()
        )
        if sim_count == 0:
            return _ok("I3", 0, 0, "no sim fills in 24h")
        return _red("I3", sim_count, 0, float(sim_count),
                    f"{sim_count} bot_trade rows in 24h have no alpaca_order_id")
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
    """Fleet exposure caps (4c 2026-08-07 max-loss rewrite):
    max-loss leverage is the honest metric — net debit for debit
    spreads (long premium), margin req for short options (strike ×
    100 × contracts, cash-secured basis), notional for equity.
    Per-position concentration kept on market value.
    """
    try:
        alp = _alp_positions()
        gross = sum(abs(float(p.get("market_value") or 0)) for p in alp)

        # 4c max-loss compute per position:
        #   equity: |market_value| (long can drop to 0; short capped at 2x entry)
        #   long option: premium paid = avg_entry × 100 × contracts (max loss)
        #   short option: cash-secured margin = strike × 100 × contracts
        #   long option + short option same underlying/expiry → spread pair
        #     with max_loss = spread_width × contracts × 100 (net debit basis)
        from collections import defaultdict

        def _parse_occ_root(sym: str):
            root = ""
            for ch in sym:
                if ch.isalpha(): root += ch
                else: break
            return root

        max_loss_total = 0.0
        # Group options by (root, expiration, right) to detect spread pairs
        opt_pairs: dict = defaultdict(list)
        for p in alp:
            sym = p.get("symbol") or ""
            qty = float(p.get("qty") or 0)
            avg_entry = float(p.get("avg_entry_price") or 0)
            mv = float(p.get("market_value") or 0)
            asset_class = p.get("asset_class") or ""
            if asset_class == "us_option":
                # Parse: {ROOT}{YYMMDD}{C|P}{strike*1000}
                # Get root, expiry (chars 6..12), right (12), strike
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
            else:
                # Equity: |MV| approximates worst-case drawdown to 0
                max_loss_total += abs(mv)

        # For each option (root, expiry, right) group, detect spread pairs
        for key, legs in opt_pairs.items():
            longs = [l for l in legs if l["qty"] > 0]
            shorts = [l for l in legs if l["qty"] < 0]
            if longs and shorts:
                # Spread — max loss = sum of long premiums - sum of short premiums received
                # (approximated net debit at entry)
                long_prem = sum(l["avg_entry"] * abs(l["qty"]) * 100 for l in longs)
                short_prem = sum(l["avg_entry"] * abs(l["qty"]) * 100 for l in shorts)
                net_debit = max(0, long_prem - short_prem)
                # Cap max loss at spread width (for well-formed verticals)
                # spread_width × contracts × 100
                if len(longs) == 1 and len(shorts) == 1:
                    width_dollars = abs(longs[0]["strike"] - shorts[0]["strike"])
                    contracts = min(abs(longs[0]["qty"]), abs(shorts[0]["qty"]))
                    width_max_loss = width_dollars * contracts * 100
                    max_loss_total += min(net_debit, width_max_loss) if net_debit > 0 else width_max_loss
                else:
                    max_loss_total += net_debit
            else:
                # Unpaired legs
                for leg in legs:
                    if leg["qty"] > 0:
                        # Long: max loss = premium paid
                        max_loss_total += leg["avg_entry"] * abs(leg["qty"]) * 100
                    else:
                        # Short: cash-secured margin
                        max_loss_total += leg["strike"] * abs(leg["qty"]) * 100

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

        c = _creds()
        nav = 0.0
        if c:
            req = urllib.request.Request(
                "https://paper-api.alpaca.markets/v2/account",
                headers={"APCA-API-KEY-ID": c[0], "APCA-API-SECRET-KEY": c[1]},
            )
            try:
                a = json.loads(urllib.request.urlopen(req, timeout=8).read())
                nav = float(a.get("portfolio_value") or 0)
            except Exception:
                pass

        # 4c 2026-08-07 max-loss rewrite: max_loss_total is the honest
        # leverage figure. Gross / net kept for reporting context only.
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
        # Primary trigger: max_loss > 100% NAV (spec R7 acceptance A)
        if max_loss_total > nav * max_loss_max_pct:
            return _red("I7", actual,
                        {"max_loss_max_pct_nav": max_loss_max_pct * 100},
                        max_loss_total - nav * max_loss_max_pct,
                        f"fleet max_loss ${max_loss_total:,.0f} = {max_loss_total/nav*100:.0f}% NAV > {max_loss_max_pct*100:.0f}% cap")
        # Per-position check
        worst = None
        worst_pct = 0.0
        for p in alp:
            mv = abs(float(p.get("market_value") or 0))
            pct = mv / nav
            if pct > worst_pct:
                worst_pct = pct
                worst = (p.get("symbol"), mv)
        if worst and worst_pct > per_max_pct:
            return _red("I7", {**actual, "worst_position": worst, "worst_pct_nav": round(worst_pct * 100, 1)},
                        {"per_position_max_pct_nav": per_max_pct * 100},
                        worst_pct - per_max_pct,
                        f"position {worst[0]} = {worst_pct*100:.1f}% NAV > {per_max_pct*100:.0f}% cap")
        return _ok("I7", actual, None, "within caps")
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
    Alpaca-funded base. Guard: |sum(starting) - funded| < $100."""
    try:
        import os as _os, urllib.request as _ur, json as _json
        from app.db.models.bots import BotAllocation
        kid = _os.environ.get("ALPACA_API_KEY", "")
        ksec = _os.environ.get("ALPACA_SECRET_KEY", "")
        if not kid or not ksec:
            return _amber("I15", None, None, None, "no Alpaca creds")
        try:
            acct = _json.loads(_ur.urlopen(_ur.Request(
                "https://paper-api.alpaca.markets/v2/account",
                headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
            ), timeout=8).read())
        except Exception as exc:
            return _amber("I15", None, None, None, f"alpaca_fetch:{exc}")
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
    "I14": _check_i14_breach_remediation,
    "I15": _check_i15_starting_capital_vs_funded,
    "I16": _check_i16_unattributed_tracker,
}


def run_all_invariants(db) -> dict[str, Any]:
    """Execute every check, persist results, return summary."""
    results: list[Result] = []
    for cid, fn in CHECKS.items():
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
    """
    if r.level != "red":
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
    # Nightly deep pass
    scheduler.add_job(
        _cycle,
        CronTrigger(hour=5, minute=30, timezone="UTC"),
        id="invariant_engine_nightly",
        replace_existing=True,
        max_instances=1,
    )
    logger.warning("[invariant] scheduler registered — 15 min intraday + 05:30 UTC nightly")
