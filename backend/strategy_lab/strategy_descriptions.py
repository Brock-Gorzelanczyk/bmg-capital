"""
Central registry of strategy descriptions surfaced in /strategy/library.

Each entry maps a bot_id or candidate file name → full description dict.
Fields:
  display_name   : human-readable name
  asset_class    : "stocks" | "crypto" | "options" | "multi"
  family         : "Momentum" | "Mean Reversion" | "Trend" | "Volatility" |
                   "Carry" | "Event-Driven" | "Cross-Asset" | "Arbitrage"
  thesis         : 1-2 sentence plain-English description
  entry_rule     : technical entry condition
  exit_rule      : technical exit condition
  risk           : stop / take-profit / sizing rules
  cadence        : how often the bot scans / trades
  academic_source: (optional) academic citation
  works_best_in  : market regimes where edge is strongest
  avoid_in       : regimes to avoid or reduce size
"""

DESCRIPTIONS: dict[str, dict] = {

    # ── Deployed bots (12) ────────────────────────────────────────────────────

    "stock_swing": {
        "display_name": "Stock Swing",
        "asset_class": "stocks",
        "family": "Momentum",
        "thesis": (
            "Captures 1-to-30-day momentum swings in Russell 1000 stocks "
            "by running an ensemble of 11 technical strategies. Profitable "
            "in trending, low-volatility regimes."
        ),
        "entry_rule": (
            "Enter LONG when ≥2 of: 52-week high breakout, golden cross, "
            "cup-and-handle pattern, MACD crossover, RSI-band bounce, or "
            "bollinger squeeze fires on the same ticker in the same session."
        ),
        "exit_rule": (
            "Exit when the primary signal reverses OR the 30-day max age is reached. "
            "Earnings-driven strategies exit the day before the event."
        ),
        "risk": (
            "Stop: 7% below entry (hard). "
            "Position size: equal-weight within a 10-position cap per allocation."
        ),
        "cadence": "Runs at 4:05 PM ET, Mon–Fri (after market close)",
        "academic_source": (
            "Jegadeesh & Titman (1993) — momentum in stock returns; "
            "George & Hwang (2004) — 52-week high and momentum"
        ),
        "works_best_in": "Bull markets, post-correction rallies, low-VIX trending regimes",
        "avoid_in": "High-VIX bear markets, sector rotations, flat/choppy tape",
    },

    "stock_day": {
        "display_name": "Stock Day",
        "asset_class": "stocks",
        "family": "Momentum",
        "thesis": (
            "Trades intraday gappers and earnings momentum. "
            "Exploits the opening-range breakout and VWAP reversion effects "
            "that are strongest in the first 90 minutes of session. "
            "All positions are flat at market close."
        ),
        "entry_rule": (
            "Enter LONG on gap-up stocks opening >3% above prior close with "
            "volume >2× average (ORB/gap-and-go). "
            "Enter LONG after post-earnings-announcement drift (PEAD) gap "
            "above a prior resistance level."
        ),
        "exit_rule": (
            "Exit at EOD hard stop (3:55 PM ET). "
            "Intraday trailing stop: 2× ATR(5) from entry. "
            "VWAP reversion exits when price crosses VWAP back toward it."
        ),
        "risk": (
            "Max intraday loss per position: 1.5× ATR(5). "
            "Max 4 simultaneous positions. "
            "Hard flat at 3:55 PM ET regardless of P&L."
        ),
        "cadence": "Active 9:30 AM–3:55 PM ET, Mon–Fri (intraday only)",
        "academic_source": (
            "Berkman et al. (2012) — overnight gap fades; "
            "Bernard & Thomas (1989) — post-earnings announcement drift"
        ),
        "works_best_in": "High-volume earnings seasons, trending gap days, FOMC mornings",
        "avoid_in": "Low-volume summer/holiday tape, pre-earnings quiet periods",
    },

    "stock_lt": {
        "display_name": "Stock Long-Term",
        "asset_class": "stocks",
        "family": "Trend",
        "thesis": (
            "S&P 500 factor model that rebalances monthly into the top stocks "
            "ranked by a blend of quality, momentum, low-volatility, and "
            "dividend-growth factors. Designed for buy-and-hold investors who "
            "want market exposure with a quality tilt."
        ),
        "entry_rule": (
            "On the first Tuesday of each month, rank the S&P 500 by a composite "
            "factor score (quality + momentum + low-vol + shareholder yield). "
            "Buy the top 10–20 names."
        ),
        "exit_rule": (
            "Sell at next rebalance if a stock drops out of the top 30 factor rank. "
            "Emergency exit: price drops >15% below 12-month high."
        ),
        "risk": (
            "Equal-weight. Monthly rebalance naturally limits drift. "
            "No hard stop; factor rank is the exit trigger."
        ),
        "cadence": "Rebalances monthly (1st Tuesday of each month)",
        "academic_source": (
            "Asness, Frazzini & Pedersen (2019) — quality minus junk; "
            "Novy-Marx (2013) — the other side of value"
        ),
        "works_best_in": "Secular bull markets, multi-year trending regimes",
        "avoid_in": "Bear markets (no hedge; holds through drawdown), credit crises",
    },

    "crypto_swing": {
        "display_name": "Crypto Swing",
        "asset_class": "crypto",
        "family": "Momentum",
        "thesis": (
            "Top-20 crypto by market cap, 1-to-30-day swing holds. "
            "Runs a 6-strategy ensemble tuned for 24/7 crypto markets "
            "with BTC dominance as a regime filter to avoid altcoin bear cycles."
        ),
        "entry_rule": (
            "Enter LONG when 2+ of: crypto RSI mean reversion, crypto momentum "
            "breakout, crypto MACD swing, crypto EMA cross, or crypto relative "
            "strength fires. BTC dominance must not be in an extreme uptrend "
            "(regime gate)."
        ),
        "exit_rule": (
            "Exit when primary signal reverses, 30-day age cap reached, "
            "or BTC dominance spikes >5% in 24h (altcoin flight to safety)."
        ),
        "risk": (
            "Stop: 10% below entry (crypto-sized, not equity). "
            "Position cap: 8 simultaneous positions. "
            "No position exceeds 12% of sub-account."
        ),
        "cadence": "Scans 4× daily (00:00, 06:00, 12:00, 18:00 UTC)",
        "academic_source": (
            "Liu & Tsyvinski (2021) — risk and return of cryptocurrency; "
            "Antonacci (2014) — dual momentum"
        ),
        "works_best_in": "BTC uptrend with altcoin rotation, low-dominance regimes",
        "avoid_in": "BTC dominance spikes, crypto-wide deleveraging events",
    },

    "crypto_day": {
        "display_name": "Crypto Day",
        "asset_class": "crypto",
        "family": "Momentum",
        "thesis": (
            "Intraday momentum and volatility breakouts on BTC, ETH, and SOL. "
            "Exploits the 'weekend effect' liquidity amplification and "
            "session-open asymmetry in 24/7 crypto markets. "
            "All positions force-closed after 8 hours."
        ),
        "entry_rule": (
            "Enter LONG on session-open breakout above first 30-minute high, "
            "OR on volatility breakout exceeding Donchian 20-period range, "
            "with 4-hour bar volume >1.5× 20-period average."
        ),
        "exit_rule": (
            "8-hour force-close (hard max age). "
            "Intraday trailing stop: 1.5× ATR(14) from session high. "
            "Session-close exit at each 6h UTC boundary."
        ),
        "risk": (
            "Max 3 simultaneous positions. "
            "Position size: 8% of sub-account per trade. "
            "No overnight holds."
        ),
        "cadence": "Scans every 5 minutes, 24/7",
        "academic_source": "Kim & Kim (2019) — intraday momentum in cryptocurrency markets",
        "works_best_in": "Trending weekday crypto sessions, high-volume breakout days",
        "avoid_in": "Weekend low-liquidity periods, post-major-liquidation chop",
    },

    "crypto_lt": {
        "display_name": "Crypto Long-Term DCA",
        "asset_class": "crypto",
        "family": "Trend",
        "thesis": (
            "Dollar-cost averaging into BTC, ETH, and top-10 majors "
            "with a monthly rebalance to target weights. "
            "Adds extra buys on >10% drawdowns from 30-day highs. "
            "Designed for long-term accumulation, not active trading."
        ),
        "entry_rule": (
            "Weekly DCA: add fixed amount to BTC/ETH at each weekly interval. "
            "Extra DCA: if any major drops >10% from 30d high, double the weekly buy. "
            "Monthly: rebalance to target weights (BTC 40%, ETH 30%, others 30%)."
        ),
        "exit_rule": (
            "Only at monthly rebalance (sell excess positions above target weight). "
            "Emergency exit if BTC dominance reaches extreme levels signaling systemic risk."
        ),
        "risk": (
            "No single position >40% of sub-account. "
            "DCA smooths entry price over time — no hard stop. "
            "BTC dominance regime gate can pause new buys."
        ),
        "cadence": "Weekly DCA buys + monthly rebalance (1st Tuesday)",
        "academic_source": (
            "Antonacci (2014) — dual momentum applied to crypto; "
            "Faber (2007) — tactical asset allocation"
        ),
        "works_best_in": "Multi-year bull cycles, accumulation phases below ATH",
        "avoid_in": "Bear market death spirals (no hedge; fully long crypto)",
    },

    "crypto_onchain": {
        "display_name": "Crypto On-Chain",
        "asset_class": "crypto",
        "family": "Event-Driven",
        "thesis": (
            "Trades BTC and ETH using blockchain-native signals: "
            "exchange net flows, MVRV-Z score, SOPR capitulation, "
            "funding rates, and social sentiment extremes. "
            "Enters at historically-proven on-chain bottom signals."
        ),
        "entry_rule": (
            "Enter LONG when: MVRV-Z < 0 (historically extreme undervaluation), "
            "OR exchange net outflow sustained for 3+ days (coin supply tightening), "
            "OR STH-SOPR crosses above 1.0 from below (capitulation bottom). "
            "Confirmation: funding rate negative or neutral."
        ),
        "exit_rule": (
            "Exit when MVRV-Z > 4 (historically extreme overvaluation) "
            "OR exchange inflow spike >50% above 30-day average "
            "OR social sentiment Galaxy Score > 80 (greed extreme)."
        ),
        "risk": (
            "On-chain signals are slow-moving (daily/weekly). "
            "Max 3 positions. No hard stop — signal exits dominate. "
            "Position size: 15% per position."
        ),
        "cadence": "Checks on-chain feeds daily at 08:00 UTC",
        "academic_source": (
            "Liu, Tsyvinski & Wu (2022) — common risk factors in crypto; "
            "Glassnode research — MVRV-Z score and SOPR frameworks"
        ),
        "works_best_in": "Bear market bottoms, post-liquidation accumulation zones",
        "avoid_in": "Greed extremes (MVRV-Z > 4), low on-chain activity periods",
    },

    "crypto_quant_aggressive": {
        "display_name": "Crypto Quant Aggressive",
        "asset_class": "crypto",
        "family": "Momentum",
        "thesis": (
            "High-turnover quantitative trading on 20 top-liquid crypto pairs "
            "using an ensemble of 5 signal models: VWAP fade, Bollinger breakout, "
            "momentum trigger, volume z-score spike, and range break-retest. "
            "Signals aggregate — any single signal above threshold can fire."
        ),
        "entry_rule": (
            "ANY of: VWAP deviation >1.5σ (fade), Bollinger band upper break "
            "on 2× volume, momentum trigger (3-period ROC z-score > 2.0), "
            "volume z-score spike >2.5σ, or range break above prior 20-period "
            "high with retest confirmation."
        ),
        "exit_rule": (
            "Each signal has its own exit: VWAP cross for fades, "
            "Bollinger mid-band for breakouts, mean-revert for momentum. "
            "Hard max: 12-hour position age."
        ),
        "risk": (
            "Position cap: 20 simultaneous open positions (1 per coin). "
            "Size: 3–5% of $100k sub-account per position. "
            "Quant ensemble reduces per-signal concentration risk."
        ),
        "cadence": "Scans every 5 minutes, 24/7",
        "academic_source": (
            "Gross & Wunder (2021) — crypto quant momentum; "
            "Barberis et al. (2015) — extrapolation and asset prices"
        ),
        "works_best_in": "High-volume trending crypto sessions, breakout days",
        "avoid_in": "Ultra-low-volume weekends, post-liquidation chop",
    },

    "crypto_quant_mean_reversion": {
        "display_name": "Crypto Quant Mean Reversion",
        "asset_class": "crypto",
        "family": "Mean Reversion",
        "thesis": (
            "Short-term mean reversion on 24/7 crypto markets. "
            "Buys oversold conditions and fades overbought extremes "
            "using z-score, RSI, Bollinger, Keltner, and pin-bar signals "
            "on 5-minute bars. Profits from overextended moves reverting to VWAP."
        ),
        "entry_rule": (
            "Enter LONG when: 30-day z-score < -2.0, OR RSI(2) on 5m < 8, "
            "OR price is outside Keltner channel lower band + pin-bar rejection candle. "
            "Enter SHORT on mirror conditions above."
        ),
        "exit_rule": (
            "Exit when z-score returns to 0 (mean), RSI(2) > 65, "
            "or price returns inside Keltner channel. "
            "Max hold: 2 hours."
        ),
        "risk": (
            "Stop: 1.5× ATR(14) from entry. "
            "No position held through a major news event. "
            "Position cap: 10 simultaneous positions."
        ),
        "cadence": "Scans every 5 minutes, 24/7",
        "academic_source": (
            "De Bondt & Thaler (1985) — mean reversion in stock prices; "
            "Connors & Alvarez (2009) — short-term trading strategies"
        ),
        "works_best_in": "Range-bound, low-trending crypto sessions, sideways markets",
        "avoid_in": "Strong directional trends (momentum overrides reversion), news events",
    },

    "crypto_quant_scalper": {
        "display_name": "Crypto Quant Scalper",
        "asset_class": "crypto",
        "family": "Mean Reversion",
        "thesis": (
            "Ultra-short-term scalping on 1-minute crypto bars. "
            "Reads orderbook imbalance, tape acceleration, and micro-breakouts "
            "to capture 0.1–0.3% moves at high frequency. "
            "Highest trade count of all bots; edge is speed and volume, not size."
        ),
        "entry_rule": (
            "Enter when: orderbook bid/ask imbalance >3:1 at current price level, "
            "OR tape acceleration (tick velocity >2× 5-minute baseline), "
            "OR micro-breakout above 5-period high on 1m bar with volume spike."
        ),
        "exit_rule": (
            "Exit at 0.2% profit (hard take-profit) or 0.15% loss (hard stop). "
            "Max hold: 15 minutes. "
            "VWAP band rejection triggers immediate exit."
        ),
        "risk": (
            "Very tight stops (0.15%). "
            "High frequency compensates for small per-trade edge. "
            "Max 5 simultaneous positions."
        ),
        "cadence": "Scans every 1 minute, 24/7",
        "academic_source": (
            "Menkveld (2013) — high frequency trading and the new market makers; "
            "Madhavan (2000) — market microstructure"
        ),
        "works_best_in": "High-liquidity major sessions (10 AM–2 PM UTC), trending tape",
        "avoid_in": "Thin weekend markets, immediately post-major-news (wide spreads)",
    },

    "options_income": {
        "display_name": "Options Income",
        "asset_class": "options",
        "family": "Carry",
        "thesis": (
            "Systematic premium selling on SPY, QQQ, and large-cap ETFs. "
            "Sells iron condors and cash-secured puts when implied volatility is "
            "elevated (IVR > 50), collecting theta decay as the primary edge. "
            "Designed to generate consistent income in range-bound markets."
        ),
        "entry_rule": (
            "Sell 16-delta strangle (iron condor) or 30-delta cash-secured put "
            "on SPY/QQQ/IWM when IVR proxy > 50 AND 5-day ATR contracting. "
            "45 DTE entry. Max 6 simultaneous positions."
        ),
        "exit_rule": (
            "Close at 50% of credit received (standard Tastytrade rule). "
            "Or at 21 DTE regardless of P&L (avoid gamma risk). "
            "Emergency close if short strike breached."
        ),
        "risk": (
            "2–3% buying power per position. "
            "Never exceed 50% of account in short premium at once. "
            "Hard stop if tested strike is breached."
        ),
        "cadence": "Evaluates daily at 10:00 AM ET for new entries; monitors open positions",
        "academic_source": (
            "Israelov & Nielsen (2014) — covered calls; "
            "Sosnoff (2014) — tastytrade mechanical premium selling"
        ),
        "works_best_in": "High IVR environments, range-bound markets, post-FOMC calm",
        "avoid_in": "Trending strongly directional markets, very low IVR (insufficient premium)",
    },

    "options_directional": {
        "display_name": "Options Directional",
        "asset_class": "options",
        "family": "Volatility",
        "thesis": (
            "Buys long calls or puts on momentum setups in high-liquidity stocks. "
            "Uses options for capital efficiency and defined risk. "
            "Enters when a strong directional signal aligns with cheap implied vol "
            "(IVR < 30) so you're not overpaying for the move."
        ),
        "entry_rule": (
            "Buy ATM-to-slight-OTM call when: stock has momentum breakout signal "
            "above 52-week high AND IVR < 30 (cheap vol). "
            "Buy ATM put when: stock breaks below 200d MA with volume confirmation. "
            "30–45 DTE."
        ),
        "exit_rule": (
            "Exit at 100% gain (double the premium). "
            "Stop at 50% loss of premium. "
            "Or exit 21 days before expiry."
        ),
        "risk": (
            "Max loss = premium paid (defined risk). "
            "Position size: 1–2% of account per trade. "
            "Max 6 simultaneous positions."
        ),
        "cadence": "Evaluates daily at 10:00 AM ET for new setups",
        "academic_source": (
            "Black & Scholes (1973) — option pricing; "
            "Coval & Shumway (2001) — expected option returns"
        ),
        "works_best_in": "Low-IVR trending markets, pre-earnings momentum setups",
        "avoid_in": "High-IVR environments (overpriced options), choppy whipsaw markets",
    },

    # ── Incubation candidates (17) ────────────────────────────────────────────

    "cross_sectional_momentum": {
        "display_name": "Cross-Sectional Momentum",
        "asset_class": "stocks",
        "family": "Momentum",
        "thesis": (
            "Ranks the investment universe by trailing 12-month return, "
            "skipping the most recent month to avoid reversal contamination. "
            "Buys the top quintile, avoids (or shorts) the bottom quintile. "
            "One of the most replicated academic anomalies in finance."
        ),
        "entry_rule": (
            "Monthly: rank universe by 12-1M return. "
            "Buy top-20% ranked names. "
            "Skip-month (exclude last 30 days) reduces short-term reversal noise."
        ),
        "exit_rule": "Exit at next monthly rebalance if rank drops below top 30%.",
        "risk": "Equal-weight within the long book. No leverage.",
        "cadence": "Monthly rebalance",
        "academic_source": "Jegadeesh & Titman (1993) — Returns to buying winners and selling losers",
        "works_best_in": "Trending bull markets with sector rotation",
        "avoid_in": "Momentum crashes (Jan 2009, Mar 2020 reversal periods)",
    },

    "time_series_momentum": {
        "display_name": "Time-Series Momentum",
        "asset_class": "multi",
        "family": "Momentum",
        "thesis": (
            "Each asset is evaluated independently: go long if its 12-month "
            "trailing return is positive, stay out (or short) if negative. "
            "Sized by inverse realized volatility so riskier assets take smaller bets. "
            "Applies across stocks, bonds, commodities, and crypto."
        ),
        "entry_rule": (
            "At each monthly rebalance: if 12M return of asset > 0, go long. "
            "If < 0, go short or hold cash. "
            "Position size = target volatility ÷ realized vol."
        ),
        "exit_rule": "Exit at monthly rebalance if 12M return flips negative.",
        "risk": "Volatility-targeted sizing (10% annualized vol target per asset).",
        "cadence": "Monthly rebalance",
        "academic_source": "Moskowitz, Ooi & Pedersen (2012) — Time series momentum",
        "works_best_in": "Persistent trending regimes, crisis periods (short leg)",
        "avoid_in": "Whipsaw months with rapid trend reversals",
    },

    "crypto_dual_momentum": {
        "display_name": "Crypto Dual Momentum",
        "asset_class": "crypto",
        "family": "Momentum",
        "thesis": (
            "Combines absolute momentum (is this crypto beating cash?) with "
            "relative momentum (which crypto is beating the others?). "
            "Only buys assets clearing both tests, avoiding the worst performers "
            "and holding cash during crypto-wide downturns."
        ),
        "entry_rule": (
            "Monthly: rank top-20 crypto by 3M return. "
            "Buy top-N only if they also have positive 3M absolute return vs. cash. "
            "Otherwise hold stablecoin."
        ),
        "exit_rule": "Exit at monthly rebalance if absolute or relative rank fails.",
        "risk": "Long-only, equal-weight among passing assets.",
        "cadence": "Monthly rebalance",
        "academic_source": (
            "Antonacci (2014) — dual momentum investing; "
            "Liu & Tsyvinski (2021) — risk and return of cryptocurrency"
        ),
        "works_best_in": "Crypto bull cycles with clear relative leaders",
        "avoid_in": "Crypto-wide bear markets (goes to cash by design)",
    },

    "overnight_gap_fade": {
        "display_name": "Overnight Gap Fade",
        "asset_class": "stocks",
        "family": "Mean Reversion",
        "thesis": (
            "Stocks that gap up or down at open tend to partially fill the gap "
            "during the first 90 minutes. Overreaction to overnight news creates "
            "intraday mean reversion opportunity. Edge is strongest for moderate "
            "gaps (1.5–5%) and weaker for extreme gap events."
        ),
        "entry_rule": (
            "Fade gap: sell short stocks gapping up >1.5% at open, "
            "buy stocks gapping down >1.5%, "
            "only when pre-market volume < 150% of average (no strong continuation signal)."
        ),
        "exit_rule": "Exit at gap fill (prior close) or 11:00 AM ET, whichever comes first.",
        "risk": "Stop: 1× gap size beyond open. Max hold: 90 minutes.",
        "cadence": "Intraday, Mon–Fri, entries at 9:35 AM ET",
        "academic_source": (
            "Branch & Ma (2008) — overnight returns and firm-specific news; "
            "Berkman et al. (2012) — sell on the news"
        ),
        "works_best_in": "Normal earnings seasons, low-VIX environments",
        "avoid_in": "Strong trending gap days, FOMC/CPI mornings, very high VIX",
    },

    "rsi2_mean_reversion": {
        "display_name": "RSI-2 Mean Reversion",
        "asset_class": "stocks",
        "family": "Mean Reversion",
        "thesis": (
            "The 2-period RSI is an extreme short-term oscillator. "
            "When it drops below 10 on a stock trading above its 200-day MA, "
            "a 1-5 day bounce is historically probable. "
            "Simple, high-win-rate rule with decades of backtest evidence."
        ),
        "entry_rule": (
            "Buy when RSI(2) closes below 10 AND price is above the 200-day MA "
            "(uptrend filter). "
            "Higher conviction at RSI(2) < 5."
        ),
        "exit_rule": "Exit when RSI(2) closes above 65, or 5 trading days have passed.",
        "risk": "Stop: 3% below entry. Equal-weight positions.",
        "cadence": "Daily scan after market close",
        "academic_source": "Connors & Alvarez (2009) — Short-term trading strategies that work",
        "works_best_in": "Pullbacks in bull markets, oversold bounces in uptrends",
        "avoid_in": "Bear markets (long-only; 200d MA filter helps but not perfect)",
    },

    "cash_and_carry": {
        "display_name": "Cash-and-Carry Basis",
        "asset_class": "crypto",
        "family": "Arbitrage",
        "thesis": (
            "Delta-neutral trade: simultaneously long spot and short perpetual futures "
            "on the same asset. Earns the positive funding rate paid by perp longs "
            "with zero directional exposure. Returns collapse when funding goes negative."
        ),
        "entry_rule": (
            "Enter when 7-day rolling average funding rate > 0.03% per 8h "
            "(annualizes to ~13%). "
            "Long 1 unit spot + short 1 unit perp simultaneously."
        ),
        "exit_rule": "Exit when 3-day rolling funding rate drops below 0.01% per 8h.",
        "risk": "Near-zero directional risk. Exchange counterparty risk. Liquidation risk if margin insufficient.",
        "cadence": "Monitors funding rates every 8 hours",
        "academic_source": "Classic futures basis arbitrage; Duffie (1996) — dynamic asset pricing theory",
        "works_best_in": "Crypto bull markets with sustained positive funding",
        "avoid_in": "Bear markets or periods of negative funding (trade reverses)",
    },

    "liquidation_cascade": {
        "display_name": "Liquidation Cascade",
        "asset_class": "crypto",
        "family": "Event-Driven",
        "thesis": (
            "Large liquidation events create temporary price dislocations. "
            "The strategy enters long after cascades flush out weak hands, "
            "fading the extreme by capturing the mean-revert bounce. "
            "Requires real-time liquidation heatmap data (Coinglass/Binance)."
        ),
        "entry_rule": (
            "Enter LONG when cumulative liquidation volume exceeds $200M in 1 hour "
            "AND price is at a key Coinglass heatmap support cluster "
            "AND funding rate is negative (confirming crowded short)."
        ),
        "exit_rule": "Exit at 2× ATR(14) profit target or 24 hours, whichever comes first.",
        "risk": "Stop: 2× ATR(14) below entry. Position size: 5% of account.",
        "cadence": "24/7 event-driven (fires on liquidation threshold breach)",
        "academic_source": (
            "Brunnermeier & Pedersen (2009) — market liquidity and funding liquidity; "
            "Coinglass real-time liquidation data"
        ),
        "works_best_in": "High-leverage crypto markets, post-flash-crash setups",
        "avoid_in": "Slow grinding bear markets without sharp liquidation spikes",
    },

    "insider_cluster_buying": {
        "display_name": "Insider Cluster Buying",
        "asset_class": "stocks",
        "family": "Event-Driven",
        "thesis": (
            "Corporate insiders have unique knowledge of their company. "
            "When multiple insiders buy simultaneously on the open market "
            "(not exercise of options), it signals genuine conviction in undervaluation. "
            "Cluster buying (3+ insiders, $500k+ combined) is the strongest signal."
        ),
        "entry_rule": (
            "Enter LONG within 3 days of detecting 3+ insiders filing Form 4 purchases "
            "totaling ≥$500k in a 30-day window, "
            "when stock price is below its 200-day MA (deep value setup)."
        ),
        "exit_rule": "Exit after 6 months or when insider signal reverses (cluster selling).",
        "risk": "Equal-weight, 15% max per position. Long hold = low turnover, low cost.",
        "cadence": "Daily scan of SEC EDGAR Form 4 filings",
        "academic_source": "Lakonishok & Lee (2001) — Are insider trades informative?",
        "works_best_in": "Bear markets / oversold deep-value setups with insider conviction",
        "avoid_in": "Momentum-driven bull markets (insiders often wrong short-term timing)",
    },

    "cross_asset_momentum": {
        "display_name": "Cross-Asset Momentum",
        "asset_class": "multi",
        "family": "Cross-Asset",
        "thesis": (
            "Rotates across 10 ETFs (equities, bonds, gold, REITs, commodities) "
            "into the top-3 performers by blended 1/3/12-month momentum. "
            "An absolute return filter prevents buying into declining assets. "
            "Credit spread gate reduces size during macro stress."
        ),
        "entry_rule": (
            "Monthly: rank 10 ETFs by blended momentum score (1M×0.3 + 3M×0.3 + 12M×0.4). "
            "Buy top 3 ONLY if each has positive absolute return over the lookback. "
            "Otherwise hold short-term bonds."
        ),
        "exit_rule": "Exit at monthly rebalance if asset drops out of top 5 or fails absolute test.",
        "risk": "Equal-weight across top 3 ETFs. Credit spread width used as macro gate.",
        "cadence": "Monthly rebalance",
        "academic_source": "Antonacci (2014) — Global Equities Momentum (GEM)",
        "works_best_in": "Multi-asset trending regimes, clear risk-on or risk-off periods",
        "avoid_in": "Rapid regime changes, correlation breakdown events",
    },

    "earnings_vol_premium": {
        "display_name": "Earnings Vol Premium",
        "asset_class": "options",
        "family": "Volatility",
        "thesis": (
            "Options are systematically overpriced in the week before earnings. "
            "Selling an iron condor 7 days out and holding through the event "
            "captures the IV crush that follows announcement. "
            "Works because the actual move is usually smaller than the priced-in move."
        ),
        "entry_rule": (
            "7 days before earnings: sell 16-delta iron condor on the reporting stock "
            "when IV rank ≥ 70% AND implied move ≥ 5%. "
            "Universe: NVDA, TSLA, META, NFLX, COIN, AMD, MU."
        ),
        "exit_rule": (
            "Exit morning after earnings announcement (capture IV crush). "
            "Or stop out if short strike is tested pre-earnings."
        ),
        "risk": "Max 3% buying power per position. Hard stop if short strike breached.",
        "cadence": "Scans for upcoming earnings weekly",
        "academic_source": (
            "Augustin, Brenner & Subrahmanyam (2014) — informed options trading pre-earnings; "
            "Goyal & Saretto (2009) — cross-section of expected option returns"
        ),
        "works_best_in": "High-IVR earnings seasons, stable macro backdrop",
        "avoid_in": "Market-wide VIX spikes (gap risk overwhelms IV crush),  low-IVR environments",
    },

    "quality_momentum_screen": {
        "display_name": "Quality Momentum Screen",
        "asset_class": "stocks",
        "family": "Momentum",
        "thesis": (
            "Combines Asness et al.'s quality factor (high profitability, safety, "
            "growth) with 12-1 month momentum and low beta. Monthly rebalance into "
            "25 stocks that score highly on all three dimensions. "
            "Flattens to cash when credit spreads widen (macro risk-off gate)."
        ),
        "entry_rule": (
            "Monthly: rank S&P 500 by composite quality score "
            "(ROE, gross profit, debt/equity, earnings stability) "
            "+ 12-1M momentum + beta penalty. "
            "Buy top 25. Flatten to cash if IG credit spread > 150 bps."
        ),
        "exit_rule": "Exit at monthly rebalance if composite rank drops below top 40.",
        "risk": "Equal-weight. Cash gate prevents buying into credit crises.",
        "cadence": "Monthly rebalance",
        "academic_source": "Asness, Frazzini & Pedersen (2019) — quality minus junk",
        "works_best_in": "Quality-growth market regimes, late-cycle environments",
        "avoid_in": "Junk rallies (low-quality outperformance), deep value cycles",
    },

    "options_iv_premium_filter": {
        "display_name": "Options IV Premium Filter",
        "asset_class": "options",
        "family": "Carry",
        "thesis": (
            "Implied volatility is consistently overpriced relative to realized vol "
            "(the volatility risk premium, VRP). Selling premium when IV rank "
            "is elevated is the most consistent edge in the options market. "
            "IVR filter prevents selling when vol is actually cheap."
        ),
        "entry_rule": (
            "Sell 30-delta cash-secured put or covered call when IV Rank ≥ 50. "
            "Half-size at IVR 30–49. "
            "Skip entirely below IVR 30."
        ),
        "exit_rule": "Close at 50% of credit received or 21 DTE.",
        "risk": "2% buying power per position. No position if IVR < 30.",
        "cadence": "Daily evaluation",
        "academic_source": "Israelov & Nielsen (2014) — covered calls and the risk-adjusted performance",
        "works_best_in": "High-IVR environments after volatility spikes",
        "avoid_in": "Low-VIX complacency (no edge selling cheap vol)",
    },

    "options_short_strangle_45d": {
        "display_name": "Short Strangle 45 DTE",
        "asset_class": "options",
        "family": "Carry",
        "thesis": (
            "Sell an OTM call and put simultaneously on high-liquidity ETFs "
            "when volatility is elevated. Profits from theta decay and "
            "IV compression toward expiry. The 45 DTE entry maximizes "
            "theta decay profile while giving the underlying room to move."
        ),
        "entry_rule": (
            "Sell 16-delta call + put on SPY/QQQ/IWM/EEM/GLD/TLT "
            "when IVR > 50 AND 20-day price range < 10% (range-bound). "
            "45 DTE. 3% buying power per position."
        ),
        "exit_rule": "Close at 50% credit | 21 DTE | short strike breach.",
        "risk": "3% buying power per position. Max 4 simultaneous strangles.",
        "cadence": "Daily evaluation at 10:00 AM ET",
        "academic_source": "Tastytrade Research — IVR-filtered premium selling",
        "works_best_in": "Range-bound markets, high IVR environments",
        "avoid_in": "Strongly trending markets, low-IVR environments",
    },

    "options_iron_condor_spy": {
        "display_name": "Iron Condor SPY",
        "asset_class": "options",
        "family": "Carry",
        "thesis": (
            "Sell a defined-risk iron condor on SPY with 10-point wings. "
            "Enters when volatility is elevated and ATR is contracting, "
            "signaling range-bound conditions. "
            "Wings provide disaster protection; net credit is the max profit."
        ),
        "entry_rule": (
            "Sell 16-delta strangle + buy 10-wide wings on SPY, 45 DTE. "
            "Entry: IVR > 30 AND 5-day ATR < 20-day ATR (contraction)."
        ),
        "exit_rule": "Close at 50% credit | 21 DTE | short strike breach.",
        "risk": "2% account risk per condor. Max 3 simultaneous condors.",
        "cadence": "Weekly evaluation on Mondays",
        "academic_source": "Sosnoff (2014) — tastytrade mechanical iron condor",
        "works_best_in": "Low-drift, range-bound SPY sessions, contracting ATR",
        "avoid_in": "Trend-following regimes, FOMC weeks, major macro uncertainty",
    },

    "options_wheel_mechanical": {
        "display_name": "Wheel Strategy (Mechanical)",
        "asset_class": "options",
        "family": "Carry",
        "thesis": (
            "State-machine income strategy: sell cash-secured puts; if assigned, "
            "sell covered calls until shares are called away; repeat. "
            "Generates income from premium on stocks you'd be comfortable owning. "
            "Works best on dividend payers and stable large-caps."
        ),
        "entry_rule": (
            "Sell 30-delta CSP on dividend ETFs/large caps when IVR > 30 and beta < 1.5. "
            "On assignment, immediately sell 30-delta covered call."
        ),
        "exit_rule": (
            "CSP: close at 50% credit or allow assignment. "
            "CC: close at 50% credit or allow assignment (shares called away). "
            "Hard stop: -20% on assigned stock."
        ),
        "risk": "Max 3 wheel positions. Hard stop if stock falls >20% post-assignment.",
        "cadence": "Weekly evaluation and roll",
        "academic_source": "Mechanical wheel — CSP → assignment → covered call",
        "works_best_in": "Range-bound to slightly bullish markets on stable stocks",
        "avoid_in": "Bear markets on high-beta or growth stocks (assignment risk)",
    },

    "options_0dte_spx_condor": {
        "display_name": "0DTE SPX Iron Condor",
        "asset_class": "options",
        "family": "Carry",
        "thesis": (
            "Same-day-expiry SPX iron condor entered at 9:35 AM ET. "
            "The 0DTE market has grown explosively; same-day theta decay is "
            "extreme and can be captured in minutes to hours. "
            "Requires precise entry timing and strict time stops."
        ),
        "entry_rule": (
            "At 9:35 AM ET: sell 10-delta SPX condor with 25-point wings "
            "that expire today (0DTE). "
            "Skip FOMC/CPI weeks. Skip if VIX > 30."
        ),
        "exit_rule": "Close at 50% credit | 3 PM ET hard time stop | strike breach.",
        "risk": "0.75% per trade (strict). Max 2 simultaneous 0DTE positions.",
        "cadence": "Daily at 9:35 AM ET, Mon–Fri",
        "academic_source": "0DTE SPX condor — gamma scalping at 9:35 ET",
        "works_best_in": "Quiet, range-bound trading days with normal VIX",
        "avoid_in": "FOMC/CPI days, VIX > 30, strong trending opens",
    },

    "options_post_earnings_ic": {
        "display_name": "Post-Earnings IV Crush IC",
        "asset_class": "options",
        "family": "Volatility",
        "thesis": (
            "The largest IV collapse of the year happens the morning after earnings. "
            "Entering a 30-DTE iron condor within 24 hours of the announcement "
            "captures residual premium that investors paid for uncertainty "
            "that has now resolved."
        ),
        "entry_rule": (
            "Within 24h of earnings report: sell 16-delta IC with 10-wide wings, "
            "30 DTE, when pre-announcement IVR was > 50. "
            "Universe: NVDA, TSLA, META, NFLX, COIN, AMD, MU."
        ),
        "exit_rule": "Close at 25% credit | 21 DTE. Stop if short strike breached.",
        "risk": "Max 2% per position. Limited to high-liquidity mega-cap names.",
        "cadence": "Event-driven — fires within 24h of each earnings report",
        "academic_source": (
            "Augustin et al. (2014) — informed options trading around earnings; "
            "Earnings IV crush is a well-documented anomaly"
        ),
        "works_best_in": "Earnings season with high pre-event IVR",
        "avoid_in": "Macro-event weeks, stocks with binary outcomes (FDA approvals)",
    },
}
