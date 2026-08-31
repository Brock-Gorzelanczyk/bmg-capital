"""Peer-group backtest — sector ETFs are too coarse.

Original backtest measured excess vs sector ETF (e.g., HOG vs XLY). But XLY
is 30% Amazon — comparing Harley to Amazon isn't apples-to-apples. Real skill
measure = excess vs actual business peers (HOG vs Polaris + BRP + Yamaha).

This backtest uses a curated PEER_MAP of ~50 tickers × 4-5 direct competitors
each. For each candidate:
  1. Compute return since arm date
  2. Compute mean return of its peer group over same window
  3. Excess vs peers = stock return - peer avg return

Then compare distributions:
  - Was HOG's +18% vs XLY actually +5% vs peers? (peers rallied too)
  - Did the sector-relative measure over/under-state alpha?
  - Which picks look MORE impressive vs peers than vs sector?

Zero cost — Yahoo Finance for all pricing.
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
from _obsidian import write_job_output  # noqa: E402
from job_confluence_backtest import CANDIDATES, COMPANY_NAMES  # noqa: E402


# ── Peer group map: ticker → list of 3-5 real business competitors ──
# Curated from my knowledge of each company's real competitive set. If a
# stock is missing, the peer backtest skips it (falls back to sector-only).
PEER_MAP = {
    # Real Estate (REITs by property type)
    "SPG":  ["MAC", "KIM", "REG", "FRT", "BRX"],   # Mall/shopping REITs
    "AAT":  ["MAC", "WPC", "VNO", "SLG"],           # Mixed-use REITs
    "EQIX": ["DLR", "AMT", "CCI", "COR"],           # Data-center + tower REITs
    "DLR":  ["EQIX", "AMT", "COR", "IRM"],

    # Consumer Discretionary — Auto/Motorcycle
    "APTV": ["MGA", "BWA", "ALV", "LEA"],            # Auto parts/suppliers
    "HOG":  ["PII", "DOOO", "LCII", "THO"],          # Powersports
    "F":    ["GM", "TSLA", "STLA", "TM"],            # Auto OEMs
    "GM":   ["F", "STLA", "TM", "HMC"],
    "TSLA": ["F", "GM", "RIVN", "LCID"],

    # Consumer Discretionary — Apparel/Footwear
    "VFC":  ["COLM", "PVH", "RL", "HBI"],
    "ONON": ["NKE", "DECK", "UAA", "SKX"],
    "NKE":  ["ONON", "DECK", "LULU", "UAA"],
    "LULU": ["NKE", "ONON", "DECK", "UAA"],
    "CROX": ["DECK", "SKX", "WWW"],

    # Consumer Discretionary — Restaurants
    "SBUX": ["MCD", "DPZ", "YUM", "CMG"],
    "MCD":  ["SBUX", "DPZ", "YUM", "CMG"],
    "CHWY": ["PETQ", "EL", "AMZN"],                  # Pet retail (loose)

    # Consumer Discretionary — Retail (dying/dollar)
    "DLTR": ["DG", "FIVE", "BIG", "OLLI"],
    "GPS":  ["M", "KSS", "JWN", "URBN"],
    "KSS":  ["M", "JWN", "GPS", "DDS"],
    "M":    ["KSS", "JWN", "DDS", "GPS"],
    "CVNA": ["KMX", "AN", "PAG"],

    # Consumer Discretionary — Other
    "ETSY": ["EBAY", "W", "SHOP"],
    "SPOT": ["NFLX", "ROKU", "SIRI"],
    "HAS":  ["MAT", "FUN", "TOY"],

    # Financials — Insurance
    "KMPR": ["MET", "AIG", "CINF", "PRU"],

    # Financials — Payments
    "V":    ["MA", "PYPL", "AXP", "DFS"],
    "MA":   ["V", "PYPL", "AXP", "DFS"],
    "PYPL": ["SQ", "V", "MA", "AFRM"],

    # Financials — Banks / Broker
    "JPM":  ["BAC", "WFC", "C", "USB"],
    "MS":   ["GS", "BAC", "JPM"],
    "GS":   ["MS", "BAC", "JPM"],
    "USB":  ["JPM", "WFC", "BAC", "PNC"],
    "BLK":  ["BX", "KKR", "APO", "SCHW"],

    # Energy — E&P
    "MTDR": ["FANG", "MRO", "DVN", "APA"],
    "DVN":  ["MTDR", "FANG", "APA", "MRO"],
    "APA":  ["MTDR", "DVN", "MRO"],
    "EOG":  ["FANG", "DVN", "MRO", "OXY"],
    "SLB":  ["HAL", "BKR", "FTI", "WFRD"],
    "HAL":  ["SLB", "BKR", "FTI"],
    "KMI":  ["EPD", "MPLX", "WMB", "OKE"],

    # Healthcare — Pharma
    "ELAN": ["ZTS", "MRK", "PFE"],                   # Elanco = animal health, ZTS competitor
    "MRK":  ["PFE", "BMY", "JNJ", "LLY"],
    "BMY":  ["MRK", "PFE", "JNJ", "LLY"],
    "PFE":  ["MRK", "BMY", "JNJ", "LLY"],
    "ABBV": ["JNJ", "MRK", "PFE", "LLY"],
    "GILD": ["BIIB", "REGN", "VRTX"],
    "MRNA": ["BNTX", "NVAX", "PFE"],
    "LLY":  ["MRK", "BMY", "PFE", "NVO"],
    "UNH":  ["ANTM", "CI", "HUM"],
    "CVS":  ["WBA", "CI", "UNH", "HUM"],
    "WBA":  ["CVS", "KR", "WMT"],

    # Healthcare — Medical Devices
    "PODD": ["DXCM", "TNDM", "MDT", "ABT"],
    "ISRG": ["MDT", "ABT", "EW", "BSX"],

    # Industrials
    "REZI": ["SWK", "GTES", "ROP", "LII"],
    "BA":   ["LMT", "GD", "NOC", "RTX"],
    "LMT":  ["BA", "NOC", "GD", "RTX"],
    "RTX":  ["LMT", "NOC", "GD", "BA"],
    "DAL":  ["UAL", "AAL", "LUV", "ALK"],
    "MMM":  ["HON", "ITW", "EMR", "ROK"],
    "UBER": ["LYFT", "DASH", "ABNB"],

    # Technology — Semis
    "TSM":  ["INTC", "MU", "AMD", "ASML"],
    "INTC": ["AMD", "MU", "TSM", "QCOM"],
    "AMD":  ["NVDA", "INTC", "QCOM", "MRVL"],
    "NVDA": ["AMD", "INTC", "AVGO", "MRVL"],
    "AVGO": ["NVDA", "AMD", "QCOM", "MRVL"],
    "MU":   ["INTC", "WDC", "STX"],
    "MRVL": ["NVDA", "AVGO", "QCOM", "KLAC"],
    "KLAC": ["AMAT", "LRCX", "ASML"],
    "AMAT": ["LRCX", "KLAC", "ASML"],
    "QCOM": ["AVGO", "MRVL", "TXN", "ADI"],
    "STX":  ["WDC", "MU"],

    # Technology — Software/Cloud
    "CRM":  ["MSFT", "NOW", "WDAY", "ORCL"],
    "PLTR": ["SNOW", "NOW", "DDOG", "MSFT"],
    "NOW":  ["CRM", "MSFT", "WDAY", "ORCL"],
    "MSFT": ["GOOGL", "CRM", "ORCL", "NOW"],
    "ADBE": ["CRM", "NOW", "ORCL"],
    "SNPS": ["CDNS", "ANSS"],
    "CDNS": ["SNPS", "ANSS"],
    "IBM":  ["ORCL", "HPQ", "DXC"],
    "HPQ":  ["DELL", "IBM"],

    # Technology — Cybersecurity
    "CRWD": ["PANW", "ZS", "NET", "FTNT"],
    "PANW": ["CRWD", "ZS", "NET", "FTNT"],
    "ANET": ["CSCO", "JNPR", "CIEN"],

    # Communication Services
    "META": ["GOOGL", "SNAP", "PINS"],
    "GOOGL":["META", "MSFT", "AMZN"],
    "NFLX": ["DIS", "PARA", "WBD", "ROKU"],
    "DIS":  ["NFLX", "PARA", "WBD", "CMCSA"],
    "PARA": ["NFLX", "DIS", "WBD"],
    "WBD":  ["NFLX", "DIS", "PARA"],
    "SNAP": ["META", "PINS", "GOOGL"],
    "PINS": ["SNAP", "META"],
    "ROKU": ["NFLX", "PARA", "SPOT"],
    "SIRI": ["SPOT", "ROKU"],
    "VZ":   ["T", "TMUS"],
    "T":    ["VZ", "TMUS"],

    # Consumer Staples
    "WMT":  ["COST", "TGT", "KR"],
    "COST": ["WMT", "TGT", "KR"],
    "KHC":  ["CPB", "GIS", "K", "HRL"],

    # Materials
    # (none in current candidate set)

    # China / International
    "BABA": ["JD", "PDD", "TCEHY", "MELI"],

    # Solar
    "FSLR": ["ENPH", "SEDG", "RUN"],
}


def _yahoo_return_since(symbol: str, arm_date_iso: str) -> Optional[float]:
    """Return % between arm_date and today (or latest close)."""
    try:
        start_ts = int(datetime.fromisoformat(arm_date_iso).replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.now(timezone.utc).timestamp())
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               f"?period1={start_ts}&period2={end_ts}&interval=1d")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        return (closes[-1] - closes[0]) / closes[0] * 100
    except Exception:
        return None


def run() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Fetching per-stock + per-peer returns...")
    results = []
    fetched = 0
    for symbol, arm_date, source, thesis, sector_etf in CANDIDATES:
        stock_ret = _yahoo_return_since(symbol, arm_date)
        if stock_ret is None:
            continue

        peers = PEER_MAP.get(symbol)
        if not peers:
            # No peer group defined — skip (would fall back to sector, but that's covered elsewhere)
            continue

        # Fetch peer returns
        peer_returns = []
        for peer in peers:
            pr = _yahoo_return_since(peer, arm_date)
            if pr is not None:
                peer_returns.append(pr)

        if not peer_returns:
            continue

        peer_avg = statistics.mean(peer_returns)
        excess_vs_peers = stock_ret - peer_avg

        # Also fetch sector for comparison
        sec_ret = _yahoo_return_since(sector_etf, arm_date)
        excess_vs_sector = (stock_ret - sec_ret) if sec_ret is not None else None

        results.append({
            "symbol": symbol,
            "company": COMPANY_NAMES.get(symbol, "?"),
            "sector_etf": sector_etf,
            "source": source,
            "arm_date": arm_date,
            "stock_ret": stock_ret,
            "peers": peers,
            "peer_returns": peer_returns,
            "peer_avg": peer_avg,
            "excess_vs_peers": excess_vs_peers,
            "sec_ret": sec_ret,
            "excess_vs_sector": excess_vs_sector,
        })
        fetched += 1
        if fetched % 10 == 0:
            print(f"  {fetched} done...")

    n = len(results)
    if n == 0:
        return "FAIL: no results"

    # ── Distribution stats ──
    peer_excesses = [r["excess_vs_peers"] for r in results]
    sec_excesses = [r["excess_vs_sector"] for r in results if r["excess_vs_sector"] is not None]

    peer_hits = sum(1 for e in peer_excesses if e >= 3.0)
    sec_hits = sum(1 for e in sec_excesses if e >= 3.0)

    peer_stats = {
        "avg": statistics.mean(peer_excesses),
        "med": statistics.median(peer_excesses),
        "hit_rate": peer_hits / n,
        "std": statistics.stdev(peer_excesses) if n > 1 else 0,
    }
    sec_stats = {
        "avg": statistics.mean(sec_excesses),
        "med": statistics.median(sec_excesses),
        "hit_rate": sec_hits / len(sec_excesses),
        "std": statistics.stdev(sec_excesses) if len(sec_excesses) > 1 else 0,
    }

    # Bucket splits
    def bucket_avg(source, key):
        vals = [r[key] for r in results if r["source"] == source and r[key] is not None]
        return statistics.mean(vals) if vals else None

    # Delta: peers vs sector for each pick — where does the measure disagree most?
    for r in results:
        r["delta"] = (r["excess_vs_peers"] - r["excess_vs_sector"]) if r["excess_vs_sector"] is not None else None

    biggest_downgrades = sorted(
        [r for r in results if r["delta"] is not None],
        key=lambda x: x["delta"],
    )[:5]
    biggest_upgrades = sorted(
        [r for r in results if r["delta"] is not None],
        key=lambda x: -x["delta"],
    )[:5]

    # ── Render ──
    lines = [
        f"# Peer-Group Backtest — {today}",
        "",
        f"**N candidates with peer data:** {n} of {len(CANDIDATES)}",
        "",
        "Sector ETFs are coarse — XLY is 30% Amazon so \"HOG vs XLY\" mostly measures \"HOG vs Amazon.\"",
        "Real skill = excess vs actual business competitors. This backtest uses hand-curated peer",
        "groups (3-5 real competitors per ticker) for the true peer-relative measure.",
        "",
        "## Headline: Peer-Relative vs Sector-Relative",
        "",
        "| Metric | vs Sector ETF | **vs Peer Group** |",
        "|---|---:|---:|",
        f"| Avg excess | {sec_stats['avg']:+.2f}% | **{peer_stats['avg']:+.2f}%** |",
        f"| Median excess | {sec_stats['med']:+.2f}% | **{peer_stats['med']:+.2f}%** |",
        f"| Hit rate (≥+3%) | {sec_stats['hit_rate']:.0%} | **{peer_stats['hit_rate']:.0%}** |",
        f"| Std dev | {sec_stats['std']:.2f}% | **{peer_stats['std']:.2f}%** |",
        "",
        "**Interpretation:** if peer-relative excess is LOWER than sector-relative, our picks",
        "were actually just BENEFITING from being in a strong-sector-vs-weak-peers setup — not",
        "real skill. If peer-relative is HIGHER, then sector rotation was masking real edge.",
        "",
        "## Bucket splits (peer-relative)",
        "",
        "| Bucket | Avg vs Sector | Avg vs Peers |",
        "|---|---:|---:|",
    ]
    for bucket_name in ["CURRENT_PICK", "FRAMEWORK_ELIGIBLE", "KNOWN_WINNER", "KNOWN_LOSER"]:
        sec_avg = bucket_avg(bucket_name, "excess_vs_sector")
        peer_avg = bucket_avg(bucket_name, "excess_vs_peers")
        label = {"CURRENT_PICK": "Current live picks",
                 "FRAMEWORK_ELIGIBLE": "Framework-eligible",
                 "KNOWN_WINNER": "Known winners",
                 "KNOWN_LOSER": "Known losers"}[bucket_name]
        if peer_avg is not None:
            sec_s = f"{sec_avg:+.2f}%" if sec_avg is not None else "—"
            lines.append(f"| {label} | {sec_s} | **{peer_avg:+.2f}%** |")
    lines.append("")

    # ── Biggest delta stocks (where measures disagree) ──
    lines.extend([
        "## Where the two measures disagree most",
        "",
        "### Biggest DOWNGRADES (looked better vs sector than vs peers)",
        "",
        "These picks were flattered by sector rotation — real peer performance was worse.",
        "",
        "| Ticker | Company | vs Sector | **vs Peers** | Delta |",
        "|---|---|---:|---:|---:|",
    ])
    for r in biggest_downgrades:
        lines.append(
            f"| **{r['symbol']}** | {r['company']} | {r['excess_vs_sector']:+.1f}% | "
            f"**{r['excess_vs_peers']:+.1f}%** | {r['delta']:+.1f}% |"
        )
    lines.extend([
        "",
        "### Biggest UPGRADES (looked worse vs sector than vs peers)",
        "",
        "These picks are BETTER than they appeared — sector was dragging down a real winner.",
        "",
        "| Ticker | Company | vs Sector | **vs Peers** | Delta |",
        "|---|---|---:|---:|---:|",
    ])
    for r in biggest_upgrades:
        lines.append(
            f"| **{r['symbol']}** | {r['company']} | {r['excess_vs_sector']:+.1f}% | "
            f"**{r['excess_vs_peers']:+.1f}%** | {r['delta']:+.1f}% |"
        )

    # ── Full per-pick table ──
    lines.extend([
        "",
        "## Per-pick detail — ranked by peer-relative excess",
        "",
        "| Ticker | Company | vs Sector | **vs Peers** | Peer Avg | Peers |",
        "|---|---|---:|---:|---:|---|",
    ])
    for r in sorted(results, key=lambda x: -x["excess_vs_peers"]):
        peers_s = ", ".join(r["peers"][:4])
        sec_s = f"{r['excess_vs_sector']:+.1f}%" if r['excess_vs_sector'] is not None else "—"
        lines.append(
            f"| **{r['symbol']}** | {r['company'][:25]} | {sec_s} | "
            f"**{r['excess_vs_peers']:+.1f}%** | {r['peer_avg']:+.1f}% | {peers_s} |"
        )

    lines.extend([
        "",
        "## Methodology notes",
        "",
        f"- Peer map hand-curated for {len(PEER_MAP)} tickers (from my domain knowledge)",
        f"- 3-5 direct business competitors per ticker",
        "- Peer group = mean of peer returns over same window as candidate",
        "- Sector ETF is still fetched for baseline comparison",
        "- Skipped candidates with no defined peer group (fall back to sector-only)",
        "",
        "## Companion notes",
        "",
        "- `research/2026-08-30-confluence-framework-backtest-analysis.md` — original sector-only backtest",
        "- `research/2026-08-30-signal-ablation-study.md` — signal quality analysis",
        "- `research/2026-08-30-confluence-framework-teaching-note.md` — framework walkthrough",
    ])

    body = "\n".join(lines)
    out = Path.home() / "Documents" / "BMG-Capital-Vault" / "research" / f"{today}-peer-backtest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return (f"wrote {out}\n"
            f"n={n} | peer_avg={peer_stats['avg']:+.2f}% "
            f"(vs sector {sec_stats['avg']:+.2f}%) | "
            f"peer_hit={peer_stats['hit_rate']:.0%}")


if __name__ == "__main__":
    print(run())
