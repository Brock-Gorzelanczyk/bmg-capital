# Strategy Candidate Queue

All strategies below are queued for future sessions. Each must be implemented as a
candidate file, submitted through the Phase 1 pipeline, and must pass all gates before
receiving any capital. No strategy below is live or allocated.

---

## Tier 2 Candidates (11–23)

| # | ID | Name | Asset Class | Strategy Type | Key Parameters | Evidence Tier |
|---|----|------|-------------|---------------|----------------|---------------|
| 11 | `put_write_monthly` | Put Write Monthly Index | Options | options_income | SPX 30-delta put, monthly, exit 50% profit or expiry | T1 |
| 12 | `vix_term_structure_roll` | VIX Term Structure Roll | Options | long_vol | Long VIX when VIX < 16 + steep contango (VX1/VX2 < 0.85); exit VIX > 20 | T1 |
| 13 | `spy_sma200_trend` | SPY 200MA Trend | Stocks | trend_following | Long SPY when close > 200MA; cash otherwise. Monthly check. | T2 |
| 14 | `factor_momentum_rotation` | Factor Momentum Rotation | Stocks | momentum | Monthly: rotate into best-performing factor ETF (MTUM/QUAL/VLUE/SIZE) on 6m return | T1 |
| 15 | `commodity_momentum` | Commodity Momentum | Stocks | momentum | Monthly 12m momentum on DBC, GLD, SLV, USO, CORN, WEAT — long top 2 | T2 |
| 16 | `crypto_nvt_signal` | Crypto NVT Signal | Crypto | mean_reversion | BTC NVT > 2 std: reduce; NVT < -1 std: add. On-chain data dependency. | T1 |
| 17 | `calendar_spread_vix` | VIX Calendar Spread | Options | long_vol | Buy near VIX futures, sell far when contango > 8%; delta-neutral. Stub if no futures feed. | T1 |
| 18 | `earnings_strangle` | Earnings Event Strangle | Options | long_vol | Buy ATM strangle 1 week before earnings on mega-caps with IV crush history < avg | T2 |
| 19 | `rate_sensitive_rotation` | Rate-Sensitive Rotation | Stocks | trend_following | Rotate between TLT and TIPS based on TIPS breakeven vs 1y z-score | T2 |
| 20 | `crypto_onchain_mvrv` | Crypto MVRV Z-Score | Crypto | mean_reversion | BTC MVRV Z > 7: exit; MVRV Z < 1: accumulate. On-chain data dependency. | T1 |
| 21 | `trend_breakout_5day` | 5-Day High Breakout | Stocks | momentum | Buy on new 5-day high close, size by ATR, exit new 5-day low close | T2 |
| 22 | `pairs_spyqqq` | SPY/QQQ Pairs Trade | Stocks | mean_reversion | Z-score of SPY/QQQ ratio; enter when |z| > 2; exit z crosses 0 | T2 |
| 23 | `global_macro_etf_momentum` | Global Macro ETF Momentum | Stocks | momentum | Monthly 12m momentum on EFA/EEM/FXI/EWJ/EWZ/EWC — long top 3 | T2 |

---

## Tier 3 Candidates (24–35)

| # | ID | Name | Asset Class | Strategy Type | Key Parameters | Evidence Tier |
|---|----|------|-------------|---------------|----------------|---------------|
| 24 | `crypto_funding_flip` | Crypto Funding Flip | Crypto | mean_reversion | BTC funding goes from positive → negative: buy spot within 24h | T2 |
| 25 | `butterfly_spread_spx` | SPX Butterfly Spread | Options | options_income | 30 DTE ATM butterfly, enter when IV30 > 1y median, exit 50% or 14 DTE | T2 |
| 26 | `volatility_risk_premium` | Vol Risk Premium Harvest | Options | options_income | Sell 1-month SPX straddle when 30d IV vs 30d realized vol spread > 3 pts | T1 |
| 27 | `sector_relative_strength` | Sector Relative Strength | Stocks | momentum | Weekly: buy top 3 sectors by 20d RS vs SPY; sell bottom 3 | T2 |
| 28 | `crypto_hash_ribbon` | Crypto Hash Ribbon | Crypto | trend_following | BTC 30d miner hash rate MA crosses 60d: buy. Requires on-chain data. | T2 |
| 29 | `tail_risk_hedge` | Tail Risk Hedge | Options | long_vol | Buy 2% OTM SPY puts 90 DTE when VIX < 15; roll monthly. Insurance layer. | T1 |
| 30 | `high_yield_momentum` | High Yield Bond Momentum | Stocks | momentum | Monthly: HYG vs LQD 3m return; long winner; cash if both negative | T2 |
| 31 | `spx_gamma_scalp` | SPX 0DTE Gamma Scalp | Options | options_income | 0DTE SPX credit spread, 10-delta, max 2%/week, only in VIX 14-22 range | T3 |
| 32 | `bitcoin_halving_cycle` | Bitcoin Halving Cycle | Crypto | trend_following | Reduce BTC exposure 6 months post-halving when 4y MA > 2.5× current price | T3 |
| 33 | `dispersion_trade` | Dispersion Trade | Options | options_income | Sell index vol (SPX), buy component vol (AAPL/MSFT/NVDA); when correlation < 0.40 | T2 |
| 34 | `vol_surface_arb` | Vol Surface Arbitrage | Options | other | Identify calendar spread mispricings in term structure. Requires options data feed. | T2 |
| 35 | `carry_ftw` | G10 Carry (ETF Proxy) | Stocks | carry | Long high-yield currencies (FXA, FXN), short low-yield (FXF, FXY) via ETFs | T2 |

---

## Seasonal Strategies (36–39)

| # | ID | Name | Asset Class | Strategy Type | Key Parameters | Evidence Tier |
|---|----|------|-------------|---------------|----------------|---------------|
| 36 | `santa_rally` | Santa Rally | Stocks | momentum | Buy SPY Dec 22, hold through Jan 3; only when Nov return > 0 | T3 |
| 37 | `january_effect_small_cap` | January Effect Small Cap | Stocks | momentum | Buy IWM Dec 20, sell Jan 15; historical small-cap seasonal | T3 |
| 38 | `sell_in_may` | Sell in May | Stocks | trend_following | Exit equity ETFs May 1, re-enter Nov 1; combine with bond/gold hold | T3 |
| 39 | `options_expiry_pin` | Options Expiry Pin | Options | mean_reversion | SPY tends to pin near max pain on monthly expiry Friday; trade mean-revert from 2 days before | T3 |

---

## Picking off the Queue

Pick the next candidate in Tier order (Tier 2 first, then 3, then Seasonal).
For each:
1. Write the candidate file in `strategy_lab/candidates/<id>.py`
2. Add `CANDIDATE_CONFIG` dict
3. Submit via `/api/candidates/sync` 
4. Run backtest → WFA → shadow mode
5. Traffic light must reach GREEN before manual promotion review

Flag any candidate as `"blocked": True` in `CANDIDATE_CONFIG` if it requires
a data feed not yet available (on-chain data, perpetual futures, etc.).
