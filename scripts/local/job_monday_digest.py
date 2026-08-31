"""Monday Morning Trader Digest — one report to start the week.

Consolidates all the weekend/overnight signals into a single Monday-morning
brief. Instead of reading 6 separate files, glance at ONE and know:
  - What regime we're in today (Faber / growth-value / mean-reversion / VIX)
  - Which of your picks are lagging peers (candidates to close)
  - Any rule scorecard PROMOTE/INVESTIGATE recommendations
  - Overall portfolio state
  - Top 3 actions for the week

Runs Mondays 7am ET (before market open). Pulls from Railway + Yahoo,
writes to Obsidian.

Zero cost, zero clicks, ready in your vault when you wake up.
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _bmg_api import get_client, BMGApiError  # noqa: E402
from _obsidian import write_job_output  # noqa: E402
from job_peer_backtest import PEER_MAP  # noqa: E402


def _yahoo_closes(symbol: str, days: int) -> Optional[list]:
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days + 5)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
    except Exception:
        return None


def _ret_pct(closes: list) -> Optional[float]:
    if not closes or len(closes) < 2:
        return None
    return (closes[-1] - closes[0]) / closes[0] * 100


def _regime_snapshot() -> dict:
    """Compute current regime state (same logic as job_regime_snapshot)."""
    result = {}

    # Faber SPY 200-SMA
    spy = _yahoo_closes("SPY", 400)
    if spy and len(spy) >= 200:
        sma200 = sum(spy[-200:]) / 200
        current = spy[-1]
        result["faber"] = "RISK-ON" if current > sma200 else "RISK-OFF"
    else:
        result["faber"] = "UNKNOWN"

    # Momentum vs Mean-Reversion (3mo MTUM vs VLUE)
    mtum = _yahoo_closes("MTUM", 100)
    vlue = _yahoo_closes("VLUE", 100)
    if mtum and vlue and len(mtum) >= 60 and len(vlue) >= 60:
        mtum_ret = (mtum[-1] - mtum[-60]) / mtum[-60] * 100
        vlue_ret = (vlue[-1] - vlue[-60]) / vlue[-60] * 100
        spread = mtum_ret - vlue_ret
        if spread > 3:
            result["mmr"] = "TREND_FOLLOWING"
        elif spread < -3:
            result["mmr"] = "MEAN_REVERSION"
        else:
            result["mmr"] = "NEUTRAL"
        result["mmr_spread"] = spread
    else:
        result["mmr"] = "UNKNOWN"

    # VIX
    vix = _yahoo_closes("^VIX", 10)
    if vix and vix[-1]:
        v = vix[-1]
        if v < 15: result["vix"] = f"LOW ({v:.1f})"
        elif v < 25: result["vix"] = f"NORMAL ({v:.1f})"
        elif v < 35: result["vix"] = f"ELEVATED ({v:.1f})"
        else: result["vix"] = f"HIGH ({v:.1f})"
    else:
        result["vix"] = "UNKNOWN"

    return result


def _peer_lag_check(ticker: str, days: int = 30) -> Optional[float]:
    """Return delta (stock - peer avg) over trailing `days`. None if no data."""
    peers = PEER_MAP.get(ticker)
    if not peers:
        return None
    stock_closes = _yahoo_closes(ticker, days + 5)
    stock_ret = _ret_pct(stock_closes[-(days + 1):]) if stock_closes else None
    if stock_ret is None:
        return None
    peer_rets = []
    for p in peers:
        pc = _yahoo_closes(p, days + 5)
        pr = _ret_pct(pc[-(days + 1):]) if pc else None
        if pr is not None:
            peer_rets.append(pr)
    if not peer_rets:
        return None
    return stock_ret - statistics.mean(peer_rets)


def run() -> str:
    api = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print("Building Monday digest...")

    # Regime state
    regime = _regime_snapshot()

    # Portfolio state
    picks = []
    try:
        j = api.get("/api/admin/confluence/journal?include_closed=false&limit=50")
        picks = j.get("open_picks", [])
    except BMGApiError:
        pass

    portfolio = {}
    try:
        s = api.get("/api/portfolio/summary")
        # /api/portfolio/summary exposes total_value_cents + alpaca_cash_cents;
        # all-time P&L lives on /api/portfolio/snapshot as
        # total_pnl_alltime_cents. Prior code used made-up field names
        # (fund_pv_cents / cash_cents / all_time_pnl_cents) that silently
        # returned 0 for a live-funded fund.
        try:
            snap = api.get("/api/portfolio/snapshot")
            _alltime_cents = int(snap.get("total_pnl_alltime_cents") or 0)
        except BMGApiError:
            _alltime_cents = 0
        portfolio = {
            "fund_pv": (s.get("total_value_cents") or 0) / 100,
            "cash": (s.get("alpaca_cash_cents") or 0) / 100,
            "all_time_pnl": _alltime_cents / 100,
        }
    except BMGApiError:
        pass

    # Peer-lag analysis per pick (30-day)
    print(f"Analyzing {len(picks)} open picks vs peers...")
    lagging = []  # 5%+ behind peers
    severe = []   # 10%+ behind
    leading = []  # 3%+ ahead
    no_data = []
    for p in picks:
        delta = _peer_lag_check(p["ticker"], days=30)
        entry = {
            "ticker": p["ticker"],
            "entry_date": p.get("entry_date"),
            "delta_30d": delta,
        }
        if delta is None:
            no_data.append(entry)
        elif delta >= 3:
            leading.append(entry)
        elif delta <= -10:
            severe.append(entry)
        elif delta <= -5:
            lagging.append(entry)

    # Compose top-3 actions
    actions = []
    if severe:
        tickers = ", ".join(f"{r['ticker']} ({r['delta_30d']:+.0f}%)" for r in sorted(severe, key=lambda x: x['delta_30d'])[:3])
        actions.append(f"🔴 **Review closing:** {tickers} — severely lagging peers 30d")
    if regime["mmr"] == "MEAN_REVERSION":
        actions.append("⚠️ **Mean-reversion regime active** — do NOT trust sector-momentum signals; beaten-down names likely to rebound")
    if regime["faber"] == "RISK-OFF":
        actions.append("⚠️ **Faber RISK-OFF** — cut all new position sizes 50%; consider raising cash")
    if regime.get("vix", "").startswith("ELEVATED") or regime.get("vix", "").startswith("HIGH"):
        actions.append(f"⚠️ **VIX elevated** ({regime['vix']}) — reduce position sizes; brace for whipsaw")
    if not actions:
        actions.append("✓ **No critical alerts** — proceed with normal weekly review")

    # ── Render ──
    lines = [
        f"# Monday Trader Digest — {today}",
        "",
        f"*Auto-generated Monday 7am ET. One-glance start-of-week brief.*",
        "",
        "## Top 3 actions this week",
        "",
    ]
    for a in actions[:4]:
        lines.append(f"- {a}")
    lines.extend([
        "",
        "---",
        "",
        "## 1. Market Regime",
        "",
        f"- **Faber SPY 200-SMA:** `{regime['faber']}`",
        f"- **Momentum vs Mean-Reversion (3mo):** `{regime['mmr']}` ({regime.get('mmr_spread', 0):+.1f}% spread)",
        f"- **VIX:** `{regime.get('vix', 'UNKNOWN')}`",
        "",
        "Interpretation:",
        "",
    ])
    if regime["faber"] == "RISK-ON":
        lines.append("- Faber gate is GREEN — normal long-side sizing OK")
    else:
        lines.append("- Faber gate is RED — halve long sizes, consider raising cash")
    if regime["mmr"] == "MEAN_REVERSION":
        lines.append("- Mean-reversion regime — value picks favored, sector-momentum filter would kill winners")
    elif regime["mmr"] == "TREND_FOLLOWING":
        lines.append("- Trend-following regime — momentum picks favored, enable sector filter")
    else:
        lines.append("- Neutral regime — no strong tilt either way")

    lines.extend([
        "",
        "## 2. Portfolio Snapshot",
        "",
        f"- **Fund PV:** ${portfolio.get('fund_pv', 0):,.0f}",
        f"- **Cash:** ${portfolio.get('cash', 0):,.0f}",
        f"- **All-time P&L:** ${portfolio.get('all_time_pnl', 0):+,.0f}",
        f"- **Open picks:** {len(picks)}",
        "",
        "## 3. Portfolio Hygiene (30d vs peers)",
        "",
        f"- 🔴 **Severely lagging (>10% behind):** {len(severe)} picks",
        f"- 🟡 **Lagging (5-10% behind):** {len(lagging)} picks",
        f"- 🟢 **Leading (+3% ahead):** {len(leading)} picks",
        f"- ⚪ No peer data: {len(no_data)} picks",
        "",
    ])

    if severe:
        lines.append("### 🔴 Severely lagging — recommend review this week")
        lines.append("")
        lines.append("| Ticker | Entry | 30d Δ vs Peers | Action |")
        lines.append("|---|---|---:|---|")
        for r in sorted(severe, key=lambda x: x["delta_30d"]):
            lines.append(
                f"| **{r['ticker']}** | {r['entry_date']} | {r['delta_30d']:+.1f}% | "
                f"Close OR document new thesis |"
            )
        lines.append("")

    if lagging:
        lines.append("### 🟡 Lagging — monitor closely")
        lines.append("")
        lines.append("| Ticker | Entry | 30d Δ vs Peers |")
        lines.append("|---|---|---:|")
        for r in sorted(lagging, key=lambda x: x["delta_30d"]):
            lines.append(f"| **{r['ticker']}** | {r['entry_date']} | {r['delta_30d']:+.1f}% |")
        lines.append("")

    if leading:
        lines.append("### 🟢 Leading — winning positions")
        lines.append("")
        lines.append("| Ticker | Entry | 30d Δ vs Peers |")
        lines.append("|---|---|---:|")
        for r in sorted(leading, key=lambda x: -x["delta_30d"]):
            lines.append(f"| **{r['ticker']}** | {r['entry_date']} | {r['delta_30d']:+.1f}% |")
        lines.append("")

    # Composition warnings
    tickers = [p["ticker"] for p in picks]
    if len(tickers) != len(set(tickers)):
        lines.append("### ⚠️ Duplicate tickers in portfolio — investigate")
        lines.append("")

    lines.extend([
        "## 4. This week's protocol",
        "",
        "1. **Monday (today):** review this digest + severe-lagging picks",
        "2. **Wednesday:** mid-week regime check (regime_snapshot updates daily)",
        "3. **Friday:** end-of-week P&L review (daily_recap updates)",
        "4. **Sunday:** scorecard (which rules discriminated) + fresh hygiene report",
        "",
        "## 5. Companion reports (auto-updated)",
        "",
        "- Daily regime: `context/local-jobs/YYYY-MM-DD-regime_snapshot.md`",
        "- Daily recap: `context/local-jobs/YYYY-MM-DD-daily_recap.md`",
        "- Weekly hygiene: `context/local-jobs/YYYY-MM-DD-portfolio_hygiene.md`",
        "- Weekly scorecard: `research/YYYY-MM-DD-weekly-scorecard.md`",
        "",
        "*This digest generated by scripts/local/job_monday_digest.py — every Monday 7am ET.*",
    ])

    body = "\n".join(lines)
    path = write_job_output("monday_digest", body)
    return (f"wrote {path}\n"
            f"regime: faber={regime['faber']} mmr={regime['mmr']} vix={regime.get('vix', '?')}\n"
            f"picks: {len(picks)} open | {len(severe)} severe | {len(lagging)} lagging | {len(leading)} leading")


if __name__ == "__main__":
    print(run())
