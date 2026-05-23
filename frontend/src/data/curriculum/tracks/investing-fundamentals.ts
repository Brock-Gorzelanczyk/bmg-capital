import type { Track, Course, Lesson } from "@/types/learn";

// ── Lessons ──────────────────────────────────────────────────────────────────

export const lessons: Lesson[] = [

  // ── Course 1: Stock Market Basics ─────────────────────────────────────────

  {
    id: "if-stocks-101-l1",
    courseId: "if-stocks-101",
    trackId: "investing-fundamentals",
    title: "What Is a Stock?",
    type: "article",
    xp: 50,
    durationMin: 6,
    body: `
<h2>What Is a Stock?</h2>
<p>A <strong>stock</strong> (also called a <strong>share</strong> or <strong>equity</strong>) represents a small slice of ownership in a company. When you buy one share of Apple, you literally own a tiny piece of Apple Inc. — its factories, its brand, its future profits.</p>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div><strong>Key concept:</strong> Shareholders are <em>part owners</em> of the business. If the company grows and becomes more valuable, your shares become worth more.</div>
</div>

<h3>Why Companies Issue Stock</h3>
<p>Companies sell stock to raise money — called <strong>capital</strong>. Instead of borrowing from a bank and paying interest, a company can sell pieces of itself to thousands of investors. That cash funds new products, hires, or expansion.</p>
<p>In exchange, investors get:</p>
<ul>
  <li><strong>Price appreciation</strong> — if the company grows, the stock price rises</li>
  <li><strong>Dividends</strong> — some companies pay shareholders a portion of profits quarterly</li>
  <li><strong>Voting rights</strong> — shareholders can vote on major company decisions</li>
</ul>

<h3>How Stock Is Created: The IPO</h3>
<p>When a private company wants to sell shares to the public for the first time, it goes through an <strong>Initial Public Offering (IPO)</strong>. Investment banks help set the initial price and sell shares to large institutions. After that, anyone can buy and sell shares on a stock exchange like the NYSE or NASDAQ.</p>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Real example:</strong> When Google went public in 2004, it sold shares at $85 each. By 2024, a single original share (split-adjusted) was worth over $180 — more than doubling investors' money in 20 years.</div>
</div>

<h3>Common vs. Preferred Stock</h3>
<p>There are two main types:</p>
<ul>
  <li><strong>Common stock</strong> — what most investors buy. You get voting rights and can benefit from price gains, but you're last in line if the company goes bankrupt.</li>
  <li><strong>Preferred stock</strong> — pays a fixed dividend and has priority over common stock in bankruptcy. Less upside, more stability. Mostly held by institutional investors.</li>
</ul>

<h3>Fractional Shares</h3>
<p>You don't need to buy a whole share. Modern brokers like Fidelity and Schwab let you buy a <em>fraction</em> of a share for as little as $1. This makes expensive stocks like Amazon ($3,000+/share) accessible to anyone.</p>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div><strong>Bottom line:</strong> Stocks give you ownership in real businesses. When the business thrives, you thrive. This is why stocks have historically outperformed cash, bonds, and most other assets over long time horizons.</div>
</div>
`,
    quiz: [
      {
        id: "if-stocks-101-l1-q1",
        question: "What does owning a share of stock represent?",
        options: ["A loan you made to the company", "Partial ownership of the company", "A guaranteed return on investment", "A bond contract"],
        answer: 1,
        explanation: "A share of stock represents partial ownership (equity) in a company. You own a small piece of the business."
      },
      {
        id: "if-stocks-101-l1-q2",
        question: "Why do companies issue stock to the public?",
        options: ["To pay off existing debt", "To reduce their tax burden", "To raise capital for growth without borrowing", "To give employees a raise"],
        answer: 2,
        explanation: "IPOs and stock issuance raise capital — cash the company can use to grow — without taking on the interest burden of a loan."
      },
      {
        id: "if-stocks-101-l1-q3",
        question: "Which type of stockholder has priority in the event of bankruptcy?",
        options: ["Common stockholders", "Preferred stockholders", "Both are treated equally", "Neither — the government is paid first"],
        answer: 1,
        explanation: "Preferred stockholders have a higher claim on assets than common stockholders if a company goes bankrupt. Creditors and bondholders still rank above both."
      },
    ],
  },

  {
    id: "if-stocks-101-l2",
    courseId: "if-stocks-101",
    trackId: "investing-fundamentals",
    title: "How Stock Markets Work",
    type: "article",
    xp: 50,
    durationMin: 7,
    body: `
<h2>How Stock Markets Work</h2>
<p>A stock market is a marketplace — like a farmer's market, but instead of vegetables, buyers and sellers trade ownership in companies. Understanding how trades actually happen demystifies the process completely.</p>

<h3>Exchanges: The Trading Floors</h3>
<p>Most U.S. stocks trade on one of two major exchanges:</p>
<ul>
  <li><strong>NYSE (New York Stock Exchange)</strong> — the world's largest exchange by market cap. Home to blue-chip companies like JPMorgan, Coca-Cola, and Berkshire Hathaway.</li>
  <li><strong>NASDAQ</strong> — fully electronic from day one. Favored by tech companies: Apple, Microsoft, Google, Meta, Amazon, Tesla.</li>
</ul>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div>Both exchanges list thousands of stocks. The exchange a stock trades on doesn't affect how you buy it — your broker handles routing automatically.</div>
</div>

<h3>How a Trade Gets Executed</h3>
<p>When you click "buy" in your brokerage app, here's what happens in milliseconds:</p>
<ol>
  <li>Your broker receives your order</li>
  <li>The order is routed to a market maker or directly to the exchange</li>
  <li>A matching engine pairs your buy order with a sell order at the same price</li>
  <li>The trade executes and you receive your shares</li>
  <li>Settlement occurs in <strong>T+1</strong> (one business day)</li>
</ol>

<h3>Market Hours</h3>
<p>The U.S. stock market is open <strong>Monday–Friday, 9:30 AM – 4:00 PM ET</strong>. Outside these hours, pre-market (4–9:30 AM ET) and after-hours (4–8 PM ET) trading exists but with lower volume and wider spreads.</p>

<h3>The Bid-Ask Spread</h3>
<p>At any moment, a stock has two prices:</p>
<ul>
  <li><strong>Bid price</strong> — the highest price a buyer is willing to pay right now</li>
  <li><strong>Ask price</strong> — the lowest price a seller is willing to accept right now</li>
</ul>
<p>The <strong>spread</strong> is the difference. For Apple (a highly liquid stock), the spread might be just $0.01. For a small-cap stock with low trading volume, the spread could be $0.50 or more — that's an instant loss the moment you buy.</p>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Practical tip:</strong> Always check the bid-ask spread before placing a market order on a thinly traded stock. A wide spread means you're immediately underwater.</div>
</div>

<h3>Market Capitalization</h3>
<p>Market cap = current share price × total shares outstanding. It's the market's valuation of the entire company.</p>
<ul>
  <li><strong>Large-cap</strong>: $10B+ (Apple, Microsoft, Amazon)</li>
  <li><strong>Mid-cap</strong>: $2B–$10B</li>
  <li><strong>Small-cap</strong>: $300M–$2B</li>
  <li><strong>Micro-cap</strong>: Under $300M</li>
</ul>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>Larger companies are generally more liquid and less volatile. Smaller companies can grow faster but carry more risk.</div>
</div>
`,
    quiz: [
      {
        id: "if-stocks-101-l2-q1",
        question: "What is T+1 settlement?",
        options: ["Trading starts 1 hour after market open", "Your trade confirms 1 minute after placing", "Ownership officially transfers one business day after the trade", "You must hold a stock for 1 day before selling"],
        answer: 2,
        explanation: "T+1 means settlement happens one business day after the trade date. You see the shares immediately but they officially transfer the next business day."
      },
      {
        id: "if-stocks-101-l2-q2",
        question: "What is the bid-ask spread?",
        options: ["The range between a stock's 52-week high and low", "The difference between the highest buy price and lowest sell price", "The commission your broker charges per trade", "The gap between pre-market and regular session prices"],
        answer: 1,
        explanation: "The bid-ask spread is the difference between what buyers are willing to pay (bid) and what sellers are asking (ask). It represents an implicit transaction cost."
      },
      {
        id: "if-stocks-101-l2-q3",
        question: "A company with 10 million shares outstanding trading at $50/share has a market cap of:",
        options: ["$5 million", "$50 million", "$500 million", "$5 billion"],
        answer: 2,
        explanation: "Market cap = shares × price = 10,000,000 × $50 = $500,000,000 = $500 million."
      },
    ],
  },

  {
    id: "if-stocks-101-l3",
    courseId: "if-stocks-101",
    trackId: "investing-fundamentals",
    title: "Bull & Bear Markets",
    type: "article",
    xp: 60,
    durationMin: 7,
    body: `
<h2>Bull &amp; Bear Markets</h2>
<p>Two words you'll hear constantly in financial news: <strong>bull market</strong> and <strong>bear market</strong>. Understanding these cycles is fundamental to making good long-term decisions — and to not panicking at the wrong time.</p>

<h3>The Definitions</h3>
<ul>
  <li><strong>Bull market</strong> — a sustained rise of 20%+ in stock prices from a recent low. Characterized by optimism, strong economic data, rising employment, and investor confidence.</li>
  <li><strong>Bear market</strong> — a sustained decline of 20%+ from a recent high. Characterized by fear, economic slowdown, and widespread selling.</li>
  <li><strong>Correction</strong> — a decline of 10–20%. A correction can happen inside a bull market; it becomes a bear market if it crosses 20%.</li>
</ul>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div>The terms come from how each animal attacks: a bull <em>thrusts upward</em> with its horns; a bear <em>swipes downward</em>.</div>
</div>

<h3>Historical Context</h3>
<p>Since 1928, the U.S. stock market has spent far more time in bull markets than bear markets:</p>
<ul>
  <li>The average bull market lasts about <strong>6.6 years</strong> and gains ~339%</li>
  <li>The average bear market lasts about <strong>1.4 years</strong> and loses ~38%</li>
  <li>Bear markets are shorter and less frequent — but they feel catastrophic in the moment</li>
</ul>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Notable bear markets:</strong> The dot-com crash (2000–2002, -49%), the financial crisis (2007–2009, -57%), and COVID crash (Feb–March 2020, -34% in just 33 days — and then the fastest recovery in history).</div>
</div>

<h3>How to Navigate Each Cycle</h3>
<p><strong>During a bull market:</strong></p>
<ul>
  <li>Stay invested — trying to "sell at the top" is notoriously difficult</li>
  <li>Rebalance periodically to avoid overconcentration in winners</li>
  <li>Don't use leverage (borrowed money) just because stocks seem unstoppable</li>
</ul>

<p><strong>During a bear market:</strong></p>
<ul>
  <li>Don't panic-sell — bear markets are temporary; locking in losses is permanent</li>
  <li>Consider dollar-cost averaging — buying fixed amounts regularly means you buy more shares when prices are low</li>
  <li>Review your risk tolerance — if you can't sleep, your allocation may be too aggressive</li>
</ul>

<h3>Sectors Behave Differently</h3>
<p>Not all stocks fall equally in a bear market. <strong>Defensive sectors</strong> like utilities, healthcare, and consumer staples tend to hold up better. <strong>Cyclical sectors</strong> like technology, energy, and consumer discretionary tend to fall more — but also recover faster.</p>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div><strong>The long game:</strong> $10,000 invested in the S&P 500 in 1990 — through multiple recessions, crashes, and crises — would be worth over $200,000 by 2024. Time in the market beats timing the market.</div>
</div>
`,
    quiz: [
      {
        id: "if-stocks-101-l3-q1",
        question: "How is a bear market officially defined?",
        options: ["Any day the market closes down", "A decline of 5% or more in a single week", "A sustained drop of 20% or more from a recent high", "Three consecutive months of negative returns"],
        answer: 2,
        explanation: "A bear market requires a sustained 20%+ decline from a recent high. A 10–20% drop is called a correction."
      },
      {
        id: "if-stocks-101-l3-q2",
        question: "Which investment strategy is most appropriate during a bear market?",
        options: ["Sell everything and move to cash immediately", "Use margin to buy more aggressively at lower prices", "Dollar-cost average and stay invested according to your plan", "Only buy defensive sectors and avoid all equities"],
        answer: 2,
        explanation: "Dollar-cost averaging and staying the course through bear markets has historically produced far better outcomes than panic selling and trying to re-enter at the 'bottom.'"
      },
      {
        id: "if-stocks-101-l3-q3",
        question: "Historically, which is true about bull vs. bear markets?",
        options: ["Bear markets last longer but gain more", "Bull markets last longer and gain more", "They are roughly equal in duration", "Bear markets occur more frequently than bull markets"],
        answer: 1,
        explanation: "Bull markets average ~6.6 years; bear markets average ~1.4 years. The gains in bull markets have historically far outweighed bear market losses."
      },
    ],
  },

  // ── Course 2: Reading Price Charts ────────────────────────────────────────

  {
    id: "if-charts-l1",
    courseId: "if-charts",
    trackId: "investing-fundamentals",
    title: "Candlestick Charts Explained",
    type: "article",
    xp: 60,
    durationMin: 8,
    body: `
<h2>Candlestick Charts Explained</h2>
<p>Candlestick charts are the universal language of trading. Every chart in BMG Capital uses them by default. Once you can read a candlestick, you can read any chart in the world — stocks, crypto, forex, futures.</p>

<h3>Anatomy of a Candlestick</h3>
<p>Each candlestick represents one time period (1 minute, 1 day, 1 week — whatever your chart's timeframe is). It contains four pieces of data:</p>
<ul>
  <li><strong>Open</strong> — the price at the start of the period</li>
  <li><strong>High</strong> — the highest price reached during the period</li>
  <li><strong>Low</strong> — the lowest price reached during the period</li>
  <li><strong>Close</strong> — the price at the end of the period</li>
</ul>
<p>The thick rectangular body shows the range between open and close. The thin lines above and below are called <strong>wicks</strong> (or shadows) and show the high/low extremes.</p>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div>
    <strong>Green candle:</strong> Close was higher than Open — bulls won this period.<br/>
    <strong>Red candle:</strong> Close was lower than Open — bears won this period.
  </div>
</div>

<h3>Reading Candle Size</h3>
<p>The <em>size</em> of a candle tells you the intensity of price movement:</p>
<ul>
  <li><strong>Long green body</strong> — strong buying pressure; bulls completely in control</li>
  <li><strong>Long red body</strong> — strong selling pressure; bears completely in control</li>
  <li><strong>Small body (doji)</strong> — indecision; buyers and sellers roughly equal. Often signals a potential reversal.</li>
</ul>

<h3>Reading the Wicks</h3>
<p>Wicks reveal what happened <em>during</em> the period:</p>
<ul>
  <li><strong>Long upper wick</strong> — price pushed up but sellers pushed it back down before close. Bearish signal if at the top of a trend.</li>
  <li><strong>Long lower wick</strong> — price dropped but buyers stepped in and pushed it back up. Bullish signal — buyers defended that level.</li>
  <li><strong>Hammer</strong> — small body at the top, long lower wick. Strong buyer defense. Often a reversal signal at the bottom of a downtrend.</li>
  <li><strong>Shooting star</strong> — small body at the bottom, long upper wick. Strong seller rejection. Often a reversal signal at the top of an uptrend.</li>
</ul>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Practical application:</strong> Open BMG Capital's chart on any stock (try AAPL). Hover over individual candles and read the OHLC values in the top bar. Notice how green days have close > open and red days have open > close.</div>
</div>

<h3>Multi-Candle Patterns</h3>
<p>Individual candles are useful, but patterns of 2–3 candles are more reliable:</p>
<ul>
  <li><strong>Engulfing pattern</strong> — a candle whose body completely contains the previous candle's body. A green engulfing after a downtrend is bullish; a red engulfing after an uptrend is bearish.</li>
  <li><strong>Three white soldiers</strong> — three consecutive green candles with each closing higher. Strong bullish momentum.</li>
  <li><strong>Evening star / Morning star</strong> — three-candle reversal patterns involving a doji in the middle.</li>
</ul>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>No single candle signal is a "guaranteed" trade. Candlestick patterns increase the probability of a move — they don't guarantee it. Always confirm with volume and trend context.</div>
</div>
`,
    quiz: [
      {
        id: "if-charts-l1-q1",
        question: "A green (bullish) candlestick means:",
        options: ["The stock made an all-time high", "The closing price was higher than the opening price", "Volume was above average", "The stock outperformed the market"],
        answer: 1,
        explanation: "A green candle simply means the price closed higher than it opened during that time period. The bull camp won the period."
      },
      {
        id: "if-charts-l1-q2",
        question: "What does a long lower wick on a candlestick indicate?",
        options: ["The stock is in a long-term downtrend", "Sellers dominated the entire session", "Buyers pushed prices back up after a decline during the period", "The opening price was much higher than the close"],
        answer: 2,
        explanation: "A long lower wick shows the price fell significantly during the period but buyers stepped in and pushed it back up — a sign of buyer support at that price level."
      },
      {
        id: "if-charts-l1-q3",
        question: "What is a 'doji' candlestick?",
        options: ["A candle with no wicks", "A candle where open and close are approximately equal", "The largest candle in a given period", "A three-candle reversal pattern"],
        answer: 1,
        explanation: "A doji has nearly equal open and close prices, creating a very small body. It signals indecision — neither buyers nor sellers clearly won the session."
      },
    ],
  },

  {
    id: "if-charts-l2",
    courseId: "if-charts",
    trackId: "investing-fundamentals",
    title: "Support & Resistance",
    type: "article",
    xp: 70,
    durationMin: 8,
    body: `
<h2>Support &amp; Resistance</h2>
<p>Support and resistance are the most fundamental concepts in all of technical analysis. Every professional trader uses them, whether they admit it or not.</p>

<h3>What Is Support?</h3>
<p>A <strong>support level</strong> is a price zone where buying interest is strong enough to stop or reverse a declining price. Think of it as a floor. When price approaches that level, buyers historically step in.</p>
<p>Why does support form? Because at certain prices, enough investors believe the stock is "cheap" and buy it. This collective behavior creates a predictable zone of buying pressure.</p>

<h3>What Is Resistance?</h3>
<p>A <strong>resistance level</strong> is a price zone where selling pressure is strong enough to stop or reverse a rising price. Think of it as a ceiling. When price approaches that level, sellers historically come out.</p>
<p>Why does resistance form? Two reasons: (1) investors who bought lower want to take profit, and (2) investors who bought at that level previously and are now "underwater" want to break even and exit.</p>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div><strong>Role reversal:</strong> When price breaks through a support level, that support often becomes new resistance. When price breaks through resistance, that resistance often becomes new support. This is one of the most reliable patterns in all of trading.</div>
</div>

<h3>How to Draw Support and Resistance Lines</h3>
<ol>
  <li>Zoom out to at least a 1-year daily chart</li>
  <li>Look for price levels where the stock has reversed multiple times (2+ touches are significant; 3+ are very significant)</li>
  <li>Draw a horizontal line at the area — it doesn't need to be an exact price, it's a <em>zone</em></li>
  <li>The more times a level has been tested and held, the stronger it is</li>
</ol>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Try it:</strong> Open BMG Capital's chart on AAPL. Draw a horizontal line at the $170 area. Notice how price has bounced off that level multiple times across different years. That's support.</div>
</div>

<h3>Dynamic Support &amp; Resistance</h3>
<p>Support and resistance don't have to be horizontal. <strong>Trendlines</strong> are diagonal support/resistance that rises or falls with the trend. A rising 50-day moving average can also act as dynamic support in an uptrend.</p>

<h3>Round Numbers as Psychological Levels</h3>
<p>Round numbers ($100, $200, $1000) act as strong support/resistance because humans anchor to them psychologically. Watch how stocks behave around major round number milestones — the battles are often fierce.</p>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>Support and resistance are most powerful on <strong>higher timeframes</strong> (weekly, monthly). A level that's held on a weekly chart for 3 years is far more significant than one on a 5-minute chart.</div>
</div>
`,
    quiz: [
      {
        id: "if-charts-l2-q1",
        question: "When a support level is broken, what often happens to it?",
        options: ["It disappears and is irrelevant", "It becomes a new resistance level", "It strengthens and becomes harder to break again", "Price immediately returns to that level"],
        answer: 1,
        explanation: "Role reversal: broken support becomes resistance. Former buyers who are now underwater will sell if price returns to their cost basis, creating selling pressure at the old support."
      },
      {
        id: "if-charts-l2-q2",
        question: "What makes a support or resistance level stronger?",
        options: ["The higher the stock's price", "The more times price has reversed at that level", "How recently the level was formed", "Whether the level is above or below the 200-day MA"],
        answer: 1,
        explanation: "The more times price has respected a level (bounced off it), the more market participants are aware of it and act on it, making it self-reinforcing."
      },
      {
        id: "if-charts-l2-q3",
        question: "Why do round numbers like $100 or $500 often act as strong support/resistance?",
        options: ["Computers trade at round numbers automatically", "Human psychology causes anchoring to round prices", "Market makers set prices at round numbers", "Round numbers always coincide with earnings announcements"],
        answer: 1,
        explanation: "Humans naturally anchor to round numbers for price targets, stop losses, and mental accounting. This collective behavior creates real supply/demand zones at those levels."
      },
    ],
  },

  {
    id: "if-charts-l3",
    courseId: "if-charts",
    trackId: "investing-fundamentals",
    title: "Volume: The Forgotten Indicator",
    type: "article",
    xp: 60,
    durationMin: 7,
    body: `
<h2>Volume: The Forgotten Indicator</h2>
<p>New traders obsess over price. Professionals watch <strong>volume</strong>. Volume — the number of shares traded in a given period — confirms whether a price move is real or a head-fake.</p>

<h3>Why Volume Matters</h3>
<p>Price tells you <em>what</em> happened. Volume tells you <em>how much conviction</em> was behind it. A stock rising 5% on 10 million shares (high volume) is a very different signal than rising 5% on 500,000 shares (low volume).</p>
<ul>
  <li><strong>High volume + price rise</strong> = Strong buying conviction. Institutions are likely participating. Move is more likely to continue.</li>
  <li><strong>Low volume + price rise</strong> = Weak buying, possibly a short-term squeeze. Move is more likely to fade.</li>
  <li><strong>High volume + price drop</strong> = Strong selling conviction. Distribution by large players. Downtrend likely to continue.</li>
  <li><strong>Low volume + price drop</strong> = Weak selling, possibly a shakeout. Often an opportunity.</li>
</ul>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div><strong>Rule of thumb:</strong> Volume should confirm price moves. Rising price + rising volume = healthy uptrend. Rising price + falling volume = divergence — potential warning sign.</div>
</div>

<h3>Volume at Breakouts</h3>
<p>One of the most important volume signals: <strong>breakouts on high volume</strong>. When a stock breaks above a significant resistance level on volume 50%+ above average, it's a much stronger signal than a quiet breakout. Institutions (who can't buy without moving markets) are the ones who create high-volume breakouts.</p>

<h3>Climax Volume</h3>
<p>Extremely high volume — sometimes 5–10× average — at the end of a move is called <strong>climax volume</strong>. After a long uptrend, climax volume often signals exhaustion: everyone who wanted to buy has bought. After a sharp decline, climax volume can signal capitulation — the last sellers finally giving up, which creates a bottom.</p>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Open BMG Capital:</strong> Pull up any stock chart and look at the volume bars at the bottom. Find a significant price move and check if volume was above or below average (the average line shows as a lighter horizontal indicator). Notice the correlation.</div>
</div>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>Before making any trade decision, check volume. A breakout without volume is called a "fakeout." High volume validates the move. Make volume your second opinion on every price signal.</div>
</div>
`,
    quiz: [
      {
        id: "if-charts-l3-q1",
        question: "A stock breaks above a major resistance level, but volume is 30% below average. This is most likely:",
        options: ["A very strong breakout that will continue for weeks", "A normal breakout with standard volume", "A weak breakout (fakeout) that may reverse", "A sign that institutions have stopped trading the stock"],
        answer: 2,
        explanation: "Low-volume breakouts frequently fail. Without strong participation from large buyers, there's not enough conviction to sustain the move above resistance."
      },
      {
        id: "if-charts-l3-q2",
        question: "What is 'climax volume' at the end of a downtrend typically a sign of?",
        options: ["Continued selling pressure ahead", "Capitulation — the last sellers giving up, potentially marking a bottom", "A warning that more decline is coming", "Normal trading activity"],
        answer: 1,
        explanation: "Climax volume at a bottom means panic sellers are exhausted. When there are no sellers left, buyers take control. This often marks important bottoms."
      },
      {
        id: "if-charts-l3-q3",
        question: "Price is rising but volume has been declining for three weeks. This is called a:",
        options: ["Volume expansion", "Bullish accumulation", "Volume-price divergence", "Dead cat bounce"],
        answer: 2,
        explanation: "Divergence between price and volume is a warning signal. Rising prices on decreasing volume suggests the rally is losing conviction and may be running out of buyers."
      },
    ],
  },

  // ── Course 3: Your First Trade ─────────────────────────────────────────────

  {
    id: "if-first-trade-l1",
    courseId: "if-first-trade",
    trackId: "investing-fundamentals",
    title: "Market Orders vs. Limit Orders",
    type: "article",
    xp: 50,
    durationMin: 6,
    body: `
<h2>Market Orders vs. Limit Orders</h2>
<p>Two order types that every investor uses. Understanding the difference — and when to use each — will save you money and frustration.</p>

<h3>The Market Order</h3>
<p>A <strong>market order</strong> says: "Buy (or sell) this stock right now, at whatever the current price is." You are guaranteed execution but <em>not</em> a specific price.</p>
<p><strong>Pros:</strong> Always fills immediately. Simple. Good for large, liquid stocks during market hours.</p>
<p><strong>Cons:</strong> In fast-moving markets or with low-liquidity stocks, you might pay much more (or receive much less) than you expected. This is called <strong>slippage</strong>.</p>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">⚠️</span>
  <div><strong>Never use market orders on illiquid stocks</strong> (small caps, penny stocks) or during after-hours trading. The bid-ask spread can be enormous and your fill price can be shocking.</div>
</div>

<h3>The Limit Order</h3>
<p>A <strong>limit order</strong> says: "Buy (or sell) this stock, but only at my specified price or better." You control the price but <em>not</em> whether it fills.</p>
<ul>
  <li><strong>Buy limit order</strong>: Executes only if the price falls to your limit or below. You set a maximum price you're willing to pay.</li>
  <li><strong>Sell limit order</strong>: Executes only if the price rises to your limit or above. You set a minimum price you're willing to accept.</li>
</ul>
<p><strong>Pros:</strong> Price certainty. Protects you from unfavorable fills.</p>
<p><strong>Cons:</strong> May not fill at all if the stock never reaches your price.</p>

<h3>When to Use Each</h3>
<table class="lesson-table">
  <thead><tr><th>Situation</th><th>Use</th></tr></thead>
  <tbody>
    <tr><td>Large, liquid stock (AAPL, SPY)</td><td>Either — market order is fine</td></tr>
    <tr><td>Small-cap or volatile stock</td><td>Limit order</td></tr>
    <tr><td>You need immediate execution</td><td>Market order</td></tr>
    <tr><td>Entering at a specific price level</td><td>Limit order</td></tr>
    <tr><td>After-hours trading</td><td>Limit order only</td></tr>
  </tbody>
</table>

<h3>Stop Orders and Stop-Limit Orders</h3>
<p>Two more order types you'll encounter:</p>
<ul>
  <li><strong>Stop order (stop-loss)</strong>: Becomes a market order once price hits your stop price. Used to limit losses — if you buy at $100 and set a stop at $90, you'll automatically sell if the stock drops to $90.</li>
  <li><strong>Stop-limit order</strong>: Becomes a limit order (not market) when triggered. More precise, but risks not filling if the stock gaps below your stop.</li>
</ul>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>Professional traders almost always use limit orders. A limit order gives you control over your entry and exit prices — an edge that compounds over hundreds of trades.</div>
</div>
`,
    quiz: [
      {
        id: "if-first-trade-l1-q1",
        question: "You place a buy limit order for TSLA at $200. TSLA is currently trading at $215. What happens?",
        options: ["The order executes immediately at $215", "The order waits until TSLA drops to $200 or below", "The order executes at $207.50 (midpoint)", "The order is rejected because your limit is below market price"],
        answer: 1,
        explanation: "A buy limit order only executes at your specified price or lower. Your order sits in the queue until Tesla drops to $200 (or below)."
      },
      {
        id: "if-first-trade-l1-q2",
        question: "What is 'slippage'?",
        options: ["A broker fee for large orders", "The difference between expected and actual fill price", "When a limit order expires unfilled", "The spread between bid and ask on a futures contract"],
        answer: 1,
        explanation: "Slippage is the difference between the price you expected to pay and the price you actually paid. It's most common with market orders during fast markets or on illiquid stocks."
      },
      {
        id: "if-first-trade-l1-q3",
        question: "Why should you avoid market orders on thinly traded stocks?",
        options: ["Market orders aren't available for small-cap stocks", "The bid-ask spread can be very wide, causing poor fill prices", "Limit orders are required by law for stocks under $5", "Market orders always get routed to the wrong exchange"],
        answer: 1,
        explanation: "Thinly traded stocks have wide bid-ask spreads. A market order immediately crosses the spread, potentially filling at a price far from where the stock was 'trading.'"
      },
    ],
  },

  {
    id: "if-first-trade-l2",
    courseId: "if-first-trade",
    trackId: "investing-fundamentals",
    title: "Position Sizing: How Much to Buy",
    type: "article",
    xp: 70,
    durationMin: 8,
    body: `
<h2>Position Sizing: How Much to Buy</h2>
<p>Most beginners ask "What should I buy?" The better question is "How much should I buy?" Position sizing is the single most important risk management tool in your arsenal — and the most ignored.</p>

<h3>Why Position Sizing Matters</h3>
<p>Imagine two traders each with $10,000. Trader A puts $9,000 into a single stock. Trader B spreads evenly across 10 positions. If one position drops 50%, Trader A loses $4,500 (45% of their account). Trader B loses $500 (5%). Same bad pick — completely different outcomes.</p>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div><strong>The first rule of position sizing:</strong> No single position should be able to devastate your account. Protect your capital. You can't trade if you blow up.</div>
</div>

<h3>The 1–2% Rule</h3>
<p>Professional traders typically risk 1–2% of their total account on any single trade. "Risking" means the amount lost if the trade hits your stop loss.</p>
<p><strong>Example:</strong></p>
<ul>
  <li>Account size: $10,000</li>
  <li>Risk per trade: 1% = $100</li>
  <li>Stock price: $50, stop loss at $45 (a $5 risk per share)</li>
  <li>Number of shares: $100 ÷ $5 = <strong>20 shares</strong></li>
  <li>Total position: 20 × $50 = $1,000 (10% of account)</li>
</ul>

<h3>Fixed Percentage of Account</h3>
<p>A simpler method: never put more than X% of your account into any single position. Common rules:</p>
<ul>
  <li><strong>Beginners</strong>: 5–10% max per position</li>
  <li><strong>Intermediate</strong>: 10–20% for high-conviction trades</li>
  <li><strong>Concentration plays</strong>: 25%+ only for experienced traders with high conviction and a clear stop</li>
</ul>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div><strong>Diversification isn't just "don't put all your eggs in one basket."</strong> It also means not concentrating in one sector, one market cap size, or one macroeconomic factor. A portfolio of 10 tech stocks isn't diversified.</div>
</div>

<h3>Kelly Criterion (Advanced)</h3>
<p>The Kelly Criterion is a mathematical formula to calculate the optimal bet size based on your win rate and average win/loss ratio. The formula: <code>f = (bp - q) / b</code> where b = win/loss ratio, p = win probability, q = loss probability (1-p).</p>
<p>Most professionals use <strong>half-Kelly</strong> or <strong>quarter-Kelly</strong> to account for uncertainty in those estimates.</p>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>Start with the 1–2% rule and a maximum of 10% of account per position. As you develop a track record, you can adjust. But many professionals trade the same sizing rules for their entire careers — it's not a stepping stone, it's the destination.</div>
</div>
`,
    quiz: [
      {
        id: "if-first-trade-l2-q1",
        question: "Using the 1% risk rule: You have a $20,000 account. Your stop loss is $5 below your entry price. How many shares should you buy?",
        options: ["20 shares", "40 shares", "100 shares", "200 shares"],
        answer: 1,
        explanation: "1% of $20,000 = $200 maximum risk. At $5 risk per share: $200 ÷ $5 = 40 shares."
      },
      {
        id: "if-first-trade-l2-q2",
        question: "A portfolio of 10 different technology stocks is:",
        options: ["Well diversified because it has 10 positions", "Concentrated in one sector and not well diversified", "The ideal portfolio size for a retail investor", "A good hedge against a tech market decline"],
        answer: 1,
        explanation: "10 positions in the same sector move together — they're all exposed to the same macro factors (interest rates, regulation, tech cycles). True diversification requires different sectors and asset classes."
      },
      {
        id: "if-first-trade-l2-q3",
        question: "What is the primary purpose of position sizing?",
        options: ["To maximize returns on winning trades", "To ensure no single loss can seriously damage your account", "To qualify for better commission rates", "To maintain a portfolio of exactly 20 positions"],
        answer: 1,
        explanation: "Position sizing is first and foremost about capital preservation. Protecting your account means you stay in the game long enough to benefit from good trades."
      },
    ],
  },

  {
    id: "if-first-trade-l3",
    courseId: "if-first-trade",
    trackId: "investing-fundamentals",
    title: "Paper Trading Challenge: Your First Trade",
    type: "challenge",
    xp: 100,
    durationMin: 10,
    body: `
<h2>Paper Trading Challenge: Your First Trade</h2>
<p>You've learned the concepts. Now it's time to apply them. In this challenge, you'll place your first paper trade on BMG Capital using everything from the course.</p>

<h3>Your Mission</h3>
<ol>
  <li>Navigate to <strong>Paper Trading</strong> in the sidebar</li>
  <li>Pick a stock you want to practice with (suggestion: AAPL, MSFT, or SPY)</li>
  <li>Open the chart and identify a <strong>support level</strong> using a horizontal line</li>
  <li>Check the current volume vs. recent average</li>
  <li>Place a <strong>buy limit order</strong> at or near the support level with a <strong>limit price</strong> (not market order)</li>
  <li>Set a mental stop loss 5–8% below your entry</li>
</ol>

<div class="lesson-callout lesson-callout--blue">
  <span class="lesson-callout__icon">💡</span>
  <div><strong>Sizing your position:</strong> Your paper account starts with $100,000. Apply the 2% risk rule: risk no more than $2,000 on this trade. If your stop is 5% below entry, your max position size is $2,000 ÷ 0.05 = $40,000. That's your ceiling for this trade.</div>
</div>

<h3>What to Document</h3>
<p>After placing the trade (or placing a limit order that may fill), write down:</p>
<ul>
  <li>Why you chose this stock</li>
  <li>Where the support level is and why it's significant</li>
  <li>Your entry price and stop loss level</li>
  <li>Your price target (where you'll take profit)</li>
  <li>Your position size in dollars and shares</li>
</ul>

<div class="lesson-callout lesson-callout--yellow">
  <span class="lesson-callout__icon">📌</span>
  <div>The documentation is more important than the trade itself. Professional traders know exactly why they're in every position. Vague entries create vague exits — and vague exits create losses.</div>
</div>

<div class="lesson-callout lesson-callout--green">
  <span class="lesson-callout__icon">✅</span>
  <div>Complete the challenge by placing your order in Paper Trading and returning here to mark it done. You'll earn <strong>100 XP</strong> — the most of any lesson in this course.</div>
</div>
`,
    challenge: {
      description: "Place a buy order in Paper Trading using a limit order on a stock you've analyzed",
      task: "buy",
      successCriteria: "Place at least one limit buy order in the Paper Trading module",
    },
    quiz: [
      {
        id: "if-first-trade-l3-q1",
        question: "You have a $100,000 paper account. Using 2% risk rule and a 5% stop loss, what is the maximum position size?",
        options: ["$2,000", "$5,000", "$10,000", "$40,000"],
        answer: 3,
        explanation: "Max risk = 2% × $100,000 = $2,000. Max position = max risk ÷ stop % = $2,000 ÷ 0.05 = $40,000."
      },
      {
        id: "if-first-trade-l3-q2",
        question: "Before entering a trade, you should document all of the following EXCEPT:",
        options: ["Your entry price and stop loss", "Your price target", "The analyst consensus price target for the next 10 years", "Why you chose this stock"],
        answer: 2,
        explanation: "A trade journal should capture your own thesis and levels. Long-range analyst consensus targets are not useful for short-to-medium term trade planning."
      },
      {
        id: "if-first-trade-l3-q3",
        question: "Why use a limit order rather than a market order when buying near support?",
        options: ["Limit orders always fill faster", "You control the exact price you pay, avoiding slippage above the support level", "Market orders aren't available for paper trading", "Limit orders require less documentation"],
        answer: 1,
        explanation: "Buying near support with a limit order ensures you don't accidentally pay above the level you identified. A market order might fill several percent higher."
      },
    ],
  },
];

// ── Courses ──────────────────────────────────────────────────────────────────

export const courses: Course[] = [
  {
    id: "if-stocks-101",
    trackId: "investing-fundamentals",
    title: "Stock Market Basics",
    description: "What stocks are, how markets work, and how to think about market cycles.",
    lessonIds: ["if-stocks-101-l1", "if-stocks-101-l2", "if-stocks-101-l3"],
    xpTotal: 160,
  },
  {
    id: "if-charts",
    trackId: "investing-fundamentals",
    title: "Reading Price Charts",
    description: "Candlesticks, support and resistance, and using volume to confirm price moves.",
    lessonIds: ["if-charts-l1", "if-charts-l2", "if-charts-l3"],
    xpTotal: 190,
  },
  {
    id: "if-first-trade",
    trackId: "investing-fundamentals",
    title: "Making Your First Trade",
    description: "Order types, position sizing, and a hands-on paper trade challenge.",
    lessonIds: ["if-first-trade-l1", "if-first-trade-l2", "if-first-trade-l3"],
    xpTotal: 220,
  },
];

// ── Track ─────────────────────────────────────────────────────────────────────

export const track: Track = {
  id: "investing-fundamentals",
  title: "Investing Fundamentals",
  description: "Everything you need to start investing intelligently — stocks, markets, charts, and your first real trade.",
  icon: "📈",
  difficulty: "beginner",
  colorClass: "emerald",
  courseIds: ["if-stocks-101", "if-charts", "if-first-trade"],
};
