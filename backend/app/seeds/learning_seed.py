"""
Seed the IMCP Learning Center curriculum.

Creates all 10 tracks, their modules, and real lesson content for
Track 1, modules 1.1 and 1.2 (3 lessons each).

Safe to run on every boot — upserts by slug so re-running is idempotent.
"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.db.models.learning import LearningTrack, LearningModule, LearningLesson

logger = logging.getLogger(__name__)

# ── Lesson content ────────────────────────────────────────────────────────────

_LESSONS_1_1 = [
    {
        "slug": "what-bmg-is",
        "title": "What BMG Capital Is and Isn't",
        "order": 1,
        "estimated_minutes": 8,
        "content_md": """## What BMG Capital Is — and Isn't

BMG Capital is a quantitative research and trading platform built for serious retail investors and students. It exists to close the gap between institutional-grade investment tools and what individual investors have historically had access to.

### What BMG Does

At its core, BMG helps you research, monitor, and develop systematic investment strategies. The platform gives you a set of integrated tools that professional analysts use every day:

**Chart** — Price action analysis with candlestick charts, technical indicators (moving averages, RSI, MACD, Bollinger Bands, volume), and drawing tools. Use it to assess entry and exit timing, identify patterns, and validate thesis.

**Screener** — Filter the entire investable universe by any combination of fundamental and technical criteria. P/E below 15, market cap above $1B, RSI under 40, recent earnings beat — you define it. Use it to find candidates that meet your criteria systematically before you ever open a chart.

**Research** — News feeds, analyst reports, and SEC EDGAR filings for any public company. Use it to answer the first question in any investment: "Is this a real business, and do I understand it?"

**Earnings** — Earnings estimates, historical surprise data, and an upcoming earnings calendar. Use it to know exactly what catalyst risk you're sitting on before any position.

**Watchlist** — Monitor a curated list of symbols. Each position shows how far current price is from your entry criteria. Use it to stay disciplined — you don't buy until the setup triggers.

**Strategy Lab** — The quantitative bot framework. Eight systematic strategies running paper trades 24/7, each with defined entry rules, position sizing, and exit logic. Use it to develop and test rule-based approaches before risking capital.

**Learning Center** — Where you are now. Structured curriculum for developing investment competency from first principles to CFA/ACG exam readiness.

**Trade Journal** — A structured log for recording entries, exits, thesis, and post-mortems. The single highest-ROI habit in trading is honest review of your own decisions.

### What BMG Does NOT Do

This matters. BMG Capital is **not a broker**. It does not hold, custody, or execute trades with your money. All Strategy Lab activity is paper trading — simulated at real market prices, but with no real capital at risk unless you explicitly connect a brokerage account.

BMG does not give personalized financial advice. The platform provides information, analysis, and tools. What you do with them is your decision, and the responsibility is yours.

BMG is not a prediction engine. No tool here — including the AI Co-Pilot — can tell you what the market will do. What good tools can do is help you make better-informed decisions faster.

### The Right Mental Model

Think of BMG as your research infrastructure. Just as a Bloomberg terminal doesn't trade for a hedge fund manager but gives them everything they need to make decisions, BMG gives you everything you need to develop real investment conviction — without the six-figure subscription fee.

The Learning Center is designed to teach you how to use each tool effectively, build the analytical frameworks professionals use, and develop the judgment that no tool can substitute for.
""",
        "exercise_md": """**Exercise: Platform Orientation**

Navigate to the Chart page (/chart) and search for any ticker you already know. Spend 2 minutes exploring the interface — change the timeframe, hover over candles, look at the volume bars below.

Then navigate to Strategy Lab (/strategy-lab) and read the descriptions of the 3 running bots. Find the **crypto_day** bot.

Write a one-sentence answer to: *"What is the primary signal source for the crypto_day bot?"*

Save your answer to the Trade Journal under the tag **Orientation**.""",
        "quiz_json": [
            {
                "question": "What does BMG Capital primarily help you do?",
                "options": [
                    "Execute trades automatically",
                    "Research, monitor, and develop systematic investment strategies",
                    "File your taxes",
                    "Pick winning lottery numbers"
                ],
                "correct": 1
            },
            {
                "question": "Which tool would you use to filter stocks by P/E ratio below 15?",
                "options": ["Chart", "Earnings", "Screener", "Trade Journal"],
                "correct": 2
            },
            {
                "question": "BMG Strategy Lab bots trade using:",
                "options": [
                    "Random entry and exit",
                    "Rule-based quantitative signals from market data",
                    "Tips from Reddit",
                    "Insider information"
                ],
                "correct": 1
            },
        ],
    },
    {
        "slug": "five-tools",
        "title": "The Five Tools: Chart, Screener, Research, Earnings, Watchlist",
        "order": 2,
        "estimated_minutes": 12,
        "content_md": """## The Five Core Tools

Every professional investment workflow runs through a small number of core activities: find candidates, validate the business, assess entry timing, monitor risk, track your positions. BMG's five primary tools map directly to those activities.

### 1. Chart — Entry and Exit Timing

The Chart is where price meets analysis. At its most basic, it shows you how a stock has traded — open, high, low, close, and volume for every period you select. At its most powerful, it's where you layer in technical indicators and context.

**When to use it:** After you've already decided a company is worth looking at (from Screener or Research), open the Chart to assess whether now is a good entry point, or whether the setup requires patience. Don't open a Chart to find ideas — use it to evaluate ideas you've already developed through other tools.

### 2. Screener — Building Candidate Universes

There are roughly 4,000 actively traded stocks in the US market. The Screener lets you cut that to a manageable list based on criteria you define. You might look for: profitable small-caps with low debt and recent insider buying. Or: large-cap tech stocks trading at a 20% discount to their 5-year average P/E.

**When to use it:** Systematically. Run your screener criteria at least once a week. The Screener finds the needle; the rest of your tools help you decide whether it's worth picking up.

### 3. Research — Understanding the Business

The Research page aggregates news, analyst reports, and direct SEC filing access. When you're evaluating a company, you need to answer several basic questions before anything else: What does this company actually do? Who are its customers? What are the growth drivers? What are the risks? What has management said recently?

**When to use it:** Before you ever look at the chart or run a valuation model. Research first. The most common retail investor mistake is buying a story without reading the business.

### 4. Earnings — Catalyst Risk Management

Earnings reports are the single most significant recurring catalyst for individual stocks. A company can move 15-20% in a single session on earnings surprise, guidance, or management commentary. Earnings shows you: consensus estimates for revenue and EPS, historical surprise data (does this company consistently beat?), and the upcoming calendar.

**When to use it:** Before entering any position, check Earnings. Know when the next report is. Decide whether you want to hold through it or not. Entering a position three days before a major earnings report is a very different decision than entering the day after.

### 5. Watchlist — Disciplined Monitoring

The Watchlist is your pipeline. It tracks specific symbols you're interested in but haven't entered yet, and it shows you the gap between current conditions and your stated entry criteria. Without a watchlist, "monitoring" a stock means opening the Chart occasionally and hoping something looks different. With a watchlist, you define what trigger you're waiting for.

**When to use it:** Every day. The Watchlist is your daily brief on your candidate pipeline. It's also where discipline lives — the best investors pass on most setups, not because they can't find them, but because the price isn't right.

---

The sixth tool is this one: the **Learning Center** itself. Knowing how to use the other five tools is the starting point. Understanding the analytical frameworks that make them powerful is what this curriculum is for.
""",
        "exercise_md": """**Exercise: The Tool Tour**

Complete this three-step tour and log your findings to the Trade Journal:

1. Go to **/screener** and apply the filter: Market Cap > $10B AND P/E < 20. Note how many results come back.

2. Pick one result from the screener list. Navigate to **/research** for that ticker. Find one concrete piece of information about their most recent quarterly results (revenue, EPS, or management commentary).

3. Navigate to **/earnings** and find when that company next reports earnings.

Write a 3-sentence summary of what you found — what company you picked, what you learned in Research, and when their next earnings date is — to the Trade Journal under tag **Tool Tour**.""",
        "quiz_json": [
            {
                "question": "The Screener's primary job is to:",
                "options": [
                    "Draw charts",
                    "Show earnings dates",
                    "Filter stocks by criteria to build a candidate universe",
                    "Display news headlines"
                ],
                "correct": 2
            },
            {
                "question": "If you want to know when Apple next reports earnings and what analysts expect, you'd use:",
                "options": ["Chart", "Screener", "Earnings", "Watchlist"],
                "correct": 2
            },
            {
                "question": "The Watchlist helps you:",
                "options": [
                    "Execute trades",
                    "Monitor specific symbols and track how close they are to your entry criteria",
                    "Find new stocks to research",
                    "Read SEC filings"
                ],
                "correct": 1
            },
        ],
    },
    {
        "slug": "strategy-lab-intro",
        "title": "The Strategy Lab: How Bots Work",
        "order": 3,
        "estimated_minutes": 15,
        "content_md": """## The Strategy Lab: How Bots Work

The Strategy Lab is where quantitative trading becomes real. Before understanding how to use it, you need to understand what it is — and what it isn't.

### What a Quantitative Trading Bot Is

A quantitative trading bot is a set of rules — precisely defined entry conditions, position sizing formulas, and exit criteria — that runs on real-time market data. There's no human making a judgment call during the trade. The bot executes when its conditions are met, exits when its exit rules trigger, and repeats.

This is both the strength and the limitation. A well-designed bot removes emotion from execution. It doesn't panic-sell during a drawdown, doesn't FOMO-buy during a breakout. It does exactly what it was programmed to do, every time.

The limitation: the rules themselves can be wrong. A bot with bad signal logic or poor risk management will lose money with perfect consistency.

### The Crypto Day Strategies

BMG's crypto_day bot runs three sub-strategies simultaneously, each looking for different conditions in crypto markets:

**Intraday Momentum** — Identifies cryptocurrencies showing sustained directional price movement during the trading session. The signal fires when recent price velocity (rate of change over a defined period) crosses a threshold, combined with volume confirmation above the 20-period average. The underlying assumption: momentum tends to persist over short time windows before mean-reverting.

**Volatility Breakout** — Monitors overnight price consolidation and fires when price breaks outside a defined range (calculated from the prior session's Average True Range). The assumption: after a period of compressed range, an expansion tends to follow a clear directional move.

**Session Open Fade** — A contrarian strategy. It fades (trades opposite to) the initial directional move at market open. Research shows that the first 15-30 minutes of session open often overshoots, creating a mean-reversion opportunity. The signal fires when price moves more than 1.5 standard deviations from the prior close within the first 30 minutes.

### The Ensemble: How Signals Combine

No single sub-strategy is always right. The ensemble concept means that the final trade decision weighs signals from all three sub-strategies. If two out of three are aligned, the conviction score is higher and the position size increases. If only one fires, the position is smaller or the bot waits for confirmation.

This is the same logic behind how hedge funds combine quantitative signals — no single factor is reliable alone, but multiple independent signals pointing the same direction increase the probability of a valid setup.

### The Watchlist Tab: Entry Readiness Scoring

On each bot's page, the Watchlist tab shows every symbol being monitored and a real-time "entry readiness" score — how far each symbol currently is from triggering any of the sub-strategy conditions.

This is important: it's not a prediction. It's a current-state status. A symbol at 80% readiness doesn't mean it will trigger. It means the current market data is 80% of the way toward meeting the defined entry conditions.

### Paper Trading vs. Live Trading

BMG Strategy Lab runs **paper trades** — simulated transactions executed at real market prices, but without any real capital. When the system "buys" $10,000 of BTC, no money moves. The position is tracked at real-time prices, PnL is calculated on real price changes, and the trade record is stored.

The purpose is to test and refine strategies before committing real capital. Paper trading reveals how your rules actually perform against live market conditions — including slippage, execution timing, and edge cases your backtests didn't anticipate.

### Risk Overlays

Every bot runs with a set of risk controls that override the signal logic:

**Daily loss limit** — If the portfolio loses more than a defined percentage in a single session, no new positions are opened for the rest of the day. The system protects against cascading losses.

**Maximum drawdown circuit breaker** — If the portfolio drops more than a larger defined threshold from its peak, the bot halts completely until manually re-enabled. This prevents catastrophic loss in adverse regimes.

**Consecutive loss halt** — After a defined number of consecutive losing trades, the bot pauses and flags for review. Sometimes a losing streak is bad luck; sometimes it's evidence the market regime has shifted against your strategy.

These aren't optional. Risk management is not a feature you add to a trading system — it's the foundation the strategy sits on.
""",
        "exercise_md": """**Exercise: Strategy Lab Orientation**

Navigate to the Strategy Lab and open the **crypto_day** bot. Go to its **Watchlist tab**.

Find the symbol that is currently **closest to triggering** (highest entry readiness score).

Answer these three questions in your Trade Journal:

1. What indicator or condition is being evaluated for that symbol?
2. What does the current value need to reach for the signal to trigger?
3. Based on the current market data shown, would you enter this trade manually right now — and why or why not?

Tag your journal entry: **Strategy Lab Orientation**.""",
        "quiz_json": [
            {
                "question": "A quantitative trading bot is:",
                "options": [
                    "An AI that makes predictions about the future",
                    "A set of rules that execute based on market data conditions",
                    "A human trader using software",
                    "A news-reading algorithm"
                ],
                "correct": 1
            },
            {
                "question": "The 'ensemble' in the crypto_day strategy means:",
                "options": [
                    "The portfolio of all bots",
                    "Multiple strategies that each generate signals, which are then combined into a trade decision",
                    "The list of symbols being traded",
                    "The risk management rules"
                ],
                "correct": 1
            },
            {
                "question": "BMG Strategy Lab paper trading:",
                "options": [
                    "Uses real money from your account",
                    "Simulates trades at real market prices without using actual capital",
                    "Predicts future prices",
                    "Connects to your brokerage"
                ],
                "correct": 1
            },
            {
                "question": "The daily loss limit in the risk overlay does what?",
                "options": [
                    "Prevents any trading on days the market falls",
                    "Halts new trades if the portfolio loses more than a set % in a day",
                    "Reduces position sizes automatically",
                    "Sends you an email"
                ],
                "correct": 1
            },
        ],
    },
]

_LESSONS_1_2 = [
    {
        "slug": "candlestick-basics",
        "title": "Candlestick Basics",
        "order": 1,
        "estimated_minutes": 12,
        "content_md": """## Candlestick Basics

Every candle on a price chart tells a story about the battle between buyers and sellers in a specific time window. Understanding what a candlestick represents — and when patterns actually matter — is the starting point for reading charts.

### What a Candlestick Shows

A single candlestick captures four price points for a given period (minute, hour, day, week):

- **Open** — Price at the start of the period
- **Close** — Price at the end of the period
- **High** — Highest price reached during the period
- **Low** — Lowest price reached during the period

The rectangular **body** spans from open to close. The thin lines above and below the body are called **wicks** (or shadows). A long upper wick means price reached high but was pushed back down — sellers took control. A long lower wick means price went low but recovered — buyers stepped in.

**Bullish candle** (close > open): The body is typically green or white. Buyers dominated the period.

**Bearish candle** (close < open): The body is typically red or black. Sellers dominated the period.

### Key Single-Candle Patterns

**Doji** — Open and close are nearly equal, leaving little or no body. Price moved up and down but ended where it started. This represents indecision — neither buyers nor sellers won the period. By itself, a doji means nothing. In context (after a sustained trend, at a known support or resistance level), it can signal a potential reversal.

**Hammer** — A short body at the top of the candle with a long lower wick (at least 2x the body length). During the period, price fell sharply but recovered, closing near the open. When this appears after a downtrend at a known support level, it often signals that sellers are exhausting and buyers are finding value there.

**Shooting Star** — The inverse of the hammer: short body at the bottom with a long upper wick. During the period, price rallied strongly but gave back most gains. When this appears at the top of an uptrend near resistance, it can signal that buyers are losing momentum.

**Bullish Engulfing** — A bearish candle followed by a bullish candle whose body completely "engulfs" the prior candle's body. This suggests a momentum shift — buyers stepped in aggressively enough to overcome the prior session's selling pressure.

**Bearish Engulfing** — The inverse: a bullish candle followed by a bearish candle that engulfs it. Sellers overwhelmed the prior session's buying.

### The Critical Caveat: Context Is Everything

No single candlestick pattern is reliable in isolation. A hammer at a random point in a chart is meaningless. A hammer at the third test of a 3-month support level, on above-average volume, after RSI has reached 30 — that's a setup worth analyzing seriously.

The patterns document a possible shift in supply and demand. They do not cause it. And they fail constantly without contextual confirmation (trend direction, volume, support/resistance levels, broader market conditions).

*Historical note: Candlestick patterns were first documented by Munehisa Homma, an 18th-century Japanese rice trader who used them to anticipate price moves in the Osaka rice futures market. They were introduced to Western markets by Steve Nison in his 1991 book "Japanese Candlestick Charting Techniques."*
""",
        "exercise_md": """**Exercise: Pattern Hunt**

Open the BMG Chart for any large-cap stock — AAPL, MSFT, or NVDA work well. Switch to the **daily timeframe**. Look at the last 60 trading days.

Find one example of each of the following:

1. A **bullish engulfing** candle
2. A **doji** (open and close within a few cents of each other)
3. A candle with an unusually **long upper wick** (wick at least 2x the body)

For each example, note:
- The approximate date
- What happened in the **next 3 trading sessions** after the candle

Record your observations in the Trade Journal under tag **Chart Reading**.

*You may not find all three in every 60-day window. If you can't find one, note what you searched for and why you couldn't identify it — that's useful learning too.*""",
        "quiz_json": [
            {
                "question": "A doji candlestick indicates:",
                "options": [
                    "Strong buying pressure",
                    "Indecision — open and close are nearly equal",
                    "The stock is going to fall",
                    "High volume"
                ],
                "correct": 1
            },
            {
                "question": "The 'body' of a candlestick represents:",
                "options": [
                    "The total range from high to low",
                    "The range between open and close",
                    "The volume traded",
                    "The moving average"
                ],
                "correct": 1
            },
            {
                "question": "A hammer candle is most meaningful when it appears:",
                "options": [
                    "At a new 52-week high",
                    "After a prolonged downtrend at a known support level",
                    "On low volume",
                    "On a Monday"
                ],
                "correct": 1
            },
        ],
    },
    {
        "slug": "volume-basics",
        "title": "Volume: The Confirmation Tool",
        "order": 2,
        "estimated_minutes": 10,
        "content_md": """## Volume: The Confirmation Tool

Price tells you what happened. Volume tells you how much conviction was behind it.

### What Volume Measures

Volume is the number of shares (or contracts, or units) traded in a given period. On a daily chart, each volume bar shows total shares changing hands that day. On an hourly chart, it shows shares traded that hour.

Volume data is exchange-reported and highly reliable for US equities — the NYSE and NASDAQ publish official volume figures. *Important caveat for crypto traders: volume figures on smaller cryptocurrency exchanges can be fabricated through wash trading. For crypto volume analysis, stick to CME futures, Coinbase, or Binance data, which have stricter reporting standards.*

### Why Volume Matters

Price moves on high volume carry more information than moves on low volume. Here's the principle:

If a stock rises 3% on 2x its average daily volume, many participants were involved in that move — institutions, ETF rebalances, momentum funds. The move reflects broad conviction.

If a stock rises 3% on 0.3x its average daily volume, a small number of participants moved the price. There was no broad conviction. The move is less likely to persist.

This is not a rule — it's a probability statement. High-volume moves still reverse. Low-volume moves still hold. But the odds are not equal.

### The 20-Day Average Volume Benchmark

The standard benchmark for "normal" volume is the 20-day average. This smooths out single-day anomalies (earnings, index events, news) while capturing the typical trading activity for that specific stock.

A volume spike — typically defined as 1.5x or 2x the 20-day average — is your signal to pay closer attention. Something drove participation above normal. It may be news, it may be technical breakout, it may be institutional accumulation or distribution.

### Volume-Price Divergence

One of the most useful signals in volume analysis is divergence between price and volume trends:

**Price rising + volume declining**: A price uptrend that keeps making higher highs but on progressively lower volume is showing weakening participation. This is called **distribution** — existing holders may be selling into strength while fewer new buyers are entering. It doesn't mean the trend will reverse immediately, but conviction is weakening.

**Price falling + volume declining**: Selling pressure is drying up. This can precede a bottoming process.

**Breakout on high volume**: When price breaks above a defined resistance level (a prior high, a consolidation range) on volume 1.5-2x normal, the breakout has better odds of sustaining. The elevated volume means many participants acknowledged the breakout and acted on it.

### On-Balance Volume (OBV)

OBV is the simplest cumulative volume indicator. It adds the day's volume when price closes up and subtracts it when price closes down, building a running total. The absolute number is meaningless — what matters is the trend of OBV relative to price.

If price makes a new high but OBV does not (negative divergence), it suggests the upside move lacks volume confirmation. If price makes a new low but OBV does not (positive divergence), it suggests selling pressure is weaker than the price move implies.

OBV is a secondary confirmation tool — useful when combined with price analysis, not as a standalone signal.
""",
        "exercise_md": """**Exercise: Volume Confirmation Study**

Go to the BMG Chart for **NVDA** on the **daily timeframe**. Look at the last 6 months.

Find:
1. **Two examples** where a significant price move (>3% in a single day) occurred on volume **above 1.5x the 20-day average**.
2. **One example** where a price move of similar size occurred on **below-average volume**.

For each example, note:
- The approximate date and price move direction
- Approximate volume vs. average
- Did the move hold or reverse in the following 5 sessions?

Record your observations in the Trade Journal under tag **Chart Reading**.

*Observation question to answer: Does the high-volume move or the low-volume move tend to sustain more in your examples?*""",
        "quiz_json": [
            {
                "question": "A stock breaks above resistance on 3x average volume. This suggests:",
                "options": [
                    "The move will definitely reverse",
                    "Strong conviction behind the breakout — more likely to follow through",
                    "The stock is overbought",
                    "Insider buying"
                ],
                "correct": 1
            },
            {
                "question": "Volume-price divergence (price rising but volume falling) typically signals:",
                "options": [
                    "A healthy uptrend",
                    "Potential distribution — buyers losing conviction",
                    "A good time to buy",
                    "No meaningful information"
                ],
                "correct": 1
            },
            {
                "question": "The 20-day average volume is used as a benchmark because:",
                "options": [
                    "It's required by the SEC",
                    "It smooths out daily noise to give a reasonable baseline of normal activity",
                    "It's the most common setting on Bloomberg",
                    "20 is a lucky number"
                ],
                "correct": 1
            },
        ],
    },
    {
        "slug": "ma-rsi-basics",
        "title": "Moving Averages and RSI",
        "order": 3,
        "estimated_minutes": 15,
        "content_md": """## Moving Averages and RSI

Moving averages and RSI are the two most widely used technical indicators. They're also two of the most misused. This lesson covers what they actually measure, the standard configurations, and the critical caveats on how to interpret them.

### Moving Averages

A moving average smooths price data by calculating the average closing price over N periods, updated every session. The result is a line that trails price, showing the average trend rather than the noisy day-to-day fluctuation.

**Simple Moving Average (SMA)** — Equal weight to every period. The 20-day SMA adds the last 20 closing prices and divides by 20. Straightforward and widely referenced.

**Exponential Moving Average (EMA)** — More weight given to recent prices. A 20-day EMA reacts faster to recent price changes than a 20-day SMA. Preferred when you want a more responsive indicator; SMA preferred when you want smoother, less reactive trend confirmation.

### The Three Key Periods

**20-day MA** — Short-term trend. Responsive to recent price action. Used for short-term swing trading and gauging whether price is in a near-term uptrend or downtrend.

**50-day MA** — Medium-term trend. The most-watched moving average by institutional traders. When price holds above the 50-day on pullbacks, it's considered a healthy uptrend. When price breaks below the 50-day on high volume, it often signals a change in medium-term trend.

**200-day MA** — The structural trend line. The 200-day MA defines the long-term trend. Stocks above their 200-day are in a long-term uptrend; below, a long-term downtrend. Institutional allocators use this as a broad risk-on/risk-off signal.

### The Golden Cross and Death Cross

**Golden Cross** — The 50-day MA crosses **above** the 200-day MA. This signals that medium-term momentum has turned bullish and is confirming the long-term trend. It's a lagging signal (price has usually already moved before the cross), but it's widely watched and can trigger institutional buying programs.

**Death Cross** — The 50-day MA crosses **below** the 200-day MA. The inverse — medium-term trend turning bearish. Also lagging, but widely watched.

Neither cross is a perfect buy or sell signal. Both are useful as trend confirmation tools.

### RSI: Relative Strength Index

RSI was introduced by J. Welles Wilder in his 1978 book *New Concepts in Technical Trading Systems*. It measures the relative size of recent gains vs. recent losses over N periods (default: 14), producing a value between 0 and 100.

**The formula:**
RSI = 100 − (100 / (1 + RS))

Where RS = (average gain over 14 periods) / (average loss over 14 periods)

**The scale:**
- RSI > 70 → Traditionally considered "overbought" — price has gained more rapidly than average recently
- RSI < 30 → Traditionally considered "oversold" — price has lost more rapidly than average recently
- RSI at 50 → Roughly neutral momentum; recent gains and losses are balanced

### The Critical Caveat on RSI

RSI > 70 does **NOT** mean sell. This is one of the most damaging misunderstandings of the indicator.

In a strong uptrend, RSI can remain above 70 for months. If you sold every time RSI hit 70 during NVDA's 2023 rally, you sold the stock at $250 and watched it run to $875. The indicator works differently in trending vs. ranging markets.

RSI is most useful for:
1. **Divergence** — Price makes a new high but RSI makes a lower high: negative divergence, weakening momentum
2. **Extreme readings in ranging markets** — In a stock that has traded in a range for 6 months, RSI below 30 genuinely may indicate a short-term low
3. **Confirming trend strength** — RSI consistently above 50 in an uptrend confirms buying pressure is dominant

RSI is a context tool, not a trigger. Use it to add information to a thesis you've already developed through price, volume, and fundamental analysis — not as a standalone sell signal.
""",
        "exercise_md": """**Exercise: Moving Average and RSI Analysis**

On the BMG Chart for any ticker of your choice, enable both the **50-day** and **200-day** moving averages.

Answer these questions:

1. Is the stock currently trading **above or below** both moving averages?
2. Is the **50-day above or below the 200-day**? (Is there a golden cross or death cross in effect?)
3. What does this tell you about the **current trend** at both the medium-term and long-term level?

Now enable **RSI (14)**:

4. Is RSI currently **above or below 50**?
5. Has RSI been above or below 70 in the last 60 days? If so, did the price continue higher, consolidate, or reverse?

Write a 5-sentence technical summary — covering trend direction (MA), momentum (RSI), and what you would want to see before considering this stock for a position — to the Trade Journal under tag **Chart Reading**.""",
        "quiz_json": [
            {
                "question": "A 'golden cross' occurs when:",
                "options": [
                    "The stock hits a new 52-week high",
                    "The 50-day MA crosses above the 200-day MA",
                    "RSI crosses above 70",
                    "Volume exceeds 2x average"
                ],
                "correct": 1
            },
            {
                "question": "RSI of 72 on a stock in a strong uptrend means:",
                "options": [
                    "You must sell immediately",
                    "The stock is overbought and will definitely fall",
                    "Momentum has been strong recently — requires context to interpret",
                    "The stock is a guaranteed buy"
                ],
                "correct": 2
            },
            {
                "question": "The EMA (Exponential Moving Average) differs from SMA because it:",
                "options": [
                    "Uses a longer time period",
                    "Weights recent prices more heavily, making it more responsive",
                    "Only works on crypto",
                    "Includes volume in its calculation"
                ],
                "correct": 1
            },
            {
                "question": "Welles Wilder introduced RSI in:",
                "options": ["1965", "1978", "1992", "2004"],
                "correct": 1
            },
        ],
    },
]

# ── Track + module data ───────────────────────────────────────────────────────

TRACKS = [
    {
        "slug": "investment-tools",
        "name": "Track 1 — Investment Tools",
        "description": "Master the BMG platform tools that do the same job as FactSet and Bloomberg: Chart, Screener, Research, Earnings, Watchlist, and the Trade Journal.",
        "order": 1,
        "cert_tier": "1",
        "estimated_hours": 6.0,
        "prereq_track_slugs": [],
        "modules": [
            {"slug": "bmg-stack", "name": "1.1 The BMG Stack", "order": 1, "estimated_hours": 1.0, "is_published": True,
             "description": "Get oriented: what each BMG tool does and when to use it."},
            {"slug": "reading-charts", "name": "1.2 Reading Stock Charts", "order": 2, "estimated_hours": 1.0, "is_published": True,
             "description": "Candlesticks, volume, moving averages, RSI — how to read a chart without noise."},
            {"slug": "screener-universes", "name": "1.3 Using the Screener", "order": 3, "estimated_hours": 0.75, "is_published": False,
             "description": "Build and filter universes. Find setups systematically instead of guessing."},
            {"slug": "ai-copilot", "name": "1.4 Reading AI Co-Pilot Output", "order": 4, "estimated_hours": 0.5, "is_published": False,
             "description": "What the AI actually does under the hood. How to use its output critically."},
            {"slug": "watchlist-building", "name": "1.5 Watchlist Building & Maintenance", "order": 5, "estimated_hours": 0.5, "is_published": False,
             "description": "Build a watchlist with real entry criteria. Know what you're watching for."},
            {"slug": "trade-journal", "name": "1.6 The Trade Journal", "order": 6, "estimated_hours": 0.75, "is_published": False,
             "description": "Why journaling is the single highest-ROI habit in trading. How to do it right."},
        ],
    },
    {
        "slug": "business-industry",
        "name": "Track 2 — Business & Industry Analysis",
        "description": "Learn to understand what a business actually does, how industries are structured, and what creates competitive advantage.",
        "order": 2,
        "cert_tier": "1",
        "estimated_hours": 8.0,
        "prereq_track_slugs": [],
        "modules": [
            {"slug": "elevator-pitch", "name": "2.1 Understanding the Business", "order": 1, "is_published": False, "estimated_hours": 1.0,
             "description": "If you can't explain it simply, you don't understand it well enough to invest."},
            {"slug": "porter-five-forces", "name": "2.2 Industry Analysis", "order": 2, "is_published": False, "estimated_hours": 1.5,
             "description": "Porter's Five Forces, TAM/SAM/SOM, industry lifecycle."},
            {"slug": "competitive-moats", "name": "2.3 Competitive Moats", "order": 3, "is_published": False, "estimated_hours": 1.5,
             "description": "Buffett's framework for economic moats. How to identify durable competitive advantage."},
            {"slug": "unit-economics", "name": "2.4 Unit Economics", "order": 4, "is_published": False, "estimated_hours": 1.5,
             "description": "CAC, LTV, gross margin, contribution margin. The math behind whether a business model works."},
            {"slug": "pricing-power", "name": "2.5 Pricing Power & Concentration", "order": 5, "is_published": False, "estimated_hours": 0.75,
             "description": "The most valuable thing a company can have. How to test for it."},
            {"slug": "growth-drivers", "name": "2.6 Growth Drivers vs. Headwinds", "order": 6, "is_published": False, "estimated_hours": 0.75,
             "description": "Separating temporary from structural. What's priced in vs. what's not."},
        ],
    },
    {
        "slug": "financial-statements",
        "name": "Track 3 — Financial Statement Analysis",
        "description": "Read 10-Ks and 10-Qs like a professional analyst. Build from the 3 statements to full ratio analysis, forecasting, and value creation.",
        "order": 3,
        "cert_tier": "1",
        "estimated_hours": 10.0,
        "prereq_track_slugs": [],
        "modules": [
            {"slug": "three-statements", "name": "3.1 The Three Statements", "order": 1, "is_published": False, "estimated_hours": 1.5,
             "description": "Income statement, balance sheet, cash flow — how they connect and how they can mislead."},
            {"slug": "reading-10k", "name": "3.2 Reading 10-Ks and 10-Qs", "order": 2, "is_published": False, "estimated_hours": 1.5,
             "description": "Where to find what matters. What to skip."},
            {"slug": "ratio-analysis", "name": "3.3 Ratio Analysis", "order": 3, "is_published": False, "estimated_hours": 2.0,
             "description": "Profitability, liquidity, solvency, efficiency — the full toolkit."},
            {"slug": "dupont", "name": "3.4 DuPont Decomposition", "order": 4, "is_published": False, "estimated_hours": 1.0,
             "description": "Break ROE into its three drivers to understand where returns actually come from."},
            {"slug": "earnings-quality", "name": "3.5 Quality of Earnings", "order": 5, "is_published": False, "estimated_hours": 1.5,
             "description": "GAAP vs. adjusted, red flags, accounting maneuvers that inflate reported results."},
            {"slug": "forecasting", "name": "3.6 Forecasting Financials", "order": 6, "is_published": False, "estimated_hours": 1.5,
             "description": "How to build a 3-year forecast from first principles."},
            {"slug": "value-creation", "name": "3.7 Identifying Value Creation", "order": 7, "is_published": False, "estimated_hours": 1.0,
             "description": "ROIC > WACC: when a company actually creates economic value vs. just generating accounting profit."},
        ],
    },
    {
        "slug": "valuation",
        "name": "Track 4 — Valuation",
        "description": "Build DCF models, run comparable company analyses, and learn when each valuation method applies.",
        "order": 4,
        "cert_tier": "1",
        "estimated_hours": 12.0,
        "prereq_track_slugs": [],
        "modules": [
            {"slug": "dcf", "name": "4.1 Discounted Cash Flow", "order": 1, "is_published": False, "estimated_hours": 2.5,
             "description": "Build a DCF from scratch. Understand what drives value, what drives error."},
            {"slug": "multiples", "name": "4.2 Multiples-Based Valuation", "order": 2, "is_published": False, "estimated_hours": 2.0,
             "description": "P/E, EV/EBITDA, P/S, P/B — when to use each and why they differ."},
            {"slug": "sotp", "name": "4.3 Sum-of-the-Parts", "order": 3, "is_published": False, "estimated_hours": 1.5,
             "description": "Break conglomerates into pieces. The sum may be worth more than the whole."},
            {"slug": "comps", "name": "4.4 Comparable Companies", "order": 4, "is_published": False, "estimated_hours": 1.5,
             "description": "How to select a real comp set. What to do when there isn't one."},
            {"slug": "precedent-tx", "name": "4.5 Precedent Transactions", "order": 5, "is_published": False, "estimated_hours": 1.0,
             "description": "M&A multiples and what control premiums tell you."},
            {"slug": "historical-ranges", "name": "4.6 Historical Valuation Ranges", "order": 6, "is_published": False, "estimated_hours": 1.0,
             "description": "When is the stock actually cheap? The answer is always relative."},
            {"slug": "reverse-dcf", "name": "4.7 Reverse DCF", "order": 7, "is_published": False, "estimated_hours": 1.5,
             "description": "What growth rate does the current price imply? Work backward from market cap to assumptions."},
        ],
    },
    {
        "slug": "portfolio-construction",
        "name": "Track 5 — Portfolio Construction",
        "description": "Build portfolios that survive real markets. Covers IPS, asset allocation, position sizing, diversification math, rebalancing, and tax efficiency.",
        "order": 5,
        "cert_tier": "2",
        "prereq_track_slugs": ["investment-tools", "valuation"],
        "estimated_hours": 9.0,
        "modules": [
            {"slug": "ips", "name": "5.1 Investment Policy Statement", "order": 1, "is_published": False, "estimated_hours": 1.0,
             "description": "Before you invest a dollar, write down the rules. The IPS is the foundation."},
            {"slug": "asset-allocation", "name": "5.2 Asset Allocation Frameworks", "order": 2, "is_published": False, "estimated_hours": 1.5,
             "description": "60/40, risk parity, the Yale endowment model — what works and for whom."},
            {"slug": "position-sizing", "name": "5.3 Position Sizing", "order": 3, "is_published": False, "estimated_hours": 1.5,
             "description": "Kelly criterion, risk parity, equal weight — the math of how much to bet."},
            {"slug": "diversification", "name": "5.4 Diversification Math", "order": 4, "is_published": False, "estimated_hours": 1.5,
             "description": "Correlation, covariance, Modern Portfolio Theory — what actually reduces risk."},
            {"slug": "rebalancing", "name": "5.5 Rebalancing Rules", "order": 5, "is_published": False, "estimated_hours": 0.75,
             "description": "When and how to rebalance. The hidden performance drag of ignoring it."},
            {"slug": "tax-efficiency", "name": "5.6 Tax Efficiency", "order": 6, "is_published": False, "estimated_hours": 1.0,
             "description": "Lots, harvesting, asset location — the returns that come from tax awareness."},
            {"slug": "strategy-lab-practice", "name": "5.7 Strategy Lab in Practice", "order": 7, "is_published": False, "estimated_hours": 1.0,
             "description": "Apply your IPS to real BMG bot allocations. Build a portfolio that reflects your actual thesis."},
        ],
    },
    {
        "slug": "macro-fixed-income",
        "name": "Track 6 — Macro, Fixed Income & Factors",
        "description": "Understand macro regimes, fixed income mechanics, performance attribution, and factor models. Build your first quantitative strategy.",
        "order": 6,
        "cert_tier": "2",
        "prereq_track_slugs": ["portfolio-construction"],
        "estimated_hours": 10.0,
        "modules": [
            {"slug": "macro-indicators", "name": "6.1 Macro Indicators That Matter", "order": 1, "is_published": False, "estimated_hours": 1.5,
             "description": "GDP, CPI, PMI, yield curve, initial claims — which ones move markets and why."},
            {"slug": "yield-curve", "name": "6.2 The Yield Curve", "order": 2, "is_published": False, "estimated_hours": 1.0,
             "description": "Inversion, steepening, bear flattening — what each signals about the economy."},
            {"slug": "fixed-income", "name": "6.3 Fixed Income Basics", "order": 3, "is_published": False, "estimated_hours": 1.5,
             "description": "Duration, convexity, credit spreads — how bonds price risk."},
            {"slug": "perf-attribution", "name": "6.4 Performance Attribution", "order": 4, "is_published": False, "estimated_hours": 1.5,
             "description": "Decompose returns by factor. Understand where alpha actually came from."},
            {"slug": "factor-models", "name": "6.5 Factor Models", "order": 5, "is_published": False, "estimated_hours": 2.0,
             "description": "Fama-French 5-factor, momentum, quality, low-vol — the empirical building blocks of returns."},
            {"slug": "backtesting", "name": "6.6 Backtesting Methodology", "order": 6, "is_published": False, "estimated_hours": 1.5,
             "description": "Look-ahead bias, survivorship bias, overfitting — why most backtests are lies."},
            {"slug": "quant-model", "name": "6.7 Building Your First Quant Model", "order": 7, "is_published": False, "estimated_hours": 1.5,
             "description": "From idea to code to backtest to live paper trading."},
        ],
    },
    {
        "slug": "risk-management",
        "name": "Track 7 — Risk Management",
        "description": "The track most traders skip — and why most traders lose. Covers position sizing, stop methodologies, hedging, and drawdown psychology.",
        "order": 7,
        "cert_tier": "2",
        "prereq_track_slugs": ["portfolio-construction"],
        "estimated_hours": 8.0,
        "modules": [
            {"slug": "why-traders-lose", "name": "7.1 Why Most Retail Traders Lose", "order": 1, "is_published": False, "estimated_hours": 1.0,
             "description": "The statistics are brutal. Understanding them is the first step."},
            {"slug": "position-size-ruin", "name": "7.2 Position Sizing & Risk of Ruin", "order": 2, "is_published": False, "estimated_hours": 1.5,
             "description": "The math of going broke. Why even a positive EV system fails with bad sizing."},
            {"slug": "stop-losses", "name": "7.3 Stop Losses", "order": 3, "is_published": False, "estimated_hours": 1.0,
             "description": "Fixed %, ATR-based, structural — which type to use and when."},
            {"slug": "hedging", "name": "7.4 Hedging", "order": 4, "is_published": False, "estimated_hours": 1.5,
             "description": "Puts, inverse ETFs, pairs trades — the cost and benefit of protection."},
            {"slug": "tail-risk", "name": "7.5 Tail Risk & Black Swans", "order": 5, "is_published": False, "estimated_hours": 1.0,
             "description": "Fat tails exist. How to survive and profit from them."},
            {"slug": "drawdown-psychology", "name": "7.6 Drawdown Psychology", "order": 6, "is_published": False, "estimated_hours": 1.0,
             "description": "Surviving the drawdown that doesn't kill your account but might kill your process."},
            {"slug": "kelly-criterion", "name": "7.7 The Kelly Criterion", "order": 7, "is_published": False, "estimated_hours": 1.0,
             "description": "The mathematically optimal bet size. Why full Kelly will destroy you."},
        ],
    },
    {
        "slug": "behavioral-ethics",
        "name": "Track 8 — Behavioral Finance, Ethics & Forensics",
        "description": "The internal game. Cognitive biases, fiduciary ethics, forensic accounting red flags, and learning from famous failures.",
        "order": 8,
        "cert_tier": "3",
        "prereq_track_slugs": ["financial-statements"],
        "estimated_hours": 9.0,
        "modules": [
            {"slug": "cognitive-biases", "name": "8.1 Cognitive Biases That Destroy Returns", "order": 1, "is_published": False, "estimated_hours": 1.5,
             "description": "Loss aversion, anchoring, recency bias, confirmation bias, herding — each one with a real market example."},
            {"slug": "process-protection", "name": "8.2 Building a Bias-Resistant Process", "order": 2, "is_published": False, "estimated_hours": 1.5,
             "description": "Checklists, pre-mortems, devil's advocate. The only way to fight biases is a system."},
            {"slug": "ethics", "name": "8.3 Ethics in Investing", "order": 3, "is_published": False, "estimated_hours": 1.0,
             "description": "CFA Code of Ethics, fiduciary duty, the difference between legal and right."},
            {"slug": "forensic-accounting", "name": "8.4 Forensic Accounting Red Flags", "order": 4, "is_published": False, "estimated_hours": 2.0,
             "description": "Revenue recognition tricks, capitalized R&D, off-balance-sheet items. How companies hide problems."},
            {"slug": "ma-analysis", "name": "8.5 M&A Analysis", "order": 5, "is_published": False, "estimated_hours": 1.5,
             "description": "Synergies, dilution, integration risk. Why most acquisitions destroy value."},
            {"slug": "case-studies", "name": "8.6 Case Studies: Famous Failures", "order": 6, "is_published": False, "estimated_hours": 1.5,
             "description": "Enron, Wirecard, Theranos — walk through the public filings before the collapse."},
        ],
    },
    {
        "slug": "stock-pitch",
        "name": "Track 9 — Stock Pitch & Investment Idea Development",
        "description": "Structure, defend, and track real investment ideas. From thesis to catalyst to exit. Culminates in a live pitch to the BMG Co-Pilot PM.",
        "order": 9,
        "cert_tier": "3",
        "prereq_track_slugs": ["valuation", "financial-statements"],
        "estimated_hours": 10.0,
        "modules": [
            {"slug": "pitch-structure", "name": "9.1 The Winning Pitch Structure", "order": 1, "is_published": False, "estimated_hours": 1.5,
             "description": "Every great pitch has the same skeleton. Learn it before you improvise."},
            {"slug": "bull-bear-base", "name": "9.2 Bull, Bear, Base Cases", "order": 2, "is_published": False, "estimated_hours": 1.5,
             "description": "Not one story — three. How to think probabilistically about an investment."},
            {"slug": "catalysts", "name": "9.3 Catalyst Identification", "order": 3, "is_published": False, "estimated_hours": 1.0,
             "description": "What has to happen and when for the market to agree with you."},
            {"slug": "sensitivity", "name": "9.4 Sensitivity Analysis", "order": 4, "is_published": False, "estimated_hours": 1.5,
             "description": "Which assumptions drive your outcome? What has to be true for your thesis to work?"},
            {"slug": "risk-reward", "name": "9.5 Risk/Reward Sizing", "order": 5, "is_published": False, "estimated_hours": 1.0,
             "description": "How big to bet based on asymmetry of outcomes."},
            {"slug": "pitch-deck", "name": "9.6 Building the Deck", "order": 6, "is_published": False, "estimated_hours": 1.5,
             "description": "Slides 1-10. What every page must answer. What to never put in a deck."},
            {"slug": "qa-defense", "name": "9.7 Defending Your Pitch", "order": 7, "is_published": False, "estimated_hours": 1.0,
             "description": "The Q&A will expose every gap. Prepare by arguing against yourself first."},
            {"slug": "postmortem", "name": "9.8 Tracking & Post-Mortem", "order": 8, "is_published": False, "estimated_hours": 0.5,
             "description": "Every pitch either works or teaches. The post-mortem is where you learn."},
        ],
    },
    {
        "slug": "exam-prep",
        "name": "Track 10 — CFA / ACG / CQA Exam Prep",
        "description": "Targeted prep for the CFA Level 1, ACG Cup, and CQA competition. Practice problems with real exam pacing.",
        "order": 10,
        "cert_tier": "exam_prep",
        "prereq_track_slugs": [],
        "estimated_hours": 40.0,
        "modules": [
            {"slug": "cfa-l1-part1", "name": "10.1 CFA Level 1 — Ethics, Quant, Economics, Financial Reporting", "order": 1, "is_published": False, "estimated_hours": 12.0,
             "description": "The first half of the CFA L1 curriculum with real practice questions."},
            {"slug": "cfa-l1-part2", "name": "10.2 CFA Level 1 — Corporate Finance, Equity, Fixed Income, Derivatives", "order": 2, "is_published": False, "estimated_hours": 12.0,
             "description": "The second half: applications across asset classes."},
            {"slug": "acg-cup", "name": "10.3 ACG Cup Framework", "order": 3, "is_published": False, "estimated_hours": 8.0,
             "description": "Investment banking M&A analysis. Prep for the national ACG Cup competition."},
            {"slug": "cqa", "name": "10.4 CQA Framework", "order": 4, "is_published": False, "estimated_hours": 6.0,
             "description": "Hedge fund portfolio simulation for the CQA competition."},
            {"slug": "practice-timing", "name": "10.5 Practice Problems & Timing", "order": 5, "is_published": False, "estimated_hours": 2.0,
             "description": "Timed mock exams across all topics. Identify your weakest areas."},
        ],
    },
]

# Map of track_slug + module_slug -> lesson list
_MODULE_LESSONS: dict[tuple[str, str], list[dict]] = {
    ("investment-tools", "bmg-stack"): _LESSONS_1_1,
    ("investment-tools", "reading-charts"): _LESSONS_1_2,
}


def seed_learning_content(db: Session) -> None:
    """Upsert all 10 tracks, their modules, and lesson content. Safe to re-run."""
    existing_count = db.query(LearningTrack).count()
    if existing_count > 0:
        logger.info("Learning tracks already seeded (%d found) — skipping seed", existing_count)
        return

    logger.info("Seeding IMCP learning curriculum…")

    for track_data in TRACKS:
        modules_data = track_data.pop("modules")

        track = LearningTrack(
            slug=track_data["slug"],
            name=track_data["name"],
            description=track_data.get("description"),
            order=track_data.get("order", 0),
            cert_tier=track_data.get("cert_tier"),
            prereq_track_slugs=track_data.get("prereq_track_slugs", []),
            estimated_hours=track_data.get("estimated_hours"),
        )
        db.add(track)
        db.flush()  # get track.id

        for mod_data in modules_data:
            module = LearningModule(
                track_id=track.id,
                slug=mod_data["slug"],
                name=mod_data["name"],
                description=mod_data.get("description"),
                order=mod_data.get("order", 0),
                estimated_hours=mod_data.get("estimated_hours"),
                is_published=mod_data.get("is_published", False),
                capstone_exercise=mod_data.get("capstone_exercise"),
            )
            db.add(module)
            db.flush()

            lesson_list = _MODULE_LESSONS.get((track.slug, module.slug), [])
            for lesson_data in lesson_list:
                lesson = LearningLesson(
                    module_id=module.id,
                    slug=lesson_data["slug"],
                    title=lesson_data["title"],
                    order=lesson_data.get("order", 0),
                    estimated_minutes=lesson_data.get("estimated_minutes"),
                    content_md=lesson_data.get("content_md"),
                    exercise_md=lesson_data.get("exercise_md"),
                    quiz_json=lesson_data.get("quiz_json"),
                )
                db.add(lesson)

        # Restore modules_data key (in case this dict is reused)
        track_data["modules"] = modules_data

    db.commit()
    logger.info("IMCP learning curriculum seeded successfully.")
