import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  FlaskConical, X, Play, TrendingUp, TrendingDown, AlertTriangle,
  Eye, Clock, CheckCircle2, RefreshCw, ExternalLink, BarChart2, Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getTrades, getCandidates, getSummary, getLog, getEquity, getRegime, runNow, closeTrade,
  getBacktestStatus, runBacktest, getBacktestResults, getBacktestDetail,
} from "@/api/strategy";
import { TICKER_NAMES } from "@/data/tickerNames";
import { COMPANY_INFO, SECTOR_COLOR } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import TradeDetailDrawer, { type EnrichedTrade } from "@/components/strategy/TradeDetailDrawer";
import ExplainButton from "@/components/explain/ExplainButton";

// ─── Strategy metadata ────────────────────────────────────────────────────────

const STRATEGIES = [
  { key: "canslim_leaders",        label: "CAN SLIM Leaders",       category: "Growth",    color: "#26a69a" },
  { key: "stage2_breakout",        label: "Stage 2 Breakout",        category: "Growth",    color: "#26a69a" },
  { key: "momentum_surge",         label: "Momentum Surge",          category: "Growth",    color: "#26a69a" },
  { key: "high_rs_momentum",       label: "High RS Leaders",         category: "Growth",    color: "#26a69a" },
  { key: "power_trend",            label: "Power Trend",             category: "Growth",    color: "#26a69a" },
  { key: "turtle_breakout",        label: "Turtle Breakout",         category: "Growth",    color: "#0ea5e9" },
  { key: "momentum_12m",           label: "12-Month Momentum",       category: "Growth",    color: "#0ea5e9" },
  { key: "darvas_box",             label: "Darvas Box",              category: "Growth",    color: "#0ea5e9" },
  { key: "mean_reversion_quality", label: "Quality Dip Buy",         category: "Reversion", color: "#3b82f6" },
  { key: "deep_value_bounce",      label: "Quality Oversold",        category: "Reversion", color: "#3b82f6" },
  { key: "rsi_oversold",           label: "RSI Oversold",            category: "Reversion", color: "#3b82f6" },
  { key: "zscore_reversion",       label: "Z-Score Reversion",       category: "Reversion", color: "#3b82f6" },
  { key: "volatility_contraction", label: "Volatility Squeeze",      category: "Pattern",   color: "#f59e0b" },
  { key: "ema_stack_uptrend",      label: "EMA Stack",               category: "Pattern",   color: "#f59e0b" },
  { key: "consecutive_gains",      label: "Momentum Continuation",   category: "Pattern",   color: "#f59e0b" },
  { key: "golden_cross",           label: "Golden Cross",            category: "Classic",   color: "#8b5cf6" },
  { key: "macd_bullish",           label: "MACD Crossover",          category: "Classic",   color: "#8b5cf6" },
  { key: "volume_surge",           label: "Volume Surge",            category: "Classic",   color: "#8b5cf6" },
  { key: "breakout_52w",           label: "52-Week High",            category: "Classic",   color: "#8b5cf6" },
];


const TRIGGER_LABELS: Record<string, string> = {
  "_breakout_pivot":    "Waiting for breakout + volume",
  "_rsi_recovery_35":  "Waiting for RSI to turn up from 35",
  "_rsi_recovery_32":  "Waiting for RSI to turn up from 32",
  "_ema_pullback":      "Waiting for EMA21 pullback + bounce",
  "_squeeze_breakout":  "Waiting for range breakout",
  "_next_open":         "Entering on next daily run",
  "_volume_direction":  "Waiting for up-day confirmation",
  "_turtle_breakout":   "Waiting for 55-day channel break",
  "_zscore_recovery":   "Waiting for z-score recovery",
  "_darvas_breakout":   "Waiting for box breakout + volume",
};

const STRATEGY_INFO: Record<string, string> = {
  canslim_leaders:        "Looks for stocks with explosive earnings growth, rising sales, and heavy institutional buying — then buys when they break out to new highs on big volume. Based on William O'Neil's proven CAN SLIM system.",
  stage2_breakout:        "Buys stocks that have been quietly building a base for months, then suddenly break above resistance with heavy volume — a signal that big money is moving in.",
  momentum_surge:         "Chases stocks already moving fast and beating the market. The logic: recent winners tend to keep winning in the short term.",
  high_rs_momentum:       "Focuses on the top performers by relative strength — stocks beating everything else in the market. Leaders tend to stay in the lead.",
  power_trend:            "Looks for stocks where the 21, 50, and 200-day moving averages are all rising and stacked in order — a textbook sign of a strong, healthy uptrend.",
  turtle_breakout:        "Buys when price breaks above the highest high of the last 55 days. Based on the legendary Turtle Traders experiment that turned beginners into millionaires in the 1980s.",
  momentum_12m:           "Buys the strongest performers of the past 12 months. Research consistently shows last year's leaders tend to outperform the following year too.",
  darvas_box:             "Nicolas Darvas turned $25k into $2M using this. It draws 'boxes' around quiet price ranges and buys when price breaks out the top with rising volume.",
  mean_reversion_quality: "Finds profitable, well-run companies that have pulled back to their 200-day moving average — essentially buying quality stocks on sale.",
  deep_value_bounce:      "Targets high-quality stocks that have dropped hard and fast, betting that sellers will run out of steam and price will snap back.",
  rsi_oversold:           "RSI measures buying/selling pressure on a 0–100 scale. When it drops below 35, the stock may be oversold (sold too much, too fast). Bets on a bounce.",
  zscore_reversion:       "Uses statistics to detect when a stock has moved way too far from its average price. Bets that extreme moves eventually return to normal.",
  volatility_contraction: "When a stock's daily price range tightens like a coiled spring, a big move is usually coming. Buys when it finally breaks out.",
  ema_stack_uptrend:      "Exponential moving averages weight recent prices more heavily. When the 20, 50, and 200-day EMAs are all aligned and rising, the trend is powerful — buy and hold.",
  consecutive_gains:      "Stocks that close higher several days in a row show short-term momentum. This strategy catches those winning streaks early.",
  golden_cross:           "When the 50-day average crosses above the 200-day average, it's a Golden Cross — one of the most widely-watched bullish signals in all of trading.",
  macd_bullish:           "MACD tracks the gap between two moving averages. When the faster line crosses above the signal line, upward momentum is building — a classic buy signal.",
  volume_surge:           "A sudden spike in trading volume often means big institutions are quietly buying. This spots those unusual volume surges before the price moves.",
  breakout_52w:           "Buying at new 52-week highs sounds risky, but research shows new highs often lead to more highs as momentum buyers pile in on the breakout.",
};

interface StrategyDetail {
  summary: string;
  howItWorks: string;
  signals: string[];
  bestIn: string;
  risk: string;
}

const STRATEGY_DETAIL: Record<string, StrategyDetail> = {
  canslim_leaders: {
    summary: "A fundamentals-first growth system that only buys stocks with explosive business momentum, then times the entry with a price breakout.",
    howItWorks: "William O'Neil studied every major stock market winner going back to the 1880s and found they all shared the same traits before their huge moves: accelerating earnings, fast revenue growth, a new product driving the business, and large institutions buying shares. This strategy scans for all of those conditions first, then waits for the stock to break out of a consolidation pattern on heavy volume — which signals that big money (mutual funds, hedge funds) is aggressively accumulating shares.",
    signals: ["Recent quarterly earnings growing 25%+ year-over-year", "Annual revenue accelerating, not slowing down", "Stock price breaking to new highs on above-average volume", "Relative strength vs. the S&P 500 in the top 15%"],
    bestIn: "Bull markets where growth stocks are leading. Struggles when the Fed is raising rates aggressively.",
    risk: "High-momentum stocks can drop fast if earnings disappoint. Stop loss is set tight, usually 7-8% below entry.",
  },
  stage2_breakout: {
    summary: "Buys stocks that have spent months quietly building a base and are just now breaking out — the moment a stock transitions from going nowhere to going up.",
    howItWorks: "Stan Weinstein's Stage Analysis divides a stock's life into 4 stages: basing, uptrend, topping, downtrend. The biggest gains happen in Stage 2. This strategy identifies stocks that have been flat for at least 6 months (Stage 1), are now above their 30-week moving average, and are breaking above resistance on rising volume. The base-building period is critical — it means overhead selling pressure has been exhausted and the stock is ready to move.",
    signals: ["Stock has been in a flat or declining base for 3-6+ months", "Price is crossing above the 30-week moving average", "Volume on the breakout is notably higher than recent weeks", "Relative strength is improving — stock is starting to outperform the index"],
    bestIn: "Any market condition, but especially powerful in early bull markets when leadership stocks begin emerging.",
    risk: "False breakouts happen — price breaks out then fails back. Stop is placed just below the breakout level.",
  },
  momentum_surge: {
    summary: "Targets stocks that are already outperforming the market strongly, with the internal strength to keep going.",
    howItWorks: "Momentum investing is backed by decades of academic research showing that stocks outperforming over the past 3-12 months tend to continue outperforming for the next 3-12 months. This reflects the reality that institutional investors build positions slowly. A stock already rising is one where big money is still accumulating. The strategy looks for strong recent price performance, high relative strength vs. peers, AND rising volume trends to confirm real demand.",
    signals: ["3-month and 6-month price return in the top 20% of the market", "RSI above 60 — momentum is alive", "Volume trend rising over time (more buying than selling pressure)", "Stock trading above its 50-day moving average"],
    bestIn: "Trending bull markets. Momentum strategies get crushed in sharp reversals — these stocks often fall the hardest.",
    risk: "High — momentum can reverse quickly. Position sizes are kept smaller to account for this volatility.",
  },
  high_rs_momentum: {
    summary: "Buys only the very top performers in the entire market — stocks beating 90%+ of everything else — on the theory that leaders keep leading.",
    howItWorks: "Relative Strength (RS) measures how a stock performs compared to every other stock. A stock with RS of 95 is outperforming 95% of all stocks. O'Neil's research showed that the biggest winners almost always had RS above 80 BEFORE their major moves. This strategy focuses on RS 90+ — which typically means powerful institutional sponsorship. The entry is timed with a price breakout so you're buying a strong stock at the right moment, not just any time.",
    signals: ["Relative Strength Rank above 90 (beating 90%+ of all stocks)", "Price holding above the 50-day moving average", "Stock near or at new 52-week highs", "Volume on up-days exceeds volume on down-days"],
    bestIn: "Bull markets, especially when growth and tech sectors are leading. These are the market's true leaders.",
    risk: "Leaders fall hard in corrections. When the market rolls over, high-RS stocks often give back gains quickly.",
  },
  power_trend: {
    summary: "Looks for stocks in the most powerful uptrends possible — where every time frame is aligned upward and supporting the price.",
    howItWorks: "A power trend is defined by all three moving averages stacking in perfect order: the 21-day EMA is above the 50-day EMA, which is above the 200-day MA, and all three are pointing upward. When all time frames align this way, it means buyers have been consistently in control for months. Pullbacks to these averages become buying opportunities. The strategy enters when price pulls back to the 21-day EMA and bounces — buying the dip within a confirmed uptrend.",
    signals: ["21-day EMA above 50-day EMA above 200-day MA (all stacked)", "All three moving averages pointing upward (positive slope)", "Price recently pulled back to or near the 21-day EMA", "RSI staying above 50 on pullbacks — buyers are defending"],
    bestIn: "Strong, sustained bull markets. Avoids whipsaw markets where trends don't last.",
    risk: "If the moving averages unstack (cross over each other), the power trend is broken and the trade is exited immediately.",
  },
  turtle_breakout: {
    summary: "A legendary trend-following system based on one of the greatest trading experiments in history — buy strength, cut losers fast.",
    howItWorks: "In 1983, trader Richard Dennis bet he could teach random people to trade profitably. He hired 23 beginners (the 'Turtles'), taught them his rules, and they made over $100 million. The core rule: buy when price makes a new 55-day high (the highest price in 55 trading days) and exit when it makes a new 20-day low. The logic is simple — a new high means the stock is in a strong trend with no overhead resistance. You're not predicting direction; you're following what price is already doing.",
    signals: ["Price closes above the highest high of the last 55 trading days", "Volume confirms the breakout (above 20-day average)", "No major earnings release in the next 2 weeks (avoids event risk)", "Market regime is bullish — SPY above its 200-day average"],
    bestIn: "Trending markets. Produces many small losses and occasional large wins — patience is required.",
    risk: "Lots of false breakouts in choppy markets. The strategy accepts this — losses are small, winners are large.",
  },
  momentum_12m: {
    summary: "Buys the strongest performers of the past year and rides their continued outperformance — one of the most academically proven strategies in finance.",
    howItWorks: "12-month momentum is one of the most replicated findings in financial research. Stocks in the top 20% by 12-month return tend to continue outperforming for the next 3-6 months. Why? Major institutional investors take months to fully build positions. When a fund decides to buy, they can't dump $500M in one day — they buy slowly, pushing price higher over time. By the time most people notice, the trend has been going on for months. This strategy buys into that ongoing institutional accumulation.",
    signals: ["12-month price return in the top 20% of all stocks", "Last month's return is positive (momentum is still alive, not reversing)", "Stock trading above its 200-day moving average", "Below-average volatility — smoother trends are more reliable"],
    bestIn: "Works in most market environments but lags when markets reverse sharply (momentum crashes).",
    risk: "Momentum crashes are rare but brutal — last year's biggest winners can become this year's biggest losers in a reversal.",
  },
  darvas_box: {
    summary: "A visual pattern system from a 1950s dancer who turned $25,000 into $2.25 million by mailing trade orders from nightclub dressing rooms worldwide.",
    howItWorks: "Nicolas Darvas was a professional dancer, not a Wall Street expert. A Darvas Box forms when a stock makes a new high, then stays within a tight range (the box) for at least 3 weeks. This represents a balance between buyers and sellers — an equilibrium. When price finally breaks ABOVE the top of the box, buyers have overwhelmed sellers and the stock is ready to move. Darvas insisted volume must surge on the breakout — without volume, it is a fake-out.",
    signals: ["Stock made a new high, then traded in a tight range for 3+ weeks", "The box's height is less than 15% (tight consolidation)", "Price breaks above the top of the box on a strong day", "Volume on the breakout is 50%+ above recent average"],
    bestIn: "Bull markets where growth stocks are setting new highs. Works poorly in bear markets or choppy action.",
    risk: "False breakouts are the main enemy. Stop is placed at the bottom of the box — if that breaks, the setup is invalid.",
  },
  mean_reversion_quality: {
    summary: "Finds profitable, financially strong companies that have pulled back to a key support level — buying quality on sale rather than chasing strength.",
    howItWorks: "Mean reversion is the idea that prices return to their long-term average over time. But not every stock that drops is worth buying — a weak company dropping is often just getting worse. This strategy only targets high-quality companies: profitable, reasonable debt, growing revenue. When one of these quality names pulls back to its 200-day moving average (the most widely watched long-term support level), institutional investors who know the business is sound step in to buy. The 200-day MA acts as a value zone for strong companies.",
    signals: ["Company is profitable (positive earnings per share)", "Debt-to-equity ratio is manageable (not overleveraged)", "Price has pulled back to within 2-5% of the 200-day moving average", "RSI between 35-50 — oversold but not in freefall"],
    bestIn: "Range-bound or mildly bullish markets. Works poorly in strong bear markets where even quality stocks keep falling.",
    risk: "The 200-day average can break in a bear market. Stop is set 5-8% below the moving average.",
  },
  deep_value_bounce: {
    summary: "Targets high-quality stocks that have been hit hard and fast — betting that the selling was overdone and a snapback rally is coming.",
    howItWorks: "When a fundamentally solid company drops 20-40% over weeks (not years), it is often due to fear, overreaction to short-term news, or forced selling by hedge funds — not because the business is broken. This creates an opportunity: the stock is oversold, and even a modest shift in sentiment can create a sharp rally. The strategy looks for quality companies (profitable, growing) with deep short-term drops and early signs that selling pressure is exhausting itself.",
    signals: ["Stock has dropped 20%+ in the past 1-3 months", "Company is fundamentally sound — profitable, not losing market share", "RSI is below 30 — deeply oversold territory", "Signs of stabilization: smaller down-days, volume drying up on declines"],
    bestIn: "Works well after market corrections when good companies get oversold. Fails if fundamentals are actually deteriorating.",
    risk: "Catching a falling knife is dangerous — sometimes stocks drop this much for good reason. Quality filters reduce but do not eliminate this risk.",
  },
  rsi_oversold: {
    summary: "Uses the RSI momentum indicator to find stocks that have been sold too hard, too fast — and bets on a bounce back toward normal levels.",
    howItWorks: "RSI (Relative Strength Index) measures the speed and magnitude of recent price changes on a scale from 0 to 100. Above 70 means overbought (too much buying), below 30 means oversold (too much selling). When a quality stock's RSI drops below 35, sellers have been aggressive and the move may be overdone. The strategy waits for RSI to turn UPWARD from that oversold zone — not just hit it — because simply being oversold does not mean it is done falling. The upturn in RSI is the actual entry trigger.",
    signals: ["RSI (14-day) drops below 35", "RSI then turns upward — first sign sellers are exhausting themselves", "Stock is above its 200-day MA — a dip in an uptrend, not a breakdown", "Volume on recovery days is greater than volume on down-days"],
    bestIn: "Bull markets where pullbacks get bought. In bear markets, oversold can become more oversold.",
    risk: "RSI can stay below 30 for weeks in strong downtrends. The 200-day moving average filter helps avoid these situations.",
  },
  zscore_reversion: {
    summary: "Uses statistics to measure exactly how abnormal a stock's price move is — and bets that extreme moves will return to average.",
    howItWorks: "A Z-score measures how many standard deviations something is from its average. In a normal distribution, 95% of observations fall within 2 standard deviations. When a stock's price is more than 2 standard deviations BELOW its 20-day average, statistically the drop is in the bottom 2.5% of normal behavior — which means the move is extreme relative to recent history. Combined with quality filters to avoid holding broken companies, this strategy looks for that extreme oversold reading to start reversing.",
    signals: ["Price Z-score relative to 20-day average is below -2.0", "The Z-score is starting to move back toward zero (mean reversion beginning)", "Company passes basic quality checks — profitable, not in collapse", "Overall market is not in a confirmed downtrend"],
    bestIn: "Sideways or mildly bullish markets. Mean reversion strategies underperform in strong trending markets.",
    risk: "Statistically extreme does not mean it cannot get more extreme. Risk is managed with hard stop losses.",
  },
  volatility_contraction: {
    summary: "Spots stocks that have gone unusually quiet — then prepares to buy when that quiet explodes into a directional move.",
    howItWorks: "Volatility cycles between expansion (big moves) and contraction (small, tight moves). The Bollinger Band Squeeze occurs when the bands narrow to their tightest point in months — meaning daily price ranges have shrunk dramatically. This is like a compressed spring. When volatility finally expands, it tends to do so strongly and in one direction. This strategy uses the squeeze as the setup and the breakout above the upper Bollinger Band (with volume) as the entry — buying the upward expansion.",
    signals: ["Bollinger Bands at their narrowest point in 20+ days (squeeze condition)", "ATR (Average True Range) below its 20-day average — unusually quiet", "Price breaks above the upper Bollinger Band", "Volume on the breakout is above average — confirming real demand"],
    bestIn: "Works in any market — the breakout direction matters more than the overall market. Only upward breakouts are traded.",
    risk: "The squeeze can break downward, not upward. Volume direction helps filter this, but not perfectly.",
  },
  ema_stack_uptrend: {
    summary: "Only trades stocks in a textbook, confirmed uptrend where every time frame is aligned — then buys pullbacks within that trend.",
    howItWorks: "An EMA Stack means the 20-day, 50-day, and 200-day Exponential Moving Averages are all layered in order and rising: 20 above 50, 50 above 200. This alignment tells you buyers have been in control over the short term (20-day), medium term (50-day), AND long term (200-day). The stock is healthy at every time frame. Rather than chasing when price is extended, this strategy waits for price to pull back to the 20-day EMA — where buyers have consistently stepped in before — and buys that dip.",
    signals: ["EMA 20 above EMA 50 above EMA 200 — perfect stack, all rising", "Price pulls back to within 2% of the 20-day EMA", "RSI pulls back to 40-55 on the dip — a healthy pause, not a breakdown", "Volume dries up on the pullback then picks up on the bounce"],
    bestIn: "Sustained bull markets. This strategy requires patience — it skips stocks that have not earned a clean stack.",
    risk: "If the EMA stack breaks (20 crosses below 50), the uptrend is over and the trade is exited.",
  },
  consecutive_gains: {
    summary: "Buys stocks that have closed higher for several days straight — evidence of consistent, persistent buying pressure that does not quit.",
    howItWorks: "When a stock closes higher 4 or more days in a row, buyers are showing up every single day and overcoming sellers. This is a short-term momentum signal that suggests the stock has caught institutional attention. The strategy looks for 4+ consecutive up-closes combined with rising volume and a stock already in a medium-term uptrend above its 50-day average. The entry is the day AFTER confirmation — joining an established short-term trend, not chasing a one-day spike.",
    signals: ["Stock has closed higher 4+ consecutive days", "Volume has increased each day — confirming real accumulation", "Stock is above its 50-day moving average — medium-term uptrend intact", "RSI between 55-75 — strong but not yet overextended"],
    bestIn: "Any bullish market. These are short-duration trades, typically lasting 5-15 days.",
    risk: "Short-term trades can reverse quickly. Stops are placed at the low of the first up-day in the streak.",
  },
  golden_cross: {
    summary: "One of the most famous signals in all of technical analysis — when the 50-day average crosses above the 200-day, signaling a major trend shift.",
    howItWorks: "A Golden Cross occurs when the 50-day moving average (medium-term trend) crosses ABOVE the 200-day moving average (long-term trend). This signals that recent buying pressure has now exceeded the long-term average — the trend is shifting from bearish or neutral to bullish. It is one of the most-watched signals by institutional investors, and that attention can become self-fulfilling. The strategy buys the cross or a small pullback after it and uses the 200-day average as the line in the sand: if price falls back below it, the thesis is broken.",
    signals: ["50-day MA crosses above the 200-day MA — the Golden Cross itself", "Both moving averages are now rising (not just one crossing a declining one)", "Price is above both averages at entry", "Volume on or around the cross day is above average"],
    bestIn: "Early-to-mid bull markets. Most powerful after a bear market bottom when momentum is genuinely shifting.",
    risk: "False crosses happen in choppy markets. The Death Cross (50 crossing back below 200) is the exit signal.",
  },
  macd_bullish: {
    summary: "Uses the MACD indicator to detect when short-term buying momentum is overtaking selling pressure — a classic early signal of a new up-move.",
    howItWorks: "MACD (Moving Average Convergence Divergence) measures the difference between the 12-day and 26-day exponential moving averages. When the MACD Line crosses ABOVE the Signal Line (a 9-day average of MACD itself), it means momentum is accelerating upward. This strategy triggers on that crossover, but only when it happens near or below the zero line — meaning the stock was genuinely weak and is now recovering, not just continuing a move that already happened.",
    signals: ["MACD Line crosses above the Signal Line", "The crossover occurs near or below the zero line — a real reversal", "MACD histogram is expanding upward — momentum accelerating", "Stock is above its 200-day MA — buying into an uptrend, not a downtrend"],
    bestIn: "Works in most conditions but generates the cleanest signals in trending markets. Produces false signals in choppy sideways markets.",
    risk: "MACD is a lagging indicator — by the time it crosses, some of the move has already happened. The goal is the middle of a move, not the bottom.",
  },
  volume_surge: {
    summary: "Detects unusual spikes in trading activity — which often signal that large institutions are quietly accumulating a stock before a big move.",
    howItWorks: "On most days a stock trades near its average volume. When volume suddenly spikes to 2-3x normal with price moving up, it signals that large investors (mutual funds, hedge funds) are buying aggressively. These players cannot buy millions of shares overnight without pushing prices up — their activity shows up in the volume data. This strategy scans for stocks with abnormally high volume on an up-day, combined with a healthy trend and proximity to a breakout point. The idea: follow the big money.",
    signals: ["Volume is 2.5x or more above the 20-day average", "Price closes up on the high-volume day — buying, not distribution", "Stock is within 5% of a 52-week or multi-month high", "Volume surge is not explained by a scheduled event like earnings — unannounced surges are most meaningful"],
    bestIn: "Any market, but especially powerful in early-to-mid bull markets when institutions are deploying capital.",
    risk: "Volume surges sometimes precede news that does not pan out. Stops are set below the high-volume day's low.",
  },
  breakout_52w: {
    summary: "Buys stocks hitting 52-week highs — counterintuitive, but research consistently shows new highs tend to lead to more new highs.",
    howItWorks: "Most people think buy low, sell high — so buying at a 52-week high feels wrong. But stocks making new highs have overcome ALL overhead selling pressure: everyone who bought in the past year is now profitable, so there is no one left rushing to sell. A new 52-week high on strong volume means demand is outpacing supply at every price level. This is often where institutional investors shift from quiet accumulation to aggressive buying. This strategy only targets quality companies hitting new highs — not random penny stocks spiking on news.",
    signals: ["Stock closes at a new 52-week high", "Volume on the breakout day is above the 20-day average", "The stock has been in an uptrend for at least 3 months — not a one-day spike", "Relative strength vs. the S&P 500 is positive — stock was already beating the market"],
    bestIn: "Bull markets. New 52-week highs in a bull market follow through. The same signal in a bear market often fails.",
    risk: "Extended stocks can reverse sharply. Stop is set just below the breakout level — if price falls back into the old range, the breakout failed.",
  },
};

const EXIT_BADGE: Record<string, { label: string; cls: string }> = {
  stop:    { label: "Stop Hit",   cls: "text-[#EF4444] border-red-400/40 bg-red-400/10" },
  target:  { label: "Target Hit", cls: "text-green-400 border-green-400/40 bg-green-400/10" },
  time:    { label: "Time Stop",  cls: "text-amber-400 border-amber-400/40 bg-amber-400/10" },
  manual:  { label: "Manual",     cls: "text-[#94A3B8] border-zinc-400/30 bg-zinc-400/10" },
  expired: { label: "Expired",    cls: "text-[#475569] border-[#334155] bg-[#334155]" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt$(n: number | null | undefined, digits = 2): string {
  if (n == null) return "—";
  return `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}
function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function pnlColor(n: number | null | undefined): string {
  if (n == null) return "text-[#94A3B8]";
  return n >= 0 ? "text-[#22C55E]" : "text-[#EF4444]";
}

// ─── Equity Curve ─────────────────────────────────────────────────────────────

function EquityCurve({ data, baseline }: { data: any[]; baseline: number }) {
  if (data.length < 2) return (
    <div className="h-28 flex items-center justify-center text-xs text-[#475569]">
      Equity curve builds after first daily run
    </div>
  );
  const vals = data.map((d) => d.portfolio_value);
  const min = Math.min(...vals) * 0.999;
  const max = Math.max(...vals) * 1.001;
  const range = max - min || 1;
  const W = 800; const H = 100; const pad = 2;
  const pts = data.map((d, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2);
    const y = H - pad - ((d.portfolio_value - min) / range) * (H - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = vals[vals.length - 1];
  const isPos = last >= baseline;
  const stroke = isPos ? "#10b981" : "#ef4444";
  const fill = isPos ? "rgba(16,185,129,0.06)" : "rgba(239,68,68,0.06)";
  const baseY = H - pad - ((baseline - min) / range) * (H - pad * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-28" preserveAspectRatio="none">
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="#3f3f46" strokeWidth={0.8} strokeDasharray="6,4" />
      <path d={`M ${pts[0]} L ${pts.join(" L ")} L ${W - pad},${H - pad} L ${pad},${H - pad} Z`} fill={fill} />
      <polyline points={pts.join(" ")} fill="none" stroke={stroke} strokeWidth={2} />
    </svg>
  );
}

// ─── Strategy Card ────────────────────────────────────────────────────────────

function StrategyCard({
  strategy, stats, openCount, watchCount, selected, onClick, onInfo,
}: {
  strategy: typeof STRATEGIES[0];
  stats: any;
  openCount: number;
  watchCount: number;
  selected: boolean;
  onClick: () => void;
  onInfo: () => void;
}) {
  const hasTrades = stats?.trades > 0;
  const pnl = stats?.total_pnl ?? 0;
  const wr = stats?.win_rate ?? 0;

  return (
    <div className="shrink-0 w-52 relative">
      <button
        onClick={onClick}
        className={cn(
          "w-full rounded-xl border p-3 text-left transition-all duration-150",
          selected
            ? "border-white/20 bg-white/5 ring-1 ring-white/10"
            : "border-[#334155] bg-[#1E293B]/60 hover:border-[#334155] hover:bg-[#1E293B]"
        )}
      >
        <div className="h-0.5 rounded-full mb-3" style={{ backgroundColor: strategy.color }} />
        <div className="pr-4">
          <div className="text-xs font-semibold text-[#F8FAFC] leading-snug mb-2">{strategy.label}</div>
          {hasTrades ? (
            <>
              <div className={cn("text-sm font-bold font-mono", pnlColor(pnl))}>
                {pnl >= 0 ? "+" : ""}{fmt$(pnl, 0)}
              </div>
              <div className="text-[10px] text-[#475569] mt-0.5">{stats.trades} trades · {wr}% win</div>
            </>
          ) : (
            <div className="text-[10px] text-[#475569]">No closed trades yet</div>
          )}
          <div className="flex gap-2 mt-2">
            {openCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22C55E]/10 text-[#22C55E] border border-emerald-400/20">
                {openCount} open
              </span>
            )}
            {watchCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-400/10 text-blue-400 border border-blue-400/20">
                {watchCount} watching
              </span>
            )}
            {openCount === 0 && watchCount === 0 && (
              <span className="text-[10px] text-[#475569]">idle</span>
            )}
          </div>
        </div>
      </button>

      {/* Info button — outside card button to avoid nested-button HTML issue */}
      <div
        role="button"
        tabIndex={0}
        onClick={onInfo}
        onKeyDown={(e) => e.key === "Enter" && onInfo()}
        className="absolute top-2.5 right-2.5 p-1 rounded text-[#475569] hover:text-[#94A3B8] transition-colors cursor-pointer z-10"
        title="How this strategy works"
      >
        <Info size={12} />
      </div>
    </div>
  );
}

function StrategyInfoModal({ strategyKey, onClose }: { strategyKey: string; onClose: () => void }) {
  const strategy = STRATEGIES.find((s) => s.key === strategyKey);
  const detail = STRATEGY_DETAIL[strategyKey];
  if (!strategy) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-[#020617]/70 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-xl rounded-2xl border border-[#334155] bg-[#1E293B] shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Color bar */}
        <div className="h-1" style={{ backgroundColor: strategy.color }} />

        {/* Scrollable body */}
        <div className="max-h-[80vh] overflow-y-auto p-6">
          <div className="flex items-start justify-between gap-3 mb-5">
            <div>
              <div className="text-[10px] text-[#475569] uppercase tracking-widest mb-1">{strategy.category} Strategy</div>
              <h2 className="text-xl font-bold text-white">{strategy.label}</h2>
            </div>
            <button onClick={onClose} className="text-[#475569] hover:text-[#F8FAFC] transition-colors shrink-0 mt-1">
              <X size={16} />
            </button>
          </div>

          {detail ? (
            <div className="space-y-5">
              {/* Summary */}
              <p className="text-sm text-[#F8FAFC] leading-relaxed font-medium">{detail.summary}</p>

              {/* How it works */}
              <div>
                <div className="text-[11px] font-semibold text-[#94A3B8] uppercase tracking-wider mb-2">How it works</div>
                <p className="text-sm text-[#94A3B8] leading-relaxed">{detail.howItWorks}</p>
              </div>

              {/* What it looks for */}
              <div>
                <div className="text-[11px] font-semibold text-[#94A3B8] uppercase tracking-wider mb-2">What it looks for</div>
                <ul className="space-y-1.5">
                  {detail.signals.map((s, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-[#94A3B8]">
                      <span className="mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full" style={{ backgroundColor: strategy.color }} />
                      {s}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Best in / Risk — side by side */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-[#334155]/60 border border-[#334155]/50 p-3">
                  <div className="text-[10px] font-semibold text-[#22C55E] uppercase tracking-wider mb-1.5">Best market for this</div>
                  <p className="text-xs text-[#94A3B8] leading-relaxed">{detail.bestIn}</p>
                </div>
                <div className="rounded-xl bg-[#334155]/60 border border-[#334155]/50 p-3">
                  <div className="text-[10px] font-semibold text-[#EF4444] uppercase tracking-wider mb-1.5">Main risk</div>
                  <p className="text-xs text-[#94A3B8] leading-relaxed">{detail.risk}</p>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-[#94A3B8]">No description available.</p>
          )}

          <div className="mt-6 pt-4 border-t border-[#334155] flex justify-end">
            <button
              onClick={onClose}
              className="text-xs px-4 py-2 rounded-lg bg-[#334155] text-[#94A3B8] hover:bg-[#1E293B] transition-colors"
            >
              Got it
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Symbol Cell (clickable) ──────────────────────────────────────────────────

function SymCell({ symbol, preset, onClick }: { symbol: string; preset: string; onClick: () => void }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      className="flex items-center gap-1.5 group text-left"
    >
      <div>
        <div className="font-mono font-bold text-white group-hover:text-[#22C55E] transition-colors">
          {symbol}
        </div>
        {TICKER_NAMES[symbol] && (
          <div className="text-[11px] text-[#475569] truncate max-w-[140px]">{TICKER_NAMES[symbol]}</div>
        )}
        <SectorPill symbol={symbol} className="mt-0.5" />
      </div>
      <ExternalLink size={10} className="text-[#475569] group-hover:text-[#22C55E] transition-colors shrink-0" />
    </button>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function StrategyLab() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [runningNow, setRunningNow] = useState(false);
  const [activeTab, setActiveTab] = useState<"open" | "watching" | "closed" | "log">("open");
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<EnrichedTrade | null>(null);
  const [infoModal, setInfoModal] = useState<string | null>(null);
  const [showAllStrategies, setShowAllStrategies] = useState(false);

  const { data: tradesData }     = useQuery({ queryKey: ["strategy-trades"],     queryFn: getTrades,        refetchInterval: 60_000,  staleTime: 55_000 });
  const { data: candidatesData } = useQuery({ queryKey: ["strategy-candidates"], queryFn: getCandidates,    refetchInterval: 60_000,  staleTime: 55_000 });
  const { data: summaryData }    = useQuery({ queryKey: ["strategy-summary"],    queryFn: getSummary,       refetchInterval: 60_000,  staleTime: 55_000 });
  const { data: logData }        = useQuery({ queryKey: ["strategy-log"],        queryFn: () => getLog(80), refetchInterval: 60_000,  staleTime: 55_000 });
  const { data: equityData }     = useQuery({ queryKey: ["strategy-equity"],     queryFn: getEquity,        refetchInterval: 300_000, staleTime: 290_000 });
  const { data: regimeData }     = useQuery({ queryKey: ["strategy-regime"],     queryFn: getRegime,        refetchInterval: 300_000, staleTime: 290_000 });

  const closeMut = useMutation({
    mutationFn: (id: number) => closeTrade(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-trades"] });
      qc.invalidateQueries({ queryKey: ["strategy-summary"] });
      toast.success("Position closed");
    },
  });

  const handleRunNow = async () => {
    setRunningNow(true);
    try {
      await runNow();
      toast.success("Daily run started — log updates in ~2 min", { duration: 5000 });
      setTimeout(() => {
        ["strategy-trades", "strategy-candidates", "strategy-summary", "strategy-log", "strategy-equity"]
          .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      }, 120_000);
    } catch { toast.error("Failed to start run"); }
    finally { setRunningNow(false); }
  };

  const goToChart = (
    symbol: string,
    preset: string,
    levels?: { entry?: number | null; stop?: number | null; target?: number | null; entryDate?: string | null },
  ) => {
    const p = new URLSearchParams({ symbol, preset });
    if (levels?.entry)     p.set("entry",     levels.entry.toString());
    if (levels?.stop)      p.set("stop",      levels.stop.toString());
    if (levels?.target)    p.set("target",    levels.target.toString());
    if (levels?.entryDate) p.set("entryDate", levels.entryDate);
    navigate(`/chart?${p}`);
  };

  // Data
  const trades: any[]     = tradesData?.trades ?? [];
  const candidates: any[] = candidatesData?.candidates ?? [];
  const overall           = summaryData?.overall ?? {};
  const byPreset: any[]   = summaryData?.by_preset ?? [];
  const logEntries: any[] = logData?.log ?? [];
  const equityPts: any[]  = equityData?.equity ?? [];
  const baseline: number  = equityData?.baseline ?? 100_000;
  const regime: string    = regimeData?.regime ?? "unknown";

  const openTrades   = trades.filter((t) => t.status === "open");
  const closedTrades = trades.filter((t) => t.status === "closed" && t.exit_reason !== "expired");

  const portfolioValue = overall.portfolio_value ?? baseline;
  const totalReturn    = portfolioValue - baseline;
  const totalReturnPct = (totalReturn / baseline) * 100;

  // Per-strategy quick lookup
  const presetStatsMap = useMemo(() => {
    const m: Record<string, any> = {};
    byPreset.forEach((s) => { m[s.preset_key] = s; });
    return m;
  }, [byPreset]);

  const openByPreset = useMemo(() => {
    const m: Record<string, number> = {};
    openTrades.forEach((t) => { m[t.preset_key] = (m[t.preset_key] ?? 0) + 1; });
    return m;
  }, [openTrades]);

  const watchByPreset = useMemo(() => {
    const m: Record<string, number> = {};
    candidates.forEach((t) => { m[t.preset_key] = (m[t.preset_key] ?? 0) + 1; });
    return m;
  }, [candidates]);

  // Filter by selected strategy
  const filteredOpen   = selectedStrategy ? openTrades.filter((t) => t.preset_key === selectedStrategy) : openTrades;
  const filteredWatch  = selectedStrategy ? candidates.filter((t) => t.preset_key === selectedStrategy) : candidates;
  const filteredClosed = selectedStrategy ? closedTrades.filter((t) => t.preset_key === selectedStrategy) : closedTrades;
  const filteredLog    = selectedStrategy ? logEntries.filter((e) => e.preset_key === selectedStrategy) : logEntries;

  const tabs = [
    { key: "open",     label: "Open",     count: filteredOpen.length },
    { key: "watching", label: "Watching", count: filteredWatch.length },
    { key: "closed",   label: "Closed",   count: filteredClosed.length },
    { key: "log",      label: "Daily Log", count: filteredLog.length },
  ] as const;

  return (
    <div className="space-y-5">

      {/* ── Top bar ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <FlaskConical size={18} className="text-[#94A3B8]" />
          <span className="text-base font-bold text-white">Strategy Lab</span>
          <span className="text-[11px] text-[#475569] hidden md:block">· 19 strategies · $100k paper · auto-runs 4:05 PM ET</span>
        </div>
        <div className="flex items-center gap-2">
          <RegimePill regime={regime} />
          <button
            onClick={handleRunNow}
            disabled={runningNow}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-[#334155] text-[#94A3B8] hover:text-[#F8FAFC] hover:border-zinc-500 transition-colors disabled:opacity-40"
          >
            <Play size={11} className={runningNow ? "animate-pulse" : ""} />
            {runningNow ? "Running…" : "Run Now"}
          </button>
        </div>
      </div>

      {/* ── Portfolio hero ─────────────────────────────────────────── */}
      <div className="bg-[#1E293B]/60 border border-[#334155] rounded-2xl p-5">
        <div className="flex flex-col md:flex-row md:items-end gap-4 mb-4">
          <div>
            <div className="text-xs text-[#475569] mb-1">Paper Portfolio Value</div>
            <div className="text-4xl font-bold text-white tracking-tight font-mono">
              ${portfolioValue.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className={cn("flex items-center gap-1.5 text-sm font-semibold mt-1 font-mono", pnlColor(totalReturn))}>
              {totalReturn >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              {totalReturn >= 0 ? "+" : ""}{fmt$(totalReturn)} ({totalReturnPct >= 0 ? "+" : ""}{totalReturnPct.toFixed(2)}%)
              <span className="text-[#475569] font-normal text-xs">total return</span>
            </div>
          </div>
          <div className="flex-1 min-h-0">
            <EquityCurve data={equityPts} baseline={baseline} />
          </div>
        </div>

        {/* Stat pills */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <StatPill label="Open P&L"    value={`${overall.open_pnl >= 0 ? "+" : ""}${fmt$(overall.open_pnl)}`} color={pnlColor(overall.open_pnl)} />
          <StatPill label="Win Rate"    value={overall.total_closed > 0 ? `${overall.win_rate}%` : "—"} sub={overall.total_closed > 0 ? `${overall.wins}W · ${overall.losses}L` : "no closed trades"} />
          <StatPill label="Expectancy"  value={overall.total_closed > 0 ? fmtPct(overall.expectancy) : "—"} color={pnlColor(overall.expectancy)} sub="avg per trade" />
          <StatPill label="Max Drawdown" value={overall.max_drawdown_pct > 0 ? `-${overall.max_drawdown_pct?.toFixed(1)}%` : "—"} color={overall.max_drawdown_pct > 15 ? "text-[#EF4444]" : "text-[#94A3B8]"} />
          <StatPill label="Positions"   value={`${overall.open_positions ?? openTrades.length} open · ${overall.candidates ?? candidates.length} watching`} />
        </div>
      </div>

      {/* ── Strategy cards ─────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] text-[#475569] uppercase tracking-widest">Strategies</span>
          <div className="flex items-center gap-3">
            {selectedStrategy && (
              <button onClick={() => setSelectedStrategy(null)} className="text-xs text-[#475569] hover:text-[#F8FAFC] flex items-center gap-1">
                <X size={11} /> Clear filter
              </button>
            )}
          </div>
        </div>
        {(() => {
          const sorted = [...STRATEGIES].sort((a, b) => {
            const aOpen = openByPreset[a.key] ?? 0;
            const bOpen = openByPreset[b.key] ?? 0;
            const aWatch = watchByPreset[a.key] ?? 0;
            const bWatch = watchByPreset[b.key] ?? 0;
            if (aOpen !== bOpen) return bOpen - aOpen;
            if (aWatch !== bWatch) return bWatch - aWatch;
            return 0;
          });
          const visible = showAllStrategies ? sorted : sorted.slice(0, 5);
          return (
            <>
              <div className="flex flex-wrap gap-2.5">
                {visible.map((s) => (
                  <StrategyCard
                    key={s.key}
                    strategy={s}
                    stats={presetStatsMap[s.key]}
                    openCount={openByPreset[s.key] ?? 0}
                    watchCount={watchByPreset[s.key] ?? 0}
                    selected={selectedStrategy === s.key}
                    onClick={() => setSelectedStrategy(selectedStrategy === s.key ? null : s.key)}
                    onInfo={() => setInfoModal(s.key)}
                  />
                ))}
              </div>
              <button
                onClick={() => setShowAllStrategies((v) => !v)}
                className="mt-3 text-xs text-[#475569] hover:text-[#F8FAFC] transition-colors flex items-center gap-1.5"
              >
                {showAllStrategies
                  ? <><X size={11} /> Show less</>
                  : <><span className="text-[#475569]">+{STRATEGIES.length - 5} more</span> · View all {STRATEGIES.length} strategies</>
                }
              </button>
            </>
          );
        })()}
      </div>

      {/* ── Tabs + tables ──────────────────────────────────────────── */}
      <div className="bg-[#1E293B]/40 border border-[#334155] rounded-2xl overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b border-[#334155] bg-[#1E293B]/60">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px",
                activeTab === tab.key
                  ? "border-white text-white bg-white/3"
                  : "border-transparent text-[#475569] hover:text-[#94A3B8]"
              )}
            >
              {tab.label}
              {tab.count > 0 && (
                <span className={cn(
                  "ml-2 text-[10px] px-1.5 py-0.5 rounded-full",
                  activeTab === tab.key ? "bg-white/10 text-[#94A3B8]" : "bg-[#334155] text-[#475569]"
                )}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="p-4">
          {/* Open Positions */}
          {activeTab === "open" && (
            filteredOpen.length === 0
              ? <Empty icon={<BarChart2 size={32} />} text="No open positions" sub={selectedStrategy ? "No open trades for this strategy" : "Positions open when entry triggers fire"} />
              : <OpenTable trades={filteredOpen} onClose={(id) => closeMut.mutate(id)} onChart={goToChart} onRowClick={(t) => setSelectedTrade(t)} />
          )}

          {/* Watching / Candidates */}
          {activeTab === "watching" && (
            filteredWatch.length === 0
              ? <Empty icon={<Eye size={32} />} text="Nothing on the watchlist" sub={selectedStrategy ? "No candidates for this strategy" : "Run automation to start scanning"} />
              : <WatchTable candidates={filteredWatch} onChart={goToChart} />
          )}

          {/* Closed */}
          {activeTab === "closed" && (
            <>
              {filteredClosed.length === 0
                ? <Empty icon={<CheckCircle2 size={32} />} text="No closed trades" sub="Positions close via stop, target, or time limit" />
                : <ClosedTable trades={filteredClosed} onChart={goToChart} />
              }
              {byPreset.length > 0 && !selectedStrategy && (
                <PerformanceTable byPreset={byPreset} />
              )}
            </>
          )}

          {/* Daily Log */}
          {activeTab === "log" && (
            filteredLog.length === 0
              ? <Empty icon={<RefreshCw size={32} />} text="No log entries" sub='Click "Run Now" to kick off the first scan' />
              : <div className="space-y-0.5 max-h-[600px] overflow-y-auto">
                  {filteredLog.map((e) => <LogRow key={e.id} entry={e} />)}
                </div>
          )}
        </div>
      </div>

      {/* ── Backtest section ────────────────────────────────────── */}
      <BacktestSection />

      <TradeDetailDrawer trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
      {infoModal && <StrategyInfoModal strategyKey={infoModal} onClose={() => setInfoModal(null)} />}
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

// ─── Backtest Section ─────────────────────────────────────────────────────────

function BacktestEquityCurve({ data, baseline }: { data: { date: string; value: number }[]; baseline: number }) {
  if (data.length < 2) return null;
  const vals = data.map((d) => d.value);
  const min = Math.min(...vals) * 0.998;
  const max = Math.max(...vals) * 1.002;
  const range = max - min || 1;
  const W = 800; const H = 80; const pad = 2;
  const pts = data.map((d, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2);
    const y = H - pad - ((d.value - min) / range) * (H - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = vals[vals.length - 1];
  const isPos = last >= baseline;
  const stroke = isPos ? "#10b981" : "#ef4444";
  const fill   = isPos ? "rgba(16,185,129,0.07)" : "rgba(239,68,68,0.07)";
  const baseY  = H - pad - ((baseline - min) / range) * (H - pad * 2);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20" preserveAspectRatio="none">
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="#3f3f46" strokeWidth={0.8} strokeDasharray="4,3" />
      <path d={`M ${pts[0]} L ${pts.join(" L ")} L ${W - pad},${H - pad} L ${pad},${H - pad} Z`} fill={fill} />
      <polyline points={pts.join(" ")} fill="none" stroke={stroke} strokeWidth={1.5} />
    </svg>
  );
}

function BacktestSection() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<string | null>(null);
  const [periodYears, setPeriodYears] = useState(3);
  const [launching, setLaunching] = useState(false);

  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["backtest-status"],
    queryFn: getBacktestStatus,
    refetchInterval: (q) => (q.state.data?.running ? 5_000 : false),
  });

  const { data: results } = useQuery({
    queryKey: ["backtest-results"],
    queryFn: getBacktestResults,
    enabled: status?.available === true,
    staleTime: Infinity,
  });

  const { data: detail } = useQuery({
    queryKey: ["backtest-detail", selectedKey],
    queryFn: () => getBacktestDetail(selectedKey!),
    enabled: !!selectedKey,
    staleTime: Infinity,
  });

  // Group all trades by company whenever detail changes
  const companies = useMemo(() => {
    if (!detail?.trades) return [];
    const map = new Map<string, { trades: any[]; wins: number; losses: number; totalPnl: number }>();
    for (const t of detail.trades) {
      if (!map.has(t.symbol)) map.set(t.symbol, { trades: [], wins: 0, losses: 0, totalPnl: 0 });
      const entry = map.get(t.symbol)!;
      entry.trades.push(t);
      const pnl = t.pnl_pct ?? 0;
      entry.totalPnl += pnl;
      if (pnl >= 0) entry.wins++; else entry.losses++;
    }
    return Array.from(map.entries())
      .map(([sym, data]) => ({
        symbol: sym,
        name: COMPANY_INFO[sym]?.name ?? sym,
        sector: COMPANY_INFO[sym]?.sector ?? "Unknown",
        tradeCount: data.trades.length,
        wins: data.wins,
        losses: data.losses,
        winRate: +(data.wins / data.trades.length * 100).toFixed(1),
        avgPnl: +(data.totalPnl / data.trades.length).toFixed(2),
        totalPnl: +data.totalPnl.toFixed(2),
        trades: [...data.trades].sort((a, b) => (a.entry_date < b.entry_date ? 1 : -1)),
      }))
      .sort((a, b) => b.tradeCount - a.tradeCount);
  }, [detail?.trades]);

  const handleRun = async () => {
    setLaunching(true);
    try {
      await runBacktest(periodYears);
      toast.success("Backtest started — takes 1–3 min. Results will appear automatically.", { duration: 6000 });
      refetchStatus();
    } catch (e: any) {
      if (e?.response?.status === 409) toast.error("Backtest already running");
      else toast.error("Failed to start backtest");
    } finally {
      setLaunching(false);
    }
  };

  // Auto-refresh results when run completes
  const wasRunning = status?.running;
  const { data: prevStatus } = useQuery({ queryKey: ["backtest-status"], queryFn: getBacktestStatus, staleTime: Infinity });
  if (wasRunning === false && prevStatus?.running === true) {
    qc.invalidateQueries({ queryKey: ["backtest-results"] });
  }

  const strategies = results?.strategies ?? [];
  const best  = strategies[0];
  const worst = strategies[strategies.length - 1];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BarChart2 size={16} className="text-[#94A3B8]" />
            <span className="text-base font-bold text-white">Historical Backtests</span>
          </div>
          <p className="text-[11px] text-[#475569] mt-0.5">
            How each strategy performed on {BACKTEST_UNIVERSE_SIZE} liquid stocks over the selected period
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Period picker */}
          <div className="flex items-center gap-1 bg-[#1E293B] border border-[#334155] rounded-lg p-0.5">
            {[1, 3, 5].map((y) => (
              <button
                key={y}
                onClick={() => setPeriodYears(y)}
                className={cn(
                  "text-xs px-2.5 py-1 rounded-md transition-colors",
                  periodYears === y ? "bg-[#1E293B] text-white" : "text-[#475569] hover:text-[#94A3B8]"
                )}
              >{y}Y</button>
            ))}
          </div>
          <button
            onClick={handleRun}
            disabled={launching || status?.running}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-[#334155] text-[#94A3B8] hover:text-[#F8FAFC] hover:border-zinc-500 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={11} className={status?.running || launching ? "animate-spin" : ""} />
            {status?.running ? "Running…" : "Run Backtest"}
          </button>
        </div>
      </div>

      {/* Empty / running state */}
      {!status?.available && (
        <div className="bg-[#1E293B]/40 border border-[#334155] rounded-2xl p-12 flex flex-col items-center gap-3 text-center">
          <BarChart2 size={36} className="text-[#475569]" />
          <p className="text-[#94A3B8] font-medium text-sm">No backtest results yet</p>
          <p className="text-[#475569] text-xs max-w-sm">
            Click "Run Backtest" to simulate all 19 strategies against 3 years of historical data.
            Takes 1–3 minutes. Results are cached so you only need to rerun when you want fresh data.
          </p>
          {status?.running && (
            <div className="flex items-center gap-2 text-xs text-amber-400 mt-2">
              <RefreshCw size={12} className="animate-spin" /> Running now — this page will update automatically…
            </div>
          )}
        </div>
      )}

      {status?.available && strategies.length > 0 && (
        <>
          {/* Summary pills */}
          {best && worst && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2.5">
                <div className="text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">Best Strategy</div>
                <div className="text-sm font-bold text-[#22C55E]">{best.strategy_label}</div>
                <div className="text-[10px] text-[#475569]">{best.total_return_pct > 0 ? "+" : ""}{best.total_return_pct}% over {results.period_years}Y</div>
              </div>
              <div className="bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2.5">
                <div className="text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">Worst Strategy</div>
                <div className="text-sm font-bold text-[#EF4444]">{worst.strategy_label}</div>
                <div className="text-[10px] text-[#475569]">{worst.total_return_pct > 0 ? "+" : ""}{worst.total_return_pct}% over {results.period_years}Y</div>
              </div>
              <div className="bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2.5">
                <div className="text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">Avg Win Rate</div>
                <div className="text-sm font-bold text-white font-mono">
                  {(strategies.reduce((a: number, s: any) => a + s.win_rate, 0) / strategies.length).toFixed(1)}%
                </div>
                <div className="text-[10px] text-[#475569]">across all strategies</div>
              </div>
              <div className="bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2.5">
                <div className="text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">Last Run</div>
                <div className="text-sm font-bold text-white">
                  {results.run_date ? new Date(results.run_date).toLocaleDateString() : "—"}
                </div>
                <div className="text-[10px] text-[#475569]">{results.period_years}Y period · {BACKTEST_UNIVERSE_SIZE} stocks</div>
              </div>
            </div>
          )}

          {/* Comparison table */}
          <div className="bg-[#1E293B]/40 border border-[#334155] rounded-2xl overflow-hidden">
            <div className="px-5 py-3 border-b border-[#334155] text-[11px] text-[#475569] uppercase tracking-widest">
              Strategy Comparison — {results.period_years}-Year Backtest
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#334155]/60">
                    <th className="px-4 py-2.5 text-left text-[11px] text-[#475569] font-medium uppercase tracking-wider">Strategy</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Total Return</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">CAGR</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Win Rate</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Avg Win</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Avg Loss</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Max DD</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Sharpe</th>
                    <th className="px-4 py-2.5 text-right text-[11px] text-[#475569] font-medium uppercase tracking-wider">Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((s: any, i: number) => {
                    const strat = STRATEGIES.find((x) => x.key === s.strategy_key);
                    const isSelected = selectedKey === s.strategy_key;
                    const ret = s.total_return_pct ?? 0;
                    return (
                      <tr
                        key={s.strategy_key}
                        onClick={() => { setSelectedKey(isSelected ? null : s.strategy_key); setSelectedCompany(null); }}
                        className={cn(
                          "border-b border-[#334155]/40 cursor-pointer transition-colors",
                          isSelected ? "bg-white/4" : "hover:bg-white/2"
                        )}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] text-[#475569] font-mono w-4">#{i + 1}</span>
                            <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: strat?.color ?? "#666" }} />
                            <span className="text-xs font-medium text-[#F8FAFC]">{s.strategy_label}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-sm font-bold">
                          <span className={ret >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}>
                            {ret >= 0 ? "+" : ""}{ret}%
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-xs text-[#94A3B8]">
                          {(s.cagr ?? 0) >= 0 ? "+" : ""}{s.cagr ?? 0}%
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-12 h-1 rounded-full bg-[#334155] overflow-hidden">
                              <div className="h-full rounded-full bg-[#22C55E]" style={{ width: `${s.win_rate ?? 0}%` }} />
                            </div>
                            <span className={cn("text-xs font-mono", (s.win_rate ?? 0) >= 50 ? "text-[#22C55E]" : "text-[#EF4444]")}>
                              {s.win_rate ?? 0}%
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-xs text-[#22C55E]">
                          +{s.avg_win_pct ?? 0}%
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-xs text-[#EF4444]">
                          {s.avg_loss_pct ?? 0}%
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-xs text-[#94A3B8]">
                          -{s.max_drawdown_pct ?? 0}%
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-xs text-[#94A3B8]">
                          {s.sharpe_ratio ?? 0}
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-[#475569]">
                          {s.total_trades ?? 0}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Detail panel */}
          {selectedKey && detail && (
            <div className="bg-[#1E293B]/40 border border-[#334155] rounded-2xl p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <div className="text-[10px] text-[#475569] uppercase tracking-widest mb-1">Backtest Detail</div>
                  <div className="text-base font-bold text-white">{detail.strategy_label}</div>
                </div>
                <button onClick={() => { setSelectedKey(null); setSelectedCompany(null); }} className="text-[#475569] hover:text-[#F8FAFC] transition-colors">
                  <X size={14} />
                </button>
              </div>

              {/* Equity curve */}
              <div className="mb-4">
                <div className="text-[10px] text-[#475569] mb-1">Equity Curve — $100k starting capital</div>
                <BacktestEquityCurve data={detail.equity_curve ?? []} baseline={100_000} />
              </div>

              {/* Metric pills */}
              <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-4">
                {[
                  { label: "Total Return", value: `${(detail.metrics?.total_return_pct ?? 0) >= 0 ? "+" : ""}${detail.metrics?.total_return_pct ?? 0}%`, color: (detail.metrics?.total_return_pct ?? 0) >= 0 ? "text-[#22C55E]" : "text-[#EF4444]" },
                  { label: "CAGR",         value: `${(detail.metrics?.cagr ?? 0) >= 0 ? "+" : ""}${detail.metrics?.cagr ?? 0}%` },
                  { label: "Win Rate",     value: `${detail.metrics?.win_rate ?? 0}%`, color: (detail.metrics?.win_rate ?? 0) >= 50 ? "text-[#22C55E]" : "text-[#EF4444]" },
                  { label: "Profit Factor", value: `${detail.metrics?.profit_factor ?? 0}x` },
                  { label: "Max Drawdown", value: `-${detail.metrics?.max_drawdown_pct ?? 0}%`, color: "text-[#EF4444]" },
                  { label: "Sharpe Ratio", value: `${detail.metrics?.sharpe_ratio ?? 0}` },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2.5">
                    <div className="text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">{label}</div>
                    <div className={cn("text-sm font-bold font-mono", color ?? "text-white")}>{value}</div>
                  </div>
                ))}
              </div>

              {/* Company list / Trade log */}
              {companies.length > 0 && (
                <div>
                  {!selectedCompany ? (
                    /* ── Company list ── */
                    <>
                      <div className="text-[10px] text-[#475569] uppercase tracking-widest mb-2">
                        Companies Traded — {companies.length} stocks · click to view trade log
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[#334155]/60">
                              <th className="px-3 py-2 text-left text-[10px] text-[#475569] font-medium uppercase tracking-wider">Symbol</th>
                              <th className="px-3 py-2 text-left text-[10px] text-[#475569] font-medium uppercase tracking-wider">Company</th>
                              <th className="px-3 py-2 text-left text-[10px] text-[#475569] font-medium uppercase tracking-wider">Sector</th>
                              <th className="px-3 py-2 text-right text-[10px] text-[#475569] font-medium uppercase tracking-wider">Trades</th>
                              <th className="px-3 py-2 text-right text-[10px] text-[#475569] font-medium uppercase tracking-wider">Win Rate</th>
                              <th className="px-3 py-2 text-right text-[10px] text-[#475569] font-medium uppercase tracking-wider">Avg Return</th>
                            </tr>
                          </thead>
                          <tbody>
                            {companies.map((c) => (
                              <tr
                                key={c.symbol}
                                onClick={() => setSelectedCompany(c.symbol)}
                                className="border-b border-[#334155]/30 hover:bg-white/4 transition-colors cursor-pointer group"
                              >
                                <td className="px-3 py-2 font-mono font-bold text-white group-hover:text-blue-300 transition-colors">{c.symbol}</td>
                                <td className="px-3 py-2 text-[#94A3B8] text-[11px]">{c.name}</td>
                                <td className="px-3 py-2">
                                  <span
                                    className="text-[10px] font-medium px-1.5 py-0.5 rounded-full"
                                    style={{
                                      backgroundColor: (SECTOR_COLOR[c.sector] ?? "#6b7280") + "22",
                                      color: SECTOR_COLOR[c.sector] ?? "#9ca3af",
                                    }}
                                  >{c.sector}</span>
                                </td>
                                <td className="px-3 py-2 text-right text-[#94A3B8] font-mono">{c.tradeCount}</td>
                                <td className="px-3 py-2 text-right">
                                  <div className="flex items-center justify-end gap-1.5">
                                    <div className="w-10 h-1 rounded-full bg-[#334155] overflow-hidden">
                                      <div className="h-full rounded-full bg-[#22C55E]" style={{ width: `${c.winRate}%` }} />
                                    </div>
                                    <span className={cn("font-mono text-[11px]", c.winRate >= 50 ? "text-[#22C55E]" : "text-[#EF4444]")}>
                                      {c.winRate}%
                                    </span>
                                  </div>
                                </td>
                                <td className={cn("px-3 py-2 text-right font-mono font-bold text-[11px]", c.avgPnl >= 0 ? "text-[#22C55E]" : "text-[#EF4444]")}>
                                  {c.avgPnl >= 0 ? "+" : ""}{c.avgPnl}%
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    /* ── Trade log for selected company ── */
                    (() => {
                      const co = companies.find((c) => c.symbol === selectedCompany);
                      if (!co) return null;
                      return (
                        <>
                          <div className="flex items-center gap-3 mb-3">
                            <button
                              onClick={() => setSelectedCompany(null)}
                              className="text-[11px] text-[#475569] hover:text-[#F8FAFC] transition-colors flex items-center gap-1"
                            >
                              ← Companies
                            </button>
                            <span className="text-[#475569]">·</span>
                            <span className="font-mono font-bold text-white text-sm">{co.symbol}</span>
                            <span className="text-[#94A3B8] text-[11px]">{co.name}</span>
                            <span
                              className="text-[10px] font-medium px-1.5 py-0.5 rounded-full"
                              style={{
                                backgroundColor: (SECTOR_COLOR[co.sector] ?? "#6b7280") + "22",
                                color: SECTOR_COLOR[co.sector] ?? "#9ca3af",
                              }}
                            >{co.sector}</span>
                            <span className="ml-auto text-[10px] text-[#475569]">{co.tradeCount} trades · {co.winRate}% win rate</span>
                          </div>
                          <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-[#334155]/60">
                                  <th className="px-3 py-2 text-left text-[10px] text-[#475569] font-medium uppercase tracking-wider">Entry Date</th>
                                  <th className="px-3 py-2 text-left text-[10px] text-[#475569] font-medium uppercase tracking-wider">Exit Date</th>
                                  <th className="px-3 py-2 text-right text-[10px] text-[#475569] font-medium uppercase tracking-wider">Entry $</th>
                                  <th className="px-3 py-2 text-right text-[10px] text-[#475569] font-medium uppercase tracking-wider">Exit $</th>
                                  <th className="px-3 py-2 text-right text-[10px] text-[#475569] font-medium uppercase tracking-wider">Return</th>
                                  <th className="px-3 py-2 text-left text-[10px] text-[#475569] font-medium uppercase tracking-wider">Outcome</th>
                                </tr>
                              </thead>
                              <tbody>
                                {co.trades.map((t: any, i: number) => {
                                  const params = new URLSearchParams({ symbol: co.symbol });
                                  if (t.entry_price) params.set("entry", String(t.entry_price));
                                  if (t.entry_date)  params.set("entryDate", t.entry_date);
                                  if (t.exit_price)  params.set("exitPrice", String(t.exit_price));
                                  if (t.exit_date)   params.set("exitDate", t.exit_date);
                                  if (t.exit_reason) params.set("exitReason", t.exit_reason);
                                  const reasonLabel = t.exit_reason === "target" ? "Take Profit" : t.exit_reason === "stop" ? "Stop Loss" : "Time Exit";
                                  const reasonColor = t.exit_reason === "target" ? "text-[#22C55E]" : t.exit_reason === "stop" ? "text-[#EF4444]" : "text-amber-400";
                                  return (
                                    <tr
                                      key={i}
                                      onClick={() => navigate(`/chart?${params}`)}
                                      className="border-b border-[#334155]/30 hover:bg-white/4 transition-colors cursor-pointer group"
                                    >
                                      <td className="px-3 py-2 text-[#94A3B8]">{t.entry_date}</td>
                                      <td className="px-3 py-2 text-[#94A3B8]">{t.exit_date ?? "—"}</td>
                                      <td className="px-3 py-2 text-right font-mono text-[#94A3B8]">${t.entry_price}</td>
                                      <td className="px-3 py-2 text-right font-mono text-[#94A3B8]">{t.exit_price ? `$${t.exit_price}` : "—"}</td>
                                      <td className={cn("px-3 py-2 text-right font-mono font-bold", (t.pnl_pct ?? 0) >= 0 ? "text-[#22C55E]" : "text-[#EF4444]")}>
                                        {(t.pnl_pct ?? 0) >= 0 ? "+" : ""}{t.pnl_pct ?? 0}%
                                      </td>
                                      <td className={cn("px-3 py-2 font-medium", reasonColor)}>{reasonLabel}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </>
                      );
                    })()
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const BACKTEST_UNIVERSE_SIZE = 150;

function RegimePill({ regime }: { regime: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    bull:     { label: "Bull Market",   cls: "text-[#22C55E] border-emerald-400/30 bg-[#22C55E]/8",  icon: <TrendingUp size={10} /> },
    risk_off: { label: "Risk Off",      cls: "text-[#EF4444] border-red-400/30 bg-red-400/8",              icon: <TrendingDown size={10} /> },
    unknown:  { label: "Checking…",    cls: "text-[#475569] border-[#334155] bg-[#334155]",                 icon: <AlertTriangle size={10} /> },
  };
  const { label, cls, icon } = map[regime] ?? map.unknown;
  return (
    <div className={cn("flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border font-medium", cls)}>
      {icon}{label}
    </div>
  );
}

const STRATEGY_EXPLAINABLE = new Set(["Sharpe Ratio", "Max Drawdown", "Win Rate", "Expectancy"]);

function StatPill({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2.5">
      <div className="flex items-center gap-1 text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">
        <span>{label}</span>
        {STRATEGY_EXPLAINABLE.has(label) && <ExplainButton term={label} size={10} />}
      </div>
      <div className={cn("text-sm font-bold font-mono leading-tight", color ?? "text-white")}>{value}</div>
      {sub && <div className="text-[10px] text-[#475569] mt-0.5">{sub}</div>}
    </div>
  );
}

function Empty({ icon, text, sub }: { icon: React.ReactNode; text: string; sub: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-[#475569] gap-3">
      {icon}
      <div className="text-center">
        <p className="text-[#94A3B8] font-medium text-sm">{text}</p>
        <p className="text-[#475569] text-xs mt-1">{sub}</p>
      </div>
    </div>
  );
}

function TH({ children }: { children?: React.ReactNode }) {
  return <th className="px-4 py-2.5 text-left text-[11px] text-[#475569] font-medium uppercase tracking-wider">{children}</th>;
}
function TD({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn("px-4 py-3", className)}>{children}</td>;
}

type OnChart = (sym: string, preset: string, levels?: { entry?: number | null; stop?: number | null; target?: number | null; entryDate?: string | null }) => void;

function OpenTable({ trades, onClose, onChart, onRowClick }: { trades: any[]; onClose: (id: number) => void; onChart: OnChart; onRowClick: (t: EnrichedTrade) => void }) {
  const stratMap = useMemo(() => {
    const m: Record<string, typeof STRATEGIES[0]> = {};
    STRATEGIES.forEach((s) => { m[s.key] = s; });
    return m;
  }, []);

  return (
    <div className="overflow-x-auto -mx-4">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-[#334155]/60">
          <TH>Symbol</TH><TH>Strategy</TH><TH>Entry</TH><TH>Current</TH>
          <TH>P&L</TH><TH>Stop / Target</TH><TH>Risk</TH><TH>Days</TH><TH></TH>
        </tr></thead>
        <tbody>
          {trades.map((t) => {
            const pos = (t.pnl_pct ?? 0) >= 0;
            const strat = stratMap[t.preset_key];
            const stopPct = t.entry_price && t.stop_price ? ((t.stop_price - t.entry_price) / t.entry_price * 100) : null;
            const tgtPct  = t.entry_price && t.target_price ? ((t.target_price - t.entry_price) / t.entry_price * 100) : null;
            return (
              <tr key={t.id} onClick={() => onRowClick(t)} className="border-b border-[#334155]/40 hover:bg-white/3 transition-colors cursor-pointer">
                <TD><SymCell symbol={t.symbol} preset={t.preset_key} onClick={() => onChart(t.symbol, t.preset_key, { entry: t.entry_price, stop: t.stop_price, target: t.target_price, entryDate: t.entry_date })} /></TD>
                <TD>
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: strat?.color, backgroundColor: `${strat?.color}15` }}>
                    {t.preset_label}
                  </span>
                </TD>
                <TD>
                  <div className="font-mono text-xs text-[#94A3B8]">{t.entry_price ? `$${t.entry_price.toFixed(2)}` : "—"}</div>
                  {t.entry_date && <div className="text-[10px] text-[#475569]">{new Date(t.entry_date).toLocaleDateString()}</div>}
                </TD>
                <TD className="font-mono text-xs text-[#94A3B8]">{t.current_price ? `$${t.current_price.toFixed(2)}` : "—"}</TD>
                <TD>
                  <div className={cn("font-mono text-sm font-bold", pos ? "text-[#22C55E]" : "text-[#EF4444]")}>
                    {t.pnl_pct != null ? fmtPct(t.pnl_pct) : "—"}
                  </div>
                  {t.pnl != null && <div className={cn("text-[10px] font-mono", pos ? "text-[#22C55E]/60" : "text-[#EF4444]/60")}>{t.pnl >= 0 ? "+" : ""}{fmt$(t.pnl, 0)}</div>}
                </TD>
                <TD className="text-xs font-mono">
                  <span className="text-[#EF4444]/70">{t.stop_price ? `$${t.stop_price.toFixed(2)}` : "—"}</span>
                  {stopPct != null && <span className="text-[#475569] text-[10px]"> ({stopPct.toFixed(1)}%)</span>}
                  <span className="text-[#475569] mx-1.5">/</span>
                  <span className="text-[#22C55E]/70">{t.target_price ? `$${t.target_price.toFixed(2)}` : "—"}</span>
                  {tgtPct != null && <span className="text-[#475569] text-[10px]"> (+{tgtPct.toFixed(1)}%)</span>}
                </TD>
                <TD className="text-xs text-[#475569]">${t.risk_dollars?.toFixed(0) ?? "—"}</TD>
                <TD className="text-xs text-[#475569]">{t.days_held}d</TD>
                <TD>
                  <button onClick={(e) => { e.stopPropagation(); onClose(t.id); }} className="text-[#475569] hover:text-[#EF4444] transition-colors p-1 rounded hover:bg-red-400/10">
                    <X size={13} />
                  </button>
                </TD>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function WatchTable({ candidates, onChart }: { candidates: any[]; onChart: OnChart }) {
  const stratMap = useMemo(() => {
    const m: Record<string, typeof STRATEGIES[0]> = {};
    STRATEGIES.forEach((s) => { m[s.key] = s; });
    return m;
  }, []);

  return (
    <div className="overflow-x-auto -mx-4">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-[#334155]/60">
          <TH>Symbol</TH><TH>Strategy</TH><TH>Current Price</TH><TH>Waiting For</TH><TH>Days Watching</TH>
        </tr></thead>
        <tbody>
          {candidates.map((t) => {
            const strat = stratMap[t.preset_key];
            const triggerLabel = TRIGGER_LABELS[t.entry_trigger ?? ""] ?? t.entry_trigger ?? "auto trigger";
            return (
              <tr key={t.id} className="border-b border-[#334155]/40 hover:bg-white/2 transition-colors">
                <TD><SymCell symbol={t.symbol} preset={t.preset_key} onClick={() => onChart(t.symbol, t.preset_key, { stop: t.stop_price, target: t.target_price })} /></TD>
                <TD>
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: strat?.color, backgroundColor: `${strat?.color}15` }}>
                    {t.preset_label}
                  </span>
                </TD>
                <TD className="font-mono text-xs text-[#94A3B8]">{t.current_price ? `$${t.current_price.toFixed(2)}` : "—"}</TD>
                <TD>
                  <div className="flex items-center gap-1.5 text-xs text-[#94A3B8]">
                    <Clock size={11} className="text-blue-400 shrink-0" />
                    {triggerLabel}
                  </div>
                </TD>
                <TD className="text-xs text-[#475569]">{t.days_held}d</TD>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ClosedTable({ trades, onChart }: { trades: any[]; onChart: OnChart }) {
  const stratMap = useMemo(() => {
    const m: Record<string, typeof STRATEGIES[0]> = {};
    STRATEGIES.forEach((s) => { m[s.key] = s; });
    return m;
  }, []);

  return (
    <div className="overflow-x-auto -mx-4">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-[#334155]/60">
          <TH>Closed</TH><TH>Symbol</TH><TH>Strategy</TH><TH>Entry → Exit</TH>
          <TH>P&L</TH><TH>Days</TH><TH>Outcome</TH>
        </tr></thead>
        <tbody>
          {trades.slice(0, 40).map((t) => {
            const badge = EXIT_BADGE[t.exit_reason ?? "manual"] ?? EXIT_BADGE.manual;
            const pos = (t.pnl_pct ?? 0) >= 0;
            const strat = stratMap[t.preset_key];
            return (
              <tr key={t.id} className="border-b border-[#334155]/40 hover:bg-white/2 transition-colors">
                <TD className="text-xs text-[#475569]">{t.exit_date ? new Date(t.exit_date).toLocaleDateString() : "—"}</TD>
                <TD><SymCell symbol={t.symbol} preset={t.preset_key} onClick={() => onChart(t.symbol, t.preset_key, { entry: t.entry_price, stop: t.stop_price, target: t.target_price, entryDate: t.entry_date })} /></TD>
                <TD>
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: strat?.color, backgroundColor: `${strat?.color}15` }}>
                    {t.preset_label}
                  </span>
                </TD>
                <TD className="font-mono text-xs text-[#94A3B8]">
                  {t.entry_price ? `$${t.entry_price.toFixed(2)}` : "—"} → {t.exit_price ? `$${t.exit_price.toFixed(2)}` : "—"}
                </TD>
                <TD>
                  <div className={cn("font-mono text-sm font-bold", pos ? "text-[#22C55E]" : "text-[#EF4444]")}>
                    {t.pnl_pct != null ? fmtPct(t.pnl_pct) : "—"}
                  </div>
                </TD>
                <TD className="text-xs text-[#475569]">{t.days_held}d</TD>
                <TD>
                  <span className={cn("text-[11px] px-2 py-0.5 rounded-full border", badge.cls)}>{badge.label}</span>
                </TD>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PerformanceTable({ byPreset }: { byPreset: any[] }) {
  return (
    <div className="mt-6 -mx-4">
      <div className="px-4 mb-3 text-[11px] text-[#475569] uppercase tracking-widest">Performance by Strategy</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-[#334155]/60">
            <TH>Strategy</TH><TH>Trades</TH><TH>Win Rate</TH><TH>Avg Win</TH><TH>Avg Loss</TH><TH>Total P&L</TH>
          </tr></thead>
          <tbody>
            {byPreset.map((s) => {
              const strat = STRATEGIES.find((x) => x.key === s.preset_key);
              return (
                <tr key={s.preset_key} className="border-b border-[#334155]/40 hover:bg-white/2">
                  <TD>
                    <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: strat?.color ?? "#fff", backgroundColor: `${strat?.color ?? "#fff"}15` }}>
                      {s.preset_label}
                    </span>
                  </TD>
                  <TD className="text-xs text-[#94A3B8]">{s.trades}</TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 rounded-full bg-[#334155] overflow-hidden">
                        <div className="h-full rounded-full bg-[#22C55E]" style={{ width: `${s.win_rate}%` }} />
                      </div>
                      <span className={cn("text-xs font-bold", s.win_rate >= 50 ? "text-[#22C55E]" : "text-[#EF4444]")}>{s.win_rate}%</span>
                    </div>
                  </TD>
                  <TD className="text-xs font-mono text-[#22C55E]">{s.avg_win_pct > 0 ? `+${s.avg_win_pct.toFixed(1)}%` : "—"}</TD>
                  <TD className="text-xs font-mono text-[#EF4444]">{s.avg_loss_pct < 0 ? `${s.avg_loss_pct.toFixed(1)}%` : "—"}</TD>
                  <TD className={cn("text-sm font-bold font-mono", s.total_pnl >= 0 ? "text-[#22C55E]" : "text-[#EF4444]")}>
                    {s.total_pnl >= 0 ? "+" : ""}{fmt$(s.total_pnl, 0)}
                  </TD>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LogRow({ entry }: { entry: any }) {
  const icons: Record<string, React.ReactNode> = {
    entry:             <CheckCircle2 size={11} className="text-[#22C55E] shrink-0 mt-0.5" />,
    exit:              <X size={11} className="text-[#EF4444] shrink-0 mt-0.5" />,
    candidate_added:   <Eye size={11} className="text-blue-400 shrink-0 mt-0.5" />,
    candidate_expired: <Clock size={11} className="text-[#475569] shrink-0 mt-0.5" />,
    daily_summary:     <RefreshCw size={11} className="text-[#475569] shrink-0 mt-0.5" />,
  };
  const icon = icons[entry.event_type] ?? icons.daily_summary;
  const isDaily = entry.event_type === "daily_summary";

  return (
    <div className={cn(
      "flex items-start gap-2.5 px-2 py-2 rounded-lg text-xs transition-colors",
      isDaily ? "bg-[#334155]/40 mt-2" : "hover:bg-[#334155]/30"
    )}>
      {icon}
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          {entry.symbol && <span className="font-mono font-bold text-white">{entry.symbol}</span>}
          {entry.symbol && TICKER_NAMES[entry.symbol] && (
            <span className="text-[#475569] text-[11px]">{TICKER_NAMES[entry.symbol]}</span>
          )}
          {entry.preset_label && <span className="text-[#475569] text-[11px]">· {entry.preset_label}</span>}
          {entry.price != null && <span className="font-mono text-[#94A3B8]">${entry.price.toFixed(2)}</span>}
          {entry.pnl_pct != null && (
            <span className={cn("font-mono font-bold text-[11px]", entry.pnl_pct >= 0 ? "text-[#22C55E]" : "text-[#EF4444]")}>
              {fmtPct(entry.pnl_pct)}
            </span>
          )}
        </div>
        <div className="text-[#475569] mt-0.5 leading-relaxed">{entry.notes}</div>
      </div>
      <div className="text-[#475569] shrink-0 font-mono">{entry.log_date}</div>
    </div>
  );
}
