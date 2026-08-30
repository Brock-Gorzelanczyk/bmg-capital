"""Diagnose why the 12 current live picks are underperforming the
framework-eligible universe by ~12 percentage points.

Pulls each live pick's signal composition + arm date + performance vs sector
from Railway API. Compares:
- Which signals fired for winners (HOG) vs losers (VFC, ONON, PODD, etc)
- Signal COMBINATION concentration (are they all firing on the same 3?)
- Sector concentration
- Arm-date clustering

Output: markdown diagnostic report to Obsidian.
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))

from _bmg_api import get_client, BMGApiError  # noqa: E402
from _obsidian import write_job_output  # noqa: E402


def _yahoo_return_since(symbol: str, arm_date: str) -> float:
    """Approx return from arm_date to today via Yahoo. Returns pct or 0 if fail."""
    try:
        start_ts = int(datetime.fromisoformat(arm_date).replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.now(timezone.utc).timestamp())
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               f"?period1={start_ts}&period2={end_ts}&interval=1d")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return 0.0
        return (closes[-1] - closes[0]) / closes[0] * 100
    except Exception:
        return 0.0


def run() -> str:
    api = get_client()
    try:
        j = api.get("/api/admin/confluence/journal?include_closed=false&limit=100")
    except BMGApiError as e:
        return f"FAIL: {e}"

    picks = j.get("open_picks", [])
    if not picks:
        return "No open picks"

    # Enrich each pick with return-since-entry
    for p in picks:
        p["return_pct"] = _yahoo_return_since(p["ticker"], p["entry_date"])

    # Sort by return desc
    picks.sort(key=lambda x: -x.get("return_pct", 0))

    # ── Signal firing analysis ────────────────────────────────────────
    signal_names = ["insider_cluster", "short_surprise_dir",
                    "analyst_revisions_dir", "fundamental_momentum", "inst_13f_net_add"]

    def signals_fired(p):
        s = p.get("signals", {})
        fired = set()
        if s.get("insider_cluster"): fired.add("insider_cluster")
        if s.get("short_surprise_dir") not in (None, 0): fired.add("short_surprise_dir")
        if s.get("analyst_revisions_dir") not in (None, 0): fired.add("analyst_revisions_dir")
        if s.get("fundamental_momentum"): fired.add("fundamental_momentum")
        if s.get("inst_13f_net_add"): fired.add("inst_13f_net_add")
        return fired

    for p in picks:
        p["_fired"] = signals_fired(p)

    winners = [p for p in picks if p["return_pct"] >= 3]
    losers = [p for p in picks if p["return_pct"] < 3]

    # Aggregate: which signals fire more often in winners vs losers
    win_signal_counts = Counter()
    lose_signal_counts = Counter()
    for p in winners:
        for s in p["_fired"]:
            win_signal_counts[s] += 1
    for p in losers:
        for s in p["_fired"]:
            lose_signal_counts[s] += 1

    # Signal combination pattern
    combo_counter = Counter()
    for p in picks:
        combo = tuple(sorted(p["_fired"]))
        combo_counter[combo] += 1

    # Arm date clustering
    arm_dates = [p["entry_date"] for p in picks]

    # Sector concentration (from thesis text — best-effort)
    from collections import defaultdict
    sectors = defaultdict(list)
    SECTOR_HINTS = {
        "Real Estate": ["SPG", "AAT"],
        "Consumer Discretionary": ["APTV", "VFC", "ONON", "HOG"],
        "Financials": ["KMPR"],
        "Energy": ["MTDR"],
        "Healthcare": ["ELAN", "PODD"],
        "Industrials": ["REZI"],
        "Technology": ["TSM"],
    }
    for p in picks:
        for sec, tickers in SECTOR_HINTS.items():
            if p["ticker"] in tickers:
                sectors[sec].append(p["ticker"])

    # ── Render ────────────────────────────────────────────────────────
    lines = [
        "## Live Picks Diagnostic — Why the 12 Are Underperforming",
        "",
        f"**Backtest date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"**Picks analyzed:** {len(picks)}",
        f"**Winners (return ≥ +3%):** {len(winners)} ({len(winners)/len(picks):.0%})",
        f"**Losers (return < +3%):** {len(losers)} ({len(losers)/len(picks):.0%})",
        "",
        "### The 12 live picks, ranked by return",
        "",
        "| Ticker | Entry Date | Return | Signals Fired | Count |",
        "|---|---|---:|---|---:|",
    ]
    for p in picks:
        fired_str = ", ".join(sorted(p["_fired"]))
        emoji = "✅" if p["return_pct"] >= 3 else ("⚠️" if p["return_pct"] >= -3 else "❌")
        lines.append(
            f"| {emoji} **{p['ticker']}** | {p['entry_date']} | "
            f"{p['return_pct']:+.1f}% | {fired_str} | {len(p['_fired'])} |"
        )

    lines.extend([
        "",
        "### Signal firing patterns — Winners vs Losers",
        "",
        "| Signal | Fired on Winners | Fired on Losers | Winner Rate | Loser Rate |",
        "|---|---:|---:|---:|---:|",
    ])
    for s in signal_names:
        w = win_signal_counts[s]
        l = lose_signal_counts[s]
        wr = w / len(winners) if winners else 0
        lr = l / len(losers) if losers else 0
        lines.append(
            f"| {s} | {w} | {l} | {wr:.0%} | {lr:.0%} |"
        )

    lines.extend([
        "",
        "### Signal combination concentration",
        "",
        "Distinct signal combinations across the 12 picks:",
        "",
    ])
    for combo, count in combo_counter.most_common():
        combo_str = " + ".join(sorted(combo)) if combo else "(none)"
        lines.append(f"- **{combo_str}** — {count} picks")

    lines.extend([
        "",
        "### Sector concentration",
        "",
        "| Sector | Picks | Tickers |",
        "|---|---:|---|",
    ])
    for sec, tickers in sorted(sectors.items(), key=lambda x: -len(x[1])):
        lines.append(f"| {sec} | {len(tickers)} | {', '.join(tickers)} |")

    # ── Arm date clustering ─────────────────────────────────────
    date_counter = Counter(arm_dates)
    if len(date_counter) < len(picks) / 2:
        lines.extend([
            "",
            "### ⚠️ Arm date clustering",
            "",
            "Arm dates are heavily clustered — possible timing bias:",
            "",
        ])
        for d, c in date_counter.most_common():
            lines.append(f"- {d}: {c} picks")

    # ── Diagnostic conclusions ──────────────────────────────────
    lines.extend([
        "",
        "### Diagnostic conclusions",
        "",
    ])

    # Find dominant signal combination
    top_combo, top_count = combo_counter.most_common(1)[0]
    if top_count >= len(picks) * 0.5:
        lines.append(
            f"**RED FLAG — signal combination concentration:** {top_count} of {len(picks)} "
            f"picks fired on the exact same signal combination "
            f"({', '.join(sorted(top_combo))}). "
            f"This means picks are not really independent — they're all the same trade type."
        )
        lines.append("")

    # Sector concentration
    max_sec = max(sectors.items(), key=lambda x: len(x[1]))
    if len(max_sec[1]) >= len(picks) * 0.35:
        lines.append(
            f"**RED FLAG — sector concentration:** {len(max_sec[1])} of {len(picks)} picks "
            f"({len(max_sec[1])/len(picks):.0%}) are in {max_sec[0]} sector "
            f"({', '.join(max_sec[1])}). Sector-specific weakness will dominate results."
        )
        lines.append("")

    # Winner signature
    if winners:
        winner_signals = winners[0]["_fired"]
        lines.append(
            f"**Winner pattern:** the only winner ({winners[0]['ticker']}) fired: "
            f"{', '.join(sorted(winner_signals))}."
        )
        # How many losers had the SAME combo?
        winner_combo = tuple(sorted(winner_signals))
        losers_same_combo = sum(1 for p in losers if tuple(sorted(p["_fired"])) == winner_combo)
        if losers_same_combo > 0:
            lines.append(
                f"But {losers_same_combo} losers fired the SAME combination. "
                f"Signal combination alone doesn't explain the difference. "
                f"Other factors (price trend, sector, timing) matter more."
            )
        lines.append("")

    body = "\n".join(lines)
    path = write_job_output("live_picks_diagnostic", body)
    return f"wrote {path}\n{len(picks)} picks | {len(winners)} winners | {len(losers)} losers"


if __name__ == "__main__":
    print(run())
