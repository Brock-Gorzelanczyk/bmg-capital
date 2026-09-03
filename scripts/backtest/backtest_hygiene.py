"""
Backtest hygiene toolkit — REQUIRED gates for any BMG backtest report.

Three checks, all must pass before a headline number can be quoted to the user:

1. LOOKAHEAD CHECK — verify signals at bar N don't change when data past bar N is removed.
   Fires on future-data leakage (e.g., using close[+1] via shift bug, or resampling that peeks ahead).

2. RECURSIVE CHECK — verify indicators at bar N are stable across different warmup lengths.
   Fires on recursive indicators (EMA, RSI-Wilder, etc.) that haven't converged with short warmup,
   causing backtest results to depend on how much history was loaded.

3. AUTO-HAIRCUT — after backtest completes, automatically compute + print:
     - Raw R
     - In-sample overfit haircut (× 0.30-0.40 per McLean-Pontiff 2016)
     - Execution cost drag (per research/36)
     - Options P&L gap (× 0.65-0.75 per research/35 + Tastytrade 40k sample)
     - Kelly-safe sizing recommendation
     - Realistic live-expectation range

Ported from Freqtrade's `lookahead-analysis` + `recursive-analysis` patterns
(see ~/repos-for-vault/freqtrade/freqtrade/optimize/analysis/{lookahead,recursive}.py).

Fixes the failure mode where Claude quotes a raw backtest number (+119R / +2338%)
without disclosure of the haircuts that turn it into a realistic +35-50R.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# 1. LOOKAHEAD CHECK
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class LookaheadReport:
    passed: bool
    n_bars_checked: int
    n_mismatches: int
    mismatched_signals: list[str] = field(default_factory=list)
    max_diff_pct: float = 0.0
    detail: str = ""


def check_lookahead(
    compute_signals_fn: Callable,
    df: pd.DataFrame,
    *args,
    sample_bars: int = 20,
    tolerance: float = 1e-6,
    signals_to_check: Optional[list[str]] = None,
    seed: int = 42,
) -> LookaheadReport:
    """
    Verify no future-data leakage in signal computation.

    Method (per Freqtrade lookahead-analysis):
    1. Compute signals on FULL df → signals_full
    2. Randomly pick sample_bars indices in the middle 50% of df
    3. For each index N:
       a. Cut df at bar N (df.iloc[:N+1])
       b. Recompute signals on the cut df → signals_cut
       c. Compare signals[N] between full and cut runs
    4. If any differ beyond tolerance → lookahead bug detected

    Returns LookaheadReport with pass/fail + which signals leaked.
    """
    rng = np.random.default_rng(seed)
    n_bars = len(df)

    # Run full-data signals once
    signals_full, _extras_full = compute_signals_fn(df, *args)

    if signals_to_check is None:
        signals_to_check = list(signals_full.keys())

    # Sample bars from middle 50% (avoid warmup edge + last-bar edge)
    lo = max(500, n_bars // 4)  # respect indicator warmup
    hi = min(n_bars - 100, 3 * n_bars // 4)
    if hi <= lo:
        return LookaheadReport(
            passed=False, n_bars_checked=0, n_mismatches=0,
            detail=f"Insufficient bars for lookahead check (n={n_bars})"
        )

    sample_indices = rng.choice(np.arange(lo, hi), size=min(sample_bars, hi - lo), replace=False)

    mismatches = []
    max_diff_pct = 0.0

    for N in sample_indices:
        df_cut = df.iloc[: N + 1].copy()
        try:
            signals_cut, _ = compute_signals_fn(df_cut, *args)
        except Exception as e:
            mismatches.append(f"bar {N}: compute_signals raised {type(e).__name__}: {e}")
            continue

        for sig_name in signals_to_check:
            if sig_name not in signals_cut:
                continue
            full_val = signals_full[sig_name].iloc[N]
            cut_val = signals_cut[sig_name].iloc[N]

            # Boolean signals: exact equality
            if pd.api.types.is_bool_dtype(signals_full[sig_name]):
                if full_val != cut_val:
                    mismatches.append(f"bar {N}: signal '{sig_name}' full={full_val} vs cut={cut_val}")
            else:
                # Numeric: check relative difference
                if pd.isna(full_val) and pd.isna(cut_val):
                    continue
                if pd.isna(full_val) or pd.isna(cut_val):
                    mismatches.append(f"bar {N}: signal '{sig_name}' NA mismatch (full={full_val}, cut={cut_val})")
                    continue
                denom = max(abs(full_val), abs(cut_val), 1e-9)
                diff_pct = abs(full_val - cut_val) / denom
                if diff_pct > tolerance:
                    mismatches.append(f"bar {N}: signal '{sig_name}' diff={diff_pct:.2%} (full={full_val:.4f} vs cut={cut_val:.4f})")
                    max_diff_pct = max(max_diff_pct, diff_pct)

    passed = len(mismatches) == 0
    detail = (
        f"✅ NO LOOKAHEAD BIAS detected in {len(signals_to_check)} signals across {len(sample_indices)} sampled bars."
        if passed else
        f"❌ LOOKAHEAD BIAS: {len(mismatches)} mismatches. First 5:\n  " + "\n  ".join(mismatches[:5])
    )
    mismatched_signals = sorted(set(m.split("'")[1] for m in mismatches if "'" in m))

    return LookaheadReport(
        passed=passed,
        n_bars_checked=len(sample_indices),
        n_mismatches=len(mismatches),
        mismatched_signals=mismatched_signals,
        max_diff_pct=max_diff_pct,
        detail=detail,
    )


# ═══════════════════════════════════════════════════════════════════════
# 2. RECURSIVE CHECK
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class RecursiveReport:
    passed: bool
    warmup_lengths_tested: list[int]
    unstable_indicators: dict[str, float] = field(default_factory=dict)  # name → max abs pct diff
    detail: str = ""


def check_recursive(
    compute_signals_fn: Callable,
    df: pd.DataFrame,
    *args,
    warmup_lengths: tuple[int, ...] = (500, 1000, 2000, 5000),
    tolerance: float = 0.005,  # 0.5% at the check bar
    check_bar_offset: int = 100,  # check bar = warmup_length + this
) -> RecursiveReport:
    """
    Verify recursive indicators (EMA/RSI/etc.) have converged with adequate warmup.

    Method (per Freqtrade recursive-analysis):
    1. For each warmup length W in warmup_lengths:
       a. Take df slice [start : start + W + check_bar_offset]
       b. Compute signals → signals_W
       c. Record signal values at the check bar (last bar of slice)
    2. Compare signal values at check bar across all W
    3. If any indicator's max pct-diff across warmups > tolerance → recursive dependency issue

    The check bar is the SAME calendar bar for each warmup (we anchor from the end).
    """
    n_bars = len(df)
    max_warmup = max(warmup_lengths)

    if n_bars < max_warmup + check_bar_offset + 100:
        return RecursiveReport(
            passed=False,
            warmup_lengths_tested=[],
            detail=f"Insufficient bars for recursive check (need {max_warmup + check_bar_offset + 100}, have {n_bars})"
        )

    # Anchor at end: check bar = n_bars - 100 (avoid last-bar edge)
    check_bar_global = n_bars - 100

    signals_at_check: dict[int, dict[str, float]] = {}

    for W in warmup_lengths:
        start = check_bar_global - W - check_bar_offset
        if start < 0:
            continue
        df_slice = df.iloc[start : check_bar_global + 1].copy()
        try:
            signals, _ = compute_signals_fn(df_slice, *args)
        except Exception as e:
            return RecursiveReport(
                passed=False, warmup_lengths_tested=list(warmup_lengths),
                detail=f"compute_signals failed at warmup {W}: {e}"
            )

        # Record last-bar values for each signal
        values = {}
        for sig_name, sig_series in signals.items():
            if len(sig_series) > 0:
                v = sig_series.iloc[-1]
                if pd.api.types.is_numeric_dtype(sig_series) and not pd.isna(v):
                    values[sig_name] = float(v)
        signals_at_check[W] = values

    # Compare across warmups
    unstable = {}
    common_signals = set.intersection(*[set(v.keys()) for v in signals_at_check.values()]) if signals_at_check else set()

    for sig_name in common_signals:
        vals = [signals_at_check[W][sig_name] for W in signals_at_check]
        if len(set(vals)) == 1:
            continue  # exact match
        max_val = max(abs(v) for v in vals) or 1e-9
        pct_diffs = [abs(v - vals[-1]) / max_val for v in vals]
        max_pct = max(pct_diffs)
        if max_pct > tolerance:
            unstable[sig_name] = max_pct

    passed = len(unstable) == 0
    detail = (
        f"✅ NO RECURSIVE INSTABILITY across warmups {list(warmup_lengths)}."
        if passed else
        f"❌ RECURSIVE INSTABILITY: {len(unstable)} indicators differ across warmup lengths. Top 5:\n  " +
        "\n  ".join(f"{k}: max diff {v:.2%}" for k, v in sorted(unstable.items(), key=lambda x: -x[1])[:5])
    )

    return RecursiveReport(
        passed=passed,
        warmup_lengths_tested=list(signals_at_check.keys()),
        unstable_indicators=unstable,
        detail=detail,
    )


# ═══════════════════════════════════════════════════════════════════════
# 3. AUTO-HAIRCUT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class HaircutReport:
    raw_r: float
    raw_trades: int
    raw_wr_pct: float
    raw_end_compound_pct: float  # at declared sizing_pct
    declared_sizing_pct: float

    # Haircuts (each is a multiplier or a delta)
    in_sample_haircut_mult: float  # e.g., 0.35 (retain 35% of raw)
    execution_cost_r: float  # -R per trade × N trades
    options_pnl_gap_mult: float  # e.g., 0.70 (options realize 70% of R-model)

    # Final estimates
    realistic_r_low: float
    realistic_r_high: float
    kelly_safe_sizing_pct: float
    realistic_annual_cagr_low: float  # at Kelly-safe sizing
    realistic_annual_cagr_high: float

    detail: str


def compute_haircut(
    raw_r: float,
    n_trades: int,
    wr_pct: float,
    avg_rr: float = 1.5,
    declared_sizing_pct: float = 5.0,
    in_sample_derived: bool = True,
    execution_scenario: str = "robinhood",
    years: float = 8.5,
) -> HaircutReport:
    """
    Apply standard haircuts to a raw backtest result. See module docstring for citations.

    Args:
        raw_r: total R from backtest
        n_trades: total trades in backtest
        wr_pct: win rate percentage (0-100)
        avg_rr: reward:risk ratio (default 1.5 for Ripper)
        declared_sizing_pct: what sizing the raw backtest assumed (default 5%)
        in_sample_derived: True if the strategy's rules were derived from the same
                          data used in this backtest (regime gates, setup selection).
                          If True, apply McLean-Pontiff 0.30-0.40 haircut.
        execution_scenario: "robinhood" or "ibkr" — per research/36 tables.
        years: backtest duration in years for CAGR calc.
    """
    # 1. In-sample haircut (McLean-Pontiff 2016 out-of-sample decay)
    if in_sample_derived:
        # Apply middle of 0.30-0.40 range
        in_sample_mult = 0.35
    else:
        in_sample_mult = 1.0  # no haircut if truly out-of-sample

    # 2. Execution cost drag (per research/36 §3-5)
    if execution_scenario == "robinhood":
        cost_per_trade_r = 0.06  # worst-case, per research/36
    elif execution_scenario == "ibkr":
        cost_per_trade_r = 0.02  # marketable limit + IBKR Pro, per research/36
    else:
        cost_per_trade_r = 0.04  # middle
    execution_drag = -cost_per_trade_r * n_trades

    # 3. Options P&L gap (Tastytrade 40k-trade sample + Haug 2007, per research/35)
    # Long-premium realizes 60-75% of R-model. Middle of range.
    options_mult = 0.70

    # Apply haircuts sequentially
    after_in_sample = raw_r * in_sample_mult
    after_execution = after_in_sample + execution_drag
    after_options = after_execution * options_mult

    # Range: low uses conservative haircuts, high uses generous
    r_low = raw_r * 0.30 + (-0.06 * n_trades) * 0.65  # heavy overfit + robinhood + 65% options gap
    r_high = raw_r * 0.40 + (-0.02 * n_trades) * 0.75  # light overfit + ibkr + 75% options gap
    r_low = min(r_low, after_options)  # sanity: low can't exceed middle
    r_high = max(r_high, after_options)  # sanity: high can't be below middle

    # Kelly-safe sizing (research/35 rule: cap at 1.5%)
    wr_frac = wr_pct / 100.0
    # Kelly = (b × p - q) / b where b = payoff ratio, p = win prob, q = 1 - p
    full_kelly_pct = ((avg_rr * wr_frac - (1 - wr_frac)) / avg_rr) * 100.0 if avg_rr > 0 else 0.0
    # Quarter Kelly is safe zone; also hard-cap at 1.5% per research/35
    quarter_kelly_pct = full_kelly_pct * 0.25
    kelly_safe_pct = min(max(0.5, quarter_kelly_pct), 1.5)

    # CAGR at safe sizing
    # Per-year R = total R / years
    # Simple approx: annual return ≈ (R_per_year × sizing_pct)
    # (Compound is complicated; this is a rough estimate)
    r_per_year_low = r_low / years
    r_per_year_high = r_high / years
    cagr_low = r_per_year_low * kelly_safe_pct / 100
    cagr_high = r_per_year_high * kelly_safe_pct / 100

    # Compound at declared sizing (for context — this is what the raw backtest showed)
    # (approx: (1 + sizing × avg_r_per_trade) ^ n_trades)
    if n_trades > 0:
        avg_r_per_trade = raw_r / n_trades
        compound_at_declared = (
            (1 + (declared_sizing_pct / 100) * avg_r_per_trade) ** n_trades - 1
        ) * 100
    else:
        compound_at_declared = 0.0

    detail = (
        f"Raw: {raw_r:+.1f}R over {n_trades:,} trades ({wr_pct:.1f}% WR)\n"
        f"  × in-sample haircut ({in_sample_mult}x, McLean-Pontiff): {after_in_sample:+.1f}R\n"
        f"  − execution drag ({execution_scenario}, {cost_per_trade_r:.2f}R/trade × {n_trades}): {after_execution:+.1f}R\n"
        f"  × options P&L gap ({options_mult}x, research/35): {after_options:+.1f}R\n"
        f"Realistic live range: {r_low:+.1f}R to {r_high:+.1f}R\n"
        f"Kelly-safe sizing: {kelly_safe_pct:.2f}% (full Kelly = {full_kelly_pct:.2f}%, quarter-Kelly capped at 1.5% per research/35)\n"
        f"Realistic annual CAGR at {kelly_safe_pct:.2f}% sizing: {cagr_low*100:+.1f}% to {cagr_high*100:+.1f}%\n"
        f"(For context: raw backtest at {declared_sizing_pct}% sizing = {compound_at_declared:+.0f}% compound — DO NOT quote this without haircuts)"
    )

    return HaircutReport(
        raw_r=raw_r,
        raw_trades=n_trades,
        raw_wr_pct=wr_pct,
        raw_end_compound_pct=compound_at_declared,
        declared_sizing_pct=declared_sizing_pct,
        in_sample_haircut_mult=in_sample_mult,
        execution_cost_r=execution_drag,
        options_pnl_gap_mult=options_mult,
        realistic_r_low=r_low,
        realistic_r_high=r_high,
        kelly_safe_sizing_pct=kelly_safe_pct,
        realistic_annual_cagr_low=cagr_low,
        realistic_annual_cagr_high=cagr_high,
        detail=detail,
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. THE GATE — call this from every backtest runner
# ═══════════════════════════════════════════════════════════════════════

def run_hygiene_gate(
    compute_signals_fn: Callable,
    df: pd.DataFrame,
    *signal_args,
    raw_r: float,
    n_trades: int,
    wr_pct: float,
    avg_rr: float = 1.5,
    declared_sizing_pct: float = 5.0,
    in_sample_derived: bool = True,
    execution_scenario: str = "robinhood",
    years: float = 8.5,
    strict: bool = True,
) -> tuple[bool, str]:
    """
    Run all hygiene checks. If any fails, refuse to return the headline number
    without a warning banner.

    Returns (all_passed, full_report_str).
    If strict=True and any check fails, prints a big warning and returns False.
    """
    print("=" * 80)
    print("BACKTEST HYGIENE GATE")
    print("=" * 80)

    print("\n[1/3] LOOKAHEAD CHECK — verifying no future-data leakage in signals...")
    la_report = check_lookahead(compute_signals_fn, df, *signal_args)
    print(f"  {la_report.detail}")

    print("\n[2/3] RECURSIVE CHECK — verifying indicator stability across warmup lengths...")
    rec_report = check_recursive(compute_signals_fn, df, *signal_args)
    print(f"  {rec_report.detail}")

    print("\n[3/3] AUTO-HAIRCUT — computing realistic live expectation...")
    hc_report = compute_haircut(
        raw_r=raw_r, n_trades=n_trades, wr_pct=wr_pct, avg_rr=avg_rr,
        declared_sizing_pct=declared_sizing_pct, in_sample_derived=in_sample_derived,
        execution_scenario=execution_scenario, years=years,
    )
    print(f"\n{hc_report.detail}")

    all_passed = la_report.passed and rec_report.passed
    print("\n" + "=" * 80)
    if all_passed:
        print(f"✅ HYGIENE GATES PASSED — headline number is defensible.")
        print(f"   Realistic live: {hc_report.realistic_r_low:+.1f}R to {hc_report.realistic_r_high:+.1f}R")
        print(f"   Recommended sizing: {hc_report.kelly_safe_sizing_pct:.2f}% per trade")
    else:
        print(f"❌ HYGIENE GATES FAILED — DO NOT quote the raw backtest number to the user.")
        if not la_report.passed:
            print(f"   → Lookahead bias detected: {la_report.mismatched_signals}")
        if not rec_report.passed:
            print(f"   → Recursive instability: {list(rec_report.unstable_indicators.keys())}")
        print(f"   Even if reported, MUST be labeled '⚠️ NOT VALIDATED — pending fix' until issues resolved.")
    print("=" * 80)

    return all_passed, hc_report.detail
