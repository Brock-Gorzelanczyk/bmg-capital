# Options Candidates — Backtest Results

**Period:** 2024-06-01 → 2026-06-01 (2 years)
**Capital:** $100,000
**Gates:** Sharpe ≥ 0.5 · Max DD ≤ 20% · Trades ≥ 30

| Strategy | Sharpe | Max DD | Win Rate | Trades | Profit Factor | Status |
|----------|--------|--------|----------|--------|---------------|--------|
| options_iron_condor_spy | -0.82 | 0.6% | 25.9% | 27 | 0.58 | ❌ FAIL |
| options_short_strangle_45d | -0.27 | 2.9% | 40.4% | 146 | 0.86 | ❌ FAIL |
| options_wheel_mechanical | -1.23 | 6.4% | 37.3% | 209 | 0.66 | ❌ FAIL |
| options_0dte_spx_condor | -1.01 | 0.3% | 20.6% | 34 | 0.40 | ❌ FAIL |
| options_post_earnings_ic | -0.90 | 1.5% | 29.2% | 24 | 0.46 | ❌ FAIL |

## Gate Results
- **Passed (0/5):** none
- **Failed (5/5):** options_iron_condor_spy, options_short_strangle_45d, options_wheel_mechanical, options_0dte_spx_condor, options_post_earnings_ic

## Simulation Methodology — Important Caveat

These results use the **equity-proxy backtester**, which models options positions as directional short positions on the underlying (SPY, AAPL, etc.) rather than actual options chains. This is a known limitation:

- **What the backtester measures:** P&L from selling the underlying short, exiting on 5% adverse move or 21-day time stop
- **What real options IC/strangle strategies measure:** P&L from theta decay (time value), with loss only when the underlying breaches short strike; these strategies are **delta-neutral**, not directional short
- **Why all strategies show negative Sharpe:** The 2024–2026 period was a strong bull market (SPY +50%). A directional short loses in bull markets. Real iron condors/strangles would be largely unaffected by slow, sustained uptrends — they only lose on sharp moves outside the strikes.

**Conclusion:** The underlying-proxy simulation is structurally ill-suited for short-vol options strategies. A negative Sharpe here does NOT mean these strategies are unprofitable — it means they need a real options backtester with IV and chain data.

## Verdict: DO NOT ALLOCATE CAPITAL BASED ON THESE RESULTS

All 5 strategies fail the proxy backtest. However, **the correct next step is shadow paper trading**, not disqualification:

1. These strategies require Alpaca options API (paid tier) with real IV data to be properly evaluated
2. The guardrail logic (IVR gate, regime filter) is correctly implemented in each strategy file
3. The `paper_only=True` flag is set on all 5 — they are already blocked from live capital

## Shadow Paper Plan (Required Before Any Live Allocation)

All 5 strategies enter **14-day shadow paper mode** using Alpaca paper trading with real options chains:
- Minimum 14 calendar days of paper trading required (options-specific requirement)
- Gate to exit shadow: ≥ 5 trades closed, win rate ≥ 50%, max loss per trade ≤ wing width
- DO NOT enable live Alpaca options trading without explicit Brock approval
- The $200k options sleeve remains reserved until shadow paper gates are met

## Staggered Rollout Plan (Post-Shadow, Requires Brock Sign-Off)

- **Day 1:** 1 strategy (best shadow paper performer), $10k cap, paper_only still True
- **Day 3:** If Day 1 positive P&L, add 1–2 more strategies at $10k each
- **Day 7:** Scale winners to $20k; add remaining strategies if all signals positive
- **Day 14:** Full $200k sleeve allocation only if:
  - All active strategies: positive net P&L in shadow
  - No single strategy > 8% of sleeve
  - Brock explicitly approves each strategy for live trading

## Files Audited

All 5 options strategy files confirmed clean (no unauthorized IVR gate changes):
- `options_iron_condor_spy.py` — IVR > 30, ATR contracting gate ✓
- `options_short_strangle_45d.py` — IVR > 50, range-bound gate ✓
- `options_wheel_mechanical.py` — IVR > 30, stable (beta < 1.5 proxy) gate ✓
- `options_0dte_spx_condor.py` — FOMC/CPI avoidance, VIX < 30 gate ✓
- `options_post_earnings_ic.py` — IVR > 35 post-crush, earnings move detected ✓

Last touched by revert commit `4a8d9cd` — no unauthorized modifications.
