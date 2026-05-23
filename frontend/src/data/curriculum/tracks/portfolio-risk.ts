import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  {
    id: "pr-intro-l1",
    courseId: "pr-intro",
    trackId: "portfolio-risk",
    title: "Diversification: The Only Free Lunch",
    type: "article",
    xp: 60,
    durationMin: 9,
    tags: ["diversification", "correlation", "portfolio-construction"],
    body: `
<h2>Why Diversification Works</h2>
<p>Nobel laureate Harry Markowitz famously called diversification "the only free lunch in investing." Owning multiple uncorrelated assets reduces risk without necessarily sacrificing expected return.</p>
<p>The key word is <strong>uncorrelated</strong>. Owning 20 tech stocks is not diversification — they move together. True diversification requires assets that respond differently to the same economic events.</p>

<div class="lesson-callout info">
  <strong>Correlation (-1 to +1):</strong>
  <ul>
    <li>+1.0 = move perfectly together (no diversification benefit)</li>
    <li>0.0 = completely uncorrelated (maximum diversification)</li>
    <li>-1.0 = move perfectly opposite (perfect hedge)</li>
  </ul>
  Adding a -0.3 correlated asset to a portfolio reduces volatility significantly.
</div>

<h2>The Math of Diversification</h2>
<p>A portfolio of 2 stocks eliminates ~46% of single-stock risk. By 20 stocks, ~95% of diversifiable risk is eliminated. Beyond 30–40 stocks, you're essentially replicating the market index — you might as well buy the index cheaper.</p>

<div class="lesson-callout success">
  <strong>The practical rule:</strong> Own 15–25 positions across at least 5–6 different sectors. Beyond that, you're adding complexity without meaningfully reducing risk.
</div>
    `,
    quiz: [
      {
        id: "pr-intro-l1-q1",
        question: "Why is owning 20 tech stocks not true diversification?",
        options: [
          "20 stocks is too many", "Tech stocks are highly correlated — they move together", "You need at least 30 stocks for diversification", "Only index funds provide diversification"],
        answer: 1,
        explanation: "True diversification requires low correlation. Tech stocks tend to move together, so 20 tech stocks have nearly the same risk profile as 5 tech stocks.",
      },
      {
        id: "pr-intro-l1-q2",
        question: "A correlation of -0.3 between two assets means:",
        options: ["They move in opposite directions 30% of the time", "They have a slight inverse relationship — when one rises, the other tends to fall slightly", "They're completely uncorrelated", "The assets are 30% identical"],
        answer: 1,
        explanation: "-0.3 correlation means a weak but real negative relationship. Adding a -0.3 correlated asset to a portfolio meaningfully reduces volatility.",
      },
      {
        id: "pr-intro-l1-q3",
        question: "Beyond 30–40 stocks in a portfolio, adding more positions:",
        options: [
          "Continues to reduce risk significantly",
          "Provides minimal additional risk reduction and adds management complexity",
          "Guarantees index-beating returns",
          "Is required by most financial regulations",
        ],
        answer: 1,
        explanation: "Diversification benefits diminish rapidly. By 30–40 stocks, you've eliminated most company-specific risk. Adding more just dilutes conviction without meaningfully reducing market risk.",
      },
    ],
  },
  {
    id: "pr-intro-l2",
    courseId: "pr-intro",
    trackId: "portfolio-risk",
    title: "Sharpe Ratio, Max Drawdown & Risk-Adjusted Returns",
    type: "article",
    xp: 70,
    durationMin: 10,
    tags: ["sharpe-ratio", "max-drawdown", "risk-adjusted-returns", "volatility"],
    body: `
<h2>Return Alone Is Meaningless Without Risk</h2>
<p>Fund A returned 20% last year. Fund B returned 15%. Fund A wins — right? Not if Fund A had three times the volatility and a 35% drawdown along the way. Most investors would have panic-sold during that drawdown and never realized the 20% gain.</p>
<p>Risk-adjusted return metrics tell you how much return you got per unit of risk taken.</p>

<div class="lesson-callout info">
  <strong>Sharpe Ratio = (Portfolio Return − Risk-Free Rate) / Portfolio Volatility</strong><br/>
  A Sharpe above 1.0 is generally good. Above 2.0 is excellent. Negative means you'd have been better off in cash.
</div>

<div class="lesson-callout info">
  <strong>Maximum Drawdown</strong> = the largest peak-to-trough decline in portfolio value.<br/>
  A portfolio that peaked at $100k, fell to $60k, and recovered represents a 40% max drawdown. Drawdowns matter because large drawdowns require even larger subsequent gains to break even (a 50% loss requires a 100% gain to recover).
</div>

<h2>The Practical Portfolio Metrics Dashboard</h2>
<p>BMG Capital's Portfolio page shows Sharpe ratio, annualized return, max drawdown, and beta for your positions. Check these quarterly to understand whether you're being compensated for the risk you're taking.</p>
    `,
    quiz: [
      {
        id: "pr-intro-l2-q1",
        question: "A Sharpe ratio of 0.3 means:",
        options: [
          "Excellent risk-adjusted returns",
          "Poor risk-adjusted returns — you're not being well-compensated for volatility taken",
          "The portfolio has 30% annual return",
          "The portfolio has 30% drawdown",
        ],
        answer: 1,
        explanation: "Sharpe below 1.0 is generally poor. 0.3 means you're earning very little return per unit of risk. Many investors would be better off in a low-cost index fund.",
      },
      {
        id: "pr-intro-l2-q2",
        question: "A portfolio that drops 50% from its peak requires what gain to break even?",
        options: ["50%", "75%", "100%", "150%"],
        answer: 2,
        explanation: "If $100 falls to $50 (50% loss), it needs to double to reach $100 again — a 100% gain. This is why controlling max drawdown is as important as targeting return.",
      },
      {
        id: "pr-intro-l2-q3",
        question: "Beta measures:",
        options: [
          "A portfolio's total return vs. a benchmark",
          "How much the portfolio moves relative to the overall market",
          "The portfolio's Sharpe ratio adjusted for skew",
          "Annualized volatility of individual positions",
        ],
        answer: 1,
        explanation: "Beta measures market sensitivity. Beta of 1.5 means the portfolio typically moves 1.5× as much as the S&P 500 in either direction.",
      },
    ],
  },
];

export const courses: Course[] = [
  {
    id: "pr-intro",
    trackId: "portfolio-risk",
    title: "Portfolio Construction",
    description: "Diversification, correlation, risk-adjusted returns, and the metrics that separate good portfolios from lucky ones.",
    lessonIds: ["pr-intro-l1", "pr-intro-l2"],
    xpTotal: 130,
  },
];

export const track: Track = {
  id: "portfolio-risk",
  title: "Portfolio & Risk Management",
  description: "Build and manage a portfolio that survives bear markets. Diversification, position sizing, drawdown control, and risk-adjusted returns.",
  icon: "🛡️",
  difficulty: "intermediate",
  colorClass: "rose",
  courseIds: ["pr-intro"],
};
