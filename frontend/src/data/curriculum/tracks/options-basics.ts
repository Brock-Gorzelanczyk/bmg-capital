import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  {
    id: "opt-intro-l1",
    courseId: "opt-intro",
    trackId: "options-basics",
    title: "What Is an Option Contract?",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["options", "calls", "puts", "strike", "expiration"],
    body: `
<h2>The Right Without the Obligation</h2>
<p>An <strong>option</strong> is a contract that gives you the <em>right</em> — but not the obligation — to buy or sell 100 shares of a stock at a specific price (<strong>strike price</strong>) before a specific date (<strong>expiration</strong>).</p>
<p>You pay a <strong>premium</strong> upfront for this right. The premium is the maximum you can lose.</p>

<div class="lesson-callout info">
  <strong>Two types:</strong>
  <ul>
    <li><strong>Call option:</strong> Right to <em>buy</em> 100 shares at the strike price. You profit if the stock rises above strike + premium.</li>
    <li><strong>Put option:</strong> Right to <em>sell</em> 100 shares at the strike price. You profit if the stock falls below strike − premium.</li>
  </ul>
</div>

<h2>Why Options Exist</h2>
<p>Options serve two purposes: <strong>hedging</strong> (protecting existing positions, like insurance) and <strong>speculation</strong> (leveraged directional bets). Institutional investors use puts as portfolio insurance. Traders use calls to gain leveraged upside exposure with defined risk.</p>

<div class="lesson-callout warning">
  <strong>Options can expire worthless.</strong> Unlike stocks, options have expiration dates. If your call expires and the stock is below the strike price, you lose 100% of the premium paid. Always size option positions as a percentage of your overall portfolio.
</div>
    `,
    quiz: [
      {
        id: "opt-intro-l1-q1",
        question: "A call option gives you the right to:",
        options: ["Sell 100 shares at the strike price", "Buy 100 shares at the strike price", "Short sell the underlying stock", "Receive the stock's dividend"],
        answer: 1,
        explanation: "A call option gives you the right (but not obligation) to buy 100 shares of the underlying stock at the strike price before expiration.",
      },
      {
        id: "opt-intro-l1-q2",
        question: "The maximum loss when buying a call option is:",
        options: ["Unlimited", "The stock's full value", "The premium paid", "The strike price"],
        answer: 2,
        explanation: "When you buy an option, your maximum loss is the premium you paid. If the option expires worthless, you lose 100% of the premium — nothing more.",
      },
      {
        id: "opt-intro-l1-q3",
        question: "One standard option contract represents how many shares?",
        options: ["1 share", "10 shares", "100 shares", "1,000 shares"],
        answer: 2,
        explanation: "One standard US equity option contract represents 100 shares of the underlying stock. A $2 premium × 100 = $200 cost to buy one contract.",
      },
    ],
  },
  {
    id: "opt-intro-l2",
    courseId: "opt-intro",
    trackId: "options-basics",
    title: "The Greeks: Delta, Theta, and IV",
    type: "article",
    xp: 80,
    durationMin: 12,
    tags: ["greeks", "delta", "theta", "implied-volatility", "time-decay"],
    body: `
<h2>Why Options Move the Way They Do</h2>
<p>Options don't move dollar-for-dollar with the stock. Their value is driven by multiple forces, collectively called "the Greeks." Understanding three of them explains 90% of what you'll observe trading options.</p>

<div class="lesson-callout info">
  <strong>Delta (Δ):</strong> How much the option price moves per $1 move in the stock.
  <ul>
    <li>Deep in-the-money call: delta ~0.90 (moves like the stock)</li>
    <li>At-the-money call: delta ~0.50</li>
    <li>Far out-of-the-money call: delta ~0.10 (lottery ticket)</li>
  </ul>
</div>

<div class="lesson-callout warning">
  <strong>Theta (Θ) — Time Decay:</strong> Every day that passes, your option loses some time value. An option that's 60 days from expiration decays faster in the last 30 days. This is <em>theta decay</em> — the option seller's built-in advantage.
</div>

<div class="lesson-callout info">
  <strong>Implied Volatility (IV):</strong> The market's forecast of how much the stock will move. High IV = expensive options. Low IV = cheap options. Selling options in high-IV environments and buying in low-IV environments is a core edges.
</div>
    `,
    quiz: [
      {
        id: "opt-intro-l2-q1",
        question: "An option with delta of 0.50 will increase in value by approximately how much if the stock rises $2?",
        options: ["$0.25", "$0.50", "$1.00", "$2.00"],
        answer: 2,
        explanation: "Delta = price change per $1 move in the stock. Delta 0.50 × $2 move = $1.00 option price increase. One contract (100 shares) would gain $100.",
      },
      {
        id: "opt-intro-l2-q2",
        question: "Theta decay means:",
        options: [
          "Options gain value as the stock rises",
          "Options lose time value every day, accelerating as expiration approaches",
          "Implied volatility increases near earnings",
          "The strike price adjusts over time",
        ],
        answer: 1,
        explanation: "Theta is time decay — each day an option exists, some time value is lost. This benefits option sellers and works against option buyers.",
      },
      {
        id: "opt-intro-l2-q3",
        question: "When implied volatility is very high (e.g., before earnings), options are:",
        options: ["Cheap — good time to buy", "Expensive — selling strategies have an edge", "The same price as normal", "Only relevant to put options"],
        answer: 1,
        explanation: "High IV means the market expects big moves, so option premiums are inflated. Selling options in high IV environments has edge — you're selling expensive insurance.",
      },
    ],
  },
];

export const courses: Course[] = [
  {
    id: "opt-intro",
    trackId: "options-basics",
    title: "Options Foundations",
    description: "Calls, puts, strikes, expiration, and the Greeks — everything you need to understand options before trading them.",
    lessonIds: ["opt-intro-l1", "opt-intro-l2"],
    xpTotal: 150,
  },
];

export const track: Track = {
  id: "options-basics",
  title: "Options Trading",
  description: "From zero to first options trade. Understand calls, puts, the Greeks, and basic strategies with defined risk.",
  icon: "⚡",
  difficulty: "intermediate",
  colorClass: "amber",
  courseIds: ["opt-intro"],
};
