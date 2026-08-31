"""MomentumBot v1 — monthly rebalance instruction generator.

Wraps the scan job (job_momentum_scan.py) to produce ACTIONABLE rebalance
orders. Given current holdings (empty on first month, existing on subsequent
months), computes:
  - SELLS: current holdings that dropped out of top-20
  - BUYS: new top-20 entries not currently held
  - REBALANCE: existing holdings that stayed in top-20 (may need size adjust)

Writes a Markdown "rebalance instruction" file to Obsidian that Brock can
follow to manually execute orders on Alpaca.

Per CLAUDE.md §L1: this is a LOCAL job. No Railway automation. Brock manually
submits orders once per month based on this spec. Simple, cheap, correct.

Config (edit at top of file for first run):
  SLEEVE_TARGET_USD = 2500.0
  CURRENT_HOLDINGS = {}  # {ticker: {qty, entry_price}} — empty on first run
  TOP_N = 20

Ref: vault/research/2026-08-31-verify-blitz-huij-martens-residual-momentum.md
     vault/research/2026-08-31-verify-frazzini-israel-moskowitz-trading-costs.md
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _obsidian import write_job_output  # noqa: E402
from _ff_data import get_ff3_monthly  # noqa: E402
from job_signal_race_backtest import UNIVERSE  # noqa: E402
# Import residual momentum computation from the scan job
from job_momentum_scan import (  # noqa: E402
    _yahoo_monthly_closes, _monthly_returns, residual_momentum_score,
)


# ─────────────────────────────────────────────────────────────────
# Config — edit these before each monthly run
# ─────────────────────────────────────────────────────────────────

SLEEVE_TARGET_USD = 2500.0
TOP_N = 20
CURRENT_HOLDINGS: Dict[str, Dict[str, float]] = {
    # Populated for months 2+. Example:
    # "INTC": {"qty": 2.08, "entry_price": 60.10},
    # "AMD":  {"qty": 0.85, "entry_price": 146.75},
}


# ─────────────────────────────────────────────────────────────────
# Live prices for rebalance sizing
# ─────────────────────────────────────────────────────────────────

def _yahoo_last_price(symbol: str) -> Optional[float]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG mom_rebal)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
        return d["chart"]["result"][0]["meta"].get("regularMarketPrice")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# Rebalance logic
# ─────────────────────────────────────────────────────────────────

def compute_rebalance(target_tickers: List[str], current: Dict[str, Dict[str, float]],
                      sleeve_target_usd: float) -> Dict:
    """Compute the delta actions to move from current → target holdings."""
    target_set = set(target_tickers)
    current_set = set(current.keys())

    sells = current_set - target_set  # in current but not target → SELL ALL
    buys = target_set - current_set    # in target but not current → BUY NEW
    holds = current_set & target_set   # stay in top-20 → possibly rebalance size

    per_position_target = sleeve_target_usd / len(target_tickers)

    # Get live prices for everything we need
    all_needed = list(target_set | current_set)
    live_prices = {}
    print(f"Fetching live prices for {len(all_needed)} tickers...")
    for t in all_needed:
        live_prices[t] = _yahoo_last_price(t)
        time.sleep(0.05)

    # Compute sell orders
    sell_orders = []
    total_sell_proceeds = 0.0
    for t in sells:
        qty = current[t]["qty"]
        entry = current[t]["entry_price"]
        cur_price = live_prices.get(t) or 0.0
        proceeds = qty * cur_price
        pnl_pct = ((cur_price / entry) - 1) * 100 if entry else 0
        sell_orders.append({
            "ticker": t,
            "action": "SELL",
            "qty": qty,
            "entry_price": entry,
            "current_price": cur_price,
            "estimated_proceeds_usd": proceeds,
            "unrealized_pnl_pct": pnl_pct,
            "reason": "dropped_out_of_top_20",
        })
        total_sell_proceeds += proceeds

    # Compute buy orders (equal-weight to target per-position)
    buy_orders = []
    total_buy_cost = 0.0
    for t in sorted(buys):
        cur_price = live_prices.get(t)
        if not cur_price or cur_price <= 0:
            buy_orders.append({"ticker": t, "action": "BUY", "error": "no_price"})
            continue
        # Fractional shares
        qty = per_position_target / cur_price
        cost = qty * cur_price
        buy_orders.append({
            "ticker": t,
            "action": "BUY",
            "qty": round(qty, 4),
            "current_price": cur_price,
            "estimated_cost_usd": round(cost, 2),
            "reason": "entered_top_20",
        })
        total_buy_cost += cost

    # Rebalance holds (size adjust if drift > 20% from target)
    rebalance_orders = []
    for t in holds:
        cur_price = live_prices.get(t) or 0.0
        current_qty = current[t]["qty"]
        current_value = current_qty * cur_price
        target_value = per_position_target
        drift_pct = ((current_value - target_value) / target_value) * 100 if target_value else 0
        if abs(drift_pct) > 20:
            # Rebalance needed
            delta_value = target_value - current_value
            delta_qty = delta_value / cur_price if cur_price > 0 else 0
            action = "BUY_MORE" if delta_qty > 0 else "SELL_SOME"
            rebalance_orders.append({
                "ticker": t,
                "action": action,
                "delta_qty": round(delta_qty, 4),
                "current_value": current_value,
                "target_value": target_value,
                "drift_pct": drift_pct,
            })

    return {
        "sells": sell_orders,
        "buys": buy_orders,
        "rebalances": rebalance_orders,
        "holds_no_action": [t for t in holds if not any(r["ticker"] == t for r in rebalance_orders)],
        "target_tickers": sorted(target_set),
        "current_tickers": sorted(current_set),
        "total_sell_proceeds": round(total_sell_proceeds, 2),
        "total_buy_cost": round(total_buy_cost, 2),
        "net_cash_delta": round(total_sell_proceeds - total_buy_cost, 2),
        "per_position_target_usd": round(per_position_target, 2),
    }


# ─────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────

def build_report(scores: List[Dict], rebalance: Dict, sleeve_size: float) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    is_first_month = len(rebalance["current_tickers"]) == 0

    lines = [
        f"# MomentumBot Rebalance — {today}",
        "",
        f"*Monthly rebalance instructions for MomentumBot sleeve (${sleeve_size:.0f}). "
        f"Execute manually on Alpaca once per month, 1st business day 11:00 ET.*",
        "",
        "## Summary",
        "",
        f"- **Sleeve size:** ${sleeve_size:.0f}",
        f"- **Target holdings:** {len(rebalance['target_tickers'])} stocks equal-weight (~${rebalance['per_position_target_usd']:.2f}/position)",
        f"- **Current holdings:** {len(rebalance['current_tickers'])} stocks",
    ]
    if is_first_month:
        lines.append("- **First-month bootstrap:** all target positions are new buys")
    else:
        lines.extend([
            f"- **SELLS:** {len(rebalance['sells'])} positions (dropped from top-20)",
            f"- **BUYS:** {len(rebalance['buys'])} new positions (entered top-20)",
            f"- **HOLDS:** {len(rebalance['holds_no_action']) + len(rebalance['rebalances'])} still in top-20 "
            f"({len(rebalance['rebalances'])} need size rebalance)",
            f"- **Net cash delta:** ${rebalance['net_cash_delta']:+.2f}",
        ])
    lines.append("")

    # BUY orders
    if rebalance["buys"]:
        lines.extend([
            "## 🟢 BUY ORDERS — execute at market open",
            "",
            "| Ticker | Qty | Price | Cost | Rank | Res Mom Z |",
            "|---|---:|---:|---:|:---:|---:|",
        ])
        score_lookup = {s["ticker"]: s for s in scores}
        for b in rebalance["buys"]:
            if "error" in b:
                lines.append(f"| **{b['ticker']}** | ERROR: {b['error']} | | | | |")
                continue
            t = b["ticker"]
            s = score_lookup.get(t, {})
            rank = "?"
            z = s.get("residual_momentum_z", "?")
            for i, sc in enumerate(scores, 1):
                if sc["ticker"] == t:
                    rank = i
                    break
            lines.append(
                f"| **{t}** | {b['qty']} | ${b['current_price']:.2f} "
                f"| ${b['estimated_cost_usd']:.2f} | {rank} | {z:+.2f} |" if isinstance(z, float) else
                f"| **{t}** | {b['qty']} | ${b['current_price']:.2f} | ${b['estimated_cost_usd']:.2f} | {rank} | {z} |"
            )
        lines.extend(["", f"**Total buy cost:** ${rebalance['total_buy_cost']:.2f}", ""])

    # SELL orders
    if rebalance["sells"]:
        lines.extend([
            "## 🔴 SELL ORDERS — execute at market open",
            "",
            "| Ticker | Qty | Entry | Current | P&L | Proceeds |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for s in rebalance["sells"]:
            lines.append(
                f"| **{s['ticker']}** | {s['qty']} | ${s['entry_price']:.2f} "
                f"| ${s['current_price']:.2f} | {s['unrealized_pnl_pct']:+.2f}% "
                f"| ${s['estimated_proceeds_usd']:.2f} |"
            )
        lines.extend(["", f"**Total sell proceeds:** ${rebalance['total_sell_proceeds']:.2f}", ""])

    # REBALANCE (holds needing size adjust)
    if rebalance["rebalances"]:
        lines.extend([
            "## 🔄 REBALANCE (size adjust) — drift > 20%",
            "",
            "| Ticker | Action | Delta Qty | Current $ | Target $ | Drift |",
            "|---|:---:|---:|---:|---:|---:|",
        ])
        for r in rebalance["rebalances"]:
            lines.append(
                f"| **{r['ticker']}** | {r['action']} | {r['delta_qty']:+.4f} "
                f"| ${r['current_value']:.2f} | ${r['target_value']:.2f} | {r['drift_pct']:+.1f}% |"
            )
        lines.append("")

    # HOLDS
    if rebalance["holds_no_action"]:
        lines.extend([
            f"## 🟡 HOLDS — no action ({len(rebalance['holds_no_action'])} positions)",
            "",
            f"{', '.join(rebalance['holds_no_action'])}",
            "",
        ])

    # Execution checklist
    lines.extend([
        "## 📋 Execution Checklist",
        "",
        "1. **Pre-open (before 9:30 ET):**",
        "   - [ ] Confirm SPY is above 200-SMA (regime green light)",
        "   - [ ] Confirm VIX is below 25 (not in fear regime)",
        "   - [ ] Confirm Alpaca account has sufficient buying power",
        "",
        "2. **At market open (9:30-10:00 ET) — SELLS first:**",
        "   - [ ] Submit all SELL orders (market or limit at bid)",
        "   - [ ] Wait for confirmations",
        "   - [ ] Verify cash from proceeds hits account",
        "",
        "3. **After sells fill (10:00-11:00 ET) — BUYS:**",
        "   - [ ] Submit all BUY orders (marketable limit)",
        "   - [ ] Split large orders into 2-3 child orders (FIM 2018 discipline)",
        "   - [ ] Verify each fill",
        "",
        "4. **After rebalance complete:**",
        "   - [ ] Update `CURRENT_HOLDINGS` dict in this script with new positions",
        "   - [ ] Commit updated script to git",
        "   - [ ] Discord post the day's action to `#momentum-log`",
        "",
        "## Regime overlay reminder (Faber/Daniel-Moskowitz)",
        "",
        "**If SPY drops BELOW its 200-SMA for 3+ consecutive days after this rebalance:**",
        "- PAUSE all new buys next month",
        "- Hold existing until natural exit (drop out of top-20)",
        "- Do NOT liquidate — momentum recovers as SPY re-crosses above 200-SMA",
        "",
        "## Refs",
        "",
        "- Signal: `vault/research/2026-08-31-verify-blitz-huij-martens-residual-momentum.md`",
        "- Execution: `vault/research/2026-08-31-verify-frazzini-israel-moskowitz-trading-costs.md`",
        "- Statistical gate: `vault/research/2026-08-31-verify-harvey-liu-zhu-factor-zoo.md`",
        "- Backtest results: `context/local-jobs/2026-08-31-momentum_backtest.md`",
        "",
        f"*Generated by scripts/local/job_momentum_rebalance.py — {today}.*",
    ])
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def run() -> str:
    print("=" * 60)
    print("MOMENTUMBOT MONTHLY REBALANCE")
    print("=" * 60)
    now = datetime.now(timezone.utc)

    # Load FF3 factors
    print("Loading FF3 factors...")
    ff3 = get_ff3_monthly()

    # Fetch universe data
    print(f"Fetching universe of {len(UNIVERSE)} tickers...")
    fetch_start = now - timedelta(days=400 * 3)
    start_ts = int(fetch_start.timestamp())
    end_ts = int(now.timestamp())
    all_closes = {}
    for i, t in enumerate(UNIVERSE, 1):
        if i % 25 == 0:
            print(f"  {i}/{len(UNIVERSE)}...")
        c = _yahoo_monthly_closes(t, start_ts, end_ts)
        if c and len(c) >= 24:
            all_closes[t] = c
        time.sleep(0.08)
    print(f"  ✓ {len(all_closes)} tickers with sufficient history")

    # Compute residual momentum
    print("Computing residual momentum...")
    scores = []
    for t, closes in all_closes.items():
        rets = _monthly_returns(closes)
        res = residual_momentum_score(rets, ff3, now)
        if res is not None:
            std_z, raw_sum, n = res
            scores.append({
                "ticker": t,
                "residual_momentum_z": std_z,
                "residual_sum_pct": raw_sum * 100,
                "n_months": n,
            })
    scores.sort(key=lambda x: -x["residual_momentum_z"])
    top_20_tickers = [s["ticker"] for s in scores[:TOP_N]]

    # Compute rebalance
    print(f"Computing rebalance vs {len(CURRENT_HOLDINGS)} current holdings...")
    rebalance = compute_rebalance(top_20_tickers, CURRENT_HOLDINGS, SLEEVE_TARGET_USD)

    # Report
    body = build_report(scores, rebalance, SLEEVE_TARGET_USD)
    path = write_job_output("momentum_rebalance", body)
    return (
        f"wrote {path}\n"
        f"target: {top_20_tickers[:5]}... | "
        f"buys: {len(rebalance['buys'])} | sells: {len(rebalance['sells'])} | "
        f"holds: {len(rebalance['holds_no_action'])}"
    )


if __name__ == "__main__":
    print(run())
