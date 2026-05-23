import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  {
    id: "macro-intro-l1",
    courseId: "macro-intro",
    trackId: "macro",
    title: "How the Fed Moves Markets",
    type: "article",
    xp: 70,
    durationMin: 11,
    tags: ["federal-reserve", "interest-rates", "inflation", "monetary-policy"],
    body: `
<h2>The Most Powerful Market Mover</h2>
<p>The Federal Reserve controls the federal funds rate — the interest rate banks charge each other for overnight loans. This single number cascades through every corner of the global economy: mortgage rates, business borrowing costs, bond yields, and ultimately stock valuations.</p>

<div class="lesson-callout info">
  <strong>The mechanism:</strong>
  <ol>
    <li>Fed raises rates → borrowing becomes more expensive for businesses and consumers</li>
    <li>Economic activity slows → corporate earnings growth slows</li>
    <li>Higher risk-free rate → investors demand higher returns from stocks → multiples compress</li>
    <li>End result: higher rates = headwind for stock valuations, especially for high-growth/tech stocks</li>
  </ol>
  The reverse is also true: rate cuts are rocket fuel for equities.
</div>

<h2>Why the 2022 Bear Market Was Predictable</h2>
<p>In 2021, inflation hit 40-year highs. The Fed was forced to raise rates from 0% to 5.25% in 18 months — the fastest tightening cycle in modern history. Growth stocks, which had been valued at 40–80× earnings on the assumption of near-zero rates forever, were repriced violently. The Nasdaq fell 33%.</p>
<p>Understanding the relationship between rates and equity valuations would have told an informed investor: "when rates rise sharply, reduce growth exposure."</p>

<h2>Key Fed Calendar Events Every Investor Tracks</h2>
<ul>
  <li><strong>FOMC meetings (8/year):</strong> The Fed's policy committee meets to vote on rate changes. Market-moving.</li>
  <li><strong>Fed Chair press conference:</strong> After every meeting. The language and tone matter as much as the decision.</li>
  <li><strong>CPI report (monthly):</strong> Consumer Price Index — measures inflation. Drives rate expectations.</li>
  <li><strong>Jobs report (monthly, first Friday):</strong> Employment data. Strong jobs = inflationary pressure = hawkish Fed.</li>
</ul>
    `,
    quiz: [
      {
        id: "macro-intro-l1-q1",
        question: "When the Federal Reserve raises interest rates, the typical effect on high-growth tech stocks is:",
        options: [
          "Stock prices rise because higher rates signal economic strength",
          "Stock prices fall because future earnings are worth less when discounted at higher rates",
          "No effect — stock prices only reflect corporate earnings",
          "Stock prices rise because bonds become less attractive",
        ],
        answer: 1,
        explanation: "Higher rates increase the discount rate used to value future cash flows — reducing the present value of long-duration assets like growth stocks. This is why growth stocks are most sensitive to interest rate changes.",
      },
      {
        id: "macro-intro-l1-q2",
        question: "The CPI report matters to investors because:",
        options: [
          "It directly sets the federal funds rate",
          "Inflation data drives Fed rate expectations, which affect stock and bond valuations",
          "It predicts next quarter's corporate earnings",
          "It measures consumer confidence",
        ],
        answer: 1,
        explanation: "CPI (inflation data) determines whether the Fed will raise, hold, or cut rates. Hotter-than-expected inflation → more rate hikes likely → market sells off. Cooler inflation → rate cuts possible → markets rally.",
      },
      {
        id: "macro-intro-l1-q3",
        question: "FOMC meetings occur how many times per year?",
        options: ["4", "6", "8", "12"],
        answer: 2,
        explanation: "The Federal Open Market Committee meets 8 times per year. These are major market events — traders watch not just the rate decision but the accompanying statement and Chair's press conference for signals about future policy.",
      },
    ],
  },
  {
    id: "macro-intro-l2",
    courseId: "macro-intro",
    trackId: "macro",
    title: "The Business Cycle and Asset Allocation",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["business-cycle", "recession", "asset-allocation", "gdp", "yield-curve"],
    body: `
<h2>The Economy Moves in Cycles</h2>
<p>The economy doesn't grow in a straight line. It expands and contracts in roughly predictable cycles: expansion → peak → recession → trough → recovery → expansion again. Knowing where you are in the cycle helps you position your portfolio for what's likely coming next.</p>

<div class="lesson-callout info">
  <strong>The four cycle phases and their typical winners:</strong>
  <table class="lesson-table">
    <tr><th>Phase</th><th>Characteristics</th><th>Asset class winners</th></tr>
    <tr><td>Early expansion</td><td>Recovery begins, rates low, credit eases</td><td>Small caps, cyclicals, real estate</td></tr>
    <tr><td>Mid expansion</td><td>Strong growth, moderate inflation</td><td>Broad equities, industrials, materials</td></tr>
    <tr><td>Late cycle</td><td>Growth slowing, inflation rising, rates rising</td><td>Energy, commodities, defensives</td></tr>
    <tr><td>Recession</td><td>GDP contraction, earnings falling, credit tight</td><td>Treasuries, cash, consumer staples, gold</td></tr>
  </table>
</div>

<h2>The Yield Curve as a Recession Predictor</h2>
<p>The <strong>yield curve</strong> shows the interest rates on US Treasuries across different maturities. Normally, long-term bonds yield more than short-term (upward sloping). An <strong>inverted yield curve</strong> — when short-term rates exceed long-term — has preceded every US recession since 1955 with a 12–24 month lead time.</p>

<div class="lesson-callout warning">
  <strong>Practical note:</strong> The yield curve inverts, then unverts (normalizes), and the recession typically starts <em>after</em> it normalizes — not while it's inverted. The 2022–2023 inversion normalized in 2024, and recession risk elevated accordingly.
</div>
    `,
    quiz: [
      {
        id: "macro-intro-l2-q1",
        question: "In the 'late cycle' phase (growth slowing, inflation rising), which assets typically outperform?",
        options: [
          "High-growth tech stocks",
          "Energy, commodities, and defensive equities",
          "Small-cap growth stocks",
          "Corporate bonds",
        ],
        answer: 1,
        explanation: "Late cycle favors real assets (energy, commodities) that benefit from inflation, and defensive equities that maintain earnings even as economic growth slows.",
      },
      {
        id: "macro-intro-l2-q2",
        question: "An inverted yield curve (short-term rates > long-term rates) is historically significant because:",
        options: [
          "It guarantees an immediate stock market crash",
          "It has preceded every US recession since 1955, typically with a 12–24 month lead",
          "It means the Fed is cutting rates",
          "It indicates high inflation",
        ],
        answer: 1,
        explanation: "Yield curve inversion has been the most reliable recession predictor historically. Banks borrow short-term and lend long-term — inversion compresses their margins and tightens credit, slowing the economy.",
      },
      {
        id: "macro-intro-l2-q3",
        question: "During an early expansion phase, which assets typically have the strongest tailwinds?",
        options: [
          "Long-term Treasury bonds",
          "Gold and cash",
          "Small caps and cyclical sectors",
          "Defensive stocks like utilities",
        ],
        answer: 2,
        explanation: "Early expansion: rates are low (Fed just finished cutting), credit is easing, and economic momentum is building. Small caps and cyclicals (consumer discretionary, industrials) see the biggest earnings recovery.",
      },
    ],
  },
];

export const courses: Course[] = [
  {
    id: "macro-intro",
    trackId: "macro",
    title: "Macro Economics for Investors",
    description: "The Fed, interest rates, the business cycle, and how global economics drive asset prices.",
    lessonIds: ["macro-intro-l1", "macro-intro-l2"],
    xpTotal: 140,
  },
];

export const track: Track = {
  id: "macro",
  title: "Macro & Economics",
  description: "How the Federal Reserve, interest rates, inflation, and the business cycle drive every asset class. Essential context for any investor.",
  icon: "🌐",
  difficulty: "intermediate",
  colorClass: "cyan",
  courseIds: ["macro-intro"],
};
