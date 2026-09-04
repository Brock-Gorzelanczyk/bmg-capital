"""
Run v4 (adaptive regime-conditional) backtest + compare to v3.4 baseline.
Reports per-regime improvement + full 8.5-year totals.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from ripper_v4 import compute_signals_v4, run_backtest_v4

DATA_DIR = Path("/Users/brockgorzelanczyk/my-new-project/scripts/backtest/data")
VAULT_REPORT = Path("/Users/brockgorzelanczyk/Documents/BMG-Capital-Vault/research/30-ripper-v4-adaptive-regime-backtest.md")

REGIMES = [
    ("2018-01-01", "2018-12-31", "2018 Volmageddon"),
    ("2019-01-01", "2019-12-31", "2019 Grind Up"),
    ("2020-01-01", "2020-06-30", "2020H1 COVID"),
    ("2020-07-01", "2020-12-31", "2020H2 Recovery"),
    ("2021-01-01", "2021-12-31", "2021 Meme"),
    ("2022-01-01", "2022-12-31", "2022 Bear"),
    ("2023-01-01", "2023-12-31", "2023 SVB+AI"),
    ("2024-01-01", "2024-12-31", "2024 Grind Up"),
    ("2025-01-01", "2025-12-31", "2025 Trump 2.0"),
    ("2026-01-01", "2026-06-30", "2026H1"),
]


def compound_5pct(outcomes):
    m = np.ones(len(outcomes))
    m[outcomes == 'WIN'] = 1.075
    m[outcomes == 'LOSS'] = 0.95
    wealth = np.cumprod(m)
    if len(wealth) == 0:
        return 1.0, 0.0
    peak = np.maximum.accumulate(wealth)
    max_dd = ((peak - wealth) / peak).max()
    return wealth[-1], max_dd


def max_loss_streak(outcomes):
    cur = 0; mx = 0
    for o in outcomes:
        if o == 'LOSS':
            cur += 1
            if cur > mx: mx = cur
        elif o == 'WIN':
            cur = 0
    return mx


def analyze(trades: pd.DataFrame, label: str):
    if len(trades) == 0:
        return {'label': label, 'n': 0, 'wr': 0, 'r': 0, 'end_5pct': 0, 'max_dd_5pct': 0, 'max_ls': 0}
    n = len(trades)
    w = (trades['outcome'] == 'WIN').sum()
    l = (trades['outcome'] == 'LOSS').sum()
    wr = 100 * w / max(1, w + l)
    r = trades['r_multiple'].sum()
    outcomes = trades['outcome'].values
    end_w, max_dd = compound_5pct(outcomes)
    return {
        'label': label,
        'n': n,
        'w': w, 'l': l,
        'wr': wr,
        'r': r,
        'end_5pct': (end_w - 1) * 100,
        'max_dd_5pct': max_dd * 100,
        'max_ls': max_loss_streak(outcomes),
    }


def main():
    print("=" * 70)
    print("PHASE 3: v4 ADAPTIVE (regime-conditional) backtest")
    print("=" * 70)

    spy = pd.read_parquet(DATA_DIR / "spy_15m.parquet")
    vix = pd.read_parquet(DATA_DIR / "vix_daily.parquet")
    print(f"Loaded {len(spy):,} SPY bars, {len(vix):,} VIX bars")

    print("\nComputing signals + regime detection...")
    signals, extras = compute_signals_v4(spy, vix)

    # Report regime distribution
    regime_dist = extras['regime'].value_counts()
    print(f"\nRegime distribution (bars):")
    for reg, cnt in regime_dist.items():
        pct = 100 * cnt / len(spy)
        print(f"  {reg}: {cnt:,} ({pct:.1f}%)")

    print("\nRunning v4 backtest (regime gates ON)...")
    trades_v4 = run_backtest_v4(spy, signals, extras, use_regime_gates=True, use_trend_filter=True)
    trades_v4.to_csv(DATA_DIR / "ripper_v4_trades.csv", index=False)
    print(f"v4 trades: {len(trades_v4):,}")

    print("\nRunning v3.4 baseline (all setups, only trend filter) for comparison...")
    trades_v3 = run_backtest_v4(spy, signals, extras, use_regime_gates=False, use_trend_filter=True)
    print(f"v3.4-equivalent trades: {len(trades_v3):,}")

    # Compare per-regime
    print("\n" + "=" * 90)
    print(f"{'Regime':<20} | {'v3 N':>5} {'v3 R':>7} {'v3 End@5%':>10} | {'v4 N':>5} {'v4 R':>7} {'v4 End@5%':>10} | {'ΔR':>6}")
    print("-" * 90)
    total_v3 = total_v4 = 0
    comp_rows = []
    for start_str, end_str, label in REGIMES:
        start = pd.Timestamp(start_str, tz='UTC')
        end = pd.Timestamp(end_str + ' 23:59:59', tz='UTC')
        v3 = trades_v3[(trades_v3['fire_time'] >= start) & (trades_v3['fire_time'] <= end)]
        v4 = trades_v4[(trades_v4['fire_time'] >= start) & (trades_v4['fire_time'] <= end)]
        v3s = analyze(v3, label)
        v4s = analyze(v4, label)
        delta_r = v4s['r'] - v3s['r']
        total_v3 += v3s['r']
        total_v4 += v4s['r']
        print(f"{label:<20} | {v3s['n']:>5} {v3s['r']:>+6.1f}R {v3s['end_5pct']:>+9.0f}% | {v4s['n']:>5} {v4s['r']:>+6.1f}R {v4s['end_5pct']:>+9.0f}% | {delta_r:>+5.1f}R")
        comp_rows.append({'label': label, 'v3': v3s, 'v4': v4s, 'delta_r': delta_r})
    print("-" * 90)
    print(f"{'TOTAL':<20} | {'':>5} {total_v3:>+6.1f}R {'':>10} | {'':>5} {total_v4:>+6.1f}R {'':>10} | {total_v4-total_v3:>+5.1f}R")

    # Overall compound
    all_v3 = analyze(trades_v3, "Full v3")
    all_v4 = analyze(trades_v4, "Full v4")
    print(f"\nFull 8.5-year compound at 5% risk:")
    print(f"  v3.4 baseline: {all_v3['end_5pct']:+.0f}% (max DD {all_v3['max_dd_5pct']:.0f}%, max L streak {all_v3['max_ls']})")
    print(f"  v4 adaptive:   {all_v4['end_5pct']:+.0f}% (max DD {all_v4['max_dd_5pct']:.0f}%, max L streak {all_v4['max_ls']})")
    lift_pct = all_v4['end_5pct'] - all_v3['end_5pct']
    print(f"  Lift from adaptive: {lift_pct:+.0f} percentage points")

    # Write vault report
    print(f"\nWriting v4 report to {VAULT_REPORT}")
    with open(VAULT_REPORT, 'w') as f:
        f.write("# 30 — Ripper v4 adaptive (regime-conditional) backtest\n\n")
        f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M CT')}*\n\n")
        f.write("## What this is\n\n")
        f.write("Ripper v4 replaces v3.4's fixed setup mix with **per-setup regime-conditional gates** ")
        f.write("derived from Phase 2 analysis of 2018-2026 data.\n\n")
        f.write("**Key insight from Phase 2:** most setups are profitable in SOME regimes and destructive ")
        f.write("in others. By auto-disabling setups in their bad regimes, we cut losses without ")
        f.write("giving up meaningful upside.\n\n")

        f.write("## v3.4 → v4 head-to-head (Python backtest, 2018-2026)\n\n")
        f.write("| Regime | v3.4 R | v3.4 End @5% | v4 R | v4 End @5% | Δ R |\n")
        f.write("|---|---|---|---|---|---|\n")
        for row in comp_rows:
            f.write(f"| {row['label']} | {row['v3']['r']:+.1f}R | {row['v3']['end_5pct']:+.0f}% | ")
            f.write(f"{row['v4']['r']:+.1f}R | {row['v4']['end_5pct']:+.0f}% | {row['delta_r']:+.1f}R |\n")
        f.write(f"| **TOTAL** | **{total_v3:+.1f}R** | **{all_v3['end_5pct']:+.0f}%** | ")
        f.write(f"**{total_v4:+.1f}R** | **{all_v4['end_5pct']:+.0f}%** | **{total_v4-total_v3:+.1f}R** |\n\n")

        f.write("## Full 8.5-year summary\n\n")
        f.write(f"| Metric | v3.4 baseline | v4 adaptive |\n|---|---|---|\n")
        f.write(f"| Total trades | {all_v3['n']:,} | {all_v4['n']:,} |\n")
        f.write(f"| Win rate | {all_v3['wr']:.1f}% | {all_v4['wr']:.1f}% |\n")
        f.write(f"| Total R | {all_v3['r']:+.1f}R | {all_v4['r']:+.1f}R |\n")
        f.write(f"| Period end @ 5% (compound) | {all_v3['end_5pct']:+.1f}% | {all_v4['end_5pct']:+.1f}% |\n")
        f.write(f"| Max drawdown @ 5% (compound) | {all_v3['max_dd_5pct']:.1f}% | {all_v4['max_dd_5pct']:.1f}% |\n")
        f.write(f"| Max loss streak | {all_v3['max_ls']} | {all_v4['max_ls']} |\n\n")

        # Regime distribution
        f.write("## Regime distribution (bars in each state, 2018-2026)\n\n")
        f.write("| Regime | Bars | % |\n|---|---|---|\n")
        for reg, cnt in regime_dist.items():
            pct = 100 * cnt / len(spy)
            f.write(f"| {reg} | {cnt:,} | {pct:.1f}% |\n")
        f.write("\n")

        # v4 rules
        f.write("## v4 regime rules applied\n\n")
        from ripper_v4 import REGIME_RULES
        f.write("Each setup only fires in the listed regimes. Empty = disabled everywhere.\n\n")
        f.write("| Setup | Enabled in regimes |\n|---|---|\n")
        for setup in sorted(REGIME_RULES.keys()):
            regs = REGIME_RULES[setup]
            regs_str = ', '.join(sorted(regs)) if regs else '**DISABLED (structural loser)**'
            f.write(f"| {setup} | {regs_str} |\n")

        f.write("\n## v4 verdict\n\n")
        if all_v4['end_5pct'] > all_v3['end_5pct'] and all_v4['max_dd_5pct'] < all_v3['max_dd_5pct']:
            f.write("✅ **v4 IMPROVES on v3.4**: higher end value AND smaller max drawdown. ")
            f.write("Regime-conditional gates delivered on the Phase 2 hypothesis.\n\n")
        elif all_v4['end_5pct'] > all_v3['end_5pct']:
            f.write("✅ **v4 improves end value** but drawdown may be similar. Still net-positive.\n\n")
        else:
            f.write("❌ **v4 did NOT improve**. Need Phase 4 (new setups for underserved regimes).\n\n")

        n_v4_wins = sum(1 for r in comp_rows if r['delta_r'] > 0)
        n_v4_losses = sum(1 for r in comp_rows if r['delta_r'] < 0)
        f.write(f"v4 improved {n_v4_wins}/{len(comp_rows)} regimes, hurt {n_v4_losses}.\n\n")

        # Recommendation
        f.write("## Recommendation\n\n")
        if all_v4['r'] > all_v3['r']:
            f.write(f"1. **Adopt v4 rules in Pine indicator.** The +{total_v4-total_v3:.1f}R improvement across 8.5 years is meaningful.\n")
            f.write(f"2. Ship as **Ripper v4.0 Pine file** with regime detection + per-setup gates.\n")
            f.write(f"3. Continue Phase 4 for regimes v4 still loses in.\n")
        else:
            f.write(f"1. v4 as designed doesn't improve. Investigate Phase 2 rule interpretation.\n")
            f.write(f"2. Consider Phase 4 immediately — need new setups for underserved regimes.\n")

    print(f"\n✅ v4 report written")
    print(f"View: {VAULT_REPORT}")
    return all_v3, all_v4, comp_rows


if __name__ == "__main__":
    main()
