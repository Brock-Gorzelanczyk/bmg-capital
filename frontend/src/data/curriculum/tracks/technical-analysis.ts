import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  // ── Course 1: Trend Analysis ─────────────────────────────────────────────
  {
    id: "ta-trend-l1",
    courseId: "ta-trend",
    trackId: "technical-analysis",
    title: "Moving Averages",
    type: "article",
    xp: 60,
    durationMin: 8,
    tags: ["trend", "moving-averages", "sma", "ema"],
    body: `
<h2>What Is a Moving Average?</h2>
<p>A <strong>moving average (MA)</strong> smooths out price noise by plotting the average closing price over a rolling window. Instead of staring at a jagged price line, you see the underlying trend direction at a glance.</p>

<div class="lesson-callout info">
  <strong>Two flavors you'll use every day:</strong>
  <ul>
    <li><strong>SMA (Simple Moving Average)</strong> — equal weight to every day in the window. The 200-day SMA is the single most-watched line on Wall Street.</li>
    <li><strong>EMA (Exponential Moving Average)</strong> — exponentially more weight to recent closes. Reacts faster; day traders prefer the 9- and 21-day EMA.</li>
  </ul>
</div>

<h2>How Traders Read Them</h2>
<p>Moving averages serve three jobs:</p>
<ol>
  <li><strong>Trend filter:</strong> Price above its 200-day SMA = generally bullish environment. Price below = bearish.</li>
  <li><strong>Dynamic support/resistance:</strong> In uptrends, price often bounces off the 50-day SMA before resuming higher. That bounce is a buy signal for many traders.</li>
  <li><strong>Crossover signals:</strong> When a short-term MA crosses above a long-term MA (golden cross), bulls gain momentum. When it crosses below (death cross), bears take control.</li>
</ol>

<h2>A Real Example: AAPL in 2023</h2>
<p>After the 2022 bear market bottom, Apple's stock crossed above its 200-day SMA in January 2023 at roughly $143. From that cross, shares ran to $198 by mid-year — a 38% move. Traders using the 200-day as a filter would have caught most of that move by simply buying when price cleared and flipped the MA into support.</p>

<div class="lesson-callout warning">
  <strong>The lag problem:</strong> MAs are <em>lagging</em> indicators — they're calculated from past prices. In choppy, sideways markets, crossovers whipsaw constantly. Always combine MAs with price action context (is the stock making higher highs and higher lows?) before trading a signal.
</div>

<h2>Common Periods to Know</h2>
<table class="lesson-table">
  <tr><th>Period</th><th>Common Use</th><th>Trader Type</th></tr>
  <tr><td>9/21 EMA</td><td>Short-term momentum, entries/exits</td><td>Day trader, swing trader</td></tr>
  <tr><td>50-day SMA</td><td>Intermediate trend, support in uptrend</td><td>Swing trader, investor</td></tr>
  <tr><td>200-day SMA</td><td>Long-term trend filter, major S/R</td><td>All timeframes</td></tr>
</table>
    `,
    quiz: [
      {
        id: "ta-trend-l1-q1",
        question: "The 200-day SMA is best described as a:",
        options: ["Short-term momentum signal", "Long-term trend filter", "Volatility measure", "Volume indicator"],
        answer: 1,
        explanation: "The 200-day SMA is Wall Street's most-watched long-term trend filter. Price above it = bullish environment; below it = bearish.",
      },
      {
        id: "ta-trend-l1-q2",
        question: "Which moving average type gives more weight to recent prices?",
        options: ["SMA (Simple)", "WMA (Weighted)", "EMA (Exponential)", "All give equal weight"],
        answer: 2,
        explanation: "EMA uses exponential weighting, making it more responsive to recent price action than a simple average.",
      },
      {
        id: "ta-trend-l1-q3",
        question: "In a strong uptrend, the 50-day SMA often acts as:",
        options: ["A ceiling that price can't break", "Dynamic support where dips get bought", "A sell signal", "A volume indicator"],
        answer: 1,
        explanation: "In uptrends, the 50-day SMA often provides dynamic support. Many traders buy when price dips to and bounces off this line.",
      },
    ],
  },

  {
    id: "ta-trend-l2",
    courseId: "ta-trend",
    trackId: "technical-analysis",
    title: "Trendlines & Channels",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["trendlines", "channels", "support", "resistance"],
    body: `
<h2>Drawing the Trend</h2>
<p>A <strong>trendline</strong> is the simplest tool in technical analysis. Connect two or more swing lows in an uptrend (or swing highs in a downtrend) and you've drawn a line that defines the trend's pace. Price approaching that line is a decision point — will it hold, or break?</p>

<div class="lesson-callout info">
  <strong>The two rules of valid trendlines:</strong>
  <ol>
    <li>Require at least <strong>two touch points</strong> to draw. Three touches confirms the line is "real" and respected by the market.</li>
    <li>Use closing prices for the most reliable lines (intraday wicks can pierce a trendline without actually breaking it).</li>
  </ol>
</div>

<h2>Ascending vs. Descending Trendlines</h2>
<ul>
  <li><strong>Ascending trendline</strong> — connects rising lows in an uptrend. Acts as support. A close below this line is a potential trend break.</li>
  <li><strong>Descending trendline</strong> — connects falling highs in a downtrend. Acts as resistance. A close above is a potential trend reversal.</li>
</ul>

<h2>Price Channels</h2>
<p>Add a parallel line above an ascending trendline (connecting the highs) and you've built a <strong>channel</strong>. Price oscillates between the two lines. Traders buy near the lower channel line and take profits near the upper, or sell short near the upper and cover near the lower.</p>

<div class="lesson-callout success">
  <strong>Channel breakouts are high-conviction signals:</strong> When price breaks out of a well-established channel on above-average volume, the move tends to be significant. The channel itself can then act as support or resistance for the new trend.
</div>

<h2>The False Break Trap</h2>
<p>Trendlines break constantly on intraday timeframes. A single candle piercing the line doesn't confirm a break. Professional traders look for:</p>
<ol>
  <li>A daily close beyond the line (not just an intraday wick)</li>
  <li>Volume expansion on the break</li>
  <li>A failed attempt to reclaim the line ("back-test from the other side")</li>
</ol>
    `,
    quiz: [
      {
        id: "ta-trend-l2-q1",
        question: "To draw a valid ascending trendline, you connect:",
        options: ["Swing highs in an uptrend", "Swing lows in an uptrend", "Any two price points", "The open and close of each candle"],
        answer: 1,
        explanation: "An ascending trendline connects the rising swing lows in an uptrend. It acts as dynamic support.",
      },
      {
        id: "ta-trend-l2-q2",
        question: "A price channel is formed by:",
        options: ["Two parallel trendlines containing price", "The 50 and 200-day moving averages", "Bollinger Band upper and lower", "High and low of the trading day"],
        answer: 0,
        explanation: "A channel adds a parallel line to a trendline, creating upper and lower boundaries that contain price oscillation.",
      },
      {
        id: "ta-trend-l2-q3",
        question: "Which of these makes a trendline break MORE reliable?",
        options: ["Any intraday pierce", "A daily close beyond the line with high volume", "Price touching the line 4+ times", "The line being very steep"],
        answer: 1,
        explanation: "A daily close beyond the line combined with above-average volume gives the most reliable trendline break signal. Intraday wicks alone are often false breaks.",
      },
    ],
  },

  {
    id: "ta-trend-l3",
    courseId: "ta-trend",
    trackId: "technical-analysis",
    title: "The Golden Cross & Death Cross",
    type: "article",
    xp: 70,
    durationMin: 8,
    tags: ["golden-cross", "death-cross", "moving-average-crossover"],
    body: `
<h2>Two Crossovers, One Billion Dollars in Headlines</h2>
<p>No moving average crossover generates more financial media coverage than the <strong>golden cross</strong> (50-day SMA crossing above the 200-day SMA) and its evil twin, the <strong>death cross</strong> (50-day crossing below the 200-day).</p>
<p>But do they actually work? The answer is nuanced — and understanding that nuance separates traders from tourists.</p>

<div class="lesson-callout info">
  <strong>Golden Cross:</strong> 50-day SMA crosses above 200-day SMA → bullish signal<br/>
  <strong>Death Cross:</strong> 50-day SMA crosses below 200-day SMA → bearish signal
</div>

<h2>The Research on Crossovers</h2>
<p>Academic studies on the S&P 500 going back to 1950 show that golden crosses have a hit rate of roughly 65–70% — meaning about two-thirds of the time, the index is higher 12 months after a golden cross than on the day it occurred. Not bad. But the 30–35% failure rate and the <em>significant lag</em> in the signal matter a great deal.</p>

<h2>The Lag Problem in Practice</h2>
<p>The death cross on the S&P 500 in March 2020 triggered on March 26, 2020 — just <em>three days before the absolute bottom</em> of the COVID crash. The market had already fallen 34% before the signal fired. A trader who sold on the death cross and bought on the golden cross would have sold near the low and bought back significantly higher.</p>

<div class="lesson-callout warning">
  <strong>Golden/death crosses are confirmation signals, not prediction signals.</strong> They tell you what has already happened. Use them to confirm a thesis you've already formed from price action — not as standalone entry and exit triggers.
</div>

<h2>Best Use Cases</h2>
<ul>
  <li><strong>Regime confirmation:</strong> Use the relationship between the 50 and 200-day SMA as a market regime filter. Be long-biased when 50 > 200, defensive when 50 < 200.</li>
  <li><strong>Secondary confirmation:</strong> If a stock you're analyzing has a golden cross AND is breaking out of a base on volume, the confluence of signals increases confidence.</li>
  <li><strong>Not for timing:</strong> Never use a golden/death cross as your precise entry or exit. By the time the signal fires, the move is usually already well underway.</li>
</ul>
    `,
    quiz: [
      {
        id: "ta-trend-l3-q1",
        question: "A golden cross occurs when:",
        options: [
          "Price crosses above the 200-day SMA",
          "The 50-day SMA crosses above the 200-day SMA",
          "Volume spikes with price rising",
          "RSI crosses above 50",
        ],
        answer: 1,
        explanation: "The golden cross is specifically the 50-day SMA crossing above the 200-day SMA — not price crossing a moving average.",
      },
      {
        id: "ta-trend-l3-q2",
        question: "The main weakness of golden/death cross signals is:",
        options: ["They're too complex to calculate", "They lag significantly — the move is often well underway", "They only work on individual stocks, not indices", "They require paid data"],
        answer: 1,
        explanation: "Crossover signals are lagging by definition. The COVID death cross fired just 3 days before the 2020 market bottom after a 34% drop.",
      },
      {
        id: "ta-trend-l3-q3",
        question: "The best use of the 50/200-day crossover is as a:",
        options: ["Precise entry timer", "Market regime filter and secondary confirmation", "Standalone buy/sell signal", "Intraday scalping tool"],
        answer: 1,
        explanation: "Use the crossover as a regime filter (bullish when 50>200, bearish when 50<200) and to confirm other signals — not as a standalone trade trigger.",
      },
    ],
  },

  // ── Course 2: Momentum ──────────────────────────────────────────────────
  {
    id: "ta-momentum-l1",
    courseId: "ta-momentum",
    trackId: "technical-analysis",
    title: "RSI Deep Dive",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["rsi", "momentum", "overbought", "oversold"],
    body: `
<h2>What RSI Actually Measures</h2>
<p>The <strong>Relative Strength Index (RSI)</strong>, developed by J. Welles Wilder in 1978, measures the <em>speed and magnitude</em> of recent price changes. It's displayed as a number from 0 to 100 and is plotted below the price chart.</p>
<p>The formula compares average gains to average losses over a period (default: 14 days). A stock that has closed up 12 of the last 14 days will have a very high RSI. A stock in free fall will be very low.</p>

<div class="lesson-callout info">
  <strong>Classic RSI levels:</strong>
  <ul>
    <li><strong>RSI &gt; 70:</strong> Overbought — the stock has risen quickly; pullback risk increases</li>
    <li><strong>RSI &lt; 30:</strong> Oversold — the stock has fallen quickly; bounce potential increases</li>
    <li><strong>RSI = 50:</strong> Neutral momentum — neither buyers nor sellers dominating</li>
  </ul>
</div>

<h2>The Misconception: RSI at 70 Doesn't Mean "Sell"</h2>
<p>Many new traders see RSI at 75 and immediately think "overbought = sell." This is backwards in a bull market. Strong stocks in powerful uptrends can stay above 70 for weeks or months. In fact, an RSI that maintains above 60 for an extended period is a sign of <em>accumulation by institutions</em> — the big money is consistently buying dips.</p>

<h2>The More Powerful Signal: RSI Divergence</h2>
<p><strong>Bearish divergence:</strong> Price makes a new high, but RSI makes a lower high. This means the rally is losing internal momentum — warning sign of a reversal.</p>
<p><strong>Bullish divergence:</strong> Price makes a new low, but RSI makes a higher low. Sellers are exhausting themselves. Often precedes a meaningful bounce.</p>

<div class="lesson-callout success">
  <strong>Real example:</strong> In late 2021, the Nasdaq made a new all-time high in November, but RSI was lower than the September high — classic bearish divergence. The subsequent 33% drop through 2022 was well-signaled in advance by momentum indicators like RSI.
</div>

<h2>RSI in Different Market Regimes</h2>
<ul>
  <li><strong>Bull market:</strong> RSI tends to stay between 40–80. Oversold is closer to 40, not 30. Overbought >70 often signals continued strength.</li>
  <li><strong>Bear market:</strong> RSI tends to stay between 20–60. Overbought is closer to 60. Rallies to 60 are often shorting opportunities.</li>
</ul>
    `,
    quiz: [
      {
        id: "ta-momentum-l1-q1",
        question: "RSI measures:",
        options: [
          "How a stock performs versus the S&P 500",
          "The speed and magnitude of recent price changes (0–100 scale)",
          "Trading volume relative to its average",
          "The gap between stock price and its moving average",
        ],
        answer: 1,
        explanation: "RSI measures the speed and magnitude of recent price changes, scaled from 0 to 100. High RSI = strong recent gains; low RSI = strong recent losses.",
      },
      {
        id: "ta-momentum-l1-q2",
        question: "Bearish RSI divergence occurs when:",
        options: [
          "Both price and RSI make new highs",
          "Price makes a new high but RSI makes a lower high",
          "RSI drops below 30",
          "Price and RSI both drop together",
        ],
        answer: 1,
        explanation: "Bearish divergence: price makes a new high but RSI is lower than its previous peak. This means the rally is losing momentum internally — a warning sign.",
      },
      {
        id: "ta-momentum-l1-q3",
        question: "In a strong bull market, a stock maintaining RSI above 60 for weeks usually indicates:",
        options: [
          "The stock is about to crash",
          "Institutional accumulation — large buyers consistently buying dips",
          "The RSI indicator is broken",
          "The stock is in a bear market rally",
        ],
        answer: 1,
        explanation: "Extended RSI above 60 in a bull market often reflects consistent institutional buying pressure, not an imminent top.",
      },
    ],
  },

  {
    id: "ta-momentum-l2",
    courseId: "ta-momentum",
    trackId: "technical-analysis",
    title: "MACD Signal Line Crossovers",
    type: "article",
    xp: 70,
    durationMin: 9,
    tags: ["macd", "momentum", "signal-line", "histogram"],
    body: `
<h2>MACD: Moving Average Convergence Divergence</h2>
<p>MACD combines two EMAs into one momentum indicator. It answers a simple question: is short-term momentum accelerating or decelerating compared to the intermediate trend?</p>

<div class="lesson-callout info">
  <strong>Three components:</strong>
  <ul>
    <li><strong>MACD Line:</strong> 12-day EMA minus 26-day EMA</li>
    <li><strong>Signal Line:</strong> 9-day EMA of the MACD line (a smoothed version)</li>
    <li><strong>Histogram:</strong> MACD Line minus Signal Line — visually shows the distance between the two</li>
  </ul>
</div>

<h2>The Signal Line Crossover</h2>
<p>The most-used MACD signal: when the <strong>MACD Line crosses above the Signal Line</strong>, buy momentum is increasing. When it crosses below, sell momentum is building.</p>
<p>The <strong>zero line</strong> matters too. Crossovers above zero (both lines positive) are stronger bullish signals than crossovers below zero (both lines negative).</p>

<h2>Reading the Histogram</h2>
<p>The histogram is arguably more useful than the crossovers. Watch for:</p>
<ul>
  <li><strong>Shrinking bars in a downtrend:</strong> Selling momentum is weakening. Potential bottom forming.</li>
  <li><strong>Expanding bars in an uptrend:</strong> Buying momentum is strengthening. Trend may be accelerating.</li>
  <li><strong>Histogram divergence:</strong> Same concept as RSI divergence — price makes a new extreme but the histogram doesn't match it.</li>
</ul>

<div class="lesson-callout warning">
  <strong>MACD is a lagging indicator.</strong> It's most useful for confirming a trend that's already in motion, not predicting reversals. In choppy, sideways markets, MACD produces constant false crossovers. Always check if the market is trending before relying on MACD signals.
</div>
    `,
    quiz: [
      {
        id: "ta-momentum-l2-q1",
        question: "The MACD Line is calculated as:",
        options: [
          "Close minus Open",
          "12-day EMA minus 26-day EMA",
          "RSI minus its 9-day average",
          "High minus Low divided by 2",
        ],
        answer: 1,
        explanation: "MACD Line = 12-day EMA - 26-day EMA. It measures the divergence between short-term and intermediate-term momentum.",
      },
      {
        id: "ta-momentum-l2-q2",
        question: "A bullish MACD crossover above the zero line is considered:",
        options: [
          "Weaker than one below zero", "Stronger than one below zero", "The same strength", "Irrelevant to trading decisions",
        ],
        answer: 1,
        explanation: "Crossovers above zero (both MACD and Signal line positive) indicate the trend is firmly in bullish territory — a stronger signal than a crossover while both lines are negative.",
      },
      {
        id: "ta-momentum-l2-q3",
        question: "Shrinking histogram bars during a downtrend suggest:",
        options: [
          "The downtrend is accelerating", "Selling momentum may be weakening — a potential bottom", "Volume is dropping", "The stock is overbought"],
        answer: 1,
        explanation: "Shrinking negative histogram bars mean the MACD and Signal lines are converging — selling momentum is losing steam. This often precedes a bottoming process.",
      },
    ],
  },

  {
    id: "ta-momentum-l3",
    courseId: "ta-momentum",
    trackId: "technical-analysis",
    title: "Volume: The Forgotten Confirmer",
    type: "article",
    xp: 60,
    durationMin: 8,
    tags: ["volume", "climax", "accumulation", "distribution"],
    body: `
<h2>Price Is the What. Volume Is the Who.</h2>
<p>Every price move tells you <em>what</em> happened — the stock went up or down. Volume tells you <em>who</em> cared. A 3% up-day on 10 million shares is very different from a 3% up-day on 200 million shares. The second one has institutional fingerprints all over it.</p>

<div class="lesson-callout info">
  <strong>The core rule:</strong> Volume should expand in the direction of the trend and contract on pullbacks.
  <ul>
    <li>Uptrend with rising volume on up-days, falling volume on down-days → healthy, sustainable trend</li>
    <li>Uptrend with falling volume on up-days, rising volume on down-days → distribution; trend likely ending</li>
  </ul>
</div>

<h2>Climax Volume: The Tell-Tale Sign</h2>
<p>A <strong>volume climax</strong> is an extreme spike — often 3–5× the 50-day average volume — that signals capitulation. At tops, it often marks panic buying by retail investors (euphoria top). At bottoms, it marks panic selling (capitulation low).</p>
<p>After a climax bar, price often enters a consolidation or reversal phase because the "fuel" for the move has been exhausted — everyone who wanted to buy (or sell) has done so.</p>

<h2>The Breakout Rule</h2>
<p>When a stock breaks out of a base or resistance level, volume should be at least 40–50% above its 50-day average. Low-volume breakouts fail far more often than high-volume ones — institutions aren't participating.</p>

<div class="lesson-callout success">
  <strong>Practical application:</strong> Before trading any breakout, check the volume. If the bar is red or volume is below average, wait. The best breakouts are large green candles on 2× normal volume or more.
</div>
    `,
    quiz: [
      {
        id: "ta-momentum-l3-q1",
        question: "In a healthy uptrend, volume should be:",
        options: [
          "Constant every day",
          "Higher on up-days, lower on pullback days",
          "Higher on pullback days to show buyers stepping in",
          "Unrelated to the price trend",
        ],
        answer: 1,
        explanation: "Healthy uptrends show expanding volume on up-days (buyers are enthusiastic) and contracting volume on pullbacks (sellers are weak).",
      },
      {
        id: "ta-momentum-l3-q2",
        question: "A volume climax bar at the top of a long uptrend most likely signals:",
        options: [
          "The trend is accelerating and will continue",
          "The move may be exhausted — everyone who wanted to buy already has",
          "Institutional accumulation beginning",
          "A healthy consolidation before another leg up",
        ],
        answer: 1,
        explanation: "A climax volume spike near highs often signals exhaustion — retail euphoria/panic buying has peaked. The subsequent move is often a consolidation or reversal.",
      },
      {
        id: "ta-momentum-l3-q3",
        question: "For a breakout to be considered high-conviction, volume should be:",
        options: [
          "Below average (quiet markets move farther)",
          "Exactly average",
          "At least 40–50% above the 50-day average",
          "The highest single volume day in history",
        ],
        answer: 2,
        explanation: "Quality breakouts need institutional participation. Volume 40–50%+ above average shows the big money is stepping in, significantly increasing the breakout's odds of follow-through.",
      },
    ],
  },

  // ── Course 3: Chart Patterns ─────────────────────────────────────────────
  {
    id: "ta-patterns-l1",
    courseId: "ta-patterns",
    trackId: "technical-analysis",
    title: "Head & Shoulders: The King of Reversals",
    type: "article",
    xp: 80,
    durationMin: 12,
    tags: ["head-and-shoulders", "reversal", "chart-patterns", "neckline"],
    body: `
<h2>The Most Reliable Reversal Pattern</h2>
<p>The <strong>head and shoulders</strong> pattern is the most widely studied reversal formation in technical analysis. It signals that a bullish trend is likely ending and a bearish trend is beginning. Its inverse — the <strong>inverse head and shoulders</strong> — signals the opposite: a bearish trend ending.</p>

<h2>Anatomy of the Pattern</h2>
<div class="lesson-callout info">
  <strong>Three peaks, one neckline:</strong>
  <ul>
    <li><strong>Left shoulder:</strong> Price rallies to a new high, then pulls back</li>
    <li><strong>Head:</strong> Price rallies to an even higher high (the "head"), then pulls back again to roughly the same level as the first pullback</li>
    <li><strong>Right shoulder:</strong> Price rallies again, but only to the level of the left shoulder — a <em>lower high</em> — then pulls back</li>
    <li><strong>Neckline:</strong> A line connecting the two pullback lows. The breakdown through this line is the entry signal.</li>
  </ul>
</div>

<h2>Why the Pattern Works</h2>
<p>The head and shoulders reveals the fundamental shift in supply and demand. Each rally attempts to reach the previous high but fails by a smaller margin. Sellers are entering at progressively lower levels. When price breaks the neckline, it confirms that buyers have completely surrendered control.</p>

<h2>Trading the Pattern</h2>
<ol>
  <li><strong>Entry:</strong> Short on a close below the neckline (or wait for a pullback back to the neckline from below)</li>
  <li><strong>Target:</strong> Measure the height from the neckline to the top of the head. Project that distance downward from the breakdown point.</li>
  <li><strong>Stop:</strong> Just above the right shoulder high</li>
  <li><strong>Volume:</strong> Volume should decline from left shoulder → head → right shoulder, and expand on the neckline breakdown</li>
</ol>

<div class="lesson-callout warning">
  <strong>The failed head and shoulders:</strong> If price breaks the neckline but quickly reverses back above it, this is called a "failed breakdown" — and it often leads to a sharp rally as trapped shorts cover. Always use a stop loss.
</div>
    `,
    quiz: [
      {
        id: "ta-patterns-l1-q1",
        question: "In a head and shoulders pattern, the 'neckline' is:",
        options: [
          "The level of the head (highest point)",
          "A line connecting the two pullback lows between the shoulders and head",
          "The 200-day moving average",
          "The support level at the left shoulder",
        ],
        answer: 1,
        explanation: "The neckline connects the two reaction lows formed during the pattern. A close below it is the entry/confirmation signal.",
      },
      {
        id: "ta-patterns-l1-q2",
        question: "The price target for a head and shoulders breakdown is calculated by:",
        options: [
          "Measuring the width of the pattern and projecting it down",
          "Measuring the height from neckline to head and projecting down from the breakdown",
          "The previous major support level",
          "A 50% retracement of the prior uptrend",
        ],
        answer: 1,
        explanation: "Classic target: neckline breakdown point minus the height from neckline to top of head. This gives a measured-move target.",
      },
      {
        id: "ta-patterns-l1-q3",
        question: "Ideal volume behavior during a head and shoulders formation is:",
        options: [
          "Increasing on every rally",
          "Declining on the left shoulder, lowest on the right shoulder, expanding on breakdown",
          "Constant throughout",
          "Highest at the head, declining on breakdown",
        ],
        answer: 1,
        explanation: "Volume should gradually decline across the three peaks (institutions losing interest) and then expand decisively when price breaks the neckline.",
      },
    ],
  },

  {
    id: "ta-patterns-l2",
    courseId: "ta-patterns",
    trackId: "technical-analysis",
    title: "Flags, Pennants & Continuation Patterns",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["flags", "pennants", "continuation", "cup-and-handle"],
    body: `
<h2>Continuation Patterns: The Market Pausing to Breathe</h2>
<p>Not all chart patterns signal reversals. <strong>Continuation patterns</strong> form when a strong trending stock pauses to consolidate gains before resuming in the same direction. Recognizing these patterns lets you add to winning positions at low-risk entry points instead of chasing breakouts.</p>

<h2>The Bull Flag</h2>
<p>A bull flag forms after a sharp, near-vertical price move (the "flagpole"). Price then consolidates in a tight, slightly downward-sloping channel (the "flag") for several days to a few weeks. Volume dries up during the flag — this is healthy. When price breaks out of the upper flag boundary on expanding volume, it signals the continuation of the prior uptrend.</p>
<div class="lesson-callout info">
  <strong>Target:</strong> Add the height of the flagpole to the breakout point. This is your measured-move target.
</div>

<h2>The Pennant</h2>
<p>A pennant is similar to a bull flag but the consolidation forms a converging triangle (like a pennant on a flagpole) rather than a parallel channel. Volume contracts sharply during the pennant, then explodes on the breakout. Pennants typically resolve faster than flags — often within 1–3 weeks.</p>

<h2>The Cup & Handle</h2>
<p>A longer-duration continuation pattern (typically weeks to months) where price forms a rounded "cup" bottom and then a brief "handle" consolidation before breaking out to new highs. William O'Neil popularized this pattern in his CAN SLIM system.</p>
<ul>
  <li>The cup should have a rounded bottom, not a V-shape</li>
  <li>The handle should be a mild pullback of no more than 15% and form in the upper half of the cup</li>
  <li>Volume should surge on the handle breakout</li>
</ul>

<div class="lesson-callout success">
  <strong>Why these patterns work:</strong> During the consolidation, weak holders sell and patient, conviction holders accumulate. When supply is exhausted and demand re-emerges, the breakout happens with power. High volume on the breakout confirms institutional participation.
</div>
    `,
    quiz: [
      {
        id: "ta-patterns-l2-q1",
        question: "A bull flag pattern is characterized by:",
        options: [
          "A sharp move down followed by a tight upward consolidation",
          "A sharp move up followed by a tight, slightly downward-sloping consolidation on declining volume",
          "A rounded bottom with a breakout to new highs",
          "Two equal highs followed by a breakdown",
        ],
        answer: 1,
        explanation: "A bull flag: sharp up-move (flagpole) → tight, slightly downward-sloping consolidation on declining volume → breakout resumes the uptrend.",
      },
      {
        id: "ta-patterns-l2-q2",
        question: "In a cup and handle pattern, the handle should ideally:",
        options: [
          "Retrace 50% or more of the cup",
          "Form in the lower half of the cup",
          "Be a mild pullback ≤15%, forming in the upper half of the cup",
          "Last at least 6 months",
        ],
        answer: 2,
        explanation: "The handle should be a minor pullback (≤15%) forming in the upper half of the cup — this keeps base quality high and signals strong accumulation.",
      },
      {
        id: "ta-patterns-l2-q3",
        question: "The measured-move target for a bull flag is calculated by:",
        options: [
          "Adding the height of the flag to the breakout point",
          "Adding the height of the flagpole to the breakout point",
          "Using the width of the flag as the target",
          "The prior major resistance level",
        ],
        answer: 1,
        explanation: "Flag target = flagpole height added to the breakout point. This gives the measured-move projection for where the next leg of the trend may reach.",
      },
    ],
  },

  {
    id: "ta-patterns-l3",
    courseId: "ta-patterns",
    trackId: "technical-analysis",
    title: "Combining Indicators: The Confluence Approach",
    type: "challenge",
    xp: 100,
    durationMin: 15,
    tags: ["confluence", "multi-indicator", "setup-building"],
    body: `
<h2>The Problem With Single Indicators</h2>
<p>Every indicator fails — sometimes badly. Moving averages whipsaw in choppy markets. RSI stays overbought for months in bull runs. MACD gives false crossovers constantly in ranging markets. Volume spikes can be noise or conviction.</p>
<p>The solution isn't to find the one perfect indicator. It's to use <strong>confluence</strong> — multiple independent signals pointing the same direction at the same time.</p>

<h2>Building a Confluence Stack</h2>
<p>A high-confidence trade setup typically requires 3–4 independent confirmations:</p>
<ol>
  <li><strong>Trend filter:</strong> Is price above or below its 200-day SMA? This tells you which side of the tape to be on.</li>
  <li><strong>Structure:</strong> Is there a clear chart pattern (flag, cup & handle, breakout from base)?</li>
  <li><strong>Momentum:</strong> Is RSI above 50? Is MACD bullish? Are momentum indicators confirming the price move?</li>
  <li><strong>Volume:</strong> Is volume above average? Is it expanding in the direction of the trade?</li>
</ol>

<div class="lesson-callout success">
  <strong>The more boxes you check, the higher the edge.</strong> A breakout from a cup & handle, above the 200-day SMA, with RSI at 65 and expanding volume is a much higher-probability setup than any single one of those signals alone.
</div>

<h2>The Killer Combination: Setup + Entry Trigger</h2>
<p>Even with perfect confluence, timing matters. Professional traders separate two things:</p>
<ul>
  <li><strong>The setup:</strong> The chart pattern, trend, and indicators that identify an opportunity</li>
  <li><strong>The entry trigger:</strong> A specific price level or candle action that says "now." The most common trigger is a breakout of the pattern's boundary on above-average volume.</li>
</ul>

<p>Never force a trade because you identified a setup. Wait for the trigger. Patience is a trading edge.</p>
    `,
    quiz: [
      {
        id: "ta-patterns-l3-q1",
        question: "What is 'confluence' in technical analysis?",
        options: [
          "Using two moving averages of the same type",
          "Multiple independent signals pointing in the same direction simultaneously",
          "A Japanese candlestick pattern",
          "When price and volume both hit new highs",
        ],
        answer: 1,
        explanation: "Confluence is when multiple independent indicators/signals all confirm the same directional bias. It significantly increases the probability of a successful trade.",
      },
      {
        id: "ta-patterns-l3-q2",
        question: "What is the difference between a 'setup' and an 'entry trigger'?",
        options: [
          "They're the same thing",
          "Setup identifies the opportunity; entry trigger is the specific price action that says 'act now'",
          "Setup is for stocks; trigger is for options",
          "Setup uses fundamentals; trigger uses technicals",
        ],
        answer: 1,
        explanation: "The setup is the broad analysis (pattern + trend + momentum). The entry trigger is a specific, objective event (e.g., breakout above resistance on volume) that initiates the trade.",
      },
      {
        id: "ta-patterns-l3-q3",
        question: "A stock breaking out of a cup and handle, above its 200-day SMA, with RSI at 65 and 2× average volume represents:",
        options: [
          "An overextended stock that should be avoided",
          "A high-confluence setup with multiple confirming signals",
          "A bearish signal because RSI is approaching overbought",
          "A setup that requires even more indicators before trading",
        ],
        answer: 1,
        explanation: "This describes an ideal high-confluence setup: the structural pattern, long-term trend filter, momentum indicator, and volume all point in the same direction.",
      },
    ],
    challenge: {
      description: "Use the BMG Capital chart to find a stock currently showing at least 2 of the 4 confluence elements: (1) above 200-day SMA, (2) a recognizable chart pattern, (3) RSI above 50, (4) above-average volume on recent up-days.",
      task: "Open the screener, run a scan for stocks above their 200-day SMA with RSI between 55–75. Pick one result, open its chart, and identify which additional confluence elements are present. Paper trade a position in that stock.",
      successCriteria: "Place at least one paper trade in a stock you identified using the confluence framework.",
    },
  },
];

export const courses: Course[] = [
  {
    id: "ta-trend",
    trackId: "technical-analysis",
    title: "Trend Analysis",
    description: "Moving averages, trendlines, channels, and the most-followed crossover signals on Wall Street.",
    lessonIds: ["ta-trend-l1", "ta-trend-l2", "ta-trend-l3"],
    xpTotal: 200,
  },
  {
    id: "ta-momentum",
    trackId: "technical-analysis",
    title: "Momentum & Volume",
    description: "RSI, MACD, and volume analysis — the three tools that tell you how strong a move really is.",
    lessonIds: ["ta-momentum-l1", "ta-momentum-l2", "ta-momentum-l3"],
    xpTotal: 200,
  },
  {
    id: "ta-patterns",
    trackId: "technical-analysis",
    title: "Chart Patterns",
    description: "Head & shoulders, flags, pennants, cup & handle, and how to combine everything into high-probability setups.",
    lessonIds: ["ta-patterns-l1", "ta-patterns-l2", "ta-patterns-l3"],
    xpTotal: 250,
  },
];

export const track: Track = {
  id: "technical-analysis",
  title: "Technical Analysis",
  description: "Read price charts like a professional trader. Learn to identify trends, momentum shifts, and high-probability patterns.",
  icon: "📈",
  difficulty: "intermediate",
  colorClass: "blue",
  courseIds: ["ta-trend", "ta-momentum", "ta-patterns"],
};
