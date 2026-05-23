import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  {
    id: "tax-intro-l1",
    courseId: "tax-intro",
    trackId: "taxes",
    title: "Capital Gains 101",
    type: "article",
    xp: 60,
    durationMin: 8,
    tags: ["capital-gains", "tax", "short-term", "long-term", "wash-sale"],
    body: `
<h2>The Tax Cost of Investing</h2>
<p>Every profitable trade generates a taxable event. Understanding the rules lets you legally minimize your tax bill — one of the highest-certainty returns available to any investor.</p>

<div class="lesson-callout info">
  <strong>Two types of capital gains:</strong>
  <ul>
    <li><strong>Short-term:</strong> Assets held ≤ 365 days. Taxed as ordinary income — up to 37% at the highest bracket.</li>
    <li><strong>Long-term:</strong> Assets held &gt; 365 days. Taxed at preferential rates: 0%, 15%, or 20% depending on income.</li>
  </ul>
  Holding an investment for one year and one day can cut your tax rate by more than half.
</div>

<h2>Tax-Loss Harvesting</h2>
<p><strong>Tax-loss harvesting</strong> is selling losing positions to realize a loss that offsets gains. If you have $10,000 in gains and harvest $8,000 in losses, you only owe taxes on $2,000 net.</p>
<p><strong>Watch the wash-sale rule:</strong> You cannot buy back a "substantially identical" security within 30 days before or after the sale, or the loss is disallowed. Solution: buy a different ETF in the same sector.</p>

<div class="lesson-callout success">
  <strong>Tax-advantaged accounts (IRAs, 401k):</strong> Trades inside these accounts generate no capital gains tax. This is why long-term investors should hold their highest-growth assets in Roth IRAs — all gains compound tax-free.
</div>
    `,
    quiz: [
      {
        id: "tax-intro-l1-q1",
        question: "Long-term capital gains tax rates apply to assets held for:",
        options: ["At least 6 months", "At least 12 months", "At least 24 months", "At least 5 years"],
        answer: 1,
        explanation: "Long-term capital gains rates (0%, 15%, 20%) apply to assets held more than one year. Short-term gains (held ≤ 1 year) are taxed as ordinary income at higher rates.",
      },
      {
        id: "tax-intro-l1-q2",
        question: "Tax-loss harvesting involves:",
        options: [
          "Waiting until year-end to take any profits",
          "Selling losing positions to create tax losses that offset gains",
          "Moving assets to a tax-exempt trust",
          "Deferring all capital gains to the following year",
        ],
        answer: 1,
        explanation: "Tax-loss harvesting: realize losses to offset gains, reducing net taxable income. The wash-sale rule limits re-buying the same security within 30 days.",
      },
      {
        id: "tax-intro-l1-q3",
        question: "The wash-sale rule prevents you from:",
        options: [
          "Selling a stock at a loss at any time",
          "Repurchasing a 'substantially identical' security within 30 days of a loss sale",
          "Having more than 10 tax losses per year",
          "Harvesting losses in IRAs",
        ],
        answer: 1,
        explanation: "The wash-sale rule disallows the loss deduction if you buy back substantially the same security within 30 days before or after the sale. Solution: substitute with a similar but not identical security.",
      },
    ],
  },
  {
    id: "tax-intro-l2",
    courseId: "tax-intro",
    trackId: "taxes",
    title: "IRAs, 401(k)s, and Tax-Advantaged Investing",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["ira", "roth-ira", "401k", "tax-advantaged", "contribution-limits"],
    body: `
<h2>The Most Powerful Tax Benefit Available</h2>
<p>The government gives investors three powerful tax-advantaged wrappers. Using them correctly is one of the highest-certainty wealth-building moves available. Yet 40% of Americans don't participate in any retirement account.</p>

<div class="lesson-callout info">
  <strong>Traditional IRA / 401(k):</strong>
  <ul>
    <li>Contributions: pre-tax (reduces taxable income today)</li>
    <li>Growth: tax-deferred (no annual taxes on dividends/gains)</li>
    <li>Withdrawals: taxed as ordinary income at retirement</li>
    <li>Best if: you expect to be in a lower tax bracket in retirement</li>
  </ul>
</div>

<div class="lesson-callout success">
  <strong>Roth IRA / Roth 401(k):</strong>
  <ul>
    <li>Contributions: post-tax (no deduction today)</li>
    <li>Growth: completely tax-free</li>
    <li>Withdrawals: tax-free in retirement (including all gains)</li>
    <li>Best if: you expect to be in a higher tax bracket at retirement, or want maximum flexibility</li>
  </ul>
  A $6,500 Roth IRA contribution at age 25 that grows at 10%/year for 40 years becomes ~$295,000 — completely tax-free.
</div>

<h2>2024 Contribution Limits</h2>
<table class="lesson-table">
  <tr><th>Account</th><th>Annual Limit (2024)</th><th>Catch-up (50+)</th></tr>
  <tr><td>IRA (Traditional or Roth)</td><td>$7,000</td><td>+$1,000</td></tr>
  <tr><td>401(k)</td><td>$23,000</td><td>+$7,500</td></tr>
  <tr><td>SEP IRA</td><td>$69,000 or 25% of comp</td><td>N/A</td></tr>
</table>
    `,
    quiz: [
      {
        id: "tax-intro-l2-q1",
        question: "Roth IRA withdrawals in retirement are:",
        options: [
          "Taxed as ordinary income",
          "Taxed only on the gains, not contributions",
          "Completely tax-free (both contributions and growth)",
          "Subject to capital gains tax",
        ],
        answer: 2,
        explanation: "Roth IRA withdrawals in qualified retirement are 100% tax-free — both the contributions AND all the growth. This is the Roth's primary advantage.",
      },
      {
        id: "tax-intro-l2-q2",
        question: "A traditional 401(k) contribution reduces your taxes because:",
        options: [
          "The IRS gives a tax credit for retirement savings",
          "Contributions are made pre-tax, reducing your taxable income in the year of contribution",
          "It converts income to long-term capital gains",
          "Employer match is always tax-free",
        ],
        answer: 1,
        explanation: "Traditional 401(k)/IRA contributions are pre-tax: they reduce your taxable income today, lowering your current year's tax bill. You pay taxes when you withdraw in retirement.",
      },
      {
        id: "tax-intro-l2-q3",
        question: "For a 25-year-old expecting to earn more in retirement than now, which account is generally preferable?",
        options: [
          "Traditional IRA — defer taxes now",
          "Roth IRA — pay taxes now at a lower rate, receive all growth tax-free later",
          "Regular taxable brokerage account",
          "Savings account",
        ],
        answer: 1,
        explanation: "If you expect to be in a higher bracket later, Roth is better: you pay tax now at the lower rate and receive all future growth completely tax-free.",
      },
    ],
  },
];

export const courses: Course[] = [
  {
    id: "tax-intro",
    trackId: "taxes",
    title: "Taxes & Accounts",
    description: "Capital gains, tax-loss harvesting, IRAs, 401(k)s — the tax knowledge every investor needs.",
    lessonIds: ["tax-intro-l1", "tax-intro-l2"],
    xpTotal: 130,
  },
];

export const track: Track = {
  id: "taxes",
  title: "Taxes & Accounts",
  description: "Master the tax rules that can make or break your returns. Capital gains, tax-loss harvesting, Roth vs. traditional, and more.",
  icon: "🏦",
  difficulty: "beginner",
  colorClass: "teal",
  courseIds: ["tax-intro"],
};
