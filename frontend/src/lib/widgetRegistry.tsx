import React from "react";
import {
  Sun, BarChart2, Wallet, Briefcase, FlaskConical, Calendar,
  TrendingUp, Newspaper, Zap, BookMarked, GraduationCap,
  MessageSquare, Bitcoin, Activity, ShieldAlert,
} from "lucide-react";

export type WidgetCategory =
  | "Markets"
  | "Portfolio"
  | "Watchlist"
  | "News"
  | "Learning"
  | "AI"
  | "Crypto"
  | "Options";

export type TierRequired = "free" | "plus" | "premium";

export interface WidgetLayout {
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
  maxW?: number;
  maxH?: number;
}

export interface WidgetDef {
  id: string;
  name: string;
  description: string;
  category: WidgetCategory;
  defaultLayout: WidgetLayout;
  icon: React.ElementType;
  tierRequired: TierRequired;
  comingSoon?: boolean;
}

export const WIDGET_REGISTRY: Record<string, WidgetDef> = {
  "morning-brief": {
    id: "morning-brief",
    name: "Morning Brief",
    description: "AI-generated daily market summary personalized to your holdings",
    category: "AI",
    defaultLayout: { x: 0, y: 0, w: 12, h: 4, minW: 6, minH: 3 },
    icon: Sun,
    tierRequired: "free",
  },
  "market-indices": {
    id: "market-indices",
    name: "Market Indices",
    description: "Live snapshot of SPY, QQQ, DIA, IWM, VXX, GLD, TLT",
    category: "Markets",
    defaultLayout: { x: 0, y: 4, w: 12, h: 4, minW: 4, minH: 3 },
    icon: BarChart2,
    tierRequired: "free",
  },
  "paper-account": {
    id: "paper-account",
    name: "Paper Portfolio",
    description: "Paper trading account equity, day P&L, and position count",
    category: "Portfolio",
    defaultLayout: { x: 0, y: 8, w: 4, h: 3, minW: 3, minH: 3 },
    icon: Wallet,
    tierRequired: "free",
  },
  "portfolio-summary": {
    id: "portfolio-summary",
    name: "Portfolio",
    description: "Total portfolio value, gain/loss, and top holdings",
    category: "Portfolio",
    defaultLayout: { x: 0, y: 11, w: 6, h: 8, minW: 4, minH: 5 },
    icon: Briefcase,
    tierRequired: "free",
  },
  "strategy-signals": {
    id: "strategy-signals",
    name: "Strategy Signals",
    description: "Open and watching signals from your strategy automation",
    category: "Markets",
    defaultLayout: { x: 6, y: 11, w: 6, h: 8, minW: 4, minH: 5 },
    icon: FlaskConical,
    tierRequired: "free",
  },
  "daily-recap": {
    id: "daily-recap",
    name: "Daily Recap",
    description: "AI-generated end-of-day market recap",
    category: "AI",
    defaultLayout: { x: 0, y: 19, w: 12, h: 4, minW: 6, minH: 3 },
    icon: Calendar,
    tierRequired: "free",
  },
  "sector-performance": {
    id: "sector-performance",
    name: "Sector Performance",
    description: "All 11 sectors sorted by today's performance",
    category: "Markets",
    defaultLayout: { x: 0, y: 23, w: 6, h: 9, minW: 4, minH: 6 },
    icon: TrendingUp,
    tierRequired: "free",
  },
  "market-news": {
    id: "market-news",
    name: "Market News",
    description: "Latest market news headlines",
    category: "News",
    defaultLayout: { x: 6, y: 23, w: 6, h: 9, minW: 4, minH: 6 },
    icon: Newspaper,
    tierRequired: "free",
  },
  "top-movers": {
    id: "top-movers",
    name: "Top Movers",
    description: "Today's biggest gainers and losers by % change",
    category: "Markets",
    defaultLayout: { x: 0, y: 0, w: 6, h: 7, minW: 4, minH: 5 },
    icon: Zap,
    tierRequired: "free",
  },
  "watchlist-table": {
    id: "watchlist-table",
    name: "Watchlist",
    description: "Your watchlist with live prices, change %, and volume",
    category: "Watchlist",
    defaultLayout: { x: 0, y: 0, w: 12, h: 7, minW: 6, minH: 5 },
    icon: BookMarked,
    tierRequired: "free",
  },
  "streak-card": {
    id: "streak-card",
    name: "Learning Streak",
    description: "Your current learning streak and next lesson CTA",
    category: "Learning",
    defaultLayout: { x: 0, y: 0, w: 4, h: 3, minW: 3, minH: 3 },
    icon: GraduationCap,
    tierRequired: "free",
    comingSoon: true,
  },
  "copilot-quick": {
    id: "copilot-quick",
    name: "Co-Pilot",
    description: "Ask BMG Intelligence anything, right from the dashboard",
    category: "AI",
    defaultLayout: { x: 0, y: 0, w: 6, h: 5, minW: 4, minH: 4 },
    icon: MessageSquare,
    tierRequired: "free",
    comingSoon: true,
  },
  "crypto-holdings": {
    id: "crypto-holdings",
    name: "Crypto Holdings",
    description: "Your paper crypto positions with live prices",
    category: "Crypto",
    defaultLayout: { x: 0, y: 0, w: 6, h: 7, minW: 4, minH: 5 },
    icon: Bitcoin,
    tierRequired: "plus",
    comingSoon: true,
  },
  "btc-dominance": {
    id: "btc-dominance",
    name: "BTC Dominance",
    description: "Bitcoin market dominance chart + altseason indicator",
    category: "Crypto",
    defaultLayout: { x: 0, y: 0, w: 4, h: 4, minW: 3, minH: 3 },
    icon: Activity,
    tierRequired: "plus",
    comingSoon: true,
  },
  "drawdown-budget": {
    id: "drawdown-budget",
    name: "Drawdown Risk Budget",
    description: "Track your annual drawdown budget usage with a configurable max-drawdown slider and 1-day VaR estimate",
    category: "Portfolio",
    defaultLayout: { x: 0, y: 0, w: 6, h: 6, minW: 4, minH: 5 },
    icon: ShieldAlert,
    tierRequired: "free",
  },
};

export const WIDGET_CATEGORIES: WidgetCategory[] = [
  "Markets", "Portfolio", "Watchlist", "News", "Learning", "AI", "Crypto", "Options",
];

export const CATEGORY_COLORS: Record<WidgetCategory, string> = {
  Markets:   "text-blue-400 bg-blue-500/10",
  Portfolio: "text-green-400 bg-green-500/10",
  Watchlist: "text-purple-400 bg-purple-500/10",
  News:      "text-yellow-400 bg-yellow-500/10",
  Learning:  "text-orange-400 bg-orange-500/10",
  AI:        "text-indigo-400 bg-indigo-500/10",
  Crypto:    "text-amber-400 bg-amber-500/10",
  Options:   "text-red-400 bg-red-500/10",
};
