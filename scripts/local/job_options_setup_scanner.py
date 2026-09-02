"""Technical options setup scanner.

Loop over the setups defined in setups.yaml. For each:
  1. Pull bars for every underlying in the setup's universe.
  2. Compute indicators (RSI, MACD, BB, VWAP, ATR, SMA, EMA, Stoch).
  3. Evaluate the setup's condition on the latest bar.
  4. For each firing underlying: pick the target contract via delta+DTE.
  5. Write a per-run report to the Obsidian vault under research/options-setups/.
  6. Log each firing to a compact JSONL log for later backtesting.

Per §L1 local-first: runs on Mac via launchd, zero Railway cost.
Per §V0 destructive-op safety: signals only — no order submission from this job.
Per §M1: expected identity is documented inline for each setup's condition and picker.

Usage:
  python3 scripts/local/job_options_setup_scanner.py
  python3 scripts/local/job_options_setup_scanner.py --dry-run   # skip vault write
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Enable importing sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import yaml  # type: ignore

import _alpaca_options as ao
from _ta_indicators import compute_all
from _obsidian import write_job_output


SETUPS_PATH = Path(__file__).parent / "setups.yaml"
LOG_PATH = Path.home() / ".bmg_options_setups.jsonl"


def load_setups() -> List[Dict[str, Any]]:
    with open(SETUPS_PATH) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("setups", [])


def bars_to_df(bars: list[dict]) -> pd.DataFrame:
    """Convert Alpaca bars response to a pandas DataFrame."""
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "t": b["t"],
        "open": b["o"],
        "high": b["h"],
        "low": b["l"],
        "close": b["c"],
        "volume": b["v"],
    } for b in bars])
    df["t"] = pd.to_datetime(df["t"])
    df = df.set_index("t").sort_index()
    return df


def eval_condition(condition: str, row: pd.Series, prev: pd.Series,
                   extras: Dict[str, Any]) -> tuple[bool, str]:
    """Evaluate a setup's condition expression against latest + prev bar.

    Returns (fired, reason_string).
    """
    scope = {}
    # Latest bar variables
    for k, v in row.items():
        scope[k] = float(v) if pd.notna(v) else float("nan")
    # Prev bar variables (prev_close, prev_rsi_14, prev_macd, prev_macd_signal, ...)
    for k, v in prev.items():
        scope[f"prev_{k}"] = float(v) if pd.notna(v) else float("nan")
    # Extras (like bb_bandwidth_pctile20)
    scope.update(extras)
    # NaN safety: any comparison with NaN -> False
    scope["nan"] = float("nan")

    try:
        fired = bool(eval(condition, {"__builtins__": {}}, scope))
        reason = f"condition={condition!r} evaluated True"
        return fired, reason
    except Exception as e:
        return False, f"eval error: {e}"


def scan_setup(setup: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run one setup across its universe. Returns list of fired signals."""
    fired: List[Dict[str, Any]] = []
    condition = setup["condition"]
    universe = setup["universe"]
    timeframe = setup.get("timeframe", "1Day")
    limit_bars = 200 if timeframe == "1Day" else 500

    for symbol in universe:
        try:
            bars = ao.get_bars(symbol, timeframe=timeframe, limit=limit_bars)
            if len(bars) < 60:
                continue
            df = bars_to_df(bars)
            df = compute_all(df)

            # Add derived percentile columns some setups reference
            # bb_bandwidth_pctile20 = 20th percentile of trailing 60 bandwidth
            df["bb_bandwidth_pctile20"] = df["bb_bandwidth"].rolling(60).quantile(0.20)

            if len(df) < 60:
                continue
            row = df.iloc[-1]
            prev = df.iloc[-2]
            extras = {
                "bb_bandwidth_pctile20": float(row.get("bb_bandwidth_pctile20", float("nan"))),
            }

            ok, reason = eval_condition(condition, row, prev, extras)
            if not ok:
                continue

            # Setup fired — pick the contract
            action = setup["action"]
            spot = float(row["close"])
            action_type = action["type"]  # buy_call, buy_put, sell_call, sell_put

            if action_type in ("buy_call", "sell_call"):
                option_type = "call"
            else:
                option_type = "put"

            contract = ao.pick_contract_by_delta(
                underlying=symbol,
                spot=spot,
                target_dte=action["target_dte"],
                option_type=option_type,
                target_delta=action["target_delta"],
                dte_tolerance=10,
            )

            fired.append({
                "setup": setup["name"],
                "symbol": symbol,
                "spot": spot,
                "timeframe": timeframe,
                "reason": reason,
                "bar_ts": row.name.isoformat() if hasattr(row.name, "isoformat") else str(row.name),
                "action": action,
                "contract": contract,
                "indicators": {
                    "rsi_14": float(row["rsi_14"]) if pd.notna(row["rsi_14"]) else None,
                    "macd": float(row["macd"]) if pd.notna(row["macd"]) else None,
                    "macd_signal": float(row["macd_signal"]) if pd.notna(row["macd_signal"]) else None,
                    "bb_pct_b": float(row["bb_pct_b"]) if pd.notna(row["bb_pct_b"]) else None,
                    "bb_bandwidth": float(row["bb_bandwidth"]) if pd.notna(row["bb_bandwidth"]) else None,
                    "atr_14": float(row["atr_14"]) if pd.notna(row["atr_14"]) else None,
                    "close": spot,
                    "sma_20": float(row["sma_20"]) if pd.notna(row["sma_20"]) else None,
                    "sma_50": float(row["sma_50"]) if pd.notna(row["sma_50"]) else None,
                },
                "ts_scanned_utc": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            print(f"  [error] {setup['name']} {symbol}: {exc}", file=sys.stderr)
    return fired


def render_report(all_fires: List[Dict[str, Any]]) -> str:
    """Render markdown report of all fires this run."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not all_fires:
        return f"# Options Setup Scanner — {now}\n\nNo setups fired.\n"

    lines = [
        f"# Options Setup Scanner — {now}",
        "",
        f"**{len(all_fires)} setup(s) fired** across {len(set(f['setup'] for f in all_fires))} unique rules and {len(set(f['symbol'] for f in all_fires))} unique underlyings.",
        "",
        "---",
        "",
    ]

    for f in all_fires:
        c = f.get("contract")
        act = f["action"]
        ind = f["indicators"]
        lines.append(f"## {f['symbol']} — {f['setup']}")
        lines.append("")
        lines.append(f"**Timeframe:** {f['timeframe']}  |  **Bar:** {f['bar_ts']}")
        lines.append(f"**Spot:** ${f['spot']:.2f}")
        lines.append("")
        lines.append("**Indicators at signal:**")
        lines.append(f"- RSI(14) = {ind.get('rsi_14'):.1f}" if ind.get("rsi_14") else "- RSI(14) = —")
        lines.append(f"- MACD = {ind.get('macd'):.3f}, signal = {ind.get('macd_signal'):.3f}" if ind.get("macd") is not None else "- MACD = —")
        lines.append(f"- BB %B = {ind.get('bb_pct_b'):.2f}, bandwidth = {ind.get('bb_bandwidth'):.4f}" if ind.get("bb_pct_b") is not None else "- BB — ")
        lines.append(f"- ATR(14) = {ind.get('atr_14'):.3f}" if ind.get("atr_14") else "- ATR = —")
        lines.append(f"- SMA20 = {ind.get('sma_20'):.2f}, SMA50 = {ind.get('sma_50'):.2f}" if ind.get("sma_20") is not None else "- SMA — ")
        lines.append("")
        lines.append(f"**Action:** {act['type'].upper()}")
        lines.append(f"- Target DTE: {act['target_dte']} days")
        lines.append(f"- Target delta: {act['target_delta']}")
        lines.append(f"- Max size: ${act['size_usd']}")
        lines.append(f"- Profit target: {act['exit_target_pct']}%  |  Stop: {act['exit_stop_pct']}%  |  Time stop: {act['exit_time_stop_hours']}h")
        lines.append("")
        if c:
            premium_cost = c["mid"] * 100
            contracts_affordable = int(act["size_usd"] / max(premium_cost, 1))
            lines.append(f"**Selected contract:**")
            lines.append(f"- `{c['occ_symbol']}`")
            lines.append(f"- Strike ${c['strike']}, {c['dte']} DTE (exp {c['expiration']})")
            lines.append(f"- Bid ${c['bid']:.2f} / Ask ${c['ask']:.2f} / Mid ${c['mid']:.2f}")
            lines.append(f"- IV {c['iv']*100:.1f}%, Delta {c['delta']}, Gamma {c['gamma']}, Theta {c['theta']}/day, Vega {c['vega']}/1% IV")
            lines.append(f"- Intrinsic ${c['intrinsic']:.2f}, Extrinsic ${max(0, c['mid']-c['intrinsic']):.2f}")
            lines.append(f"- Cost per contract: ${premium_cost:.0f}. Budget ${act['size_usd']} = **{contracts_affordable} contracts**")
        else:
            lines.append(f"**Selected contract:** NONE FOUND — chain empty at target DTE/delta")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- This is a SIGNAL scanner. No orders are submitted from this job (per §V0).")
    lines.append("- To execute, review the contract details and paste into Robinhood / Alpaca manually,")
    lines.append("  or extend this job to POST to `/admin/place-limit-mleg` once you're comfortable.")
    lines.append("- Every fire is also logged JSON-lines to `~/.bmg_options_setups.jsonl` for backtesting.")

    return "\n".join(lines)


def append_jsonl_log(fires: List[Dict[str, Any]]) -> None:
    if not fires:
        return
    with open(LOG_PATH, "a") as f:
        for fire in fires:
            f.write(json.dumps(fire, default=str) + "\n")


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    print(f"[options-scanner] starting {datetime.now(timezone.utc).isoformat()}")

    try:
        setups = load_setups()
    except Exception as e:
        print(f"[options-scanner] failed to load setups: {e}", file=sys.stderr)
        return 1

    print(f"[options-scanner] loaded {len(setups)} setups")

    all_fires: List[Dict[str, Any]] = []
    for setup in setups:
        print(f"[options-scanner] scanning {setup['name']} across {len(setup['universe'])} symbols...")
        try:
            fires = scan_setup(setup)
        except Exception as e:
            print(f"[options-scanner] setup {setup['name']} FAILED: {e}", file=sys.stderr)
            traceback.print_exc()
            continue
        if fires:
            print(f"[options-scanner]   → {len(fires)} fires: {[f['symbol'] for f in fires]}")
        all_fires.extend(fires)

    print(f"[options-scanner] TOTAL: {len(all_fires)} fires this run")

    report = render_report(all_fires)

    if not dry_run:
        try:
            path = write_job_output(
                job_name="options-setup-scanner",
                body=report,
                subdir="options-setups",
            )
            print(f"[options-scanner] report → {path}")
            append_jsonl_log(all_fires)
            print(f"[options-scanner] JSONL log → {LOG_PATH}")
        except Exception as e:
            print(f"[options-scanner] vault write failed: {e}", file=sys.stderr)
            traceback.print_exc()
    else:
        print(report[:2000])

    return 0


if __name__ == "__main__":
    sys.exit(main())
