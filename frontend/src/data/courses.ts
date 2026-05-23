// ─────────────────────────────────────────────────────────────────────────────
// BMG Capital Learning Center — Course Data
// Standalone course format with rich LessonBlock content (distinct from the
// full curriculum system in /data/curriculum which uses raw HTML bodies).
// ─────────────────────────────────────────────────────────────────────────────

export interface Quiz {
  id: string;
  question: string;
  options: string[];
  correct: number; // 0-indexed
  explanation: string;
}

export type LessonBlock =
  | { type: "text"; content: string }
  | { type: "heading"; content: string }
  | { type: "callout"; variant: "info" | "tip" | "warning" | "example"; content: string }
  | { type: "chart"; symbol: string; description: string }
  | { type: "list"; items: string[] }
  | { type: "keyterm"; term: string; definition: string };

export interface Lesson {
  id: string;
  courseId: string;
  order: number;
  title: string;
  subtitle: string;
  emoji: string;
  xpReward: number;
  readingTimeMin: number;
  content: LessonBlock[];
  quiz: Quiz[];
}

export interface Course {
  id: string;
  title: string;
  subtitle: string;
  emoji: string;
  color: string; // Tailwind gradient-from color class stem
  totalXP: number;
  estimatedHours: number;
  lessons: Lesson[];
  badge: {
    id: string;
    name: string;
    emoji: string;
    description: string;
  };
}

export interface ComingSoonCourse {
  id: string;
  title: string;
  subtitle: string;
  emoji: string;
  color: string;
  description: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// INVESTING FUNDAMENTALS COURSE
// ─────────────────────────────────────────────────────────────────────────────

const LESSON_1: Lesson = {
  id: "if-cs-l1",
  courseId: "investing-fundamentals",
  order: 1,
  title: "What is a Stock?",
  subtitle: "Ownership, value, and why companies go public",
  emoji: "📈",
  xpReward: 100,
  readingTimeMin: 5,
  content: [
    {
      type: "text",
      content:
        "When you buy a share of stock, you are purchasing a small piece of ownership in a real business. That business has employees, customers, assets, and liabilities — and as a shareholder, you own a proportional slice of all of it. If the company grows and becomes more valuable, the price of your slice goes up. If it struggles, your slice loses value. It's that direct.",
    },
    {
      type: "heading",
      content: "Why Companies Sell Stock: The IPO Process",
    },
    {
      type: "text",
      content:
        "Every public company was once private — owned by its founders, early employees, and venture capital investors. At some point, the founders decide they want to raise more capital to grow, or early investors want to cash out. The solution: sell shares to the general public through an Initial Public Offering (IPO). Investment banks underwrite the deal, set an initial price, and sell shares to large institutions. Once the company lists on an exchange like the NYSE or NASDAQ, anyone can buy and sell those shares.",
    },
    {
      type: "callout",
      variant: "example",
      content:
        "When Apple went public in December 1980, shares were priced at $22. After multiple stock splits, those original shares are worth thousands of times that amount today. An investor who bought $1,000 worth of Apple at the IPO would hold tens of millions of dollars worth of stock by 2024.",
    },
    {
      type: "heading",
      content: "Market Capitalization: The Market's Valuation of a Company",
    },
    {
      type: "text",
      content:
        "Market capitalization (market cap) is the total market value of all a company's outstanding shares. The formula is simple: share price multiplied by total shares outstanding. This number tells you what the entire market collectively believes the company is worth at any given moment.",
    },
    {
      type: "callout",
      variant: "info",
      content:
        "If Apple has 15.4 billion shares outstanding and the stock trades at $178, its market cap is 15.4B × $178 = approximately $2.74 trillion — making it one of the most valuable companies in the history of the world.",
    },
    {
      type: "chart",
      symbol: "AAPL",
      description: "Apple Inc. — one of the most-traded stocks in the world",
    },
    {
      type: "heading",
      content: "How Stock Prices Are Determined",
    },
    {
      type: "text",
      content:
        "Stock prices are set by supply and demand — but the underlying driver of that supply and demand is earnings expectations. If investors believe a company will earn more money in the future than they currently expect, they buy shares, driving the price up. If they downgrade their expectations — perhaps because of weak guidance, a competitor, or a macro shift — they sell shares, driving the price down. In the short run, emotions, news, and sentiment dominate. In the long run, actual earnings and cash flows win.",
    },
    {
      type: "list",
      items: [
        "Supply and demand: more buyers than sellers drives price up; more sellers than buyers drives it down",
        "Earnings expectations: company guidance, analyst estimates, and quarterly results move stocks",
        "Macro factors: interest rates, inflation, GDP growth, and geopolitical events affect all stocks broadly",
        "Sentiment: fear and greed cause short-term dislocations from fundamental value",
        "Insider buying/selling and institutional flows signal conviction from informed investors",
      ],
    },
    {
      type: "keyterm",
      term: "Market Capitalization",
      definition:
        "The total dollar market value of a company's outstanding shares, calculated as share price × shares outstanding. Companies are classified as micro-cap (<$300M), small-cap ($300M–$2B), mid-cap ($2B–$10B), large-cap ($10B–$200B), or mega-cap ($200B+).",
    },
    {
      type: "keyterm",
      term: "IPO (Initial Public Offering)",
      definition:
        "The process by which a private company offers shares to the public for the first time on a stock exchange. Investment banks underwrite the offering, setting the initial price and distributing shares to institutional investors before public trading begins.",
    },
    {
      type: "keyterm",
      term: "Float",
      definition:
        "The number of shares available for public trading — total shares outstanding minus shares held by insiders, institutions under lockup, or the company itself (treasury shares). Low-float stocks can be more volatile because small orders move the price more.",
    },
    {
      type: "keyterm",
      term: "Share Dilution",
      definition:
        "When a company issues new shares — for acquisitions, employee compensation, or fundraising — existing shareholders' ownership percentage shrinks. Dilution isn't always bad (if capital is deployed profitably), but it must be weighed against earnings growth.",
    },
  ],
  quiz: [
    {
      id: "if-cs-l1-q1",
      question: "What does owning one share of a public company entitle you to?",
      options: [
        "A guaranteed annual dividend payment",
        "Fractional ownership of the company and its assets",
        "A fixed interest payment like a bond",
        "The right to appoint a board member",
      ],
      correct: 1,
      explanation:
        "A share of stock represents fractional (partial) ownership in the company. You own a proportional slice of the business — its assets, future earnings, and voting rights. There is no guarantee of dividends.",
    },
    {
      id: "if-cs-l1-q2",
      question:
        "Apple has 15.4 billion shares outstanding. If the stock trades at $178, what is Apple's market cap?",
      options: ["$178 billion", "$2.74 trillion", "$15.4 billion", "$890 billion"],
      correct: 1,
      explanation:
        "Market cap = share price × shares outstanding = $178 × 15.4 billion = approximately $2.74 trillion. This represents the market's collective estimate of the company's total value.",
    },
    {
      id: "if-cs-l1-q3",
      question:
        "A company issues 10 million new shares to fund an acquisition. You own 1 million shares. What happens to your ownership percentage?",
      options: [
        "It stays the same — you still own 1 million shares",
        "It increases because the company is growing",
        "It decreases — this is called share dilution",
        "It is cancelled and replaced with new shares",
      ],
      correct: 2,
      explanation:
        "This is share dilution. If you owned 1M of 10M shares (10%), and the company issues 10M more shares, you now own 1M of 20M (5%). Your ownership percentage has been cut in half, even though you still hold the same number of shares.",
    },
  ],
};

const LESSON_2: Lesson = {
  id: "if-cs-l2",
  courseId: "investing-fundamentals",
  order: 2,
  title: "Reading a Stock Chart",
  subtitle: "Candlesticks, trends, and what the chart tells you",
  emoji: "🕯️",
  xpReward: 150,
  readingTimeMin: 7,
  content: [
    {
      type: "text",
      content:
        "A stock chart is a visual history of every trade that has occurred. It condenses millions of individual buy and sell decisions into a single image. Learning to read a chart doesn't mean predicting the future — it means understanding what has happened and what patterns tend to repeat, because markets are driven by human psychology which does not change.",
    },
    {
      type: "heading",
      content: "The Candlestick: One Period in Four Numbers",
    },
    {
      type: "text",
      content:
        "Each candlestick on a chart represents one complete time period — one minute, one hour, one day, one week. Within that period, four things are recorded: the price when trading opened (Open), the highest price reached (High), the lowest price reached (Low), and the price when trading closed (Close). These four values — OHLC — are all you need to reconstruct what happened in any period.",
    },
    {
      type: "callout",
      variant: "info",
      content:
        "Green candle: Close > Open — buyers won the period. The body spans from open to close, and the wicks show the high/low extremes. Red candle: Open > Close — sellers won the period. The larger the body, the more decisive the move. A very small body (called a doji) means neither side won — indecision.",
    },
    {
      type: "heading",
      content: "Support and Resistance: Where Price Remembers",
    },
    {
      type: "text",
      content:
        "Support is a price level where buying has historically been strong enough to stop or reverse a decline — a floor. Resistance is a price level where selling has historically been strong enough to stop or reverse a rally — a ceiling. These levels form because investors have memory: if a stock bounced at $150 twice before, traders are conditioned to buy there again. When price breaks through resistance, that level often becomes new support — a phenomenon called role reversal.",
    },
    {
      type: "heading",
      content: "Identifying Trends: Higher Highs and Higher Lows",
    },
    {
      type: "text",
      content:
        "A trend is simply the direction price is moving over time. An uptrend is characterized by a series of higher highs (each rally peak is above the previous one) and higher lows (each pullback stops higher than the previous one). A downtrend is the opposite: lower highs and lower lows. When a stock fails to make a new higher high, or breaks below a previous higher low, the uptrend may be ending.",
    },
    {
      type: "callout",
      variant: "tip",
      content:
        "The trend is your friend — until it ends. Most professional traders only take positions in the direction of the prevailing trend. Trading against a strong trend is the most common beginner mistake.",
    },
    {
      type: "heading",
      content: "Volume: The Conviction Behind the Move",
    },
    {
      type: "text",
      content:
        "Price tells you what happened. Volume tells you how much conviction was behind it. A stock rising 5% on 3× average volume is very different from rising 5% on half average volume. High volume on a breakout means institutions are participating — that move is more likely to sustain. Low-volume breakouts frequently fail. Always check volume before acting on a price signal.",
    },
    {
      type: "chart",
      symbol: "SPY",
      description: "S&P 500 ETF — the benchmark for US large-cap stocks",
    },
    {
      type: "heading",
      content: "Moving Averages: Dynamic Support",
    },
    {
      type: "text",
      content:
        "A moving average (MA) plots the average closing price over a specified number of periods, creating a smoothed line that filters out day-to-day noise. The 50-day and 200-day moving averages are watched by virtually every professional market participant. In a healthy uptrend, price tends to stay above its 50-day MA and pullbacks to that level are often buying opportunities. The 200-day MA is the longer-term trend indicator — stocks trading above it are in a long-term uptrend.",
    },
    {
      type: "callout",
      variant: "example",
      content:
        "The 'Death Cross' occurs when the 50-day MA crosses below the 200-day MA — a bearish signal. The 'Golden Cross' is the opposite (50-day crossing above 200-day) — historically bullish. These signals are lagging indicators (they confirm trends rather than predict them) but are widely watched and self-fulfilling.",
    },
    {
      type: "keyterm",
      term: "Candlestick",
      definition:
        "A chart element showing the open, high, low, and close prices for a given period. The body (open to close) is filled green if price rose and red if it fell. The wicks show the high and low extremes.",
    },
    {
      type: "keyterm",
      term: "Support Level",
      definition:
        "A price zone where historical buying demand has been strong enough to halt a declining price. The more times price has bounced at a level, the stronger the support.",
    },
  ],
  quiz: [
    {
      id: "if-cs-l2-q1",
      question:
        "A candlestick has an open of $100, high of $108, low of $97, and close of $103. What color is the candle and why?",
      options: [
        "Red — the high was higher than the open",
        "Green — the close is higher than the open",
        "Red — the low was below the open",
        "Neither — the wicks are too long to determine color",
      ],
      correct: 1,
      explanation:
        "Candle color is determined solely by comparing open and close. Close ($103) > Open ($100) = green candle. The wicks (high $108, low $97) show the range but don't affect color.",
    },
    {
      id: "if-cs-l2-q2",
      question:
        "A stock breaks above a key resistance level on 3× average daily volume. This is most likely:",
      options: [
        "A false breakout that will reverse quickly",
        "A valid breakout with institutional participation likely to sustain",
        "A sign that the stock is overbought and will decline",
        "Irrelevant — volume doesn't affect breakout validity",
      ],
      correct: 1,
      explanation:
        "High-volume breakouts are far more reliable than low-volume ones. When volume is 3× average, large institutions are clearly buying — they can't buy without moving the market. This conviction makes the move more likely to continue.",
    },
    {
      id: "if-cs-l2-q3",
      question: "An uptrend is defined by which price structure?",
      options: [
        "Price above its 200-day moving average",
        "More green candles than red candles",
        "A series of higher highs and higher lows",
        "Volume increasing steadily over time",
      ],
      correct: 2,
      explanation:
        "An uptrend is technically defined as a series of higher highs (each rally peak exceeds the prior one) and higher lows (each pullback stops above the prior pullback low). This structure confirms that buyers are progressively more aggressive.",
    },
  ],
};

const LESSON_3: Lesson = {
  id: "if-cs-l3",
  courseId: "investing-fundamentals",
  order: 3,
  title: "Building Your First Portfolio",
  subtitle: "Diversification, risk, and long-term thinking",
  emoji: "🏗️",
  xpReward: 200,
  readingTimeMin: 8,
  content: [
    {
      type: "text",
      content:
        "Building a portfolio isn't about picking the single best stock. It's about constructing a collection of investments that work together to meet your goals with the right amount of risk. The best portfolios are built intentionally — with clear rules, understood risk, and a time horizon matched to reality.",
    },
    {
      type: "heading",
      content: "Diversification: Why It Matters More Than You Think",
    },
    {
      type: "text",
      content:
        "Diversification is the practice of spreading investments across different assets so that no single failure can destroy your portfolio. The mathematical basis: assets that are not perfectly correlated — meaning they don't move together lockstep — reduce the overall volatility of a portfolio without necessarily reducing expected returns. Harry Markowitz won the Nobel Prize for proving this in 1952.",
    },
    {
      type: "callout",
      variant: "warning",
      content:
        "A portfolio of 20 tech stocks is NOT diversified, even though it has 20 positions. If interest rates rise or tech regulation tightens, all 20 positions will fall together. True diversification requires exposure to different sectors, asset classes, and geographies.",
    },
    {
      type: "heading",
      content: "Asset Classes: The Building Blocks",
    },
    {
      type: "list",
      items: [
        "Stocks (Equities): Ownership in companies. Highest long-term return potential, highest short-term volatility. Best suited for longer time horizons (5+ years).",
        "Bonds (Fixed Income): Loans to governments or corporations. Lower returns than stocks, lower volatility. Provides portfolio stability and income through interest payments.",
        "ETFs (Exchange-Traded Funds): Baskets of securities trading on exchanges. SPY holds the 500 largest US companies. QQQ holds the Nasdaq 100. One purchase = instant diversification.",
        "Real Estate (REITs): Real estate investment trusts own properties and pay dividends. Low correlation to stocks, inflation hedge, provides income.",
        "Commodities: Gold, oil, agricultural products. Strong inflation hedge. Gold specifically tends to rise when stocks fall — useful for portfolio stability.",
        "Crypto: High-volatility digital assets. High return potential, extreme risk. Small allocation (1–5% of portfolio) is common for risk-tolerant investors.",
      ],
    },
    {
      type: "heading",
      content: "The 60/40 Portfolio: A Classic Starting Point",
    },
    {
      type: "text",
      content:
        "The 60/40 portfolio — 60% stocks, 40% bonds — has been the default 'balanced' allocation for decades. The logic: stocks provide growth, bonds provide stability and income. When stocks fall sharply, bonds often rise (or fall less), cushioning the portfolio. Over the past 50 years, a 60/40 portfolio returned approximately 9% annually with much lower volatility than 100% stocks. However, in 2022, both stocks and bonds fell simultaneously — a reminder that no allocation is immune to all environments.",
    },
    {
      type: "chart",
      symbol: "QQQ",
      description: "Nasdaq 100 ETF — heavy tech exposure, higher growth potential",
    },
    {
      type: "heading",
      content: "Dollar-Cost Averaging: Remove Emotion from Investing",
    },
    {
      type: "text",
      content:
        "Dollar-cost averaging (DCA) means investing a fixed dollar amount at regular intervals — say $500 every month — regardless of what the market is doing. When prices are high, your $500 buys fewer shares. When prices are low, it buys more. Over time, you automatically buy more at lower prices and less at higher prices, resulting in a lower average cost than if you tried to time the market. DCA also removes the psychological burden of deciding 'is now a good time to invest?'",
    },
    {
      type: "callout",
      variant: "example",
      content:
        "An investor who put $500/month into SPY (S&P 500 ETF) starting in January 2010 would have invested $84,000 by 2024 and watched it grow to over $300,000 — a nearly 4× return — without ever trying to time the market, predict recessions, or pick individual stocks.",
    },
    {
      type: "heading",
      content: "Expense Ratios: The Hidden Cost That Compounds Against You",
    },
    {
      type: "text",
      content:
        "An expense ratio is the annual fee a fund charges as a percentage of your assets. A 1% expense ratio on $100,000 costs $1,000/year. Sounds small — but over 30 years, that 1% difference relative to a 0.03% ETF (like Vanguard's VOO) can cost you hundreds of thousands of dollars in lost compounding. Always check expense ratios before investing in any fund. Most index ETFs now charge 0.03%–0.20%. Actively managed funds charging 1%+ must outperform the market by that amount just to break even — most don't.",
    },
    {
      type: "heading",
      content: "Time Horizon and Risk Tolerance: Match Your Portfolio to Your Life",
    },
    {
      type: "text",
      content:
        "Your time horizon — when you need the money — is the single most important factor in determining how much risk you can take. If you need the money in 2 years, a 30% market drawdown is a crisis. If you need it in 30 years, that same drawdown is a buying opportunity. Risk tolerance is partly mathematical (what loss percentage can you financially handle?) and partly psychological (what loss will make you panic-sell at the bottom?).",
    },
    {
      type: "keyterm",
      term: "Diversification",
      definition:
        "Spreading investments across assets with low correlation to each other, reducing overall portfolio risk without necessarily sacrificing returns. True diversification spans sectors, asset classes, geographies, and market caps.",
    },
    {
      type: "keyterm",
      term: "Expense Ratio",
      definition:
        "The annual fee charged by a fund, expressed as a percentage of assets under management. A 0.03% expense ratio on $100,000 = $30/year. A 1% ratio = $1,000/year. Over decades, high expense ratios dramatically reduce compounded returns.",
    },
    {
      type: "keyterm",
      term: "Dollar-Cost Averaging (DCA)",
      definition:
        "Investing a fixed dollar amount at regular intervals, regardless of price. Results in automatically buying more shares when prices are low and fewer when prices are high, reducing the impact of timing decisions and emotional decision-making.",
    },
  ],
  quiz: [
    {
      id: "if-cs-l3-q1",
      question:
        "You hold 20 different technology stocks. A new regulation crushing the tech sector is announced. What happens to your portfolio?",
      options: [
        "You are well protected because you have 20 positions",
        "Roughly all 20 positions decline together because they share the same risk factor",
        "Half your positions decline and half rise, balancing out",
        "Your bonds automatically offset the tech losses",
      ],
      correct: 1,
      explanation:
        "20 tech stocks are highly correlated — they share the same sector risk. A regulatory shock, interest rate change, or earnings cycle downturn will hit all of them simultaneously. This is why true diversification requires exposure to different sectors and asset classes, not just more names in the same sector.",
    },
    {
      id: "if-cs-l3-q2",
      question: "What is the primary advantage of dollar-cost averaging?",
      options: [
        "It guarantees higher returns than lump-sum investing",
        "It eliminates market timing decisions and automatically buys more shares when prices are low",
        "It only works with index funds, not individual stocks",
        "It reduces your tax liability on investment gains",
      ],
      correct: 1,
      explanation:
        "DCA removes the timing decision ('is now a good time?') and mechanically results in buying more shares when prices are lower. Lump-sum investing statistically outperforms DCA in rising markets, but DCA dramatically reduces the psychological burden and timing risk.",
    },
    {
      id: "if-cs-l3-q3",
      question:
        "Two funds both track the S&P 500. Fund A has an expense ratio of 0.03%. Fund B has an expense ratio of 1.0%. Over 30 years with equal returns before fees, which is better and why?",
      options: [
        "They are equivalent — the 0.97% difference is negligible",
        "Fund B — higher fees indicate better management quality",
        "Fund A — lower expenses mean more of your return compounds over time",
        "It depends entirely on which fund has better performance in Year 1",
      ],
      correct: 2,
      explanation:
        "The 0.97% annual fee difference compounds dramatically over time. On a $100,000 investment over 30 years at 8% gross return, Fund A grows to ~$1,006,000 while Fund B grows to only ~$761,000 — a $245,000 difference from fees alone. Lower costs always win in equivalent funds.",
    },
  ],
};

export const INVESTING_FUNDAMENTALS_COURSE: Course = {
  id: "investing-fundamentals",
  title: "Investing Fundamentals",
  subtitle: "Master the core principles that every investor needs",
  emoji: "📈",
  color: "emerald",
  totalXP: 450,
  estimatedHours: 0.5,
  lessons: [LESSON_1, LESSON_2, LESSON_3],
  badge: {
    id: "investing-fundamentals-graduate",
    name: "Market Fundamentalist",
    emoji: "🎓",
    description: "Completed the Investing Fundamentals course",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// COMING SOON COURSES
// ─────────────────────────────────────────────────────────────────────────────

export const COMING_SOON_COURSES: ComingSoonCourse[] = [
  {
    id: "technical-analysis-mastery",
    title: "Technical Analysis Mastery",
    subtitle: "Advanced chart patterns and indicators",
    emoji: "📊",
    color: "blue",
    description:
      "Go deep on chart patterns, RSI, MACD, Bollinger Bands, and the indicators that professional traders actually use to time entries and exits.",
  },
  {
    id: "options-101",
    title: "Options 101",
    subtitle: "Leverage, hedging, and income strategies",
    emoji: "🎯",
    color: "amber",
    description:
      "Learn calls, puts, spreads, and covered calls. Understand how options give you asymmetric payoffs and how to use them to generate income or protect positions.",
  },
  {
    id: "crypto-fundamentals",
    title: "Crypto Fundamentals",
    subtitle: "Blockchain, DeFi, and digital assets",
    emoji: "₿",
    color: "orange",
    description:
      "Understand blockchain technology, how Bitcoin and Ethereum work, the risks and opportunities of DeFi, and how to size a crypto position responsibly.",
  },
  {
    id: "value-investing",
    title: "Value Investing",
    subtitle: "Find great businesses at fair prices",
    emoji: "🔍",
    color: "violet",
    description:
      "Learn to read financial statements, calculate intrinsic value, and apply the principles of Warren Buffett and Charlie Munger to find undervalued companies.",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// ALL COURSES (for lookup)
// ─────────────────────────────────────────────────────────────────────────────

export const COURSES: Course[] = [INVESTING_FUNDAMENTALS_COURSE];

export const COURSE_MAP: Record<string, Course> = Object.fromEntries(
  COURSES.map((c) => [c.id, c])
);

export const LESSON_MAP: Record<string, Lesson> = Object.fromEntries(
  COURSES.flatMap((c) => c.lessons).map((l) => [l.id, l])
);
