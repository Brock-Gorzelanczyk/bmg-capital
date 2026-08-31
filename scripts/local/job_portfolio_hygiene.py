"""Weekly portfolio hygiene — flag current picks underperforming peers.

Directly applies the peer-backtest finding (2026-08-30): current picks
are averaging -8.61% vs peers. Instead of finding out AT close, this job
runs weekly and flags picks that are actively lagging their peer group
by 5%+ over the trailing 30 days — a leading indicator of trouble.

For each open pick:
  1. Pull the pick's return over trailing 30 days
  2. Pull the peer group's mean return over same window
  3. If pick underperforming peers by 5%+ → flag as LAGGING
  4. If underperforming by 10%+ → flag as SEVERELY LAGGING, recommend review

Also computes 60-day and 90-day windows so we see whether the underperformance
is acute (30-day) or chronic (90-day).

Runs Sundays 9am ET. Writes to Obsidian.
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _bmg_api import get_client, BMGApiError  # noqa: E402
from _obsidian import write_job_output  # noqa: E402
from job_peer_backtest import PEER_MAP  # noqa: E402


def _yahoo_return_over_days(symbol: str, days: int) -> Optional[float]:
    """Return % over trailing `days` calendar days."""
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days + 5)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        return (closes[-1] - closes[0]) / closes[0] * 100
    except Exception:
        return None


def _peer_avg_return(peers: list, days: int) -> Optional[float]:
    rets = []
    for p in peers:
        r = _yahoo_return_over_days(p, days)
        if r is not None:
            rets.append(r)
    return statistics.mean(rets) if rets else None


def run() -> str:
    api = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        j = api.get("/api/admin/confluence/journal?include_closed=false&limit=50")
    except BMGApiError as e:
        return f"FAIL: {e}"

    picks = j.get("open_picks", [])
    if not picks:
        return "No open picks"

    print(f"Analyzing {len(picks)} open picks vs peers...")

    results = []
    for p in picks:
        ticker = p["ticker"]
        peers = PEER_MAP.get(ticker)
        if not peers:
            results.append({
                "ticker": ticker,
                "no_peers": True,
                "entry_date": p.get("entry_date"),
            })
            continue

        # 30d / 60d / 90d windows
        rets = {}
        for days in [30, 60, 90]:
            stock_ret = _yahoo_return_over_days(ticker, days)
            peer_ret = _peer_avg_return(peers, days)
            if stock_ret is not None and peer_ret is not None:
                rets[f"{days}d"] = {
                    "stock": stock_ret,
                    "peers": peer_ret,
                    "delta": stock_ret - peer_ret,
                }
            else:
                rets[f"{days}d"] = None

        # Classification based on 30-day delta
        delta_30 = rets["30d"]["delta"] if rets["30d"] else None
        if delta_30 is None:
            status = "UNKNOWN"
        elif delta_30 >= 3:
            status = "🟢 LEADING"
        elif delta_30 >= -3:
            status = "⚪ NEUTRAL"
        elif delta_30 >= -10:
            status = "🟡 LAGGING"
        else:
            status = "🔴 SEVERELY LAGGING"

        results.append({
            "ticker": ticker,
            "peers": peers,
            "entry_date": p.get("entry_date"),
            "rets": rets,
            "status": status,
            "no_peers": False,
        })

    # ── Categorize ──
    leading = [r for r in results if r.get("status") == "🟢 LEADING"]
    neutral = [r for r in results if r.get("status") == "⚪ NEUTRAL"]
    lagging = [r for r in results if r.get("status") == "🟡 LAGGING"]
    severe = [r for r in results if r.get("status") == "🔴 SEVERELY LAGGING"]
    no_peers = [r for r in results if r.get("no_peers")]

    lines = [
        f"# Portfolio Hygiene — {today}",
        "",
        f"**Open picks analyzed:** {len(picks)}",
        f"**With peer data:** {len(picks) - len(no_peers)}",
        "",
        "## Status summary",
        "",
        f"- 🟢 **Leading peers (30d):** {len(leading)}",
        f"- ⚪ **Neutral (±3%):** {len(neutral)}",
        f"- 🟡 **Lagging 3-10% vs peers:** {len(lagging)}",
        f"- 🔴 **SEVERELY lagging (>10% behind):** {len(severe)}",
        "",
    ]

    if severe:
        lines.extend([
            "## 🔴 SEVERELY LAGGING — Recommend Review / Close",
            "",
            "These picks are more than 10% behind their peer group over the trailing 30 days.",
            "The peer-backtest showed underperformance vs peers is a leading indicator of failure.",
            "",
            "| Ticker | Entry Date | 30d Δ vs Peers | 60d Δ | 90d Δ | Recommendation |",
            "|---|---|---:|---:|---:|---|",
        ])
        for r in sorted(severe, key=lambda x: x["rets"]["30d"]["delta"]):
            d60 = f"{r['rets']['60d']['delta']:+.1f}%" if r['rets']['60d'] else "—"
            d90 = f"{r['rets']['90d']['delta']:+.1f}%" if r['rets']['90d'] else "—"
            lines.append(
                f"| **{r['ticker']}** | {r['entry_date']} | "
                f"{r['rets']['30d']['delta']:+.1f}% | {d60} | {d90} | "
                f"Review — close or force-hold with new thesis |"
            )

    if lagging:
        lines.extend([
            "",
            "## 🟡 LAGGING — Monitor Closely",
            "",
            "3-10% behind peers over 30d. Not yet critical but worth watching.",
            "",
            "| Ticker | Entry Date | 30d Δ vs Peers | 60d Δ | 90d Δ |",
            "|---|---|---:|---:|---:|",
        ])
        for r in sorted(lagging, key=lambda x: x["rets"]["30d"]["delta"]):
            d60 = f"{r['rets']['60d']['delta']:+.1f}%" if r['rets']['60d'] else "—"
            d90 = f"{r['rets']['90d']['delta']:+.1f}%" if r['rets']['90d'] else "—"
            lines.append(
                f"| **{r['ticker']}** | {r['entry_date']} | "
                f"{r['rets']['30d']['delta']:+.1f}% | {d60} | {d90} |"
            )

    if neutral or leading:
        lines.extend([
            "",
            "## ⚪ NEUTRAL / 🟢 LEADING — Keep",
            "",
            "| Ticker | Entry Date | 30d Δ vs Peers | Status |",
            "|---|---|---:|---|",
        ])
        for r in sorted(leading + neutral, key=lambda x: -x["rets"]["30d"]["delta"]):
            lines.append(
                f"| **{r['ticker']}** | {r['entry_date']} | "
                f"{r['rets']['30d']['delta']:+.1f}% | {r['status']} |"
            )

    if no_peers:
        lines.extend([
            "",
            "## ⚠️ No peer data available",
            "",
            "These picks need peer definitions added to `scripts/local/job_peer_backtest.py`:",
            "",
        ])
        for r in no_peers:
            lines.append(f"- **{r['ticker']}** (entered {r.get('entry_date')})")

    lines.extend([
        "",
        "## How to use this report",
        "",
        "**Weekly protocol:**",
        "1. Any 🔴 SEVERELY LAGGING → close position OR document why keeping (new thesis)",
        "2. Any 🟡 LAGGING → set a mental stop at 15% peer underperformance",
        "3. 🟢 LEADING → likely proceeding well, no action needed",
        "",
        "**Why this matters (from 2026-08-30 peer backtest):**",
        "- Framework's picks were averaging -8.61% vs their peer groups",
        "- Underperformance vs peers is a leading indicator of failure",
        "- Waiting until close to notice loses months of dead money",
        "",
        "Runs Sundays 9am ET automatically. This is the ACTION side of the",
        "peer-relative measurement work.",
        "",
        "Companion notes:",
        "- `research/2026-08-31-peer-backtest.md` — the study this is based on",
        "- `research/2026-08-30-confluence-framework-backtest-analysis.md`",
    ])

    body = "\n".join(lines)
    path = write_job_output("portfolio_hygiene", body)
    return (f"wrote {path}\n"
            f"leading: {len(leading)} | neutral: {len(neutral)} | "
            f"lagging: {len(lagging)} | severe: {len(severe)} | no_peers: {len(no_peers)}")


if __name__ == "__main__":
    print(run())
