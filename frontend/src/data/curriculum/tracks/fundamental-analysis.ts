import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  // ── Course 1: Reading Financial Statements ──────────────────────────────
  {
    id: "fa-financials-l1",
    courseId: "fa-financials",
    trackId: "fundamental-analysis",
    title: "The Income Statement Decoded",
    type: "article",
    xp: 60,
    durationMin: 10,
    tags: ["income-statement", "revenue", "earnings", "margins"],
    body: `
<h2>The Story of a Dollar</h2>
<p>The income statement (also called the P&L — Profit and Loss) tracks one thing: <em>what happened to every dollar the company earned</em>. Starting from the top line (revenue) and working down through costs, taxes, and interest, it ends at the bottom line (net income). Every line in between is a different story about where money went.</p>

<div class="lesson-callout info">
  <strong>Top 5 lines every investor must know:</strong>
  <ol>
    <li><strong>Revenue (top line):</strong> Total money from products/services sold. Raw. No deductions yet.</li>
    <li><strong>Gross Profit:</strong> Revenue minus Cost of Goods Sold (COGS). Measures how profitable the core business is before overhead.</li>
    <li><strong>Operating Income (EBIT):</strong> Gross profit minus operating expenses (R&D, sales, admin). The profit from the actual business.</li>
    <li><strong>Net Income (bottom line):</strong> After interest and taxes. What shareholders technically "own."</li>
    <li><strong>EPS (Earnings Per Share):</strong> Net income divided by shares outstanding. The number every Wall Street estimate is based on.</li>
  </ol>
</div>

<h2>Why Margins Matter More Than Absolute Numbers</h2>
<p>Company A earns $100M in net income. Company B earns $10M. Company A is better, right? Not necessarily. If Company A has $5 billion in revenue, its net margin is 2%. If Company B has $40M in revenue, its net margin is 25%. Company B is far more efficient at turning sales into profit.</p>

<div class="lesson-callout success">
  <strong>The three margin metrics:</strong>
  <ul>
    <li><strong>Gross margin</strong> = Gross profit / Revenue → How efficient is production?</li>
    <li><strong>Operating margin</strong> = Operating income / Revenue → How efficiently does the whole business run?</li>
    <li><strong>Net margin</strong> = Net income / Revenue → After everything, how much profit per dollar of sales?</li>
  </ul>
</div>

<h2>Revenue Growth Rate: The Number Analysts Watch First</h2>
<p>Before anything else, analysts ask: is revenue growing? A shrinking top line almost always eventually shows up in the bottom line. Year-over-year (YoY) revenue growth above 15–20% typically commands a premium valuation multiple. Below 5% in a growing market is a red flag worth investigating.</p>

<h2>One-Time Items: The Art of Stripping Noise</h2>
<p>Net income can be distorted by one-time events — asset sales, restructuring charges, legal settlements. That's why analysts focus on <strong>adjusted EPS</strong>, which strips out non-recurring items to show the underlying earnings power of the business.</p>
    `,
    quiz: [
      {
        id: "fa-financials-l1-q1",
        question: "Gross profit equals:",
        options: ["Net income plus taxes", "Revenue minus Cost of Goods Sold", "Revenue minus all expenses", "Operating income minus interest"],
        answer: 1,
        explanation: "Gross Profit = Revenue - COGS. It measures core product/service profitability before accounting for overhead like R&D, marketing, and admin.",
      },
      {
        id: "fa-financials-l1-q2",
        question: "Company A has 2% net margin on $5B revenue. Company B has 25% net margin on $40M revenue. Which is more profitable on a per-dollar-of-sales basis?",
        options: ["Company A, because it earns more absolute dollars", "Company B, because it retains more of each dollar it earns", "They're identical", "Can't determine without knowing share count"],
        answer: 1,
        explanation: "Net margin measures efficiency, not absolute size. 25% vs 2% means Company B keeps $0.25 of every dollar vs Company A's $0.02 — far more efficient.",
      },
      {
        id: "fa-financials-l1-q3",
        question: "Why do analysts focus on 'adjusted EPS' rather than reported net income?",
        options: [
          "Adjusted EPS is always higher and looks better",
          "To strip out one-time items and see the underlying earnings power",
          "SEC requires it for all public companies",
          "It includes stock-based compensation",
        ],
        answer: 1,
        explanation: "Adjusted EPS removes one-time items (asset sales, restructuring, legal settlements) to reveal the recurring, sustainable earnings power of the business.",
      },
    ],
  },

  {
    id: "fa-financials-l2",
    courseId: "fa-financials",
    trackId: "fundamental-analysis",
    title: "The Balance Sheet Essentials",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["balance-sheet", "assets", "liabilities", "equity", "debt"],
    body: `
<h2>A Snapshot in Time</h2>
<p>If the income statement is a movie (showing what happened over a period), the balance sheet is a photograph — it shows exactly what a company owns, owes, and is worth at a single moment in time. That moment is typically the last day of the quarter or fiscal year.</p>

<div class="lesson-callout info">
  <strong>The Accounting Equation (always true, no exceptions):</strong><br/>
  <code>Assets = Liabilities + Shareholders' Equity</code><br/>
  Everything a company has (assets) was either borrowed (liabilities) or built with owners' money (equity).
</div>

<h2>Assets: What the Company Owns</h2>
<ul>
  <li><strong>Current assets:</strong> Cash, accounts receivable, inventory — expected to convert to cash within a year</li>
  <li><strong>Non-current assets:</strong> Property, equipment, patents, goodwill — long-term productive assets</li>
</ul>
<p>Cash and cash equivalents deserves special attention. A company sitting on $50B in cash (Apple had over $160B at its peak) has enormous financial flexibility and downside protection.</p>

<h2>Liabilities: What the Company Owes</h2>
<ul>
  <li><strong>Current liabilities:</strong> Accounts payable, short-term debt — due within a year</li>
  <li><strong>Long-term liabilities:</strong> Bonds, long-term loans — due beyond a year</li>
</ul>
<p>Long-term debt is normal and often productive. But <strong>debt-to-equity ratio</strong> above 2–3× in a cyclical industry is a yellow flag — if revenue drops sharply, can the company still service its debt?</p>

<h2>Key Ratios From the Balance Sheet</h2>
<table class="lesson-table">
  <tr><th>Ratio</th><th>Formula</th><th>What it tells you</th></tr>
  <tr><td>Current Ratio</td><td>Current Assets / Current Liabilities</td><td>Can it pay near-term bills? (&gt;1.5 = comfortable)</td></tr>
  <tr><td>Debt-to-Equity</td><td>Total Debt / Total Equity</td><td>How leveraged is the company? (&gt;2 = scrutinize)</td></tr>
  <tr><td>Book Value per Share</td><td>Shareholder Equity / Shares Outstanding</td><td>Net asset value per share</td></tr>
</table>
    `,
    quiz: [
      {
        id: "fa-financials-l2-q1",
        question: "The accounting equation states that:",
        options: [
          "Assets = Revenue - Expenses",
          "Assets = Liabilities + Shareholders' Equity",
          "Net Income = Revenue - All Costs",
          "Cash Flow = Net Income + Depreciation",
        ],
        answer: 1,
        explanation: "The fundamental accounting identity: Assets = Liabilities + Shareholders' Equity. Everything a company has was either borrowed or built with owners' capital.",
      },
      {
        id: "fa-financials-l2-q2",
        question: "A current ratio of 0.7 means:",
        options: [
          "The company has strong short-term liquidity",
          "The company has more current liabilities than current assets — potential liquidity concern",
          "The company's stock is undervalued",
          "Debt-to-equity is at a healthy level",
        ],
        answer: 1,
        explanation: "Current ratio < 1.0 means current liabilities exceed current assets. The company may struggle to pay near-term obligations without raising cash.",
      },
      {
        id: "fa-financials-l2-q3",
        question: "Goodwill appears on the balance sheet when:",
        options: [
          "The company has high customer satisfaction",
          "A company acquires another for more than its book value",
          "The company's stock trades above book value",
          "The company has significant intellectual property",
        ],
        answer: 1,
        explanation: "Goodwill is the premium paid above book value in an acquisition. It represents the value of brand, customer relationships, and other intangibles.",
      },
    ],
  },

  {
    id: "fa-financials-l3",
    courseId: "fa-financials",
    trackId: "fundamental-analysis",
    title: "Cash Flow Is King",
    type: "article",
    xp: 70,
    durationMin: 12,
    tags: ["cash-flow", "free-cash-flow", "capex", "operating-cash-flow"],
    body: `
<h2>Why Cash Flow Beats Net Income</h2>
<p>Net income can be manipulated — legally. Aggressive revenue recognition, generous depreciation assumptions, and one-time gains can all make earnings look better than the underlying business reality. Cash flow cannot be faked as easily. Either cash came in the door, or it didn't.</p>
<p>Warren Buffett has said for decades: <em>"In the short term, earnings can be massaged. In the long term, cash flow is what matters."</em></p>

<div class="lesson-callout info">
  <strong>Three sections of the cash flow statement:</strong>
  <ol>
    <li><strong>Operating Cash Flow (OCF):</strong> Cash generated from the actual business (collecting from customers, paying suppliers, employees). The most important number.</li>
    <li><strong>Investing Cash Flow:</strong> Cash spent on capital expenditures (buildings, equipment), acquisitions, or received from asset sales.</li>
    <li><strong>Financing Cash Flow:</strong> Cash from issuing debt/equity, or used to repay debt, buy back stock, or pay dividends.</li>
  </ol>
</div>

<h2>Free Cash Flow: The Holy Grail</h2>
<p><strong>Free Cash Flow (FCF) = Operating Cash Flow − Capital Expenditures</strong></p>
<p>FCF is the cash left over after a company has paid for everything needed to maintain and grow the business. This is the cash that can be returned to shareholders (buybacks, dividends), used for acquisitions, or reinvested. High FCF generation is one of the most reliable indicators of a quality business.</p>

<div class="lesson-callout success">
  <strong>FCF yield = FCF / Market Capitalization</strong><br/>
  An FCF yield above 4–5% often signals an undervalued stock. Below 1% on a non-growth stock suggests the market has priced in a lot of optimism.
</div>

<h2>Red Flags in Cash Flow</h2>
<ul>
  <li><strong>Net income significantly higher than OCF for multiple quarters:</strong> Something's not converting to cash — investigate accounts receivable growth.</li>
  <li><strong>Heavy capex relative to OCF:</strong> The company may be on a treadmill — spending heavily just to maintain the business (low "maintenance capex" businesses are more attractive).</li>
  <li><strong>Financing cash flow consistently positive:</strong> The company keeps issuing debt or stock to fund operations — not self-funding.</li>
</ul>
    `,
    quiz: [
      {
        id: "fa-financials-l3-q1",
        question: "Free Cash Flow is calculated as:",
        options: [
          "Net Income + Depreciation",
          "Operating Cash Flow − Capital Expenditures",
          "Revenue − All Cash Expenses",
          "EBITDA − Taxes",
        ],
        answer: 1,
        explanation: "FCF = Operating Cash Flow - CapEx. It represents the cash truly available to shareholders after maintaining and growing the business.",
      },
      {
        id: "fa-financials-l3-q2",
        question: "If a company's net income is consistently much higher than its operating cash flow over several quarters, this is:",
        options: [
          "A sign of excellent accounting quality",
          "A potential red flag — earnings may not be converting to real cash",
          "Normal for high-growth companies",
          "Proof the company is undervalued",
        ],
        answer: 1,
        explanation: "Persistent divergence between net income and operating cash flow warrants investigation. It could indicate aggressive revenue recognition or growing receivables that haven't been collected.",
      },
      {
        id: "fa-financials-l3-q3",
        question: "An FCF yield of 6% compared to a stock trading at a P/E of 30 would suggest:",
        options: [
          "The stock is definitely overvalued",
          "The stock generates substantial cash relative to its market cap — potentially attractive vs. the earnings multiple alone",
          "The company is paying too much in dividends",
          "CapEx is too low",
        ],
        answer: 1,
        explanation: "A 6% FCF yield means you're getting $6 of free cash for every $100 invested — quite attractive. A high P/E but also high FCF yield can signal a quality business trading at a reasonable cash flow valuation.",
      },
    ],
  },

  // ── Course 2: Valuation Methods ─────────────────────────────────────────
  {
    id: "fa-valuation-l1",
    courseId: "fa-valuation",
    trackId: "fundamental-analysis",
    title: "P/E Ratio in Practice",
    type: "article",
    xp: 70,
    durationMin: 9,
    tags: ["pe-ratio", "valuation", "earnings-multiple", "growth"],
    body: `
<h2>The Price Tag on Earnings</h2>
<p>The <strong>Price-to-Earnings (P/E) ratio</strong> is the most-cited valuation metric in investing. It answers: how much are investors willing to pay for each dollar of annual earnings?</p>
<p><code>P/E = Stock Price / Earnings Per Share (EPS)</code></p>
<p>A P/E of 20 means investors are paying $20 for every $1 of annual earnings. The S&P 500's historical average P/E is roughly 15–17. In low-interest rate environments, it has expanded to 25–30+. During recessions, it can compress to 10–12.</p>

<div class="lesson-callout info">
  <strong>Trailing vs. Forward P/E:</strong>
  <ul>
    <li><strong>Trailing P/E (TTM):</strong> Uses the last 12 months of actual earnings. Backward-looking.</li>
    <li><strong>Forward P/E:</strong> Uses the next 12 months of analyst earnings estimates. More relevant — you're buying the future, not the past.</li>
  </ul>
</div>

<h2>P/E Is Meaningless Without Context</h2>
<p>A P/E of 30 is expensive for a utility company growing 2% annually. It's cheap for a software company growing 40% annually. P/E must always be compared against:</p>
<ol>
  <li><strong>The company's own history:</strong> Is it cheap or expensive vs. its 5-year average P/E?</li>
  <li><strong>Industry peers:</strong> The semiconductor sector commands different multiples than financials.</li>
  <li><strong>Growth rate (PEG):</strong> P/E ÷ EPS growth rate. A PEG below 1.0 is often considered undervalued.</li>
</ol>

<div class="lesson-callout warning">
  <strong>P/E breaks in these situations:</strong>
  <ul>
    <li>Negative earnings (you can't divide by a negative number meaningfully)</li>
    <li>Cyclical companies at peak earnings (artificially low P/E)</li>
    <li>Companies investing heavily for future growth (earnings are depressed by choice)</li>
  </ul>
  For these cases, use EV/EBITDA, P/S, or P/FCF instead.
</div>
    `,
    quiz: [
      {
        id: "fa-valuation-l1-q1",
        question: "A stock trading at $50 with EPS of $2.50 has a P/E ratio of:",
        options: ["20x", "25x", "47.5x", "12.5x"],
        answer: 0,
        explanation: "P/E = $50 / $2.50 = 20x. For every $20 of stock price, the company earns $1 annually.",
      },
      {
        id: "fa-valuation-l1-q2",
        question: "A P/E of 35x is most likely justified for a company that is:",
        options: [
          "A mature utility with 1% annual earnings growth",
          "A bank in a recession",
          "A software company growing earnings 40% annually",
          "A commodity producer at peak margins",
        ],
        answer: 2,
        explanation: "High-growth companies command premium P/E multiples because investors are paying for future earnings. A 35x P/E for a 40% grower may actually be cheap on a PEG basis.",
      },
      {
        id: "fa-valuation-l1-q3",
        question: "The PEG ratio adjusts P/E by dividing it by the company's:",
        options: ["Revenue growth rate", "EPS growth rate", "Book value growth", "Dividend growth rate"],
        answer: 1,
        explanation: "PEG = P/E ÷ EPS growth rate. It normalizes the P/E for growth. A PEG below 1.0 suggests the P/E may be cheap relative to the company's growth rate.",
      },
    ],
  },

  {
    id: "fa-valuation-l2",
    courseId: "fa-valuation",
    trackId: "fundamental-analysis",
    title: "EV/EBITDA & Comparable Company Analysis",
    type: "article",
    xp: 80,
    durationMin: 12,
    tags: ["ev-ebitda", "comparables", "enterprise-value", "comps"],
    body: `
<h2>Beyond P/E: Enterprise Value Multiples</h2>
<p><strong>Enterprise Value (EV)</strong> is the "true" cost to buy a business: market cap plus net debt (or minus net cash). It's what an acquirer would actually pay.</p>
<p><code>EV = Market Cap + Total Debt − Cash & Equivalents</code></p>
<p>Two companies with the same market cap but very different debt levels have very different enterprise values — and EV-based multiples capture this while P/E ignores it.</p>

<div class="lesson-callout info">
  <strong>EV/EBITDA explained:</strong><br/>
  EBITDA = Earnings Before Interest, Taxes, Depreciation, and Amortization<br/>
  EV/EBITDA = Enterprise Value ÷ EBITDA<br/><br/>
  This ratio is preferred by M&A bankers and buyout firms because it:
  <ul>
    <li>Works even when net income is negative or distorted by one-time items</li>
    <li>Is capital-structure neutral (doesn't change based on leverage)</li>
    <li>Lets you compare companies across different tax regimes and depreciation policies</li>
  </ul>
</div>

<h2>Typical EV/EBITDA Ranges by Sector</h2>
<table class="lesson-table">
  <tr><th>Sector</th><th>Typical EV/EBITDA</th></tr>
  <tr><td>Software (SaaS)</td><td>15–40×</td></tr>
  <tr><td>Healthcare / Pharma</td><td>12–20×</td></tr>
  <tr><td>Consumer Staples</td><td>10–15×</td></tr>
  <tr><td>Industrial</td><td>8–12×</td></tr>
  <tr><td>Energy</td><td>5–8×</td></tr>
  <tr><td>Banking</td><td>N/A (use P/B instead)</td></tr>
</table>

<h2>Comparable Company Analysis ("Comps")</h2>
<p>The most common valuation method on Wall Street: find 5–10 similar public companies, calculate their multiples (P/E, EV/EBITDA, P/S), build a range, and apply that range to your target company's financials to derive a valuation.</p>
<p>The output is a "trading range" (e.g., "based on comps, the stock should trade between $45–$65"). You then form a view on where within that range the company belongs based on its specific quality and growth profile.</p>

<div class="lesson-callout warning">
  <strong>Comps problem:</strong> Garbage in, garbage out. If the comp set isn't truly comparable (similar growth, similar margins, similar business model), the analysis is meaningless. An analyst's biggest job is choosing the right peers.
</div>
    `,
    quiz: [
      {
        id: "fa-valuation-l2-q1",
        question: "A company has a $10B market cap, $3B in debt, and $1B in cash. Its Enterprise Value is:",
        options: ["$10B", "$12B", "$9B", "$14B"],
        answer: 1,
        explanation: "EV = Market Cap + Debt - Cash = $10B + $3B - $1B = $12B. An acquirer would pay the market cap but also inherit the debt (adding cost) and receive the cash (offsetting it).",
      },
      {
        id: "fa-valuation-l2-q2",
        question: "EV/EBITDA is preferred over P/E because it:",
        options: [
          "Always produces a lower number",
          "Is capital-structure neutral and works even with negative net income",
          "Only uses publicly available data",
          "Is based on revenue, not earnings",
        ],
        answer: 1,
        explanation: "EV/EBITDA works regardless of leverage, tax rates, and depreciation policies, making it ideal for comparing companies across different capital structures or when net income is negative.",
      },
      {
        id: "fa-valuation-l2-q3",
        question: "The primary risk in 'comparable company analysis' is:",
        options: [
          "Using too many comparables",
          "Selecting a comp set that isn't truly comparable, making the analysis misleading",
          "Using forward rather than trailing multiples",
          "Enterprise value being hard to calculate",
        ],
        answer: 1,
        explanation: "Comps analysis is only as good as the peer group. Poorly chosen comps lead to valuation ranges that don't reflect the target company's actual business characteristics.",
      },
    ],
  },

  {
    id: "fa-valuation-l3",
    courseId: "fa-valuation",
    trackId: "fundamental-analysis",
    title: "DCF in Plain English",
    type: "article",
    xp: 80,
    durationMin: 14,
    tags: ["dcf", "discounted-cash-flow", "intrinsic-value", "terminal-value"],
    body: `
<h2>The Theory Behind Every Valuation</h2>
<p>All valuation methods are ultimately shortcuts for one idea: <strong>a company is worth the present value of all the cash it will ever generate</strong>. The Discounted Cash Flow (DCF) model tries to calculate that directly.</p>
<p>The core insight: $100 today is worth more than $100 a year from now. If you could invest $100 at 10%, you'd have $110 in a year. So $110 in a year has a "present value" of $100 today. This is the time value of money.</p>

<div class="lesson-callout info">
  <strong>DCF in 3 steps:</strong>
  <ol>
    <li><strong>Project free cash flows:</strong> Forecast the company's FCF for the next 5–10 years based on growth assumptions.</li>
    <li><strong>Discount to present value:</strong> Apply a "discount rate" (typically the Weighted Average Cost of Capital, or WACC) to convert future cash flows to today's dollars.</li>
    <li><strong>Add terminal value:</strong> After your explicit forecast period, assume the company generates cash flows forever at a stable growth rate. This "terminal value" often represents 60–80% of the total DCF value.</li>
  </ol>
</div>

<h2>The Problem With DCF: Garbage In, Garbage Out</h2>
<p>DCF's greatest strength is also its greatest weakness. It forces you to make your assumptions explicit — but tiny changes in those assumptions lead to huge swings in the final valuation. A 1% change in the terminal growth rate can change the fair value estimate by 20–40%.</p>

<div class="lesson-callout warning">
  <strong>The "analyst with a DCF" joke:</strong> Tell me your desired conclusion and I'll show you which discount rate and growth rate to use to get there. DCF is most useful as a <em>stress-testing</em> tool ("what growth rate is the market implying at today's price?") rather than an absolute valuation oracle.
</div>

<h2>Reverse DCF: The More Honest Approach</h2>
<p>Instead of projecting cash flows and solving for value, flip it: at today's stock price, what growth rate is already "priced in"? If the market is pricing in 30% annual FCF growth for 10 years, you have to decide: is that realistic? If you think 20% is more likely, the stock is overvalued at today's price. If you think 40% is possible, it's undervalued.</p>
    `,
    quiz: [
      {
        id: "fa-valuation-l3-q1",
        question: "The core principle of DCF valuation is:",
        options: [
          "A company is worth the sum of all its assets",
          "A company is worth the present value of all its future free cash flows",
          "A company is worth its highest recent stock price",
          "A company is worth the average of its peer group's valuation",
        ],
        answer: 1,
        explanation: "DCF directly applies the time value of money principle: the company is worth the sum of all future cash flows, discounted back to today's dollars.",
      },
      {
        id: "fa-valuation-l3-q2",
        question: "In a typical DCF, 'terminal value' refers to:",
        options: [
          "The salvage value when the company closes",
          "The value of cash flows beyond the explicit forecast period, assuming stable perpetual growth",
          "The value of long-term assets on the balance sheet",
          "The debt that must be repaid",
        ],
        answer: 1,
        explanation: "Terminal value captures the value of all cash flows after the explicit forecast period (year 5 or 10), typically assuming a stable long-term growth rate. It often represents 60–80% of total DCF value.",
      },
      {
        id: "fa-valuation-l3-q3",
        question: "A 'reverse DCF' is most useful for:",
        options: [
          "Companies with negative cash flows",
          "Determining what growth rate the market is already pricing in at today's stock price",
          "International companies with different currencies",
          "Only works for banks and insurance companies",
        ],
        answer: 1,
        explanation: "Reverse DCF answers: 'At this price, what does the market have to believe about growth?' This is often more practical than forward DCF because it reveals the implied market assumptions you're deciding to agree or disagree with.",
      },
    ],
  },

  // ── Course 3: Competitive Analysis ──────────────────────────────────────
  {
    id: "fa-moats-l1",
    courseId: "fa-moats",
    trackId: "fundamental-analysis",
    title: "Moats & Competitive Advantage",
    type: "article",
    xp: 70,
    durationMin: 12,
    tags: ["moat", "competitive-advantage", "pricing-power", "network-effects"],
    body: `
<h2>Warren Buffett's Most Important Question</h2>
<p>Before valuing any company, Warren Buffett asks: <em>"What protects this business from competition in 10 years?"</em> He calls the answer a <strong>moat</strong> — a durable competitive advantage that lets a company earn above-average returns on capital for a long time without being eroded by rivals.</p>
<p>A business without a moat is like a castle without a moat — anyone with capital can attack it. Commodities businesses, contract manufacturers, and retailers in crowded markets often have no moat. Their margins are competed away.</p>

<div class="lesson-callout info">
  <strong>The five sources of moats:</strong>
  <ol>
    <li><strong>Network effects:</strong> The product becomes more valuable as more people use it. (Visa, Meta, Airbnb)</li>
    <li><strong>Switching costs:</strong> Leaving the product is expensive, painful, or risky. (Salesforce, Oracle, Epic Systems)</li>
    <li><strong>Cost advantages:</strong> Structural cost lead that can't be easily replicated. (Costco's membership model, Amazon's logistics scale)</li>
    <li><strong>Intangible assets:</strong> Brands, patents, regulatory licenses. (Coca-Cola, Novo Nordisk's GLP-1 patents)</li>
    <li><strong>Efficient scale:</strong> Market too small to attract a second competitor. (Regional utilities, niche industrial suppliers)</li>
  </ol>
</div>

<h2>How to Test for a Moat: The Pricing Power Test</h2>
<p>The fastest moat test: can the company raise prices without losing significant customers? If yes, it has pricing power — the most direct expression of competitive advantage.</p>
<p>Buffett famously uses Coca-Cola: it raised its price from 5 cents (where it was set in 1886) continuously for 100 years and never lost its market position. That's pricing power.</p>

<h2>Moat Width vs. Moat Depth</h2>
<p>Not all moats are equal. A <strong>wide moat</strong> (e.g., Google's search network effects) may last decades. A <strong>narrow moat</strong> (e.g., a regional brand) may be eroded in 5–10 years. Pay attention to whether competitive threats are narrowing the moat over time.</p>

<div class="lesson-callout warning">
  <strong>Moat destruction is happening faster:</strong> Technology accelerates creative destruction. Blockbuster had a moat (distribution scale). Netflix ended it in 10 years. Always ask: what could a startup with unlimited capital do to undercut this business?
</div>
    `,
    quiz: [
      {
        id: "fa-moats-l1-q1",
        question: "A 'network effect' moat means:",
        options: [
          "The company has the most locations",
          "The product becomes more valuable as more people use it",
          "The company's internet infrastructure is proprietary",
          "Customers have high switching costs",
        ],
        answer: 1,
        explanation: "Network effects: each additional user makes the product more valuable for all existing users. Visa, Meta, and Airbnb benefit from this — more users means more value, making it harder for new entrants to compete.",
      },
      {
        id: "fa-moats-l1-q2",
        question: "The fastest way to test whether a company has a moat is to ask:",
        options: [
          "Does the company have a large market cap?",
          "Can the company raise prices without losing significant customers?",
          "Does the company have many employees?",
          "Is the company's revenue growing?",
        ],
        answer: 1,
        explanation: "Pricing power — the ability to raise prices without proportionate customer loss — is the most direct evidence of competitive advantage. No moat = immediate customer flight when prices rise.",
      },
      {
        id: "fa-moats-l1-q3",
        question: "Oracle's enterprise software is an example of which type of moat?",
        options: [
          "Network effects", "Switching costs", "Cost advantages", "Efficient scale",
        ],
        answer: 1,
        explanation: "Oracle has high switching costs — replacing an enterprise database system is enormously expensive, risky, and disruptive. This locks in customers for years or decades.",
      },
    ],
  },

  {
    id: "fa-moats-l2",
    courseId: "fa-moats",
    trackId: "fundamental-analysis",
    title: "Cyclical vs. Defensive Stocks",
    type: "article",
    xp: 60,
    durationMin: 9,
    tags: ["cyclical", "defensive", "sector-rotation", "beta"],
    body: `
<h2>Not All Stocks Move Together</h2>
<p>When a recession hits, some industries get hammered while others barely flinch. When the economy booms, some sectors explode while others plod along. Understanding this dynamic — called <strong>sector rotation</strong> — helps you position your portfolio for the economic environment you're in.</p>

<div class="lesson-callout info">
  <strong>Cyclical sectors</strong> (sensitive to economic cycles):
  <ul>
    <li>Consumer Discretionary (luxury goods, restaurants, hotels)</li>
    <li>Industrials (manufacturing, aerospace, construction)</li>
    <li>Materials (steel, chemicals, mining)</li>
    <li>Energy (oil & gas — follows commodity prices)</li>
    <li>Financials (banks — sensitive to interest rates and credit cycles)</li>
  </ul>
  <strong>Defensive sectors</strong> (relatively insensitive to economic cycles):
  <ul>
    <li>Consumer Staples (food, beverages, household products — people always need them)</li>
    <li>Healthcare (people don't defer surgery or medicine in recessions)</li>
    <li>Utilities (electricity and water demand is inelastic)</li>
  </ul>
</div>

<h2>Beta: Measuring Market Sensitivity</h2>
<p><strong>Beta</strong> measures how much a stock moves relative to the market (S&P 500 = beta of 1.0).</p>
<ul>
  <li>Beta 1.5 = the stock typically moves 50% more than the market (amplified risk and reward)</li>
  <li>Beta 0.5 = the stock typically moves half as much as the market (more stable, but less upside)</li>
  <li>Beta near 0 = gold, utilities — nearly uncorrelated with the stock market</li>
</ul>

<h2>When to Rotate</h2>
<p>Professional portfolio managers rotate between cyclicals and defensives based on their economic outlook:</p>
<ul>
  <li><strong>Early economic recovery:</strong> Overweight cyclicals — they'll benefit most from accelerating growth</li>
  <li><strong>Late cycle / recession risk rising:</strong> Rotate to defensives — Consumer Staples, Healthcare, Utilities</li>
  <li><strong>Deep recession:</strong> Cash, bonds, and defensive equities preserve capital</li>
</ul>
    `,
    quiz: [
      {
        id: "fa-moats-l2-q1",
        question: "Which sector is considered 'defensive' because demand barely changes in recessions?",
        options: ["Consumer Discretionary", "Industrials", "Consumer Staples", "Energy"],
        answer: 2,
        explanation: "Consumer Staples (food, beverages, household products) are defensive — people keep buying toothpaste and soup regardless of whether the economy is booming or crashing.",
      },
      {
        id: "fa-moats-l2-q2",
        question: "A stock with beta of 1.8 means it typically:",
        options: [
          "Moves 80% less than the market", "Moves 80% more than the market", "Is 80% correlated with bonds", "Has an 80% win rate",
        ],
        answer: 1,
        explanation: "Beta 1.8 = the stock moves ~80% more than the market. A 10% market up-day means roughly +18% for this stock; a 10% down-day means roughly -18%.",
      },
      {
        id: "fa-moats-l2-q3",
        question: "In a late economic cycle with recession risk rising, the classic rotation is toward:",
        options: [
          "Industrials and Energy",
          "Consumer Staples, Healthcare, and Utilities",
          "Small-cap growth stocks",
          "Cryptocurrencies",
        ],
        answer: 1,
        explanation: "Late-cycle rotation favors defensive sectors (Consumer Staples, Healthcare, Utilities) that maintain earnings even as economic growth slows — capital preservation over growth.",
      },
    ],
  },

  {
    id: "fa-moats-l3",
    courseId: "fa-moats",
    trackId: "fundamental-analysis",
    title: "Red Flags in Financial Statements",
    type: "challenge",
    xp: 90,
    durationMin: 14,
    tags: ["red-flags", "accounting", "fraud-detection", "financial-quality"],
    body: `
<h2>The Art of Financial Forensics</h2>
<p>Not every company presents its financials honestly. Between aggressive (but legal) accounting and outright fraud, investors who can spot warning signs in financial statements have a massive edge — they avoid landmines that others step on.</p>

<div class="lesson-callout warning">
  <strong>The 10 Red Flags checklist:</strong>
  <ol>
    <li><strong>Revenue growing faster than cash from operations:</strong> Are they recognizing revenue before cash arrives?</li>
    <li><strong>Accounts receivable growing much faster than revenue:</strong> Are customers not paying? Or is revenue being stuffed into the future?</li>
    <li><strong>Gross margins declining while revenue grows:</strong> Usually means price competition or rising input costs eroding the moat.</li>
    <li><strong>Auditor changes, especially to a less prominent firm:</strong> The previous auditor may have raised issues.</li>
    <li><strong>CFO or CEO departures without clear explanation:</strong> Often precedes bad news by 6–12 months.</li>
    <li><strong>Frequent restatements of prior periods:</strong> Suggests poor internal controls or intentional misreporting.</li>
    <li><strong>Related-party transactions:</strong> Company is paying large fees to entities controlled by the CEO — value extraction.</li>
    <li><strong>Heavy insider selling while executives talk publicly about the bright future.</strong></li>
    <li><strong>Goodwill impairments:</strong> Company is admitting it overpaid for acquisitions. Often the first of several write-downs.</li>
    <li><strong>Working capital deteriorating while income statement looks fine:</strong> Cash conversion is breaking down.</li>
  </ol>
</div>

<h2>The Enron Pattern</h2>
<p>Enron used complex related-party transactions and special purpose entities to hide debt off the balance sheet. None of it would have been obvious to an investor reading just the income statement. The tells were in the footnotes: related-party transactions to entities run by the CFO, confusing off-balance-sheet arrangements, and an auditor (Arthur Andersen) that clearly wasn't independent.</p>
<p>The lesson: <strong>always read the footnotes</strong>. The income statement is marketing. The footnotes are where the real story is told.</p>
    `,
    quiz: [
      {
        id: "fa-moats-l3-q1",
        question: "If accounts receivable are growing much faster than revenue, this could indicate:",
        options: [
          "The company has excellent customer relationships",
          "Revenue may be recognized before cash is collected — quality concern",
          "The company is expanding into new markets",
          "The CFO is being conservative",
        ],
        answer: 1,
        explanation: "Accounts receivable growing faster than revenue means the company is booking revenue but not collecting it. This can indicate channel stuffing, aggressive recognition, or customers in financial trouble.",
      },
      {
        id: "fa-moats-l3-q2",
        question: "An unexplained CFO departure is a red flag because:",
        options: [
          "It always means the company is about to be acquired",
          "CFOs are the first to know of financial problems; unexplained departures often precede bad news",
          "It increases the company's operating expenses",
          "It means the stock will definitely fall",
        ],
        answer: 1,
        explanation: "CFO departures without clear explanation (retirement, health, etc.) statistically precede earnings restatements or negative financial surprises more often than chance — the CFO knew something.",
      },
      {
        id: "fa-moats-l3-q3",
        question: "Why is reading the financial statement footnotes important?",
        options: [
          "They contain the stock price target",
          "They often reveal related-party transactions, off-balance-sheet liabilities, and accounting policy choices that the main statements obscure",
          "They're required by law to explain the income statement",
          "They only matter for companies with negative earnings",
        ],
        answer: 1,
        explanation: "Footnotes contain the detail behind the numbers: related-party transactions, litigation, pension liabilities, accounting policy choices. Enron's fraud was partly visible in footnotes years before the collapse.",
      },
    ],
    challenge: {
      description: "Look up the latest 10-K filing for any S&P 500 company in the Research section of BMG Capital.",
      task: "Find the company's most recent annual report, navigate to the Notes to Financial Statements, and identify one item from the Red Flags checklist that is either present (concerning) or notably absent (reassuring). Write a 2–3 sentence thesis on whether the financial quality appears high or low.",
      successCriteria: "Open the Research page for any stock and locate a piece of information about its financial quality that isn't visible on the summary page.",
    },
  },
];

export const courses: Course[] = [
  {
    id: "fa-financials",
    trackId: "fundamental-analysis",
    title: "Reading Financial Statements",
    description: "Decode the income statement, balance sheet, and cash flow statement like an analyst.",
    lessonIds: ["fa-financials-l1", "fa-financials-l2", "fa-financials-l3"],
    xpTotal: 200,
  },
  {
    id: "fa-valuation",
    trackId: "fundamental-analysis",
    title: "Valuation Methods",
    description: "P/E, EV/EBITDA, DCF, and comps — the four tools that determine whether a stock is cheap or expensive.",
    lessonIds: ["fa-valuation-l1", "fa-valuation-l2", "fa-valuation-l3"],
    xpTotal: 230,
  },
  {
    id: "fa-moats",
    trackId: "fundamental-analysis",
    title: "Competitive Analysis",
    description: "Identify moats, understand sector rotation, and spot red flags before the market does.",
    lessonIds: ["fa-moats-l1", "fa-moats-l2", "fa-moats-l3"],
    xpTotal: 220,
  },
];

export const track: Track = {
  id: "fundamental-analysis",
  title: "Fundamental Analysis",
  description: "Value companies like a professional investor. Read financial statements, apply valuation multiples, and identify durable competitive advantages.",
  icon: "🏛️",
  difficulty: "intermediate",
  colorClass: "violet",
  courseIds: ["fa-financials", "fa-valuation", "fa-moats"],
};
