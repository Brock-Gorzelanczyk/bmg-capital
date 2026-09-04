"""
PHASE 2: Per-regime setup performance analysis.

For each of 10 regimes and each of 13 setups, compute:
- N trades
- WR
- R total
- Best regime for each setup
- Best setups for each regime

Then propose regime-conditional enable/disable rules.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/brockgorzelanczyk/my-new-project/scripts/backtest/data")
VAULT_REPORT = Path("/Users/brockgorzelanczyk/Documents/BMG-Capital-Vault/research/29-ripper-phase2-regime-setup-matrix.md")

REGIMES = [
    ("2018-01-01", "2018-12-31", "2018_Volmageddon"),
    ("2019-01-01", "2019-12-31", "2019_LowVolGrindUp"),
    ("2020-01-01", "2020-06-30", "2020H1_COVID_Crash"),
    ("2020-07-01", "2020-12-31", "2020H2_Recovery"),
    ("2021-01-01", "2021-12-31", "2021_MemeMania"),
    ("2022-01-01", "2022-12-31", "2022_BearMarket"),
    ("2023-01-01", "2023-12-31", "2023_SVB_AI_Rally"),
    ("2024-01-01", "2024-12-31", "2024_LowVolGrindUp"),   # THE DISASTER YEAR
    ("2025-01-01", "2025-12-31", "2025_Trump2"),
    ("2026-01-01", "2026-06-30", "2026H1"),
]


def load_trades():
    t = pd.read_csv(DATA_DIR / "ripper_trades_2018-2026.csv")
    t['fire_time'] = pd.to_datetime(t['fire_time'])
    return t


def analyze_setup_in_period(trades: pd.DataFrame, setup: str) -> dict:
    """Analyze one setup's performance in a filtered period."""
    s = trades[trades['setup'] == setup]
    n = len(s)
    w = (s['outcome'] == 'WIN').sum()
    l = (s['outcome'] == 'LOSS').sum()
    to = (s['outcome'] == 'TIMEOUT').sum()
    wr = 100 * w / max(1, w + l)
    r = s['r_multiple'].sum()
    return {'n': n, 'w': w, 'l': l, 'to': to, 'wr': wr, 'r': r}


def build_matrix(trades: pd.DataFrame) -> pd.DataFrame:
    """Build setup × regime matrix of R totals."""
    setups = sorted(trades['setup'].unique())
    rows = []
    for setup in setups:
        row = {'setup': setup}
        for start_str, end_str, regime_name in REGIMES:
            start = pd.Timestamp(start_str, tz='UTC')
            end = pd.Timestamp(end_str + ' 23:59:59', tz='UTC')
            period_trades = trades[(trades['fire_time'] >= start) & (trades['fire_time'] <= end)]
            stats = analyze_setup_in_period(period_trades, setup)
            row[regime_name] = stats['r']
            row[regime_name + '_N'] = stats['n']
            row[regime_name + '_WR'] = stats['wr']
        row['total_R'] = sum(row[r[2]] for r in REGIMES)
        row['total_N'] = sum(row[r[2] + '_N'] for r in REGIMES)
        rows.append(row)
    return pd.DataFrame(rows).sort_values('total_R', ascending=False)


def build_regime_x_setup_r(trades: pd.DataFrame) -> pd.DataFrame:
    """Simple R-total matrix: rows = setups, columns = regimes."""
    setups = sorted(trades['setup'].unique())
    regime_names = [r[2] for r in REGIMES]
    matrix = pd.DataFrame(0.0, index=setups, columns=regime_names)
    for setup in setups:
        for start_str, end_str, regime_name in REGIMES:
            start = pd.Timestamp(start_str, tz='UTC')
            end = pd.Timestamp(end_str + ' 23:59:59', tz='UTC')
            s = trades[(trades['fire_time'] >= start) & (trades['fire_time'] <= end) & (trades['setup'] == setup)]
            matrix.loc[setup, regime_name] = s['r_multiple'].sum()
    matrix['total'] = matrix.sum(axis=1)
    return matrix.sort_values('total', ascending=False)


def propose_regime_rules(matrix: pd.DataFrame) -> dict:
    """For each regime, identify winning + losing setups. Propose enable/disable rules."""
    rules = {}
    for start_str, end_str, regime_name in REGIMES:
        # Setups sorted by R in this regime
        regime_col = matrix[regime_name].sort_values(ascending=False)
        winners = regime_col[regime_col >= 3.0].index.tolist()   # >= +3R in regime
        marginal = regime_col[(regime_col > 0) & (regime_col < 3.0)].index.tolist()
        losers = regime_col[regime_col <= -3.0].index.tolist()   # <= -3R in regime
        breakevens = regime_col[(regime_col > -3.0) & (regime_col <= 0)].index.tolist()
        rules[regime_name] = {
            'winners': winners,
            'marginal': marginal,
            'losers': losers,
            'breakeven': breakevens,
            'winner_r_total': regime_col[winners].sum() if winners else 0,
            'loser_r_total': regime_col[losers].sum() if losers else 0,
            'if_only_winners': regime_col[winners].sum() if winners else 0,  # theoretical improvement
            'if_kill_losers': regime_col[[s for s in matrix.index if s not in losers]].sum(),
        }
    return rules


def main():
    print("PHASE 2: Per-regime × per-setup analysis")
    print("=" * 70)
    trades = load_trades()
    print(f"Loaded {len(trades):,} trades")

    # Build the matrix
    matrix = build_regime_x_setup_r(trades)
    print("\nSetup × Regime R-matrix:")
    print(matrix.round(1))

    # Rules per regime
    rules = propose_regime_rules(matrix)

    # Write markdown report
    print(f"\nWriting Phase 2 report to {VAULT_REPORT}")
    with open(VAULT_REPORT, 'w') as f:
        f.write("# 29 — Ripper Phase 2: per-regime × per-setup R matrix\n\n")
        f.write(f"*Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M CT')}*\n\n")
        f.write("## What this is\n\n")
        f.write("For each of the 10 regimes in the 2018-2026 backtest, compute which of ")
        f.write("the 13 Ripper setups was profitable (positive R) and which was destructive (negative R).\n\n")
        f.write("**Key insight target:** which setups should be DISABLED in specific regimes to ")
        f.write("turn the -87% 2024 disaster into a break-even or profitable year?\n\n")

        f.write("## The full matrix (R totals by setup × regime)\n\n")
        f.write("Rows = setups, columns = regimes. Cell = R total for that setup during that regime.\n\n")
        # Format as markdown table
        f.write("| Setup |")
        for _, _, name in REGIMES:
            f.write(f" {name[:10]} |")
        f.write(" **TOTAL** |\n|---|")
        for _ in REGIMES:
            f.write("---:|")
        f.write("---:|\n")
        for setup in matrix.index:
            f.write(f"| {setup} |")
            for _, _, name in REGIMES:
                r = matrix.loc[setup, name]
                marker = "✅" if r >= 3 else ("❌" if r <= -3 else "")
                f.write(f" {r:+.1f} {marker} |")
            total = matrix.loc[setup, 'total']
            f.write(f" **{total:+.1f}** |\n")
        f.write("\nLegend: ✅ = winner (≥+3R), ❌ = loser (≤-3R)\n\n")

        f.write("## Per-regime rules (proposed)\n\n")
        for start_str, end_str, name in REGIMES:
            r = rules[name]
            f.write(f"### {name} ({start_str} → {end_str})\n\n")
            f.write(f"- **Winners** (enable): {', '.join(r['winners']) if r['winners'] else 'NONE'}\n")
            f.write(f"- **Marginal** (keep/discretionary): {', '.join(r['marginal']) if r['marginal'] else 'NONE'}\n")
            f.write(f"- **Breakeven** (keep for optionality): {', '.join(r['breakeven']) if r['breakeven'] else 'NONE'}\n")
            f.write(f"- **Losers** (DISABLE): {', '.join(r['losers']) if r['losers'] else 'NONE'}\n")
            f.write(f"- Total R if we KEEP EVERYTHING: **{matrix[name].sum():+.1f}R**\n")
            f.write(f"- Total R if we KILL LOSERS: **{r['if_kill_losers']:+.1f}R**\n")
            f.write(f"- Total R if we KEEP ONLY WINNERS: **{r['if_only_winners']:+.1f}R**\n\n")

        f.write("## Consolidated regime rules (for Phase 3 Pine implementation)\n\n")
        # Cross-regime — which setups are ALWAYS winners? which are ALWAYS losers?
        always_winner = []
        always_loser = []
        for setup in matrix.index:
            regime_rs = [matrix.loc[setup, r[2]] for r in REGIMES]
            n_winning = sum(1 for r in regime_rs if r > 0)
            n_losing = sum(1 for r in regime_rs if r < 0)
            if n_winning >= 7:  # winning in ≥7 of 10 regimes
                always_winner.append((setup, n_winning, matrix.loc[setup, 'total']))
            if n_losing >= 7:
                always_loser.append((setup, n_losing, matrix.loc[setup, 'total']))
        f.write("**Setups profitable in ≥7 of 10 regimes:**\n\n")
        for setup, n, total in sorted(always_winner, key=lambda x: -x[2]):
            f.write(f"- {setup}: {n}/10 regimes positive, total +{total:.1f}R → **ALWAYS ENABLE**\n")
        f.write("\n**Setups losing in ≥7 of 10 regimes:**\n\n")
        for setup, n, total in sorted(always_loser, key=lambda x: x[2]):
            f.write(f"- {setup}: {n}/10 regimes negative, total {total:+.1f}R → **ALWAYS DISABLE** (or fix logic)\n")

        # Compute best/worst regimes for each setup
        f.write("\n## Each setup's best and worst regime\n\n")
        f.write("| Setup | Best regime | R | Worst regime | R |\n|---|---|---|---|---|\n")
        for setup in matrix.index:
            regime_only = matrix.loc[setup, [r[2] for r in REGIMES]]
            best = regime_only.idxmax()
            worst = regime_only.idxmin()
            f.write(f"| {setup} | {best} | {regime_only[best]:+.1f} | {worst} | {regime_only[worst]:+.1f} |\n")

        # KEY INSIGHT: If we could magically pick perfect regime rules, what's the max R?
        f.write("\n## Theoretical maximum with perfect regime hindsight\n\n")
        f.write("If we had PERFECT foresight and only enabled setups that made money in each specific regime:\n\n")
        total_perfect = 0
        f.write("| Regime | R with perfect hindsight |\n|---|---|\n")
        for _, _, name in REGIMES:
            perfect_r = matrix[name].clip(lower=0).sum()  # only positive contributions
            total_perfect += perfect_r
            f.write(f"| {name} | +{perfect_r:.1f}R |\n")
        f.write(f"\n**Total across 8.5 years with perfect hindsight: +{total_perfect:.1f}R**\n\n")
        f.write(f"vs actual (all setups always on): {matrix['total'].sum():+.1f}R\n\n")
        f.write(f"**Gap between perfect and actual: {total_perfect - matrix['total'].sum():+.1f}R** — this is the ")
        f.write(f"theoretical alpha available if we could always pick the right regime rules. In practice ")
        f.write(f"we won't achieve this (regime detection has lag) but ~50-70% of it is realistic.\n")

    print(f"Phase 2 report written: {VAULT_REPORT}")

    # Also save the matrix as CSV for programmatic use in Phase 3
    matrix.to_csv(DATA_DIR / "phase2_regime_setup_matrix.csv")
    print(f"Matrix CSV saved: {DATA_DIR / 'phase2_regime_setup_matrix.csv'}")

    return matrix, rules


if __name__ == "__main__":
    matrix, rules = main()

    # Console highlights
    print("\n" + "=" * 70)
    print("PHASE 2 HIGHLIGHTS")
    print("=" * 70)
    print("\nCross-regime winners (always positive):")
    for setup in matrix.index:
        regime_rs = [matrix.loc[setup, r[2]] for r in REGIMES]
        n_win = sum(1 for r in regime_rs if r > 0)
        if n_win >= 7:
            print(f"  {setup}: {n_win}/10 profitable, total {matrix.loc[setup, 'total']:+.1f}R")

    print("\nCross-regime losers (always negative):")
    for setup in matrix.index:
        regime_rs = [matrix.loc[setup, r[2]] for r in REGIMES]
        n_lose = sum(1 for r in regime_rs if r < 0)
        if n_lose >= 7:
            print(f"  {setup}: {n_lose}/10 losing, total {matrix.loc[setup, 'total']:+.1f}R")

    print("\n2024 (the disaster year) — what worked?")
    r24 = matrix['2024_LowVolGrindUp'].sort_values(ascending=False)
    for setup, r in r24.head(5).items():
        print(f"  Best: {setup} = {r:+.1f}R")
    for setup, r in r24.tail(5).items():
        print(f"  Worst: {setup} = {r:+.1f}R")
    print(f"  Total (all setups on): {r24.sum():+.1f}R")
    print(f"  If we killed all negative setups: +{r24[r24 > 0].sum():.1f}R")
