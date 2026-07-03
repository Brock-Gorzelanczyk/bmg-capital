"""Verify each of Brock's 4 new stock bots will fire signals against real market data.

Runs each bot's strategies against yfinance-fetched bars and reports how many
symbols trigger. Analogous to the CSP verification approach used earlier.

Usage:
  .venv/bin/python scripts/test_new_stock_bots.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
import yfinance as yf

from strategy_lab.strategies import (
    gap_fade_intraday,
    orb_stocks_in_play,
    momentum_breakout,
    bull_flag_continuation,
    darvas_box_breakout,
    fifty_two_week_high_momentum,
    pead_earnings_drift,
    earnings_drift_post,
    crabel_orb,
)

PROFILES = Path(__file__).resolve().parents[1] / "strategy_lab" / "profiles"


def _load_universe(profile_name: str) -> tuple[list[str], dict]:
    cfg = yaml.safe_load((PROFILES / f"{profile_name}.yaml").read_text())
    return list(cfg["universe"]["symbols"]), cfg


def _daily_bars(symbols: list[str], period: str = "3mo") -> dict:
    """Fetch daily OHLCV bars, return {sym: [{o,h,l,c,v}]} oldest-first."""
    bars = {}
    df = yf.download(symbols, period=period, interval="1d",
                     progress=False, auto_adjust=False, group_by="ticker")
    if df is None or df.empty:
        return bars
    for sym in symbols:
        try:
            if len(symbols) == 1:
                sub = df
            else:
                sub = df[sym]
            sub = sub.dropna()
            if sub.empty:
                continue
            bars[sym] = [
                {"o": float(row.Open), "h": float(row.High),
                 "l": float(row.Low), "c": float(row.Close),
                 "v": float(row.Volume)}
                for row in sub.itertuples()
            ]
        except Exception:
            continue
    return bars


def _intraday_bars(symbols: list[str]) -> dict:
    """Fetch 5-min bars for last 5 trading days (yfinance limit for 5m)."""
    bars = {}
    df = yf.download(symbols, period="5d", interval="5m",
                     progress=False, auto_adjust=False, group_by="ticker")
    if df is None or df.empty:
        return bars
    for sym in symbols:
        try:
            if len(symbols) == 1:
                sub = df
            else:
                sub = df[sym]
            sub = sub.dropna()
            if sub.empty:
                continue
            bars[sym] = [
                {"o": float(row.Open), "h": float(row.High),
                 "l": float(row.Low), "c": float(row.Close),
                 "v": float(row.Volume)}
                for row in sub.itertuples()
            ]
        except Exception:
            continue
    return bars


def _test_bot(name: str, strategies: list, bars: dict, cfg: dict,
              walk_days: int = 30, min_history: int = 30) -> dict:
    """Walk through the last `walk_days` end-of-day snapshots for each symbol,
    calling generate_signals as if the bot ran at close of each day."""
    regime = {"vix_regime": "normal", "vix": 15.0}
    per_strategy = {s.STRATEGY_NAME: 0 for s in strategies}
    total_signals = []
    fire_days = set()

    max_len = max((len(b) for b in bars.values()), default=0)
    walk_days = min(walk_days, max(0, max_len - min_history))

    for offset in range(walk_days, 0, -1):
        truncated = {sym: bar_list[:-offset] if offset > 0 else bar_list
                     for sym, bar_list in bars.items()
                     if len(bar_list) - offset >= min_history}
        if not truncated:
            continue
        for strat in strategies:
            try:
                sigs = strat.generate_signals(truncated, cfg, regime) or []
            except Exception as exc:
                per_strategy[strat.STRATEGY_NAME] = f"ERROR: {exc}"
                continue
            if sigs:
                fire_days.add(offset)
                per_strategy[strat.STRATEGY_NAME] += len(sigs)
                total_signals.extend([(offset, s) for s in sigs])

    # Also test the most recent bar (end of yesterday)
    for strat in strategies:
        try:
            sigs = strat.generate_signals(bars, cfg, regime) or []
        except Exception as exc:
            per_strategy[strat.STRATEGY_NAME] = f"ERROR: {exc}"
            continue
        if sigs:
            per_strategy[strat.STRATEGY_NAME] += len(sigs)
            total_signals.extend([(0, s) for s in sigs])
            fire_days.add(0)

    return {
        "bot": name,
        "symbols_scanned": len(bars),
        "walked_days": walk_days,
        "per_strategy": per_strategy,
        "total_signals": len(total_signals),
        "days_with_fires": len(fire_days),
        "sample": [(off, s.symbol, s.side, round(s.confidence, 2), s.strategy)
                   for off, s in total_signals[:8]],
    }


def main() -> None:
    tests = [
        ("stock_gap_fade",           [gap_fade_intraday],                                  "1d"),
        ("stock_orb_breakout",       [orb_stocks_in_play, crabel_orb],                      "5m"),
        ("stock_momentum_breakout",  [momentum_breakout, bull_flag_continuation,
                                      darvas_box_breakout, fifty_two_week_high_momentum],   "1d"),
        ("stock_pead",               [pead_earnings_drift, earnings_drift_post],            "1d"),
    ]

    results = []
    for profile, strategies, tf in tests:
        symbols, cfg = _load_universe(profile)
        print(f"\n>>> {profile}: fetching {tf} bars for {len(symbols)} symbols…")
        if tf == "5m":
            bars = _intraday_bars(symbols)
        else:
            # momentum_breakout needs >=21 bars; give 6mo for max coverage
            period = "1y" if profile in ("stock_momentum_breakout", "stock_pead") else "3mo"
            bars = _daily_bars(symbols, period=period)
        res = _test_bot(profile, strategies, bars, cfg)
        results.append(res)
        print(f"    scanned {res['symbols_scanned']} sym, walked {res['walked_days']} days, "
              f"{res['days_with_fires']} days had fires, {res['total_signals']} total signals")
        for k, v in res["per_strategy"].items():
            print(f"      - {k}: {v}")
        for off, sym, side, conf, strat in res["sample"]:
            print(f"      day -{off:>2}  {sym:<6} {side:<4} conf={conf:.2f} ({strat})")

    print("\n" + "=" * 60)
    print("SUMMARY — signals expected to fire in a real intraday scan")
    print("=" * 60)
    for r in results:
        status = "✓" if r["total_signals"] > 0 else ("~" if r["symbols_scanned"] > 0 else "✗")
        print(f"  {status} {r['bot']:<28} {r['total_signals']:>3} signals across "
              f"{r['symbols_scanned']:>2} symbols")

    ready = sum(1 for r in results if r["total_signals"] > 0 or r["symbols_scanned"] > 0)
    print(f"\n{ready}/{len(results)} bots have working data pipelines.")


if __name__ == "__main__":
    main()
