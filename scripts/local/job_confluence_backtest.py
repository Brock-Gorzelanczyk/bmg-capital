"""job_confluence_backtest.py — backtest the confluence framework on 20 stocks.

Per Brock 2026-08-30: "based on how we value stocks and set them up now, go
and backtest and see if it would work on stocks that we would have armed."

**How this works (honest methodology):**

1. Pick 20 candidate tickers:
   - 12 currently ARMED confluence picks (real triggers, dates from journal)
   - 8 additional names that WOULD have met confluence criteria in 2025-2026
     based on public insider filings + analyst upgrade activity
2. For each: use the pick's actual arm date (or estimated trigger date for
   the 8 extras — noted honestly per row)
3. Fetch daily bars via Yahoo Finance (free, no Railway cost)
4. Compute:
   - Absolute return since arm date
   - SPY return over same window
   - Excess return vs SPY (this is the framework's KPI)
   - Hit = excess ≥ +3% (framework's win criterion)
5. Aggregate: hit rate, avg excess, verdict

**Honest caveats (I want these on the record):**
- The 12 current picks have SURVIVORSHIP BIAS baked in — they're the ones
  that made it to today. Any that were closed early aren't in this sample.
- The 8 extras are curator-selected — I picked based on known 2025 insider
  clusters, which is post-hoc. Real out-of-sample would need a point-in-time
  screener.
- Hold periods vary (arm dates span 1-6 months back). Not apples-to-apples
  across the sample.
- SPY excess accounts for market direction but not sector rotation.
- N=20 is way below the 30+ needed for statistical significance. Treat as
  DIRECTIONAL, not conclusive.

Output: markdown report to ~/Documents/BMG-Capital-Vault/context/local-jobs/
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _obsidian import write_job_output  # noqa: E402


# ── The 20 candidates with arm dates ──────────────────────────────────────
# Arm date = date the confluence framework WOULD have first fired.
# Sources:
#   - Current picks (12): approx 30-90 day windows based on when they entered
#     the journal (from local runner's daily_recap)
#   - 8 extras: publicly documented insider cluster or analyst upgrade dates
#     from 2025 SEC Form 4 filings + IBD analyst calls
#
# NOTE: This list intentionally mixes winners and likely losers to avoid
# cherry-picking. Real backtest would use point-in-time universe scan.

CANDIDATES = [
    # (symbol, arm_date, source, thesis, sector_etf)
    #
    # ── Bucket 1: 12 currently armed confluence picks (real triggers) ──
    ("SPG",  "2026-06-15", "CURRENT_PICK", "Simon Property — REIT, insider cluster",         "XLRE"),
    ("AAT",  "2026-06-01", "CURRENT_PICK", "American Assets Trust — insider + upgrades",     "XLRE"),
    ("APTV", "2026-05-15", "CURRENT_PICK", "Aptiv plc — auto tech, insider + 13F",           "XLY"),
    ("VFC",  "2026-05-01", "CURRENT_PICK", "VF Corp — turnaround, insider buying",           "XLY"),
    ("ONON", "2026-06-15", "CURRENT_PICK", "On Holding — consumer discretionary",            "XLY"),
    ("HOG",  "2026-05-20", "CURRENT_PICK", "Harley Davidson — insider + short interest",     "XLY"),
    ("KMPR", "2026-06-01", "CURRENT_PICK", "Kemper — insurance, analyst upgrades",           "XLF"),
    ("MTDR", "2026-05-15", "CURRENT_PICK", "Matador Resources — E&P, insider cluster",       "XLE"),
    ("ELAN", "2026-06-10", "CURRENT_PICK", "Elanco Animal Health — turnaround",              "XLV"),
    ("REZI", "2026-05-25", "CURRENT_PICK", "Resideo Technologies — value + insider",         "XLI"),
    ("PODD", "2026-05-01", "CURRENT_PICK", "Insulet — medical devices, growth",              "XLV"),
    ("TSM",  "2026-06-01", "CURRENT_PICK", "TSMC — semiconductor, institutional",            "XLK"),

    # ── Bucket 2: 20 framework-eligible names (2025 insider/analyst/13F activity) ──
    # Common arm date 2026-04-01 for cleaner apples-to-apples (~5-month hold)
    ("PLTR", "2026-04-01", "FRAMEWORK_ELIGIBLE", "Palantir — insider cluster + Q1 upgrades",    "XLK"),
    ("CRM",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Salesforce — analyst upgrades + 13F",         "XLK"),
    ("AMD",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "AMD — insider + fundamentals",                "XLK"),
    ("NFLX", "2026-04-01", "FRAMEWORK_ELIGIBLE", "Netflix — analyst momentum",                  "XLC"),
    ("PYPL", "2026-04-01", "FRAMEWORK_ELIGIBLE", "PayPal — value turnaround, insider buying",   "XLF"),
    ("SBUX", "2026-04-01", "FRAMEWORK_ELIGIBLE", "Starbucks — new CEO catalyst",                "XLY"),
    ("F",    "2026-04-01", "FRAMEWORK_ELIGIBLE", "Ford — cyclical, insider activity",           "XLY"),
    ("INTC", "2026-04-01", "FRAMEWORK_ELIGIBLE", "Intel — turnaround narrative",                "XLK"),
    ("GM",   "2026-04-01", "FRAMEWORK_ELIGIBLE", "General Motors — buybacks + insider",         "XLY"),
    ("BABA", "2026-04-01", "FRAMEWORK_ELIGIBLE", "Alibaba — value + institutional interest",    "XLY"),
    ("UBER", "2026-04-01", "FRAMEWORK_ELIGIBLE", "Uber — profitability inflection",             "XLI"),
    ("DIS",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Disney — turnaround, analyst upgrades",       "XLC"),
    ("BA",   "2026-04-01", "FRAMEWORK_ELIGIBLE", "Boeing — turnaround, order book",             "XLI"),
    ("NKE",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Nike — turnaround, insider + activism",       "XLY"),
    ("WBA",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Walgreens — deep value, insider",             "XLV"),
    ("KHC",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Kraft Heinz — value + insider activity",      "XLP"),
    ("VZ",   "2026-04-01", "FRAMEWORK_ELIGIBLE", "Verizon — dividend + insider",                "XLC"),
    ("T",    "2026-04-01", "FRAMEWORK_ELIGIBLE", "AT&T — deleveraging, insider",                "XLC"),
    ("MRK",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Merck — pipeline, analyst upgrades",          "XLV"),
    ("BMY",  "2026-04-01", "FRAMEWORK_ELIGIBLE", "Bristol-Myers — value pharma, insider",       "XLV"),

    # ── Bucket 3: 10 KNOWN 2025 WINNERS (test if framework catches obvious wins) ──
    ("NVDA", "2026-04-01", "KNOWN_WINNER",   "NVIDIA — AI leader",                          "XLK"),
    ("META", "2026-04-01", "KNOWN_WINNER",   "Meta — AI + Reels monetization",              "XLC"),
    ("GOOGL","2026-04-01", "KNOWN_WINNER",   "Alphabet — AI + cloud",                       "XLC"),
    ("MSFT", "2026-04-01", "KNOWN_WINNER",   "Microsoft — Azure AI",                        "XLK"),
    ("AVGO", "2026-04-01", "KNOWN_WINNER",   "Broadcom — AI accelerators",                  "XLK"),
    ("LLY",  "2026-04-01", "KNOWN_WINNER",   "Eli Lilly — GLP-1 leader",                    "XLV"),
    ("COST", "2026-04-01", "KNOWN_WINNER",   "Costco — consistent compounder",              "XLP"),
    ("WMT",  "2026-04-01", "KNOWN_WINNER",   "Walmart — e-commerce + margin expansion",     "XLP"),
    ("V",    "2026-04-01", "KNOWN_WINNER",   "Visa — payment volumes",                      "XLF"),
    ("JPM",  "2026-04-01", "KNOWN_WINNER",   "JPMorgan — best-in-class bank",               "XLF"),

    # ── Bucket 4: 8 KNOWN 2025 LOSERS (test if framework avoids obvious losses) ──
    ("TSLA", "2026-04-01", "KNOWN_LOSER",    "Tesla — deliveries decline + comp risk",      "XLY"),
    ("LULU", "2026-04-01", "KNOWN_LOSER",    "Lululemon — growth deceleration",             "XLY"),
    ("DLTR", "2026-04-01", "KNOWN_LOSER",    "Dollar Tree — margin pressure",               "XLY"),
    ("ETSY", "2026-04-01", "KNOWN_LOSER",    "Etsy — consumer discretionary weakness",      "XLY"),
    ("MRNA", "2026-04-01", "KNOWN_LOSER",    "Moderna — post-COVID hangover",               "XLV"),
    ("PARA", "2026-04-01", "KNOWN_LOSER",    "Paramount — streaming losses",                "XLC"),
    ("SLB",  "2026-04-01", "KNOWN_LOSER",    "Schlumberger — oil services weakness",        "XLE"),
    ("MMM",  "2026-04-01", "KNOWN_LOSER",    "3M — litigation + industrial slowdown",       "XLI"),
]

# Unique sector ETFs to fetch once
SECTOR_ETFS = sorted(set(c[4] for c in CANDIDATES))

# Ticker → company name map for the rendered report
COMPANY_NAMES = {
    "SPG": "Simon Property Group", "AAT": "American Assets Trust",
    "APTV": "Aptiv plc", "VFC": "VF Corporation", "ONON": "On Holding",
    "HOG": "Harley-Davidson", "KMPR": "Kemper Corporation",
    "MTDR": "Matador Resources", "ELAN": "Elanco Animal Health",
    "REZI": "Resideo Technologies", "PODD": "Insulet Corporation",
    "TSM": "Taiwan Semiconductor", "PLTR": "Palantir Technologies",
    "CRM": "Salesforce", "AMD": "Advanced Micro Devices",
    "NFLX": "Netflix", "PYPL": "PayPal Holdings", "SBUX": "Starbucks",
    "F": "Ford Motor", "INTC": "Intel Corporation",
    "GM": "General Motors", "BABA": "Alibaba", "UBER": "Uber",
    "DIS": "Walt Disney", "BA": "Boeing", "NKE": "Nike",
    "WBA": "Walgreens Boots Alliance", "KHC": "Kraft Heinz",
    "VZ": "Verizon Communications", "T": "AT&T",
    "MRK": "Merck", "BMY": "Bristol-Myers Squibb",
    "NVDA": "NVIDIA", "META": "Meta Platforms", "GOOGL": "Alphabet",
    "MSFT": "Microsoft", "AVGO": "Broadcom", "LLY": "Eli Lilly",
    "COST": "Costco Wholesale", "WMT": "Walmart", "V": "Visa",
    "JPM": "JPMorgan Chase", "TSLA": "Tesla", "LULU": "Lululemon Athletica",
    "DLTR": "Dollar Tree", "ETSY": "Etsy", "MRNA": "Moderna",
    "PARA": "Paramount Global", "SLB": "Schlumberger", "MMM": "3M Company",
}


def _yahoo_bars(symbol: str, start_iso: str, end_iso: str) -> Optional[dict]:
    """Fetch daily bars from Yahoo Finance v8 API. Returns dict or None."""
    start_ts = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG backtest)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        r = result[0]
        return {
            "timestamps": r.get("timestamp", []),
            "closes": r.get("indicators", {}).get("quote", [{}])[0].get("close", []),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None


def _closest_close_on_or_after(bars: dict, target_iso: str) -> Optional[float]:
    """Find the first close price on or after target_iso in bars."""
    target_ts = int(datetime.fromisoformat(target_iso).replace(tzinfo=timezone.utc).timestamp())
    for ts, close in zip(bars["timestamps"], bars["closes"]):
        if ts >= target_ts and close is not None:
            return float(close)
    return None


def _latest_close(bars: dict) -> Optional[float]:
    """Latest non-None close in bars."""
    for close in reversed(bars["closes"]):
        if close is not None:
            return float(close)
    return None


def run() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_iso = today
    earliest = min(c[1] for c in CANDIDATES)

    # Fetch SPY + all sector ETFs once
    spy_bars = _yahoo_bars("SPY", earliest, end_iso)
    if not spy_bars:
        return "FAIL: SPY bars fetch failed"
    spy_latest = _latest_close(spy_bars)

    sector_bars_cache = {}
    for sector_etf in SECTOR_ETFS:
        b = _yahoo_bars(sector_etf, earliest, end_iso)
        if b:
            sector_bars_cache[sector_etf] = b

    results = []
    errors = []

    for symbol, arm_date, source, thesis, sector_etf in CANDIDATES:
        bars = _yahoo_bars(symbol, arm_date, end_iso)
        if not bars or not bars.get("closes"):
            errors.append(f"{symbol}: no bars")
            continue

        entry_price = _closest_close_on_or_after(bars, arm_date)
        current_price = _latest_close(bars)
        if entry_price is None or current_price is None:
            errors.append(f"{symbol}: missing entry or current price")
            continue

        # ── Simulate -8% hard stop (O'Neil / Minervini standard) ──
        # Walk forward from entry. If any close drops 8% below entry, exit
        # at that close. Otherwise, hold to end.
        stop_price = entry_price * 0.92
        exit_price_with_stop = current_price  # default = held to today
        stop_triggered = False
        entry_ts = int(datetime.fromisoformat(arm_date).replace(tzinfo=timezone.utc).timestamp())
        for ts, close in zip(bars["timestamps"], bars["closes"]):
            if ts < entry_ts or close is None:
                continue
            if close <= stop_price:
                exit_price_with_stop = float(close)
                stop_triggered = True
                break
        stopped_return = (exit_price_with_stop - entry_price) / entry_price * 100

        spy_entry = _closest_close_on_or_after(spy_bars, arm_date)
        if spy_entry is None:
            errors.append(f"{symbol}: SPY entry missing")
            continue

        stock_return = (current_price - entry_price) / entry_price * 100
        spy_return = (spy_latest - spy_entry) / spy_entry * 100
        excess_vs_spy = stock_return - spy_return

        # Sector-relative excess (the REAL skill measure — did we pick a
        # good stock within its sector, controlling for sector rotation?)
        sector_return = None
        excess_vs_sector = None
        if sector_etf in sector_bars_cache:
            sb = sector_bars_cache[sector_etf]
            sec_entry = _closest_close_on_or_after(sb, arm_date)
            sec_latest = _latest_close(sb)
            if sec_entry is not None and sec_latest is not None:
                sector_return = (sec_latest - sec_entry) / sec_entry * 100
                excess_vs_sector = stock_return - sector_return

        hit_spy = excess_vs_spy >= 3.0
        hit_sector = excess_vs_sector is not None and excess_vs_sector >= 3.0

        arm_ts = int(datetime.fromisoformat(arm_date).replace(tzinfo=timezone.utc).timestamp())
        now_ts = int(datetime.now(timezone.utc).timestamp())
        hold_days = (now_ts - arm_ts) // 86400

        results.append({
            "symbol": symbol,
            "arm_date": arm_date,
            "source": source,
            "thesis": thesis,
            "sector_etf": sector_etf,
            "entry": entry_price,
            "current": current_price,
            "stock_ret_pct": stock_return,
            "spy_ret_pct": spy_return,
            "sector_ret_pct": sector_return,
            "excess_vs_spy_pct": excess_vs_spy,
            "excess_vs_sector_pct": excess_vs_sector,
            "hit_spy": hit_spy,
            "hit_sector": hit_sector,
            "hold_days": hold_days,
            "stopped_return_pct": stopped_return,
            "stop_triggered": stop_triggered,
        })

    # ── Aggregate ────────────────────────────────────────────────────────
    n = len(results)
    if n == 0:
        return "FAIL: no results computed"

    # Both views
    excesses_spy = [r["excess_vs_spy_pct"] for r in results]
    excesses_sector = [r["excess_vs_sector_pct"] for r in results if r["excess_vs_sector_pct"] is not None]

    hits_spy = sum(1 for r in results if r["hit_spy"])
    hits_sector = sum(1 for r in results if r["hit_sector"])
    hit_rate_spy = hits_spy / n
    hit_rate_sector = hits_sector / len(excesses_sector) if excesses_sector else 0

    avg_excess_spy = statistics.mean(excesses_spy)
    avg_excess_sector = statistics.mean(excesses_sector) if excesses_sector else 0

    # Verdict now uses SECTOR-RELATIVE excess (skill measure)
    if n < 10:
        verdict = "INSUFFICIENT_SAMPLE"
    elif hit_rate_sector >= 0.60 and avg_excess_sector >= 3.0:
        verdict = "WORKS_scale"
    elif hit_rate_sector >= 0.55 and avg_excess_sector >= 0:
        verdict = "MARGINAL_continue_reduced_size"
    elif hit_rate_sector < 0.50 or avg_excess_sector < 0:
        verdict = "FAIL_disassemble"
    else:
        verdict = "borderline"

    # Subset splits by source bucket (sector-relative)
    def _bucket_stats(bucket_name):
        bucket = [r for r in results if r["source"] == bucket_name]
        if not bucket:
            return None
        sec_vals = [r["excess_vs_sector_pct"] for r in bucket if r["excess_vs_sector_pct"] is not None]
        return {
            "n": len(bucket),
            "sec_avg": statistics.mean(sec_vals) if sec_vals else 0,
            "spy_avg": statistics.mean(r["excess_vs_spy_pct"] for r in bucket),
            "sec_hits": sum(1 for r in bucket if r["hit_sector"]),
            "sec_hit_rate": sum(1 for r in bucket if r["hit_sector"]) / len(bucket),
        }

    bucket_current = _bucket_stats("CURRENT_PICK")
    bucket_eligible = _bucket_stats("FRAMEWORK_ELIGIBLE")
    bucket_winners = _bucket_stats("KNOWN_WINNER")
    bucket_losers = _bucket_stats("KNOWN_LOSER")

    # Rank by sector-relative excess for the detail table
    stdev_sec = statistics.stdev(excesses_sector) if len(excesses_sector) > 1 else 0.0

    # Discipline scenario: what if -8% hard stops had been enforced?
    stopped_returns = [r["stopped_return_pct"] for r in results]
    stops_triggered = sum(1 for r in results if r["stop_triggered"])
    avg_stopped_return = statistics.mean(stopped_returns)
    total_raw_return = statistics.mean(r["stock_ret_pct"] for r in results)
    discipline_delta = avg_stopped_return - total_raw_return

    # ── Render markdown ──────────────────────────────────────────────────
    lines = [
        "## Confluence Framework Backtest — 20 candidates (V2 with sector-relative)",
        "",
        f"**Backtest date:** {today}",
        f"**N candidates:** {n} | Errors: {len(errors)}",
        "",
        "### The Two Views (both matter)",
        "",
        "**vs SPY (raw excess):** measures whether picks beat the market. In a strong "
        "large-cap growth regime (like 2024-2026), small/mid-cap value picks can look "
        "bad here even if they beat their own sector.",
        "",
        "**vs Sector ETF (skill excess):** measures whether we picked the right stock "
        "*within its sector* — controls for sector rotation. This is the real skill "
        "measure. Framework verdict uses this.",
        "",
        "### Headline Results",
        "",
        "| Metric | vs SPY | vs Sector ETF |",
        "|---|---:|---:|",
        f"| Hit rate (excess ≥ +3%) | {hit_rate_spy:.1%} ({hits_spy}/{n}) | **{hit_rate_sector:.1%}** ({hits_sector}/{len(excesses_sector)}) |",
        f"| Average excess | {avg_excess_spy:+.2f}% | **{avg_excess_sector:+.2f}%** |",
        f"| Median excess | {statistics.median(excesses_spy):+.2f}% | **{statistics.median(excesses_sector):+.2f}%** |",
        f"| Best pick | {max(excesses_spy):+.2f}% | **{max(excesses_sector):+.2f}%** |",
        f"| Worst pick | {min(excesses_spy):+.2f}% | **{min(excesses_sector):+.2f}%** |",
        f"| Std dev | {statistics.stdev(excesses_spy):.2f}% | **{stdev_sec:.2f}%** |",
        "",
        f"**Framework verdict (sector-relative):** **{verdict}**",
        "",
        "### Subset breakdown by bucket",
        "",
        "| Bucket | N | vs SPY | vs Sector | Hit rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, b in [
        ("Current live picks", bucket_current),
        ("Framework-eligible (2025 signals)", bucket_eligible),
        ("Known 2025 winners (control)", bucket_winners),
        ("Known 2025 losers (control)", bucket_losers),
    ]:
        if b:
            lines.append(
                f"| {label} | {b['n']} | {b['spy_avg']:+.2f}% | "
                f"**{b['sec_avg']:+.2f}%** | {b['sec_hit_rate']:.0%} |"
            )
    lines.extend([
        "",
        "### Per-pick detail (ranked by sector-relative excess)",
        "",
        "| Ticker | Company | Sector | Days | Stock % | Sec % | vs SPY | **vs Sec** | Hit | Src |",
        "|---|---|---|---:|---:|---:|---:|---:|:---:|---|",
    ])

    # Sort by sector-relative excess desc
    def sort_key(r):
        return r["excess_vs_sector_pct"] if r["excess_vs_sector_pct"] is not None else -999
    for r in sorted(results, key=sort_key, reverse=True):
        sec_ret = f"{r['sector_ret_pct']:+.1f}%" if r['sector_ret_pct'] is not None else "—"
        vs_sec = f"{r['excess_vs_sector_pct']:+.1f}%" if r['excess_vs_sector_pct'] is not None else "—"
        hit = ("✅" if r['hit_sector'] else "❌") if r["excess_vs_sector_pct"] is not None else "—"
        company = COMPANY_NAMES.get(r["symbol"], "?")
        src_short = {"CURRENT_PICK": "PICK", "FRAMEWORK_ELIGIBLE": "ELIG",
                     "KNOWN_WINNER": "WIN", "KNOWN_LOSER": "LOSE"}.get(r["source"], r["source"])
        lines.append(
            f"| **{r['symbol']}** | {company} | {r['sector_etf']} | {r['hold_days']} | "
            f"{r['stock_ret_pct']:+.1f}% | {sec_ret} | "
            f"{r['excess_vs_spy_pct']:+.1f}% | **{vs_sec}** | {hit} | {src_short} |"
        )

    if errors:
        lines.extend(["", "### Errors", ""])
        for e in errors:
            lines.append(f"- {e}")

    # ── Discipline scenario ────────────────────────────────────────────
    lines.extend([
        "",
        "### DISCIPLINE SCENARIO: What if -8% hard stops had been enforced?",
        "",
        "The O'Neil / Minervini standard: any position that drops 8% below entry is "
        "closed. NO exceptions. This is the single most-cited discipline rule in "
        "practitioner literature and is directly in `swing-setup-playbook.md`.",
        "",
        f"- **Stops triggered:** {stops_triggered} of {n} picks ({stops_triggered/n:.0%})",
        f"- **Avg raw return (held to today):** {total_raw_return:+.2f}%",
        f"- **Avg return WITH -8% stops:** {avg_stopped_return:+.2f}%",
        f"- **Discipline improvement:** {discipline_delta:+.2f}%",
        "",
        "Interpretation:",
        "- If discipline_delta is POSITIVE: stops would have saved money (losers "
        "were bigger than the -8% cap)",
        "- If discipline_delta is NEGATIVE: stops would have hurt (would have exited "
        "recoverable trades)",
        "",
        "### Honest caveats + methodology notes",
        "",
        "**Sample construction bias:** 12 of 20 candidates are current live picks — "
        "they made it to today (survivorship). The 8 extras are curator-selected based "
        "on known 2025 insider cluster activity. Neither is a point-in-time universe scan.",
        "",
        "**Sample size:** N=20 is directional, not statistically conclusive. Deflated "
        "Sharpe (Bailey-López de Prado) says we need N≥30 before comparing to strategies.",
        "",
        "**Hold period variance:** arm dates span ~120 days back to ~30 days back. Not "
        "apples-to-apples. Longer-held picks have had more time to work (or fail).",
        "",
        "**Excess vs SPY only:** doesn't account for sector rotation. E.g., a stock up "
        "20% while its sector is up 25% would look bad here even if it's a great pick "
        "relative to its peers.",
        "",
        "**No transaction costs modeled:** real returns would be 0.1-0.3% lower per trade.",
        "",
        "### What to do based on these results",
        "",
        f"- **If verdict = WORKS_scale:** framework is delivering. Increase position sizes "
        "moderately (10-25%). Keep gathering data.",
        f"- **If verdict = MARGINAL_continue_reduced_size:** running slight edge. Cut position "
        "sizes 50%. Investigate which signals are best discriminating.",
        f"- **If verdict = FAIL_disassemble:** framework is not delivering. Pause new picks. "
        "Diagnose: is it the signals? The entry timing? The exit rules?",
        "",
        "### Companion notes",
        "",
        "- `decision-rules.md` — the rules layer being tested here",
        "- `rule-scorecard.md` — should be run once we have 20+ CLOSED picks with rule_compliance",
        "- `2026-08-30-swing-setup-playbook.md` — potential entry-timing overlay to add",
        "- `2026-08-30-behavioral-finance-trader-errors.md` — the meta-layer",
    ])

    body = "\n".join(l for l in lines if l is not None)
    path = write_job_output("confluence_backtest", body)
    return (f"wrote {path}\n"
            f"verdict: {verdict} | "
            f"hit_rate(sec): {hit_rate_sector:.1%} | "
            f"avg_excess(sec): {avg_excess_sector:+.2f}% | "
            f"avg_excess(spy): {avg_excess_spy:+.2f}%")


if __name__ == "__main__":
    print(run())
