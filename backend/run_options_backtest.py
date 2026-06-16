"""
Run backtests on all 5 Phase 3 options candidates.
Usage: python3 run_options_backtest.py
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("DATABASE_URL", "sqlite:///./dev.db")

import importlib
from strategy_lab.core.backtester import run_backtest

START = "2024-06-01"
END   = "2026-06-01"
CAPITAL = 100_000

# Register options candidates under the short name the backtester expects
_OPTIONS = [
    "options_iron_condor_spy",
    "options_short_strangle_45d",
    "options_wheel_mechanical",
    "options_0dte_spx_condor",
    "options_post_earnings_ic",
]
for _name in _OPTIONS:
    _mod = importlib.import_module(f"strategy_lab.strategies.candidates.options.{_name}")
    sys.modules[f"strategy_lab.strategies.{_name}"] = _mod

STRATEGIES = [
    ("options_iron_condor_spy",    {"universe": ["SPY", "^VIX"], "capital": CAPITAL}),
    ("options_short_strangle_45d", {"universe": ["SPY", "QQQ", "IWM", "GLD", "TLT", "XLK", "^VIX"], "capital": CAPITAL}),
    ("options_wheel_mechanical",   {"universe": ["AAPL", "MSFT", "NVDA", "AMZN", "KO", "JNJ", "^VIX"], "capital": CAPITAL}),
    ("options_0dte_spx_condor",    {"universe": ["SPY", "^VIX"], "capital": CAPITAL, "backtesting": True}),
    ("options_post_earnings_ic",   {"universe": ["NVDA", "TSLA", "META", "NFLX", "AMD", "MU", "^VIX"], "capital": CAPITAL}),
]

PASS_GATES = {"sharpe": 0.5, "max_drawdown_pct": -20.0, "total_trades": 30}

results = []
for name, config in STRATEGIES:
    print(f"\n{'='*60}")
    print(f"Backtesting: {name}")
    print(f"{'='*60}")
    try:
        r = run_backtest(name, config, START, END, CAPITAL)
        passed = (
            r.sharpe >= PASS_GATES["sharpe"]
            and r.max_drawdown_pct >= PASS_GATES["max_drawdown_pct"]
            and r.total_trades >= PASS_GATES["total_trades"]
        )
        results.append({
            "name": name,
            "sharpe": r.sharpe,
            "max_dd": r.max_drawdown_pct,
            "win_rate": r.win_rate_pct,
            "trades": r.total_trades,
            "net_return": r.net_return_pct if hasattr(r, "net_return_pct") else None,
            "profit_factor": r.profit_factor,
            "passed": passed,
        })
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  Sharpe:        {r.sharpe:.2f}")
        print(f"  Max Drawdown:  {r.max_drawdown_pct:.1f}%")
        print(f"  Win Rate:      {r.win_rate_pct:.1f}%")
        print(f"  Total Trades:  {r.total_trades}")
        print(f"  Profit Factor: {r.profit_factor:.2f}")
        print(f"  STATUS: {status}")
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"name": name, "error": str(e), "passed": False})

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
passed = [r for r in results if r.get("passed")]
failed = [r for r in results if not r.get("passed")]
print(f"Passed gate ({len(passed)}/5): {[r['name'] for r in passed]}")
print(f"Failed gate ({len(failed)}/5): {[r['name'] for r in failed]}")

# Write markdown report
md_lines = [
    "# Options Candidates — Backtest Results",
    f"",
    f"**Period:** {START} → {END} (2 years)",
    f"**Capital:** ${CAPITAL:,}",
    f"**Gates:** Sharpe ≥ 0.5 · Max DD ≤ 20% · Trades ≥ 30",
    f"",
    "| Strategy | Sharpe | Max DD | Win Rate | Trades | Profit Factor | Status |",
    "|----------|--------|--------|----------|--------|---------------|--------|",
]
for r in results:
    if "error" in r:
        md_lines.append(f"| {r['name']} | ERROR | — | — | — | — | ❌ ERROR: {r['error'][:60]} |")
    else:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        md_lines.append(
            f"| {r['name']} | {r['sharpe']:.2f} | {r['max_dd']:.1f}% | {r['win_rate']:.1f}% | {r['trades']} | {r['profit_factor']:.2f} | {status} |"
        )

md_lines += [
    "",
    "## Gate Results",
    f"- **Passed ({len(passed)}/5):** " + (", ".join(r["name"] for r in passed) or "none"),
    f"- **Failed ({len(failed)}/5):** " + (", ".join(r["name"] for r in failed) or "none"),
    "",
    "## Shadow Paper Plan",
    "Strategies that passed will enter 14-day shadow paper mode.",
    "DO NOT enable live Alpaca paper trading without explicit Brock approval.",
    "The $200k options sleeve remains reserved.",
    "",
    "## Staggered Rollout Plan (post-shadow)",
    "- Day 1: 1 strategy, $10k cap",
    "- Day 3: +2 strategies if positive, $10k each",
    "- Day 7: scale winners to $20k, add more",
    "- Day 14: full allocation only if all signals positive AND no single strategy > 8% of sleeve",
]

report_path = os.path.join(
    os.path.dirname(__file__),
    "strategy_lab/strategies/candidates/options/BACKTEST_RESULTS.md"
)
with open(report_path, "w") as f:
    f.write("\n".join(md_lines) + "\n")
print(f"\nReport written: {report_path}")
