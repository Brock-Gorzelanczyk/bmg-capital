"""Options flow scanner — DIY Unusual Whales alternative on Alpaca free data.

Scans a universe of tickers for unusual options activity, ranks by composite
score (vol_ratio × log(volume) × direction_agreement, with new-positioning
bonus if vol > OI), publishes a daily digest to the Obsidian vault, and
appends every flag to a JSONL log for later backtesting.

Load-bearing constraint from research/25:
  Raw flow-following is NEGATIVE alpha at retail latency (Blocher 2020).
  This job produces FLAGS, not TRADES. Every flag is a CONFLUENCE input.
  The historical log at ~/.bmg_options_flow.jsonl is BMG's proprietary
  edge — after 90 days we can backtest whether these flags predict
  returns AT OUR LATENCY.

Runs locally per §L1 (no Railway cost). Register in schedule.yaml at
30-min intervals during market hours.

Usage:
  python3 scripts/local/job_options_flow_scanner.py               # live scan + vault write
  python3 scripts/local/job_options_flow_scanner.py --dry-run     # print only
  python3 scripts/local/job_options_flow_scanner.py --universe SPY,QQQ,AAPL  # custom
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Enable sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _options_flow as of
from _obsidian import write_job_output


# Default universe — high liquidity + high options volume
DEFAULT_UNIVERSE = [
    # Indexes
    "SPY", "QQQ", "IWM", "DIA",
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    # Momentum / high-vol names
    "AMD", "PLTR", "MSTR", "COIN", "ARM", "SMCI",
    # Semis + AI
    "AVGO", "TSM", "MU", "MRVL",
    # Consumer / other
    "NFLX", "DIS", "JPM", "BAC",
]

LOG_PATH = Path.home() / ".bmg_options_flow.jsonl"
MAX_EXPS_PER_UNDERLYING = 3   # scan nearest 3 expirations
MIN_TIER_FOR_DIGEST = "C"     # include tier C+ in digest; JSONL captures all


def next_n_fridays(n: int = 8) -> list[str]:
    """Return the next N Friday dates as 'YYYY-MM-DD' — options expiration probes."""
    today = date.today()
    exps = []
    d = today
    while len(exps) < n:
        if d.weekday() == 4 and d >= today:  # Friday
            exps.append(d.isoformat())
        d += timedelta(days=1)
    return exps


def scan_symbol(symbol: str, spot: float) -> list[dict]:
    """Scan one underlying for UOA. Returns list of flag dicts."""
    flags = []
    exps_to_check = next_n_fridays(MAX_EXPS_PER_UNDERLYING)

    for exp in exps_to_check:
        # Fetch chain within ±20% of spot to capture ITM through OTM
        try:
            chain = of.fetch_chain_snapshots(
                underlying=symbol,
                expiration=exp,
                strike_gte=spot * 0.80,
                strike_lte=spot * 1.20,
            )
        except Exception as e:
            print(f"  [{symbol}] chain fetch failed for {exp}: {e}", file=sys.stderr)
            continue

        if not chain:
            continue

        for occ_sym, snap in chain.items():
            # Extract today's cumulative volume + open interest
            # Alpaca's indicative snapshot has latestTrade; the daily bar has volume
            parsed = of.parse_occ_symbol(occ_sym)
            if not parsed:
                continue

            # Get today's bar (volume + OI)
            bars = of.fetch_option_bars(occ_sym, timeframe="1Day", limit=1)
            if not bars:
                continue
            today_bar = bars[0]
            today_volume = int(today_bar.get("v", 0))
            if today_volume < 100:
                continue  # ignore illiquid

            # Trailing 30-day avg volume
            trailing_avg = of.compute_trailing_avg_volume(occ_sym, days=30)
            if trailing_avg < 5:
                continue  # brand new contract, no baseline

            # Open interest (Alpaca sometimes exposes; else use latest snapshot)
            oi = int(snap.get("openInterest", 0) or 0)
            if oi <= 0:
                # Estimate from a prior bar if available
                bars7 = of.fetch_option_bars(occ_sym, timeframe="1Day", limit=7)
                if bars7:
                    oi = int(sum(b.get("v", 0) for b in bars7))

            # Latest quote + trade
            lq = snap.get("latestQuote", {}) or {}
            lt = snap.get("latestTrade", {}) or {}
            bid = float(lq.get("bp") or 0)
            ask = float(lq.get("ap") or 0)
            last_trade_price = float(lt.get("p") or 0)

            # Direction inference (snapshot-based, not tick-based since we
            # can't easily fetch tick-level options trades for every contract)
            direction = of.bucket_direction_via_bidask(last_trade_price, bid, ask)

            # UOA score
            uoa = of.compute_uoa_score(
                current_volume=today_volume,
                trailing_avg_volume=trailing_avg,
                open_interest=oi,
                direction=direction,
            )

            if uoa["tier"] == "none":
                continue

            flag = {
                "ts_scanned_utc": datetime.now(timezone.utc).isoformat(),
                "occ_symbol": occ_sym,
                "underlying": symbol,
                "spot_at_scan": spot,
                "expiration": parsed["expiration"],
                "right": parsed["right"],
                "strike": parsed["strike"],
                "moneyness": round(parsed["strike"] / spot, 4),
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 4) if bid > 0 and ask > 0 else None,
                "last_trade": last_trade_price,
                "today_volume": today_volume,
                "trailing_30d_avg_volume": round(trailing_avg, 1),
                "open_interest": oi,
                **uoa,
            }
            flags.append(flag)

    return flags


def render_digest(all_flags: list[dict]) -> str:
    """Render markdown digest of all flagged UOA."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"# Options Flow Scanner — {now}", ""]

    if not all_flags:
        lines.append("No UOA flags this scan.")
        lines.append("")
        lines.append("**Interpretation:** either markets are quiet, or all the ")
        lines.append("volume today is inside normal ranges. Both are informative.")
        return "\n".join(lines)

    # Split by tier
    tier_a = [f for f in all_flags if f["tier"] == "A"]
    tier_b = [f for f in all_flags if f["tier"] == "B"]
    tier_c = [f for f in all_flags if f["tier"] == "C"]

    lines.append(f"**{len(all_flags)} UOA flags** — "
                 f"Tier A: {len(tier_a)} | Tier B: {len(tier_b)} | Tier C: {len(tier_c)}")
    lines.append("")
    lines.append("**Reading:** each flag = a contract with unusual volume today. ")
    lines.append("Tier A = high conviction (vol > 5x avg, > 1000 contracts). ")
    lines.append("Direction = BUY (fill near ask) / SELL (near bid) / MID (unclear).")
    lines.append("")
    lines.append("**RULE (per research/22 + research/25):** DO NOT enter on UOA alone. ")
    lines.append("Raw flow-following is negative alpha at retail latency. Use as ")
    lines.append("CONFLUENCE input on top of 13F / insider / chart pattern.")
    lines.append("")

    for tier_label, tier_flags in [("A", tier_a), ("B", tier_b), ("C", tier_c)]:
        if not tier_flags:
            continue
        lines.append(f"## Tier {tier_label} — {len(tier_flags)} flags")
        lines.append("")
        lines.append("| Symbol | Contract | Type | Strike | Exp | Vol | Vol/Avg | OI | Dir | Mid | Score |")
        lines.append("|--------|----------|------|--------|-----|-----|---------|----|----|-----|-------|")
        # Sort by score desc within tier
        for f in sorted(tier_flags, key=lambda x: -x["composite_score"]):
            lines.append(
                f"| {f['underlying']} "
                f"| `{f['occ_symbol']}` "
                f"| {f['right'].upper()} "
                f"| ${f['strike']:.0f} "
                f"| {f['expiration']} "
                f"| {f['today_volume']:,} "
                f"| {f['vol_ratio']}x "
                f"| {f['open_interest']:,} "
                f"| {f['direction']} "
                f"| ${f['mid'] or 0:.2f} "
                f"| {f['composite_score']:.1f} |"
            )
        lines.append("")

    # Aggregated per-underlying summary
    lines.append("## Per-underlying summary")
    lines.append("")
    per_underlying = {}
    for f in all_flags:
        u = f["underlying"]
        if u not in per_underlying:
            per_underlying[u] = {"n": 0, "call_bias": 0, "put_bias": 0}
        per_underlying[u]["n"] += 1
        if f["right"] == "call" and f["direction"] == "BUY":
            per_underlying[u]["call_bias"] += 1
        elif f["right"] == "put" and f["direction"] == "BUY":
            per_underlying[u]["put_bias"] += 1

    lines.append("| Underlying | Flags | Bullish (call buys) | Bearish (put buys) | Skew |")
    lines.append("|-----------|-------|--------------------|--------------------|------|")
    for u, stats in sorted(per_underlying.items(), key=lambda x: -x[1]["n"]):
        skew = stats["call_bias"] - stats["put_bias"]
        skew_str = f"+{skew}" if skew > 0 else str(skew)
        lines.append(f"| {u} | {stats['n']} | {stats['call_bias']} | {stats['put_bias']} | {skew_str} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"JSONL log: `{LOG_PATH}` ({len(all_flags)} rows appended this scan)")

    return "\n".join(lines)


def append_jsonl(flags: list[dict]) -> None:
    if not flags:
        return
    with open(LOG_PATH, "a") as f:
        for flag in flags:
            f.write(json.dumps(flag, default=str) + "\n")


def get_spot(symbol: str) -> float:
    """Get current mid price for underlying."""
    import requests
    r = requests.get(
        f"{of.DATA_BASE}/v2/stocks/{symbol}/quotes/latest",
        headers=of._headers(), timeout=10,
    )
    if r.status_code != 200:
        return 0.0
    q = r.json().get("quote", {}) or {}
    bp = float(q.get("bp") or 0)
    ap = float(q.get("ap") or 0)
    return (bp + ap) / 2 if bp > 0 and ap > 0 else 0.0


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    # Parse --universe
    universe = DEFAULT_UNIVERSE
    for i, arg in enumerate(sys.argv):
        if arg == "--universe" and i + 1 < len(sys.argv):
            universe = [s.strip().upper() for s in sys.argv[i + 1].split(",")]
            break

    print(f"[options-flow] starting {datetime.now(timezone.utc).isoformat()}")
    print(f"[options-flow] universe: {universe}")
    print(f"[options-flow] scanning up to {MAX_EXPS_PER_UNDERLYING} exps per symbol")

    all_flags: list[dict] = []
    for symbol in universe:
        try:
            spot = get_spot(symbol)
            if spot <= 0:
                print(f"[options-flow] SKIP {symbol}: no spot price")
                continue
            print(f"[options-flow] scanning {symbol} @ ${spot:.2f}...")
            flags = scan_symbol(symbol, spot)
            if flags:
                by_tier = {}
                for f in flags:
                    by_tier[f["tier"]] = by_tier.get(f["tier"], 0) + 1
                print(f"[options-flow]   → {len(flags)} flags: {by_tier}")
            all_flags.extend(flags)
        except Exception as e:
            print(f"[options-flow] FAILED {symbol}: {e}", file=sys.stderr)
            traceback.print_exc()

    print(f"[options-flow] TOTAL: {len(all_flags)} flags this scan")

    digest = render_digest(all_flags)

    if not dry_run:
        try:
            path = write_job_output(
                job_name="options-flow-scanner",
                body=digest,
                subdir="options-flow",
            )
            print(f"[options-flow] digest → {path}")
            append_jsonl(all_flags)
            print(f"[options-flow] JSONL → {LOG_PATH} (total lines in history: {sum(1 for _ in open(LOG_PATH))})")
        except Exception as e:
            print(f"[options-flow] vault write failed: {e}", file=sys.stderr)
    else:
        print("---DIGEST---")
        print(digest[:3000])

    return 0


if __name__ == "__main__":
    sys.exit(main())
