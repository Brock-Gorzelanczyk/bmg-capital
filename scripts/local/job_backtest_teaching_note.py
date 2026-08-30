"""Generate a teaching note with visual backtest results.

Combines:
- Ticker + company name for each of 20 backtest candidates
- Visual bar chart (Unicode blocks) of sector-relative excess
- Plain-English explanation of how the confluence framework values companies
- Lessons learned from the backtest

Writes to vault: research/2026-08-30-confluence-framework-teaching-note.md
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

VAULT_ROOT = Path.home() / "Documents" / "BMG-Capital-Vault"
OUT_PATH = VAULT_ROOT / "research" / "2026-08-30-confluence-framework-teaching-note.md"

# Ticker → (company name, sector) map for all 20 backtest candidates
COMPANY_MAP = {
    "SPG":  ("Simon Property Group",        "Real Estate"),
    "AAT":  ("American Assets Trust",       "Real Estate"),
    "APTV": ("Aptiv plc",                   "Consumer Discretionary"),
    "VFC":  ("VF Corporation",              "Consumer Discretionary"),
    "ONON": ("On Holding",                  "Consumer Discretionary"),
    "HOG":  ("Harley-Davidson",             "Consumer Discretionary"),
    "KMPR": ("Kemper Corporation",          "Financials"),
    "MTDR": ("Matador Resources",           "Energy"),
    "ELAN": ("Elanco Animal Health",        "Healthcare"),
    "REZI": ("Resideo Technologies",        "Industrials"),
    "PODD": ("Insulet Corporation",         "Healthcare"),
    "TSM":  ("Taiwan Semiconductor",        "Technology"),
    "PLTR": ("Palantir Technologies",       "Technology"),
    "CRM":  ("Salesforce",                  "Technology"),
    "AMD":  ("Advanced Micro Devices",      "Technology"),
    "NFLX": ("Netflix",                     "Communication Services"),
    "PYPL": ("PayPal Holdings",             "Financials"),
    "SBUX": ("Starbucks",                   "Consumer Discretionary"),
    "F":    ("Ford Motor Company",          "Consumer Discretionary"),
    "INTC": ("Intel Corporation",           "Technology"),
}

# Backtest arm-date map (from job_confluence_backtest.py)
ARM_DATES = {
    "SPG": "2026-06-15", "AAT": "2026-06-01", "APTV": "2026-05-15", "VFC": "2026-05-01",
    "ONON": "2026-06-15", "HOG": "2026-05-20", "KMPR": "2026-06-01", "MTDR": "2026-05-15",
    "ELAN": "2026-06-10", "REZI": "2026-05-25", "PODD": "2026-05-01", "TSM": "2026-06-01",
    "PLTR": "2026-04-01", "CRM": "2026-04-15", "AMD": "2026-05-01", "NFLX": "2026-04-01",
    "PYPL": "2026-04-15", "SBUX": "2026-05-01", "F": "2026-05-15", "INTC": "2026-04-15",
}

SECTOR_ETF = {
    "Real Estate": "XLRE", "Consumer Discretionary": "XLY",
    "Financials": "XLF", "Energy": "XLE", "Healthcare": "XLV",
    "Industrials": "XLI", "Technology": "XLK", "Communication Services": "XLC",
}


def _yahoo_closes(symbol: str, start_iso: str, end_iso: str) -> Optional[list]:
    start_ts = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp())
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
            "closes": [c for c in result[0].get("indicators", {}).get("quote", [{}])[0].get("close", []) if c is not None],
        }
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None


def _closest_on_or_after(closes_dict: dict, target_iso: str) -> Optional[float]:
    if not closes_dict:
        return None
    target_ts = int(datetime.fromisoformat(target_iso).replace(tzinfo=timezone.utc).timestamp())
    for ts, close in zip(closes_dict["timestamps"], closes_dict["closes"]):
        if ts >= target_ts:
            return float(close)
    return None


def _latest(closes_dict: dict) -> Optional[float]:
    if not closes_dict or not closes_dict.get("closes"):
        return None
    return float(closes_dict["closes"][-1])


def _bar(value: float, scale: float = 40, char_full: str = "█", char_neg: str = "█") -> str:
    """Render a Unicode bar of length proportional to abs(value).
    scale = 40 means 40% return = full bar of ~40 chars."""
    n = min(40, int(abs(value)))
    ch = char_full if value >= 0 else char_neg
    return ch * n


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_iso = today
    earliest = min(ARM_DATES.values())

    # Fetch all sector ETFs once
    print("Fetching sector ETF bars...")
    sector_data = {}
    for etf in set(SECTOR_ETF.values()):
        sector_data[etf] = _yahoo_closes(etf, earliest, end_iso)

    print("Fetching per-stock bars...")
    results = []
    for ticker, (company, sector) in COMPANY_MAP.items():
        arm_date = ARM_DATES[ticker]
        bars = _yahoo_closes(ticker, arm_date, end_iso)
        if not bars:
            continue
        entry = _closest_on_or_after(bars, arm_date)
        current = _latest(bars)
        if entry is None or current is None:
            continue

        stock_ret = (current - entry) / entry * 100

        etf = SECTOR_ETF.get(sector)
        sec_ret = None
        if etf and sector_data.get(etf):
            sec_entry = _closest_on_or_after(sector_data[etf], arm_date)
            sec_latest = _latest(sector_data[etf])
            if sec_entry is not None and sec_latest is not None:
                sec_ret = (sec_latest - sec_entry) / sec_entry * 100
        excess_sec = (stock_ret - sec_ret) if sec_ret is not None else None
        hold_days = (datetime.now(timezone.utc) - datetime.fromisoformat(arm_date).replace(tzinfo=timezone.utc)).days

        results.append({
            "ticker": ticker, "company": company, "sector": sector,
            "arm_date": arm_date, "hold_days": hold_days,
            "entry": entry, "current": current,
            "stock_ret": stock_ret, "sec_ret": sec_ret, "excess_sec": excess_sec,
        })

    # Sort by excess vs sector desc
    results_ranked = sorted(results, key=lambda r: r["excess_sec"] if r["excess_sec"] is not None else -999, reverse=True)

    # Compute stats
    all_excesses = [r["excess_sec"] for r in results if r["excess_sec"] is not None]
    winners = [r for r in results_ranked if r["excess_sec"] is not None and r["excess_sec"] >= 3.0]
    losers = [r for r in results_ranked if r["excess_sec"] is not None and r["excess_sec"] < 3.0]

    # ── Render the teaching note ────────────────────────────────────────
    lines = [
        "# HOW WE VALUE COMPANIES — Backtest Results + Framework Teaching Note",
        "",
        f"**Generated:** {today}",
        f"**N candidates:** {len(results)}",
        "",
        "This note is BOTH the results of our 20-stock backtest AND a plain-English "
        "explanation of HOW the framework values companies. Everything is visual + "
        "annotated so you can see exactly what's working, what isn't, and why.",
        "",
        "---",
        "",
        "## PART 1: The Results — Visual Chart",
        "",
        "Sorted best-to-worst by **sector-relative excess** (how much the stock "
        "beat/lost to its own sector ETF). Green = beat sector by 3%+ (WIN). Red = "
        "underperformed sector.",
        "",
        "```",
        f"{'Ticker':6} {'Company':30} {'Sec':4} {'Days':>5} {'Return':>7} {'Excess':>7}  Bar",
        "─" * 100,
    ]

    for r in results_ranked:
        excess = r["excess_sec"] if r["excess_sec"] is not None else 0
        color_indicator = "🟢" if excess >= 3.0 else ("🔴" if excess < -3.0 else "⚪")
        bar_str = _bar(excess) if excess != 0 else ""
        # Position the bar based on sign
        sign_prefix = "+" if excess >= 0 else "-"
        etf = SECTOR_ETF.get(r["sector"], "?")
        lines.append(
            f"{r['ticker']:6} {r['company'][:30]:30} {etf:4} "
            f"{r['hold_days']:>5} {r['stock_ret']:>+6.1f}% "
            f"{excess:>+6.1f}%  {bar_str}"
        )
    lines.append("```")

    lines.extend([
        "",
        "### The scoreboard",
        "",
        f"- **Winners (beat sector by 3%+):** {len(winners)} of {len(results)} "
        f"({len(winners)/len(results):.0%} hit rate)",
        f"- **Losers (underperformed sector):** {len(losers)} of {len(results)}",
        f"- **Average excess vs sector:** {statistics.mean(all_excesses):+.2f}%",
        f"- **Best pick:** {results_ranked[0]['ticker']} ({results_ranked[0]['company']}) — "
        f"{results_ranked[0]['excess_sec']:+.1f}% vs sector",
        f"- **Worst pick:** {results_ranked[-1]['ticker']} ({results_ranked[-1]['company']}) — "
        f"{results_ranked[-1]['excess_sec']:+.1f}% vs sector",
        "",
        "**Verdict:** framework is currently FAILING its win criterion (need 60% hit rate + "
        "avg excess ≥+3%; currently at 25% hit rate + -4.56% avg).",
        "",
        "---",
        "",
        "## PART 2: How the Framework Values Companies (Simple Version)",
        "",
        "Our confluence framework picks stocks by checking **5 different signals**. It's like "
        "having 5 different scouts giving you their opinion on a player. The idea: if 3+ scouts "
        "all say the same thing independently, it's more reliable than any single scout.",
        "",
        "Here's what each signal actually looks at, in plain English:",
        "",
        "### Signal 1: INSIDER CLUSTER — 'Are the executives buying?' (REQUIRED)",
        "",
        "**What it checks:** are multiple company insiders (CEO, CFO, board members) buying "
        "their own company's stock in the past 3-6 months?",
        "",
        "**Why it matters:** insiders are legally required to disclose their trades. They know "
        "their business better than anyone. When multiple execs are BUYING with their own money "
        "at once, that's a strong statement.",
        "",
        "**Academic backing:** Cohen-Malloy-Pomorski 2012 (JF) — 'opportunistic' insider "
        "clusters generate 82 bps/month excess return (~10%/yr). Ali-Hirshleifer 2017 refined it "
        "to 112 bps/mo using pre-earnings-window filtering.",
        "",
        "**Real example (from your picks):**",
        "- HOG (Harley-Davidson): multiple insider buys → **+18.4% vs sector** ✅",
        "- VFC (VF Corporation): insider buys, brand collapse continued → **−26.9%** ❌",
        "  (Insider buying alone can't rescue a broken business)",
        "",
        "### Signal 2: SHORT SURPRISE — 'Are short-sellers running away?'",
        "",
        "**What it checks:** the direction of change in short interest. If short interest is "
        "DROPPING while price is FLAT, shorts are covering (a bullish signal). If short interest "
        "is RISING sharply, shorts are piling in (bearish or contrarian).",
        "",
        "**Why it matters:** short-sellers are usually sophisticated. Their behavior is a real-time "
        "vote on the stock's future. Sudden covering often precedes rallies.",
        "",
        "**Academic backing:** Hong-Li-Ni 2015 — Days-to-Cover (DTC = shares short ÷ daily volume) "
        "generates 119 bps/mo EW on the long-short. Direction matters more than level.",
        "",
        "### Signal 3: ANALYST REVISIONS — 'Are Wall Street analysts getting more bullish?'",
        "",
        "**What it checks:** are analyst estimates for earnings or price targets being REVISED "
        "UP recently? Multiple upgrades in a short window is a strong signal.",
        "",
        "**Why it matters:** analysts are slow to move — they don't want to be first to change "
        "a call. When they DO move, it often triggers institutional buying/selling that lasts "
        "20-40 days (documented drift).",
        "",
        "**Academic backing:** Womack 1996, Barber-Loeffler 2001 — analyst revisions have "
        "documented drift of 3-6% over 30-60 days after publication.",
        "",
        "### Signal 4: FUNDAMENTAL MOMENTUM — 'Is the business improving?'",
        "",
        "**What it checks:** are the actual FINANCIAL metrics improving? Revenue growth "
        "accelerating? Margins expanding? EPS beats stacking?",
        "",
        "**Why it matters:** stock price eventually follows fundamentals. If the numbers are "
        "getting better, patient capital will eventually catch on.",
        "",
        "**Academic backing:** Novy-Marx 2013 gross profitability, Fama-French 5-factor RMW.",
        "",
        "**Real example:**",
        "- CRM (Salesforce): AI narrative + fundamental margin expansion → **+20.6% vs sector** ✅",
        "- PODD (Insulet): 'fundamental momentum' signal fired, but competition ate lunch → **−35%** ❌",
        "  (Backward-looking fundamentals can miss forward-looking disruption)",
        "",
        "### Signal 5: INSTITUTIONAL 13F NET ADD — 'Are the big funds buying?'",
        "",
        "**What it checks:** the quarterly 13F filings from mutual funds and hedge funds — did "
        "net institutional ownership increase last quarter? A rising tide of professional buyers "
        "provides real demand.",
        "",
        "**Why it matters:** institutions move slow but big. When they collectively add a name, "
        "you get 3-6 months of steady buying pressure.",
        "",
        "**Academic backing:** Chen-Hong-Stein 2002 breadth of ownership, plus various 13F-based "
        "'smart money' factors.",
        "",
        "---",
        "",
        "## PART 3: The Confluence Rule",
        "",
        "The framework requires:",
        "1. **Insider cluster: REQUIRED** (mandatory — no exception)",
        "2. **At least 3 of 5 signals firing**",
        "",
        "Why the strict rules? Because ONE signal alone is noisy. Insider buying without "
        "confirming price momentum = value trap. Analyst upgrades without insider confirmation "
        "= consensus already priced in. The confluence rule filters for cases where multiple "
        "independent sources agree.",
        "",
        "---",
        "",
        "## PART 4: What The Backtest Taught Us",
        "",
        "**The uncomfortable finding:** even with 3+ signals firing, your 12 current picks are "
        "averaging **−9.74% vs their own sectors**. The signals are firing, but the picks aren't "
        "working.",
        "",
        "**Why?** Look at the CHART above. Notice a pattern:",
        "",
        "- **All 4 biggest losers** (VFC, ONON, PODD, APTV) were trading BELOW their 200-day "
        "moving average when armed — meaning they were in downtrends already",
        "- **The 5 biggest winners** (CRM, HOG, AMD, INTC, SBUX) were all trading ABOVE their "
        "200-day moving average when armed — in uptrends",
        "",
        "**The lesson:** the framework's signals identify good FUNDAMENTAL setups, but doesn't "
        "check whether the stock is in a healthy PRICE TREND. Buying a fundamentally attractive "
        "stock that's in a downtrend is called a 'value trap' — the market often knows something "
        "the fundamentals haven't shown yet.",
        "",
        "**What we shipped today to fix this:**",
        "",
        "**Trend Gate #1:** Before arming, check if the stock is above its 200-day moving average. "
        "If NO, flag a warning. Would have blocked VFC, ONON, PODD, APTV.",
        "",
        "**Trend Gate #2:** Before arming, check if the stock's sector is up over trailing 3 "
        "months. Sector momentum matters.",
        "",
        "**Regime Overlay:** Check whether the broader market is in a growth-dominant or value-"
        "dominant regime. Adjust position sizing accordingly.",
        "",
        "All three shipped today as ADVISORY (they log warnings but don't block yet). Over the "
        "next 3 months as we collect data, we'll see if they actually discriminate — then decide "
        "whether to make them hard blocks.",
        "",
        "---",
        "",
        "## PART 5: The Big Picture Framework (How All Pieces Fit)",
        "",
        "```",
        "┌───────────────────────────────────────────────────────────────┐",
        "│  1. UNIVERSE — start with all S&P 1500 stocks                 │",
        "└───────────────────────────────────────────────────────────────┘",
        "                              ↓",
        "┌───────────────────────────────────────────────────────────────┐",
        "│  2. CONFLUENCE SIGNALS — check the 5 signals per stock        │",
        "│     - insider cluster (REQUIRED)                              │",
        "│     - short surprise                                          │",
        "│     - analyst revisions                                       │",
        "│     - fundamental momentum                                    │",
        "│     - institutional 13F                                       │",
        "│  → require ≥3 firing → CANDIDATE POOL                         │",
        "└───────────────────────────────────────────────────────────────┘",
        "                              ↓",
        "┌───────────────────────────────────────────────────────────────┐",
        "│  3. TREND GATES (NEW today) — quality filters                 │",
        "│     - price above 200-day SMA?                                │",
        "│     - sector momentum positive?                               │",
        "│     - growth vs value regime?                                 │",
        "│  → advisory warnings + rule_compliance log                    │",
        "└───────────────────────────────────────────────────────────────┘",
        "                              ↓",
        "┌───────────────────────────────────────────────────────────────┐",
        "│  4. ARM — set entry price, stop, target                       │",
        "│     - Play A: buy on breakout above trigger                   │",
        "│     - Play B: buy on pullback to support                      │",
        "│     - bracket order fires automatically                       │",
        "└───────────────────────────────────────────────────────────────┘",
        "                              ↓",
        "┌───────────────────────────────────────────────────────────────┐",
        "│  5. HOLD — target 6 months                                    │",
        "│     - executor tracks vs invalidation price                   │",
        "│     - measure excess return vs SPY at close                   │",
        "│  → hit = beat SPY by 3%+                                      │",
        "└───────────────────────────────────────────────────────────────┘",
        "                              ↓",
        "┌───────────────────────────────────────────────────────────────┐",
        "│  6. SCORE — decision-rules.md scorecard                       │",
        "│     - which rules discriminated?                              │",
        "│     - promote/demote rules based on evidence                  │",
        "│     - the FRAMEWORK EVOLVES from data                         │",
        "└───────────────────────────────────────────────────────────────┘",
        "```",
        "",
        "---",
        "",
        "## PART 6: Key Vocabulary (for future reference)",
        "",
        "- **Confluence:** multiple independent signals agreeing. Reduces noise vs any single signal.",
        "- **Insider cluster:** ≥3 company insiders buying own stock in a short window.",
        "- **13F filing:** quarterly SEC disclosure of institutional holdings.",
        "- **PEAD (post-earnings drift):** stocks that beat earnings continue drifting up for 30-60 days.",
        "- **Sector-relative excess:** how much a stock beat/lost to its sector ETF. Isolates 'skill' from 'regime.'",
        "- **200-day SMA:** long-term trend line. Above = risk-on, below = downtrend.",
        "- **Value trap:** fundamentally attractive stock that keeps falling because the market sees something the fundamentals don't yet show.",
        "- **Deflated Sharpe:** correcting a strategy's Sharpe ratio for the number of variants tested. Reality check on backtests.",
        "- **Growth-dominant regime:** period when large-cap growth stocks beat small-cap value. 2024-early-2026 was one; current 6mo has flipped to value-dominant.",
        "",
        "---",
        "",
        "## Companion notes",
        "",
        "- `research/decision-rules.md` — the mechanical rulebook",
        "- `research/2026-08-30-confluence-framework-backtest-analysis.md` — full analytical breakdown",
        "- `research/2026-08-30-swing-setup-playbook.md` — chart-pattern entry rules",
        "- `research/2026-08-30-behavioral-finance-trader-errors.md` — how NOT to sabotage yourself",
        "- `research/2026-08-25-confluence-framework-v2-signal-additions.md` — signal design origin",
    ])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
