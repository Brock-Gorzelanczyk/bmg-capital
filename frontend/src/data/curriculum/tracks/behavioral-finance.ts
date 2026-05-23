import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  {
    id: "bf-intro-l1",
    courseId: "bf-intro",
    trackId: "behavioral-finance",
    title: "Why Smart People Make Dumb Market Decisions",
    type: "article",
    xp: 60,
    durationMin: 10,
    tags: ["behavioral-finance", "cognitive-bias", "loss-aversion", "overconfidence"],
    body: `
<h2>The Brain Is Not Built for Markets</h2>
<p>Human brains evolved to avoid predators and find food, not to make rational financial decisions. The same cognitive shortcuts (heuristics) that kept our ancestors alive are systematically exploited by markets — and understanding them is one of the highest-return investments you can make.</p>

<div class="lesson-callout warning">
  <strong>The 6 biases costing you money right now:</strong>
  <ol>
    <li><strong>Loss aversion:</strong> Losses feel ~2× more painful than equivalent gains feel good. This causes investors to hold losing positions too long and sell winners too early.</li>
    <li><strong>Overconfidence:</strong> 74% of fund managers believe they're above average. Active trading is 90% correlated with overconfidence — and destroys value.</li>
    <li><strong>Confirmation bias:</strong> Seeking information that confirms existing beliefs while ignoring contrary evidence. The bull who never reads the bear case.</li>
    <li><strong>Recency bias:</strong> Extrapolating recent performance into the future. Buying after a 2-year bull market; selling after a crash.</li>
    <li><strong>Anchoring:</strong> Refusing to sell a stock below your cost basis, as if the market cares what you paid.</li>
    <li><strong>Herding:</strong> Buying what everyone else is buying. FOMO. Meme stocks.</li>
  </ol>
</div>

<h2>The Antidote: Process Over Outcome</h2>
<p>Professional traders build <em>systems</em> — written rules for entry, exit, and position sizing — precisely because they know they can't trust their in-the-moment judgment. A pre-written trading plan reviewed before the market opens is worth more than any indicator.</p>
    `,
    quiz: [
      {
        id: "bf-intro-l1-q1",
        question: "Loss aversion means investors:",
        options: [
          "Avoid all investments that could lose money",
          "Feel losses roughly twice as intensely as equivalent gains — causing them to hold losers too long",
          "Prefer bonds to stocks",
          "Diversify too aggressively",
        ],
        answer: 1,
        explanation: "Loss aversion (Kahneman & Tversky): the pain of losing $100 is roughly twice as intense as the pleasure of gaining $100. This causes investors to irrationally hold losing positions, hoping to 'break even.'",
      },
      {
        id: "bf-intro-l1-q2",
        question: "Anchoring bias in investing refers to:",
        options: [
          "Investing only in stable blue-chip stocks",
          "Refusing to sell a stock below the price you paid, as if cost basis is relevant to current fair value",
          "Only buying stocks that have been recommended by anchors",
          "Waiting for a price anchor before trading",
        ],
        answer: 1,
        explanation: "Anchoring: investors anchor to their purchase price ('I'll sell when I break even') even though the market has no memory of what you paid. A stock at $40 that you bought at $80 may still be overvalued at $40.",
      },
      {
        id: "bf-intro-l1-q3",
        question: "The best antidote to cognitive biases in trading is:",
        options: [
          "Trading more frequently to build experience",
          "A pre-written trading plan with objective entry/exit/sizing rules",
          "Watching financial news for real-time guidance",
          "Following successful investors on social media",
        ],
        answer: 1,
        explanation: "Pre-written systems and rules prevent in-the-moment emotional decisions. If your plan says 'stop loss at -8%,' you execute it — you don't debate it while watching the stock fall.",
      },
    ],
  },
  {
    id: "bf-intro-l2",
    courseId: "bf-intro",
    trackId: "behavioral-finance",
    title: "Market Cycles and the Psychology of Bubbles",
    type: "article",
    xp: 70,
    durationMin: 11,
    tags: ["market-cycles", "bubbles", "fear-greed", "sentiment"],
    body: `
<h2>Markets Are Driven by Fear and Greed</h2>
<p>Benjamin Graham's famous metaphor: "In the short run, the market is a voting machine. In the long run, it's a weighing machine." The voting machine is driven by sentiment — fear and greed cycles that repeat in recognizable patterns.</p>

<div class="lesson-callout info">
  <strong>The psychology of a market bubble (in order):</strong>
  <ol>
    <li><strong>Stealth phase:</strong> Smart money accumulates quietly. Price rises slowly. No media coverage.</li>
    <li><strong>Awareness phase:</strong> Institutional investors notice. Price accelerates. Early media coverage.</li>
    <li><strong>Mania phase:</strong> Public piles in driven by FOMO. Everyone knows about it. Taxi drivers have opinions. "This time it's different."</li>
    <li><strong>Blow-off top:</strong> Final parabolic move. Late buyers push price to extreme. Volume spikes.</li>
    <li><strong>Crash:</strong> Institutional selling overwhelms retail buying. Price collapses toward the pre-mania level.</li>
  </ol>
</div>

<h2>The Contrarian's Edge</h2>
<p>Warren Buffett: "Be fearful when others are greedy, and greedy when others are fearful." This is not a cliché — it's actionable. The CNN Fear & Greed Index, the VIX (volatility index), and the put/call ratio are measurable proxies for market sentiment. Extremes in sentiment often precede reversals.</p>

<div class="lesson-callout success">
  <strong>Practical rule:</strong> When a non-financial friend asks you about a specific stock for the first time, the top is probably near. When your financial-professional friends say the market will never recover, the bottom is probably near.
</div>
    `,
    quiz: [
      {
        id: "bf-intro-l2-q1",
        question: "Benjamin Graham's 'weighing machine' metaphor for long-term markets means:",
        options: [
          "Markets accurately price all information instantly",
          "Over time, prices reflect underlying business value rather than short-term sentiment",
          "The Federal Reserve controls long-term prices",
          "Heavier (larger) companies have more stable prices",
        ],
        answer: 1,
        explanation: "Graham's weighing machine: in the long run, stock prices converge to reflect actual business value. Short-term, voting (sentiment) dominates; long-term, weighing (fundamentals) wins.",
      },
      {
        id: "bf-intro-l2-q2",
        question: "During the 'mania phase' of a bubble, the best contrarian action is typically:",
        options: [
          "Buy heavily — momentum is strongest",
          "Reduce exposure and prepare for a reversal",
          "Short sell immediately",
          "Hold cash and wait for the IPO",
        ],
        answer: 1,
        explanation: "The mania phase is characterized by maximum public participation and FOMO. This is typically when risk/reward for new buyers is worst. Reducing exposure protects capital for buying at lower prices after the inevitable correction.",
      },
      {
        id: "bf-intro-l2-q3",
        question: "The VIX (volatility index) is useful as a sentiment indicator because:",
        options: [
          "It tracks the S&P 500's daily price movement",
          "High VIX indicates extreme fear — historically a contrarian buy signal; low VIX indicates complacency",
          "It predicts the next quarter's earnings",
          "It only moves when the Federal Reserve acts",
        ],
        answer: 1,
        explanation: "VIX measures implied volatility of S&P 500 options — a proxy for market fear. Extreme high VIX (>40) has historically been a contrarian buy signal; very low VIX (<12) suggests complacency that often precedes corrections.",
      },
    ],
  },
];

export const courses: Course[] = [
  {
    id: "bf-intro",
    trackId: "behavioral-finance",
    title: "Mind Over Markets",
    description: "Identify the cognitive biases that cost investors money and build the mental frameworks to overcome them.",
    lessonIds: ["bf-intro-l1", "bf-intro-l2"],
    xpTotal: 130,
  },
];

export const track: Track = {
  id: "behavioral-finance",
  title: "Behavioral Finance",
  description: "The psychology of investing. Understand the biases that drive market bubbles, panic selling, and irrational decision-making — then build systems to beat them.",
  icon: "🧠",
  difficulty: "intermediate",
  colorClass: "purple",
  courseIds: ["bf-intro"],
};
