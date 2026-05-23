"""
Curated financial glossary — brief (tooltip) + full (panel) definitions.
Used as fallback when no AI key is configured.
"""

from __future__ import annotations

GLOSSARY: dict[str, dict] = {
    # ── Valuation ──────────────────────────────────────────────────────────
    "p/e ratio": {
        "aliases": ["pe ratio", "price-to-earnings", "price to earnings", "p/e"],
        "brief": "How much investors pay per $1 of annual earnings. S&P 500 average is ~17×.",
        "full": (
            "The Price-to-Earnings (P/E) ratio divides a stock's price by its earnings per share (EPS). "
            "A P/E of 20 means investors pay $20 for every $1 the company earns annually.\n\n"
            "Two variants matter: **Trailing P/E** uses the last 12 months of actual earnings. "
            "**Forward P/E** uses the next 12 months of analyst estimates — more relevant since you're buying the future.\n\n"
            "Context is everything. A 35× P/E is cheap for a 40% grower but expensive for a 2% grower. "
            "Always compare against the company's own history, sector peers, and the growth rate (see PEG ratio)."
        ),
        "related": ["eps", "peg ratio", "forward p/e", "ev/ebitda"],
    },
    "eps": {
        "aliases": ["earnings per share"],
        "brief": "Net income divided by shares outstanding — the number Wall Street estimates are based on.",
        "full": (
            "Earnings Per Share (EPS) = Net Income ÷ Weighted Average Shares Outstanding. "
            "It's the standard unit of profitability Wall Street forecasts and compares.\n\n"
            "**Diluted EPS** includes the potential dilution from options, warrants, and convertibles — always the more conservative and preferred figure.\n\n"
            "**Adjusted EPS** strips out one-time items (asset sales, restructuring charges) to show recurring earnings power. "
            "When a company 'beats estimates,' they're almost always beating the adjusted EPS consensus."
        ),
        "related": ["p/e ratio", "net income", "dilution"],
    },
    "peg ratio": {
        "aliases": ["peg", "price/earnings to growth"],
        "brief": "P/E divided by earnings growth rate. Below 1.0 often signals undervaluation.",
        "full": (
            "PEG = P/E Ratio ÷ EPS Growth Rate. It adjusts the P/E for the company's growth, "
            "answering: 'Are you paying a fair price for the growth you're getting?'\n\n"
            "A PEG below 1.0 is often considered undervalued — you're paying less than 1× for each unit of growth. "
            "Above 2.0 may indicate the growth is already fully priced in.\n\n"
            "Limitation: PEG relies on analyst growth estimates, which are often wrong. "
            "Use it as a directional guide, not a precise target."
        ),
        "related": ["p/e ratio", "eps", "growth rate"],
    },
    "ev/ebitda": {
        "aliases": ["enterprise value to ebitda", "ev ebitda"],
        "brief": "Enterprise value divided by EBITDA — favored by M&A bankers for cross-company comparisons.",
        "full": (
            "EV/EBITDA compares a company's total value (equity + debt − cash) to its earnings before interest, "
            "taxes, depreciation, and amortization.\n\n"
            "It's preferred over P/E for three reasons: it works when net income is negative, "
            "it's capital-structure neutral (same whether funded by debt or equity), "
            "and it ignores depreciation differences between companies.\n\n"
            "Typical ranges: Software/SaaS 15–40×, Healthcare 12–20×, Industrials 8–12×, Energy 5–8×. "
            "Private equity buyout firms typically pay 7–12× EBITDA."
        ),
        "related": ["enterprise value", "ebitda", "p/e ratio", "comps"],
    },
    "market cap": {
        "aliases": ["market capitalization", "market value"],
        "brief": "Stock price × shares outstanding. The market's current price tag on the whole company.",
        "full": (
            "Market Capitalization = Stock Price × Total Shares Outstanding. "
            "It's the total dollar value the stock market places on the company right now.\n\n"
            "Size categories: Large-cap (>$10B), Mid-cap ($2–10B), Small-cap ($300M–2B), Micro-cap (<$300M). "
            "These categories matter because they behave differently — small-caps are more volatile "
            "but historically outperform large-caps over long periods.\n\n"
            "Market cap alone doesn't tell you if a stock is cheap or expensive. "
            "A $100B market cap is cheap if the company earns $10B/year, expensive if it earns $500M."
        ),
        "related": ["enterprise value", "shares outstanding", "float"],
    },
    "enterprise value": {
        "aliases": ["ev"],
        "brief": "Market cap + debt − cash. The 'true' acquisition cost of a business.",
        "full": (
            "Enterprise Value (EV) = Market Cap + Total Debt − Cash & Cash Equivalents.\n\n"
            "Think of it as the price an acquirer would actually pay: they'd pay the market cap for the equity, "
            "inherit the debt (cost), and receive the cash (offset).\n\n"
            "Example: A company with $10B market cap, $3B debt, $1B cash has EV of $12B. "
            "EV is always the numerator in acquisition-style multiples like EV/EBITDA and EV/Sales."
        ),
        "related": ["market cap", "ev/ebitda", "net debt"],
    },
    "book value": {
        "aliases": ["book value per share", "p/b ratio", "price to book"],
        "brief": "Net assets per share (assets minus liabilities). Stock trading below book value = trading below liquidation value.",
        "full": (
            "Book Value Per Share = (Total Assets − Total Liabilities) ÷ Shares Outstanding. "
            "It's the accounting value of what shareholders would receive if the company were liquidated today.\n\n"
            "The Price-to-Book (P/B) ratio compares market price to book value. "
            "P/B < 1.0 means the stock trades below its accounting net worth — historically a value signal. "
            "P/B is most meaningful for banks, insurance companies, and asset-heavy industrials. "
            "For asset-light businesses (software, brands), P/B has little meaning."
        ),
        "related": ["p/e ratio", "net assets", "goodwill"],
    },
    # ── Indicators ─────────────────────────────────────────────────────────
    "rsi": {
        "aliases": ["relative strength index"],
        "brief": "Momentum oscillator (0–100). Above 70 = potentially overbought. Below 30 = potentially oversold.",
        "full": (
            "The Relative Strength Index (RSI) measures the speed and magnitude of recent price changes. "
            "It's displayed as a number from 0 to 100, calculated by comparing average gains to average losses "
            "over the past 14 days (default period).\n\n"
            "Classic interpretation: RSI > 70 = overbought (pullback risk), RSI < 30 = oversold (bounce potential). "
            "But in strong trends, RSI can stay above 70 for weeks — it's not a standalone sell signal.\n\n"
            "The more powerful signal is **RSI divergence**: price makes a new high but RSI doesn't — "
            "momentum is weakening, warning of a potential reversal."
        ),
        "related": ["macd", "momentum", "divergence", "overbought"],
    },
    "macd": {
        "aliases": ["moving average convergence divergence"],
        "brief": "Trend-following momentum indicator using two EMAs. Crossover = buy/sell signal.",
        "full": (
            "MACD = 12-day EMA minus 26-day EMA. The Signal Line is a 9-day EMA of MACD. "
            "The Histogram is the difference between them.\n\n"
            "**Signal line crossover**: MACD crossing above Signal = bullish momentum building. "
            "Crossing below = bearish momentum. Crossovers above the zero line are stronger signals.\n\n"
            "**Histogram divergence** is the most powerful signal: if price makes a new high but the "
            "histogram is lower, momentum is decelerating — often precedes a reversal.\n\n"
            "Limitation: MACD is a lagging indicator and produces many false signals in choppy markets."
        ),
        "related": ["rsi", "ema", "moving average", "momentum"],
    },
    "moving average": {
        "aliases": ["sma", "ema", "simple moving average", "exponential moving average", "200-day ma", "50-day ma"],
        "brief": "Average price over a rolling window. Smooths noise and reveals trend direction.",
        "full": (
            "A moving average calculates the average closing price over a set number of days (period), "
            "rolling forward each day. It smooths out daily noise to reveal the underlying trend.\n\n"
            "**SMA (Simple)**: Equal weight to all days. The 200-day SMA is the most-watched trend filter on Wall Street.\n\n"
            "**EMA (Exponential)**: More weight to recent prices. Reacts faster. Day traders use the 9/21 EMA.\n\n"
            "Key levels: 50-day (intermediate support/resistance), 200-day (long-term trend filter). "
            "Price above the 200-day SMA = generally bullish regime."
        ),
        "related": ["golden cross", "death cross", "support", "resistance"],
    },
    "beta": {
        "aliases": [],
        "brief": "How much a stock moves relative to the market. Beta 1.5 = moves 50% more than the S&P 500.",
        "full": (
            "Beta measures a stock's sensitivity to overall market movements, with the S&P 500 as the benchmark (beta = 1.0).\n\n"
            "Beta 1.5: the stock typically moves 50% more than the market in either direction. "
            "If the S&P falls 10%, this stock typically falls ~15%.\n\n"
            "Beta 0.5: half as volatile as the market. Utilities and consumer staples often have low beta.\n\n"
            "Beta near 0: nearly uncorrelated with the market (gold, some alternative assets).\n\n"
            "Negative beta: moves opposite the market (rare). "
            "Note: beta is calculated from historical returns and may not predict future volatility."
        ),
        "related": ["volatility", "sharpe ratio", "correlation"],
    },
    "sharpe ratio": {
        "aliases": ["sharpe"],
        "brief": "Return per unit of risk taken. Above 1.0 is good. Below 0 means cash would have been better.",
        "full": (
            "Sharpe Ratio = (Portfolio Return − Risk-Free Rate) ÷ Portfolio Volatility (standard deviation).\n\n"
            "It answers: how much return did I get for each unit of risk I took?\n\n"
            "Benchmarks: Sharpe > 2.0 = excellent. 1.0–2.0 = good. 0–1.0 = mediocre. "
            "Negative = you'd have done better holding cash.\n\n"
            "The Sharpe ratio penalizes volatility equally on the upside and downside. "
            "The Sortino ratio (a variant) only penalizes downside volatility — "
            "often a better measure for return-seeking portfolios."
        ),
        "related": ["volatility", "max drawdown", "risk-adjusted return", "beta"],
    },
    "max drawdown": {
        "aliases": ["maximum drawdown", "drawdown"],
        "brief": "Largest peak-to-trough loss in portfolio history. A 50% drop requires a 100% gain to recover.",
        "full": (
            "Maximum Drawdown is the largest percentage loss from a portfolio's peak value to its subsequent trough, "
            "before a new peak is reached.\n\n"
            "Why it matters psychologically: large drawdowns are the main reason investors abandon good strategies. "
            "A strategy with 20% annual returns but 60% max drawdown is unlivable for most people — "
            "they'll bail near the bottom.\n\n"
            "Recovery math: a 25% drawdown requires a 33% gain to recover. "
            "A 50% drawdown requires a 100% gain. A 75% drawdown requires a 300% gain.\n\n"
            "Controlling max drawdown through position sizing and stop losses preserves capital and composure."
        ),
        "related": ["sharpe ratio", "volatility", "stop loss", "position sizing"],
    },
    # ── Fundamentals ───────────────────────────────────────────────────────
    "free cash flow": {
        "aliases": ["fcf", "free cash flow yield"],
        "brief": "Cash left after paying for all capex. The purest measure of profitability.",
        "full": (
            "Free Cash Flow = Operating Cash Flow − Capital Expenditures.\n\n"
            "It's the cash a company generates after spending everything needed to maintain and grow the business. "
            "This is the cash available for dividends, buybacks, acquisitions, or debt repayment.\n\n"
            "Warren Buffett focuses on 'owner earnings' (similar concept): what can actually be taken out of "
            "the business without impairing its competitive position?\n\n"
            "**FCF Yield** = FCF ÷ Market Cap. Above 4–5% often indicates good value. "
            "FCF is harder to manipulate than net income — it's the closest thing to objective profitability."
        ),
        "related": ["operating cash flow", "capex", "net income", "owner earnings"],
    },
    "ebitda": {
        "aliases": [],
        "brief": "Earnings before interest, taxes, depreciation, and amortization. A proxy for operating cash flow.",
        "full": (
            "EBITDA = Earnings Before Interest, Taxes, Depreciation, and Amortization.\n\n"
            "It's designed to approximate a company's operating cash-generating ability, "
            "stripping out financing decisions (interest), tax jurisdiction differences, "
            "and non-cash accounting (D&A).\n\n"
            "Critics (including Charlie Munger) note that depreciation is very real — "
            "physical assets wear out and must be replaced. 'EBITDA is not earnings.'\n\n"
            "Still the most-used metric in M&A, leveraged buyouts, and cross-company comparisons "
            "because it allows apples-to-apples comparison across different capital structures."
        ),
        "related": ["ev/ebitda", "operating income", "depreciation", "free cash flow"],
    },
    "gross margin": {
        "aliases": ["gross profit margin"],
        "brief": "Revenue minus COGS, as a percentage of revenue. Measures core product profitability.",
        "full": (
            "Gross Margin = (Revenue − Cost of Goods Sold) ÷ Revenue × 100.\n\n"
            "It measures how efficiently a company produces its products or services. "
            "High gross margin = strong pricing power or low production costs.\n\n"
            "SaaS software: typically 70–80% gross margins (low marginal cost of another user). "
            "Retailers: 25–35%. Commodity producers: 5–15%.\n\n"
            "Expanding gross margins over time signal improving competitive position. "
            "Contracting gross margins — especially while revenue grows — is a yellow flag: "
            "the company may be cutting prices to grow, or input costs are rising."
        ),
        "related": ["operating margin", "net margin", "cost of goods sold", "pricing power"],
    },
    "roe": {
        "aliases": ["return on equity"],
        "brief": "Net income divided by shareholders' equity. Measures how efficiently the company uses owners' capital.",
        "full": (
            "Return on Equity (ROE) = Net Income ÷ Shareholders' Equity.\n\n"
            "It answers: for every dollar shareholders have invested, how much profit does management generate?\n\n"
            "ROE > 15–20% is generally considered good. Warren Buffett looks for consistently high ROE "
            "(without excessive debt) as a sign of durable competitive advantage.\n\n"
            "Caveat: ROE can be inflated by high leverage — a heavily indebted company can show high ROE "
            "even with mediocre operations. Always check ROE alongside debt levels."
        ),
        "related": ["roa", "roce", "net income", "shareholders equity"],
    },
    "dividend yield": {
        "aliases": ["dividend", "yield"],
        "brief": "Annual dividend per share divided by stock price. How much income you earn per dollar invested.",
        "full": (
            "Dividend Yield = Annual Dividend Per Share ÷ Stock Price × 100.\n\n"
            "A 3% yield means you receive $3 annually for every $100 invested (before taxes).\n\n"
            "High yields (>5–6%) deserve scrutiny: either the stock has fallen sharply (yield rises as price falls), "
            "or the dividend is at risk of being cut. A 'dividend trap' is a high-yield stock "
            "where the dividend is unsustainable.\n\n"
            "Look at the payout ratio (dividends ÷ net income): above 80–90% is a warning sign. "
            "The best dividend stocks grow their dividends consistently — dividend growth, not just current yield, "
            "is what compounds wealth."
        ),
        "related": ["payout ratio", "dividend growth", "yield trap", "income investing"],
    },
    # ── Options ────────────────────────────────────────────────────────────
    "call option": {
        "aliases": ["call"],
        "brief": "Right (not obligation) to buy 100 shares at the strike price before expiration.",
        "full": (
            "A call option gives the holder the right — but not the obligation — to purchase 100 shares "
            "of the underlying stock at the strike price, at any time before the expiration date.\n\n"
            "You pay a premium upfront. Maximum loss = premium paid. "
            "Profit begins when the stock price exceeds strike + premium paid.\n\n"
            "Calls are used for: leveraged bullish bets, covered calls (income on existing positions), "
            "and hedging short positions.\n\n"
            "Leverage example: buying a $2 call on a $50 stock costs $200 (1 contract = 100 shares). "
            "If the stock rises to $60, the call is worth at least $10 ($1,000) — a 5× return "
            "on a 20% stock move."
        ),
        "related": ["put option", "strike price", "expiration", "premium", "delta"],
    },
    "put option": {
        "aliases": ["put"],
        "brief": "Right (not obligation) to sell 100 shares at the strike price before expiration.",
        "full": (
            "A put option gives the holder the right — but not the obligation — to sell 100 shares "
            "at the strike price before expiration.\n\n"
            "Puts profit when the stock falls below the strike price. "
            "They're used for: hedging long stock positions (portfolio insurance), "
            "bearish speculation, and generating income by selling puts (cash-secured puts).\n\n"
            "Puts become very expensive before earnings or when market volatility is high — "
            "check implied volatility before buying puts as protection."
        ),
        "related": ["call option", "strike price", "implied volatility", "delta"],
    },
    "implied volatility": {
        "aliases": ["iv", "implied vol"],
        "brief": "The market's forecast of future price movement, embedded in option prices. High IV = expensive options.",
        "full": (
            "Implied Volatility (IV) is derived from option prices — it's the market's consensus forecast "
            "of how much the stock will move over the option's life.\n\n"
            "High IV = expensive options (market expects big moves). Typical around earnings. "
            "Low IV = cheap options (market expects calm). Typical in low-volatility markets.\n\n"
            "**IV crush**: After earnings are released, uncertainty resolves and IV collapses — "
            "option prices drop even if the stock moved as expected. "
            "Buying options before earnings and holding through them is often a losing strategy because of IV crush.\n\n"
            "The VIX is the IV of S&P 500 index options — the market's 'fear gauge.'"
        ),
        "related": ["vix", "option premium", "call option", "put option", "iv crush"],
    },
    "delta": {
        "aliases": [],
        "brief": "How much an option price moves per $1 move in the stock. ATM call ≈ 0.50.",
        "full": (
            "Delta measures how much an option's price changes for a $1 move in the underlying stock.\n\n"
            "Deep in-the-money call: delta ~0.90 (moves almost like the stock). "
            "At-the-money call: delta ~0.50. Far out-of-the-money call: delta ~0.10.\n\n"
            "Delta also approximates the probability the option expires in the money: "
            "delta 0.50 ≈ 50% chance of expiring ITM.\n\n"
            "Portfolio delta: multiply each option's delta by 100 (contract size) and sum across positions. "
            "Net positive delta = net bullish exposure. Net negative = bearish."
        ),
        "related": ["gamma", "theta", "call option", "implied volatility"],
    },
    "theta": {
        "aliases": ["time decay"],
        "brief": "Daily option value lost due to time passing. Accelerates in the final 30 days before expiration.",
        "full": (
            "Theta is the amount an option loses in value each day, all else equal — time decay.\n\n"
            "An option with theta of -0.05 loses $0.05 per day ($5 per contract).\n\n"
            "Time decay accelerates non-linearly: it's fastest in the last 30 days before expiration. "
            "This is why buying options far from expiration is often preferable — "
            "you're not racing against the clock as aggressively.\n\n"
            "Theta works in the seller's favor: option sellers collect premium that erodes over time. "
            "The most common income strategies (covered calls, cash-secured puts, credit spreads) "
            "exploit theta."
        ),
        "related": ["option premium", "implied volatility", "delta", "expiration"],
    },
    # ── Market structure ───────────────────────────────────────────────────
    "short selling": {
        "aliases": ["short sell", "short", "shorting"],
        "brief": "Borrowing shares to sell now, hoping to buy them back cheaper later. Profit from price declines.",
        "full": (
            "Short selling: borrow shares from a broker, sell them immediately, then buy them back later "
            "at (hopefully) a lower price. Profit = sale price − buyback price − borrowing costs.\n\n"
            "Risk is theoretically unlimited: a stock can only fall to zero (limited profit), "
            "but can rise indefinitely (unlimited loss).\n\n"
            "Short squeezes occur when heavily shorted stocks rise rapidly, forcing short sellers to cover "
            "(buy) simultaneously — which pushes the price higher, forcing more covering. "
            "GameStop in January 2021 is the canonical example.\n\n"
            "Short interest ratio (days to cover): high short interest + low float = higher squeeze risk."
        ),
        "related": ["short squeeze", "short interest", "float", "margin"],
    },
    "support": {
        "aliases": ["support level"],
        "brief": "A price level where buying pressure tends to halt or reverse a decline.",
        "full": (
            "Support is a price level where a stock has historically found buying interest — "
            "demand has consistently outpaced supply at this level.\n\n"
            "Why support exists: traders remember previous lows. Investors who missed a previous bounce "
            "say 'I'll buy if it gets back to that level.' This collective memory creates buying pressure.\n\n"
            "The more times a support level holds, the more significant it is — but once broken, "
            "a former support level often becomes resistance (the level flips).\n\n"
            "Types: horizontal support (specific price), trendline support (rising floor), "
            "moving average support (dynamic, e.g. 50-day SMA)."
        ),
        "related": ["resistance", "trendline", "moving average", "breakout"],
    },
    "resistance": {
        "aliases": ["resistance level"],
        "brief": "A price level where selling pressure tends to halt or reverse a rally.",
        "full": (
            "Resistance is a price level where selling pressure historically overwhelms buying. "
            "Traders who bought at a previous high and are 'underwater' tend to sell when price "
            "returns to their entry — this creates overhead supply.\n\n"
            "Resistance that breaks on high volume is a high-conviction breakout signal. "
            "The previous resistance often becomes the new support (level flip).\n\n"
            "Major psychological levels (round numbers like $100, $200, $500) often act as resistance "
            "due to the concentration of limit orders placed at those prices."
        ),
        "related": ["support", "breakout", "volume", "trendline"],
    },
    "volume": {
        "aliases": ["trading volume"],
        "brief": "Number of shares traded in a period. High volume confirms price moves; low volume questions them.",
        "full": (
            "Volume is the total number of shares traded during a period. "
            "It's the 'weight' behind a price move — the same move on 2× average volume "
            "carries far more conviction than on half-average volume.\n\n"
            "Key rules: volume should expand in the direction of the trend (up-days on high volume, "
            "pullbacks on low volume). Volume expanding against the trend is a warning sign of distribution.\n\n"
            "Breakout volume: quality breakouts from bases should show 40–50%+ above the 50-day average volume. "
            "Low-volume breakouts fail more often.\n\n"
            "Volume climax: extreme spike (3–5× normal) often marks exhaustion tops or capitulation bottoms."
        ),
        "related": ["support", "resistance", "breakout", "accumulation", "distribution"],
    },
    "float": {
        "aliases": ["public float", "shares float"],
        "brief": "Shares actually available to trade publicly (excluding insider-held shares).",
        "full": (
            "Float = Total Shares Outstanding − Restricted Shares (insider holdings, lockup shares).\n\n"
            "Low float stocks are more volatile: the same buying pressure spread over fewer shares "
            "creates larger price moves. This is why small-cap stocks with 5M float can move 20% in a day.\n\n"
            "Short float %: if 30%+ of float is sold short, the stock is heavily shorted — "
            "elevated short squeeze risk if positive news hits.\n\n"
            "Secondary offerings increase float (dilutive — negative short-term), "
            "buybacks decrease float (positive — same earnings spread over fewer shares)."
        ),
        "related": ["shares outstanding", "short interest", "dilution", "market cap"],
    },
    # ── Macro / Economy ────────────────────────────────────────────────────
    "inflation": {
        "aliases": ["cpi", "consumer price index"],
        "brief": "General rise in prices over time. Erodes purchasing power; drives Federal Reserve policy.",
        "full": (
            "Inflation measures the rate at which the general price level rises. "
            "The CPI (Consumer Price Index) tracks a basket of goods and services; "
            "2% annual inflation is the Federal Reserve's target.\n\n"
            "For investors: moderate inflation is healthy (companies can raise prices). "
            "High inflation (>4–5%) forces the Fed to raise interest rates, which compresses stock valuations "
            "and hurts long-duration bonds most severely.\n\n"
            "Real return = Nominal Return − Inflation. A 7% stock return in a 4% inflation environment "
            "delivers only 3% real purchasing power gain."
        ),
        "related": ["federal reserve", "interest rates", "bonds", "real return"],
    },
    "federal reserve": {
        "aliases": ["fed", "fomc", "central bank"],
        "brief": "US central bank that sets interest rates. The single most market-moving institution.",
        "full": (
            "The Federal Reserve (Fed) has a dual mandate: maximum employment and stable prices (2% inflation). "
            "It achieves this by setting the federal funds rate — the benchmark interest rate.\n\n"
            "Rate hikes slow the economy (expensive borrowing, lower corporate earnings, lower equity multiples). "
            "Rate cuts stimulate (cheap borrowing, higher multiples, risk-on environment).\n\n"
            "The FOMC (Federal Open Market Committee) meets 8 times per year to vote on rates. "
            "Every word of the post-meeting statement is analyzed for signals about future policy. "
            "The 'Fed pivot' — from hiking to cutting — is one of the most market-moving events in finance."
        ),
        "related": ["interest rates", "inflation", "bond yields", "quantitative easing"],
    },
    "yield curve": {
        "aliases": ["inverted yield curve", "10-year yield", "treasury yield"],
        "brief": "Chart of US Treasury interest rates across maturities. Inverted = reliable recession predictor.",
        "full": (
            "The yield curve plots interest rates on US Treasury bonds across different maturities "
            "(3-month, 2-year, 10-year, 30-year). Normally upward-sloping (long-term > short-term).\n\n"
            "**Inversion**: when short-term rates exceed long-term (2-year yield > 10-year yield). "
            "Has preceded every US recession since 1955, typically 12–18 months in advance.\n\n"
            "Why it matters for stocks: banks borrow short and lend long — inversion compresses their margins, "
            "tightening credit conditions across the economy.\n\n"
            "The curve typically un-inverts shortly before the actual recession begins."
        ),
        "related": ["federal reserve", "recession", "bonds", "interest rates"],
    },
    # ── Orders & Trading ───────────────────────────────────────────────────
    "market order": {
        "aliases": [],
        "brief": "Buy or sell immediately at whatever price the market offers. Guarantees execution, not price.",
        "full": (
            "A market order executes immediately at the best available price. "
            "You're guaranteed to fill — but not at a specific price.\n\n"
            "Risk: slippage. In thin markets or around news events, the price you get may differ "
            "significantly from the last quoted price.\n\n"
            "Best used for highly liquid large-cap stocks during regular trading hours, "
            "when the bid-ask spread is tight and you need immediate execution.\n\n"
            "Avoid market orders for illiquid stocks, pre/after-hours, or large sizes — use limit orders instead."
        ),
        "related": ["limit order", "bid-ask spread", "slippage", "liquidity"],
    },
    "limit order": {
        "aliases": [],
        "brief": "Buy or sell only at your specified price or better. Guarantees price, not execution.",
        "full": (
            "A limit order executes only at your specified price or better. "
            "Buy limit: execute at your price or lower. Sell limit: execute at your price or higher.\n\n"
            "Advantage: no slippage. You control the price you pay.\n\n"
            "Disadvantage: may not fill if the stock doesn't reach your limit price. "
            "For active traders, a missed fill in a fast-moving market can be costly.\n\n"
            "Best practice: place limit orders slightly above the ask (buying) or below the bid (selling) "
            "to increase fill probability while still controlling price."
        ),
        "related": ["market order", "stop loss", "bid-ask spread"],
    },
    "stop loss": {
        "aliases": ["stop-loss", "stop order"],
        "brief": "Sell order that triggers automatically if the stock falls to your specified price.",
        "full": (
            "A stop-loss order automatically sells your position if the stock falls to the stop price, "
            "limiting your loss.\n\n"
            "Example: buy at $50, set stop at $45. If the stock falls to $45, it triggers — "
            "protecting you from larger losses.\n\n"
            "**Stop-limit vs. stop-market**: A stop-market order converts to a market order when triggered "
            "(guaranteed execution, but may fill lower in fast declines). "
            "A stop-limit converts to a limit order (may not fill in a gap-down).\n\n"
            "Placement: ATR-based stops (1–2× average true range below entry) are more systematic "
            "than arbitrary percentage stops."
        ),
        "related": ["limit order", "position sizing", "risk management", "max loss"],
    },
    "bid-ask spread": {
        "aliases": ["spread", "bid ask"],
        "brief": "Gap between the highest buy price (bid) and lowest sell price (ask). The hidden cost of every trade.",
        "full": (
            "The bid is the highest price a buyer will pay. The ask is the lowest price a seller will accept. "
            "The spread is the difference — and it's an immediate cost every time you trade.\n\n"
            "AAPL might have a $0.01 spread (very liquid). A small-cap stock might have a $0.50 spread "
            "on a $5 stock — 10% round-trip cost just in spread!\n\n"
            "Market makers profit from the spread by continuously buying at the bid and selling at the ask. "
            "For active traders, minimizing spread costs through limit orders in liquid stocks is essential."
        ),
        "related": ["market order", "liquidity", "market maker", "slippage"],
    },
}

# Build lookup by alias → canonical key
ALIAS_MAP: dict[str, str] = {}
for canonical, data in GLOSSARY.items():
    ALIAS_MAP[canonical] = canonical
    for alias in data.get("aliases", []):
        ALIAS_MAP[alias.lower()] = canonical


def lookup(term: str) -> dict | None:
    """Look up a term by canonical name or alias. Returns the glossary entry or None."""
    key = ALIAS_MAP.get(term.lower().strip())
    if key:
        return {"term": key, **GLOSSARY[key]}
    return None


def all_terms() -> list[str]:
    """Return all canonical terms plus aliases, for autocomplete."""
    terms = list(GLOSSARY.keys())
    for data in GLOSSARY.values():
        terms.extend(data.get("aliases", []))
    return sorted(set(terms))
