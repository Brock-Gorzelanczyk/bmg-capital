"""Backtest v3 — 50 stocks with new filters applied.

Runs the 50-stock backtest AND simulates what would have happened if we'd
applied the newly-shipped filters:
  1. Trend gate: price > 200-day SMA at ARM DATE (Priority 1)
  2. Sector momentum: sector ETF up over trailing 3 months at arm date (Priority 2)
  3. Diversity filter: max 3 per sector (approximates hunter's post-processing)

Reports 4 scenarios:
  - Baseline (all 50 held): current framework, no filters
  - Trend gate only: reject picks that fail 200-SMA test at arm date
  - Sector momentum only: reject picks in weak sectors at arm date
  - All filters (trend + sector + diversity cap): the new full stack

Compares each scenario's hit rate + avg excess vs sector.

Writes to Obsidian vault.
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _obsidian import write_job_output  # noqa: E402

# Import the 50-stock list from the main backtest job
from job_confluence_backtest import CANDIDATES, SECTOR_ETFS, COMPANY_NAMES  # noqa: E402


def _yahoo_bars(symbol: str, days_back: int = 400) -> Optional[dict]:
    """Fetch daily bars for the past days_back days."""
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        return {
            "timestamps": result[0].get("timestamp", []),
            "closes": result[0].get("indicators", {}).get("quote", [{}])[0].get("close", []),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None


def _price_at(bars: dict, target_iso: str) -> Optional[float]:
    """Get the close nearest to target date. For a date in the future or on
    non-trading days (weekends), returns the latest available close instead."""
    if not bars or not bars.get("closes"):
        return None
    target_ts = int(datetime.fromisoformat(target_iso).replace(tzinfo=timezone.utc).timestamp())
    # First try to find first close on or after target
    for ts, close in zip(bars["timestamps"], bars["closes"]):
        if ts >= target_ts and close is not None:
            return float(close)
    # Target is in future / non-trading day → return latest available close
    for close in reversed(bars["closes"]):
        if close is not None:
            return float(close)
    return None


def _sma_at(bars: dict, target_iso: str, window: int) -> Optional[float]:
    """Compute SMA(window) as of target_iso — the mean of the `window` closes
    ending on the last trading day <= target_iso."""
    if not bars or not bars.get("closes"):
        return None
    target_ts = int(datetime.fromisoformat(target_iso).replace(tzinfo=timezone.utc).timestamp())
    # Get all closes up to target date
    closes_before = [c for ts, c in zip(bars["timestamps"], bars["closes"])
                     if ts <= target_ts and c is not None]
    if len(closes_before) < window:
        return None
    return sum(closes_before[-window:]) / window


def _return_between(bars: dict, start_iso: str, end_iso: str) -> Optional[float]:
    """Return % between start_iso and end_iso."""
    start_p = _price_at(bars, start_iso)
    end_p = _price_at(bars, end_iso)
    if start_p is None or end_p is None:
        return None
    return (end_p - start_p) / start_p * 100


def run() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    earliest_arm = min(c[1] for c in CANDIDATES)

    print("Fetching all bars (stocks + sector ETFs)...")
    # Fetch all bars with enough history for 200-SMA
    all_bars = {}
    for c in CANDIDATES:
        symbol = c[0]
        all_bars[symbol] = _yahoo_bars(symbol, days_back=500)
    for etf in SECTOR_ETFS:
        all_bars[etf] = _yahoo_bars(etf, days_back=500)

    print("Computing per-candidate results + gate evaluations...")
    results = []
    for symbol, arm_date, source, thesis, sector_etf in CANDIDATES:
        bars = all_bars.get(symbol)
        sec_bars = all_bars.get(sector_etf)
        if not bars or not sec_bars:
            continue

        entry_price = _price_at(bars, arm_date)
        current_price = _price_at(bars, today)
        if entry_price is None or current_price is None:
            continue

        # Return metrics
        stock_return = (current_price - entry_price) / entry_price * 100
        sec_entry = _price_at(sec_bars, arm_date)
        sec_current = _price_at(sec_bars, today)
        if sec_entry is None or sec_current is None:
            continue
        sec_return = (sec_current - sec_entry) / sec_entry * 100
        excess_sec = stock_return - sec_return

        # Gate 1: was price above 200-SMA at ARM DATE?
        sma200_at_arm = _sma_at(bars, arm_date, 200)
        gate1_pass = (sma200_at_arm is not None) and (entry_price > sma200_at_arm)

        # Gate 2: sector 3-month return positive at arm date?
        three_mo_before_arm = (datetime.fromisoformat(arm_date).replace(tzinfo=timezone.utc)
                               - timedelta(days=90)).strftime("%Y-%m-%d")
        sec_3mo_return = _return_between(sec_bars, three_mo_before_arm, arm_date)
        gate2_pass = (sec_3mo_return is not None) and (sec_3mo_return > 0)

        results.append({
            "symbol": symbol,
            "company": COMPANY_NAMES.get(symbol, "?"),
            "sector_etf": sector_etf,
            "arm_date": arm_date,
            "source": source,
            "stock_return": stock_return,
            "sec_return": sec_return,
            "excess_sec": excess_sec,
            "sma200_at_arm": sma200_at_arm,
            "entry_price": entry_price,
            "gate1_pass": gate1_pass,
            "gate2_pass": gate2_pass,
            "sec_3mo_return": sec_3mo_return,
        })

    n_total = len(results)

    # ── Scenario analysis ────────────────────────────────────────────
    def compute_stats(subset):
        if not subset:
            return {"n": 0, "avg_excess": 0, "hit_rate": 0, "med_excess": 0}
        excesses = [r["excess_sec"] for r in subset]
        hits = sum(1 for e in excesses if e >= 3.0)
        return {
            "n": len(subset),
            "avg_excess": statistics.mean(excesses),
            "med_excess": statistics.median(excesses),
            "hit_rate": hits / len(subset),
        }

    baseline = compute_stats(results)

    trend_only = compute_stats([r for r in results if r["gate1_pass"]])
    sector_only = compute_stats([r for r in results if r["gate2_pass"]])
    both_gates = compute_stats([r for r in results if r["gate1_pass"] and r["gate2_pass"]])

    # Diversity filter: max 3 per sector, prioritize by (excess prior expectation? no —
    # we can't cheat with future data). Simulate a random-ish deterministic pick order:
    # sort by symbol alphabetical (equivalent to arbitrary selection order at arm time).
    sector_counts = defaultdict(int)
    diverse_subset = []
    # Also apply both gates for the "full stack" scenario
    for r in sorted(results, key=lambda x: x["symbol"]):
        if not (r["gate1_pass"] and r["gate2_pass"]):
            continue
        if sector_counts[r["sector_etf"]] >= 3:
            continue
        sector_counts[r["sector_etf"]] += 1
        diverse_subset.append(r)
    full_stack = compute_stats(diverse_subset)

    # ── Render ────────────────────────────────────────────────────────
    lines = [
        "## Filtered Backtest — Does the new filter stack actually help?",
        "",
        f"**Date:** {today}",
        f"**N candidates:** {n_total}",
        "",
        "Applied the newly-shipped filters to the 50-stock backtest to see if they",
        "actually would have helped past picks. Four scenarios:",
        "",
        "| Scenario | N kept | Avg Excess vs Sector | Hit Rate | Verdict |",
        "|---|---:|---:|---:|---|",
        f"| **Baseline (no filters)** | {baseline['n']} | {baseline['avg_excess']:+.2f}% | {baseline['hit_rate']:.0%} | (reference) |",
        f"| Trend gate only (price > 200-SMA at arm) | {trend_only['n']} | {trend_only['avg_excess']:+.2f}% | {trend_only['hit_rate']:.0%} | {'✅ improved' if trend_only['avg_excess'] > baseline['avg_excess'] else '❌ worse'} |",
        f"| Sector momentum only (sector 3-mo > 0) | {sector_only['n']} | {sector_only['avg_excess']:+.2f}% | {sector_only['hit_rate']:.0%} | {'✅ improved' if sector_only['avg_excess'] > baseline['avg_excess'] else '❌ worse'} |",
        f"| Both gates + diversity cap (full stack) | {full_stack['n']} | {full_stack['avg_excess']:+.2f}% | {full_stack['hit_rate']:.0%} | {'✅ improved' if full_stack['avg_excess'] > baseline['avg_excess'] else '❌ worse'} |",
        "",
        "### What each filter DID",
        "",
        f"- **Trend gate dropped:** {n_total - trend_only['n']} of {n_total} picks (were below 200-SMA at arm date)",
        f"- **Sector gate dropped:** {n_total - sector_only['n']} of {n_total} picks (sector was negative 3-mo)",
        f"- **Full stack kept:** {full_stack['n']} of {n_total} picks",
        "",
        "### Per-pick detail — which filters passed/failed each pick",
        "",
        "| Ticker | Company | Sec | Excess vs Sec | Gate1 | Gate2 | Source |",
        "|---|---|---|---:|:---:|:---:|---|",
    ]

    for r in sorted(results, key=lambda x: -x["excess_sec"]):
        g1 = "✅" if r["gate1_pass"] else "❌"
        g2 = "✅" if r["gate2_pass"] else "❌"
        src = {"CURRENT_PICK": "PICK", "FRAMEWORK_ELIGIBLE": "ELIG",
               "KNOWN_WINNER": "WIN", "KNOWN_LOSER": "LOSE"}.get(r["source"], r["source"])
        lines.append(
            f"| **{r['symbol']}** | {r['company'][:25]} | {r['sector_etf']} | "
            f"{r['excess_sec']:+.1f}% | {g1} | {g2} | {src} |"
        )

    lines.extend([
        "",
        "### The kept picks — what the filtered portfolio would have been",
        "",
        f"After applying trend + sector gates + diversity cap: **{full_stack['n']} picks** kept.",
        "",
    ])
    if diverse_subset:
        lines.append("| Ticker | Company | Sector | Excess vs Sec | Source |")
        lines.append("|---|---|---|---:|---|")
        for r in sorted(diverse_subset, key=lambda x: -x["excess_sec"]):
            src = {"CURRENT_PICK": "PICK", "FRAMEWORK_ELIGIBLE": "ELIG",
                   "KNOWN_WINNER": "WIN", "KNOWN_LOSER": "LOSE"}.get(r["source"], r["source"])
            lines.append(
                f"| **{r['symbol']}** | {r['company'][:30]} | {r['sector_etf']} | "
                f"**{r['excess_sec']:+.1f}%** | {src} |"
            )

    lines.extend([
        "",
        "### Interpretation",
        "",
        "**If the 'Full stack' scenario improved vs baseline:** the new filters (already",
        "shipped as advisory) actually would have helped. Consider promoting them from",
        "advisory to hard blocks.",
        "",
        "**If it hurt vs baseline:** the filters are catching noise not signal. Keep",
        "them as advisory logging, do NOT promote to blocks.",
        "",
        "**Sample size caveat:** N=50 is directional. This is one data point per pick,",
        "not a statistical proof. But it does confirm/refute the theoretical expectation",
        "from the backtest analysis (2026-08-30).",
        "",
        "Companion notes:",
        "- `research/2026-08-30-confluence-framework-backtest-analysis.md`",
        "- `research/2026-08-30-confluence-framework-teaching-note.md`",
        "- `scripts/local/job_confluence_backtest.py` (source of the candidate list)",
    ])

    body = "\n".join(lines)
    path = write_job_output("backtest_v3_filtered", body)
    return (f"wrote {path}\n"
            f"baseline: {baseline['avg_excess']:+.2f}% ({baseline['hit_rate']:.0%})\n"
            f"trend only: {trend_only['avg_excess']:+.2f}% ({trend_only['hit_rate']:.0%})\n"
            f"sector only: {sector_only['avg_excess']:+.2f}% ({sector_only['hit_rate']:.0%})\n"
            f"full stack: {full_stack['avg_excess']:+.2f}% ({full_stack['hit_rate']:.0%})")


if __name__ == "__main__":
    print(run())
