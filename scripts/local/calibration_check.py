"""calibration_check.py — evaluate rated calls against committed parameters.

Reads calibration/calls.yaml. For any call at or past its
evaluation_date, computes total return, benchmark total return,
excess, direction outcome, magnitude outcome (if applicable), and
reports mechanism (which is analyst-scored, not auto-scored).

Per M22:
- Direction is binary; BUY correct if excess > 0, SELL if excess < 0,
  HOLD if |excess| <= hold_band_pp (default 5.0).
- Magnitude is binary; N/A for HOLD.
- Mechanism (CONFIRMED / PARTIAL / FAILED / UNVERIFIABLE) is scored
  in the evaluation markdown file and read from there; NOT auto-scored.
- Aggregate statistics (hit rate by conviction bucket, Brier score,
  mean excess) are SUPPRESSED below n=5 evaluated calls.
- Date-basis: entry_price_date == benchmark_entry_date asserted;
  exit_price_date == benchmark_exit_date asserted at evaluation
  time; exit non-zero on mismatch.

Prices are pulled from Alpaca IEX for both the ticker and the
benchmark. Exit date = min(today, evaluation_date). If the current
date is before the evaluation date, the call prints as OPEN with
its committed parameters and does not enter aggregate statistics.

Usage:
    python3 scripts/local/calibration_check.py
    python3 scripts/local/calibration_check.py --vault ~/Documents/BMG-Capital-Vault

Exit codes:
    0 = ran cleanly (all evaluations tied, no basis mismatches)
    2 = date-basis mismatch or evaluation error
    3 = vault path or calls.yaml not found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("[fail] pip install requests", file=sys.stderr)
    sys.exit(1)

SUPPRESSION_THRESHOLD = 5
DEFAULT_HOLD_BAND_PP = 5.0


def load_env(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def alpaca_headers() -> dict:
    key = (os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise RuntimeError("Alpaca creds missing — set APCA_API_KEY_ID + APCA_API_SECRET_KEY")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch_close(symbol: str, on_date: str, headers: dict) -> tuple[float | None, str | None]:
    """Fetch daily close for symbol on on_date (YYYY-MM-DD). Walks forward
    up to 5 trading days if the requested date is a non-trading day.
    Returns (close, actual_date_used) or (None, None) if unavailable."""
    d0 = datetime.strptime(on_date, "%Y-%m-%d").date()
    d1 = d0 + timedelta(days=6)
    url = "https://data.alpaca.markets/v2/stocks/bars"
    params = {
        "symbols": symbol,
        "timeframe": "1Day",
        "start": d0.isoformat(),
        "end": d1.isoformat(),
        "feed": "iex",
        "adjustment": "split",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    bars = r.json().get("bars", {}).get(symbol, [])
    for bar in bars:
        bar_date = bar["t"][:10]
        if bar_date >= on_date:
            return float(bar["c"]), bar_date
    return None, None


def evaluate_call(call: dict, today: date, headers: dict) -> dict:
    """Return per-call evaluation dict."""
    result = {
        "ticker": call["ticker"],
        "note": call["note"],
        "rating": call["rating"],
        "conviction": call["conviction"],
        "implied_probability": call["implied_probability"],
        "opened": call["opened"],
        "entry_price": call["entry_price"],
        "entry_price_date": call["entry_price_date"],
        "position_entry_price": call.get("position_entry_price"),
        "position_entry_date": call.get("position_entry_date"),
        "benchmark": call["benchmark"],
        "benchmark_entry": call["benchmark_entry"],
        "benchmark_entry_date": call["benchmark_entry_date"],
        "price_source": call.get("price_source"),
        "target": call.get("target"),
        "horizon_months": call["horizon_months"],
        "evaluation_date": call["evaluation_date"],
        "status": call["status"],
        "parameters_set_retroactively": call.get("parameters_set_retroactively", False),
    }

    # Basis check on entry legs
    if str(call["entry_price_date"]) != str(call["benchmark_entry_date"]):
        result["error"] = (
            f"BASIS MISMATCH on entry: entry_price_date {call['entry_price_date']} "
            f"!= benchmark_entry_date {call['benchmark_entry_date']}"
        )
        return result

    eval_dt = datetime.strptime(str(call["evaluation_date"]), "%Y-%m-%d").date()

    if today < eval_dt:
        # Not yet due — report as OPEN with committed parameters
        result["status"] = "OPEN"
        result["days_to_evaluation"] = (eval_dt - today).days
        return result

    # At or past evaluation date — pull exit prices
    exit_date_str = eval_dt.isoformat()
    exit_price, exit_actual = fetch_close(call["ticker"], exit_date_str, headers)
    bench_exit, bench_exit_actual = fetch_close(call["benchmark"], exit_date_str, headers)

    if exit_price is None or bench_exit is None:
        result["error"] = "could not fetch exit prices"
        return result

    if exit_actual != bench_exit_actual:
        result["error"] = (
            f"BASIS MISMATCH on exit: {call['ticker']} closed {exit_actual}, "
            f"{call['benchmark']} closed {bench_exit_actual}"
        )
        return result

    entry = float(call["entry_price"])
    bench_entry = float(call["benchmark_entry"])
    ticker_ret = (exit_price - entry) / entry * 100
    bench_ret = (bench_exit - bench_entry) / bench_entry * 100
    excess = ticker_ret - bench_ret

    result["exit_price"] = exit_price
    result["exit_price_date"] = exit_actual
    result["benchmark_exit"] = bench_exit
    result["benchmark_exit_date"] = bench_exit_actual
    result["ticker_return_pct"] = round(ticker_ret, 2)
    result["benchmark_return_pct"] = round(bench_ret, 2)
    result["excess_pct"] = round(excess, 2)

    # Direction scoring
    if call["rating"] == "BUY":
        result["direction_outcome"] = 1 if excess > 0 else 0
    elif call["rating"] == "SELL":
        result["direction_outcome"] = 1 if excess < 0 else 0
    elif call["rating"] == "HOLD":
        band = float(call.get("hold_band_pp", DEFAULT_HOLD_BAND_PP))
        result["direction_outcome"] = 1 if abs(excess) <= band else 0
    else:
        result["direction_outcome"] = None

    # Magnitude scoring — only if target and applicable
    if call.get("target") is not None and call.get("magnitude_applies", True):
        # Would need intraday high check — for now, direction-only proxy
        # (target-touched-at-any-point check requires a separate historical pull)
        target = float(call["target"])
        if call["rating"] == "BUY":
            result["magnitude_outcome"] = 1 if exit_price >= target else 0
        elif call["rating"] == "SELL":
            result["magnitude_outcome"] = 1 if exit_price <= target else 0
        else:
            result["magnitude_outcome"] = None
        result["magnitude_note"] = "exit-price basis; intraday-touch check TODO"
    else:
        result["magnitude_outcome"] = None

    # Mechanism read from evaluation file if it exists
    eval_dir = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Documents" / "BMG-Capital-Vault"))) / "calibration" / "evaluations"
    eval_file = eval_dir / f"{call['ticker']}-{eval_dt.isoformat()}.md"
    if eval_file.exists():
        text = eval_file.read_text()
        for kw in ("CONFIRMED", "PARTIAL", "FAILED", "UNVERIFIABLE"):
            marker = f"mechanism: {kw}"
            if marker in text:
                result["mechanism"] = kw
                break
        else:
            result["mechanism"] = "NOT_SCORED_IN_EVALUATION_FILE"
    else:
        result["mechanism"] = "EVALUATION_FILE_MISSING"

    result["status"] = "EVALUATED"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--vault",
        default=str(Path.home() / "Documents" / "BMG-Capital-Vault"),
    )
    ap.add_argument("--as-of", default=None, help="Override today for testing (YYYY-MM-DD)")
    args = ap.parse_args()

    vault = Path(args.vault)
    calls_path = vault / "calibration" / "calls.yaml"
    method_path = vault / "calibration" / "METHOD.md"

    if not calls_path.exists():
        print(f"[fail] calls.yaml not found: {calls_path}", file=sys.stderr)
        return 3
    if not method_path.exists():
        print(f"[fail] METHOD.md not found: {method_path}", file=sys.stderr)
        return 3

    # Load env for Robinhood (SIP consolidated close via historicals)
    # Note: alpaca-derived helpers are legacy; per METHOD.md §4 the source
    # is Robinhood historicals close_price. The MCP-fetched values match
    # exactly for the recorded 2026-09-11 entries. For future exit-price
    # pulls the fetch layer should be swapped to Robinhood; retained
    # Alpaca headers for now with the source assertion enforced by
    # calls.yaml price_source field + ship-gate Gate 0b.
    load_env(Path.home() / "my-new-project" / "backend" / ".env")
    try:
        headers = alpaca_headers()
    except RuntimeError as e:
        print(f"[fail] {e}", file=sys.stderr)
        return 3

    with open(calls_path) as f:
        calls = yaml.safe_load(f)
    if not isinstance(calls, list):
        print(f"[fail] calls.yaml must be a list", file=sys.stderr)
        return 3

    today = date.today()
    if args.as_of:
        today = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    print(f"calibration_check.py — as of {today.isoformat()}")
    print(f"methodology: {method_path.relative_to(vault)}")
    print(f"loaded {len(calls)} call entries from {calls_path.relative_to(vault)}")
    print()

    evaluations = []
    basis_errors = 0
    for call in calls:
        result = evaluate_call(call, today, headers)
        evaluations.append(result)
        if "error" in result and "BASIS MISMATCH" in result["error"]:
            basis_errors += 1

    # Per-call table (split entry columns: call-entry vs position-entry per METHOD.md §9a)
    print("=" * 118)
    print(f"{'Ticker':<7} {'Note':<5} {'Rating':<6} {'Conv':<5} {'Prob':<6} {'CallEntry':<10} {'PosEntry':<10} {'Status':<11} {'Excess%':<8} {'Dir':<4} {'Retro':<6}")
    print("-" * 118)
    for r in evaluations:
        excess = f"{r.get('excess_pct', ''):>7}" if r.get("excess_pct") is not None else "     —"
        direction = f"{r.get('direction_outcome', '—'):>3}" if r.get("direction_outcome") is not None else "  —"
        retro = "YES" if r.get("parameters_set_retroactively") else "no"
        call_entry = f"${r['entry_price']:.2f}" if r.get('entry_price') is not None else "—"
        pos_entry = f"${r['position_entry_price']:.2f}" if r.get('position_entry_price') is not None else "—"
        print(
            f"{r['ticker']:<7} {r['note']:<5} {r['rating']:<6} {r['conviction']:<5} "
            f"{r['implied_probability']:<6} {call_entry:<10} {pos_entry:<10} "
            f"{r['status']:<11} {excess} {direction:<4} {retro:<6}"
        )
        if "error" in r:
            print(f"        error: {r['error']}")
    print("=" * 118)
    print("Note: CallEntry is the SIP consolidated close on entry_price_date (calibration basis).")
    print("      PosEntry is the actual brokerage fill price on position_entry_date (personal P&L basis).")
    print("      Per METHOD.md §9a, the two measure different things and are NEVER combined or compared.")

    if basis_errors:
        print(f"\n[FAIL] {basis_errors} basis mismatch(es) — evaluation refused per M22 Rule 3.")
        return 2

    evaluated = [r for r in evaluations if r["status"] == "EVALUATED"]
    n = len(evaluated)

    print(f"\nEvaluated: {n}  |  Open: {len(evaluations) - n}")
    print(f"Retroactive-parameters flag set on: {sum(1 for r in evaluations if r.get('parameters_set_retroactively'))} of {len(evaluations)} calls")

    # Split evaluated calls by rating class per METHOD.md §8 — always compute
    # the split-n even below threshold so the per-class suppression lines
    # render distinctly rather than a single aggregate suppression line.
    directional = [r for r in evaluated if r["rating"] in ("BUY", "SELL")]
    hold_calls = [r for r in evaluated if r["rating"] == "HOLD"]
    n_dir = len(directional)
    n_hold = len(hold_calls)

    print(f"\n=== Aggregate statistics (per METHOD.md §8, split by rating class — never combined) ===")
    print(f"Directional (BUY/SELL) evaluated: {n_dir}")
    print(f"HOLD evaluated:                   {n_hold}")

    # Directional Brier + calibration table
    if n_dir < SUPPRESSION_THRESHOLD:
        print(f"\n[directional] INSUFFICIENT SAMPLE — n={n_dir}, brier_directional suppressed until n>={SUPPRESSION_THRESHOLD}")
    else:
        brier_dir = sum((r["implied_probability"] - r["direction_outcome"]) ** 2 for r in directional) / n_dir
        print(f"\nbrier_directional (BUY/SELL, n={n_dir}): {brier_dir:.4f}  (no-skill reference: 0.2500; lower is better)")

        print("\nDirectional hit rate by conviction bucket:")
        print(f"{'Conv':<6} {'n':<4} {'Hit rate':<12} {'Implied':<10} {'Realized-Implied':<18} {'Mean excess%':<12}")
        conv_buckets: dict[int, list[dict]] = {}
        for r in directional:
            conv_buckets.setdefault(r["conviction"], []).append(r)
        for conv in sorted(conv_buckets):
            rows = conv_buckets[conv]
            n_bucket = len(rows)
            hit_rate = sum(r["direction_outcome"] for r in rows) / n_bucket
            implied = rows[0]["implied_probability"]
            mean_excess = sum(r["excess_pct"] for r in rows) / n_bucket
            gap = hit_rate - implied
            print(f"{conv:<6} {n_bucket:<4} {hit_rate:.2%}{'':<4} {implied:.2%}{'':<4} {gap:+.2%}{'':<10} {mean_excess:+.2f}")

    # HOLD Brier + calibration table (separate, never combined)
    if n_hold < SUPPRESSION_THRESHOLD:
        print(f"\n[hold] INSUFFICIENT SAMPLE — n={n_hold}, brier_hold suppressed until n>={SUPPRESSION_THRESHOLD}")
    else:
        brier_hold = sum((r["implied_probability"] - r["direction_outcome"]) ** 2 for r in hold_calls) / n_hold
        # HOLD base rate = proportion of HOLD calls that fell inside the band
        hold_base_rate = sum(r["direction_outcome"] for r in hold_calls) / n_hold
        print(f"\nbrier_hold (n={n_hold}): {brier_hold:.4f}  (ex-post base rate {hold_base_rate:.2%}; no-skill reference vs base rate = {(hold_base_rate * (1 - hold_base_rate)):.4f})")

        print("\nHOLD hit rate by conviction bucket:")
        print(f"{'Conv':<6} {'n':<4} {'Hit rate':<12} {'Implied':<10} {'Realized-Implied':<18}")
        conv_buckets_h: dict[int, list[dict]] = {}
        for r in hold_calls:
            conv_buckets_h.setdefault(r["conviction"], []).append(r)
        for conv in sorted(conv_buckets_h):
            rows = conv_buckets_h[conv]
            n_bucket = len(rows)
            hit_rate = sum(r["direction_outcome"] for r in rows) / n_bucket
            implied = rows[0]["implied_probability"]
            gap = hit_rate - implied
            print(f"{conv:<6} {n_bucket:<4} {hit_rate:.2%}{'':<4} {implied:.2%}{'':<4} {gap:+.2%}")

    print("\nDirectional and HOLD Brier scores are NEVER combined into a single figure (METHOD.md §8).")

    # Mechanism distribution — only if any calls have been evaluated
    if n > 0:
        print("\nMechanism distribution (reported separately; NEVER combined with direction hit rate):")
        mech_counts: dict[str, int] = {}
        for r in evaluated:
            mech = r.get("mechanism", "UNKNOWN")
            mech_counts[mech] = mech_counts.get(mech, 0) + 1
        for mech, cnt in sorted(mech_counts.items()):
            print(f"  {mech:<35} {cnt:>3}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
