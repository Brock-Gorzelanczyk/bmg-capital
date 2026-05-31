import type { DemoPersona } from "@/lib/demoMode";

export interface DemoPosition {
  symbol: string;
  qty: number;
  cost_basis: number;
  current_price: number;
}

export interface DemoData {
  persona: DemoPersona;
  user: { id: number; email: string; username: string; display_name: string };
  account: {
    cash: number;
    portfolio_value: number;
    day_pnl: number;
    day_pnl_pct: number;
    total_pnl: number;
    total_pnl_pct: number;
  };
  positions: DemoPosition[];
  watchlists: Array<{ name: string; symbols: string[] }>;
  notifications: Array<{ id: number; title: string; body: string; read: boolean; created_at: string }>;
  strategy_signals: Array<{ symbol: string; strategy: string; signal: string }>;
  learning_progress?: {
    track: string;
    completion_pct: number;
    streak_days: number;
    quizzes_completed: number;
  };
}

// ── Long-Term Investor ────────────────────────────────────────────────────────

export const LONG_TERM_DATA: DemoData = {
  persona: "long_term",
  user: {
    id: 1001,
    email: "demo@bmgcapital.com",
    username: "long_term_demo",
    display_name: "Alex (Long-Term)",
  },
  account: {
    cash: 24587,
    portfolio_value: 35124,
    day_pnl: 246.78,
    day_pnl_pct: 0.84,
    total_pnl: 8432,
    total_pnl_pct: 18.2,
  },
  positions: [
    { symbol: "VOO",  qty: 12.5, cost_basis: 398,  current_price: 478  },
    { symbol: "VTI",  qty: 8.2,  cost_basis: 360,  current_price: 435  },
    { symbol: "SCHD", qty: 22,   cost_basis: 72,   current_price: 79   },
    { symbol: "AAPL", qty: 14,   cost_basis: 165,  current_price: 211  },
    { symbol: "MSFT", qty: 6,    cost_basis: 320,  current_price: 435  },
    { symbol: "NVDA", qty: 2.5,  cost_basis: 480,  current_price: 950  },
    { symbol: "COST", qty: 3,    cost_basis: 640,  current_price: 850  },
    { symbol: "JNJ",  qty: 12,   cost_basis: 148,  current_price: 152  },
  ],
  watchlists: [
    { name: "My Holdings", symbols: ["VOO", "VTI", "SCHD", "AAPL", "MSFT", "NVDA", "COST", "JNJ"] },
    { name: "Dividend Aristocrats", symbols: ["T", "VZ", "JNJ", "KO", "PG", "XOM"] },
    { name: "Top Tech", symbols: ["AAPL", "MSFT", "GOOGL", "META", "AMZN"] },
    { name: "Sector Leaders", symbols: ["XLK", "XLF", "XLE", "XLV"] },
  ],
  notifications: [
    {
      id: 1,
      title: "Strategy Signal — VOO",
      body: "Your Trend-Follow strategy generated a BUY signal on VOO at $476.20.",
      read: false,
      created_at: "2026-05-31T09:35:00Z",
    },
    {
      id: 2,
      title: "Earnings Reminder — MSFT",
      body: "Microsoft (MSFT) reports earnings after close tomorrow. You hold 6 shares.",
      read: false,
      created_at: "2026-05-30T16:00:00Z",
    },
    {
      id: 3,
      title: "Account Milestone",
      body: "Your total portfolio gain crossed $8,000. Nice work staying the course!",
      read: true,
      created_at: "2026-05-28T12:00:00Z",
    },
  ],
  strategy_signals: [
    { symbol: "VOO",  strategy: "Trend-Follow",  signal: "BUY"  },
    { symbol: "SCHD", strategy: "Dividend-Growth", signal: "HOLD" },
    { symbol: "NVDA", strategy: "Momentum",       signal: "HOLD" },
  ],
};

// ── Active Trader ─────────────────────────────────────────────────────────────

export const ACTIVE_TRADER_DATA: DemoData = {
  persona: "active_trader",
  user: {
    id: 1002,
    email: "demo@bmgcapital.com",
    username: "active_trader_demo",
    display_name: "Jordan (Active Trader)",
  },
  account: {
    cash: 9200,
    portfolio_value: 51890,
    day_pnl: 1247.5,
    day_pnl_pct: 3.2,
    total_pnl: 12890,
    total_pnl_pct: 25.4,
  },
  positions: [
    { symbol: "NVDA",  qty: 8,   cost_basis: 580,  current_price: 950  },
    { symbol: "AMD",   qty: 15,  cost_basis: 125,  current_price: 178  },
    { symbol: "TSLA",  qty: 10,  cost_basis: 220,  current_price: 245  },
    { symbol: "SMCI",  qty: 20,  cost_basis: 350,  current_price: 420  },
    { symbol: "PLTR",  qty: 50,  cost_basis: 18,   current_price: 28   },
    { symbol: "MSTR",  qty: 5,   cost_basis: 370,  current_price: 520  },
    { symbol: "COIN",  qty: 8,   cost_basis: 180,  current_price: 235  },
    { symbol: "SPY",   qty: 3,   cost_basis: 480,  current_price: 535  },
    { symbol: "QQQ",   qty: 4,   cost_basis: 410,  current_price: 465  },
    { symbol: "SOFI",  qty: 100, cost_basis: 8.2,  current_price: 10.8 },
    { symbol: "RKLB",  qty: 60,  cost_basis: 12,   current_price: 22   },
    { symbol: "IONQ",  qty: 40,  cost_basis: 15,   current_price: 28   },
  ],
  watchlists: [
    { name: "Earnings This Week", symbols: ["NVDA", "AMD", "COIN", "PLTR", "SMCI"] },
    { name: "Unusual Options", symbols: ["TSLA", "SPY", "QQQ", "MSTR", "SOFI"] },
    { name: "Day Trade Setups", symbols: ["RKLB", "IONQ", "AMD", "NVDA", "PLTR"] },
    { name: "My Holdings", symbols: ["NVDA", "AMD", "TSLA", "SMCI", "PLTR", "MSTR", "COIN", "SPY", "QQQ", "SOFI", "RKLB", "IONQ"] },
  ],
  notifications: [
    {
      id: 4,
      title: "Strategy Signal — NVDA",
      body: "Momentum strategy: NVDA broke above $940 with high volume. Signal: STRONG BUY.",
      read: false,
      created_at: "2026-05-31T10:02:00Z",
    },
    {
      id: 5,
      title: "Unusual Options — TSLA",
      body: "Unusual call options flow detected on TSLA $260C expiring this Friday.",
      read: false,
      created_at: "2026-05-31T09:48:00Z",
    },
    {
      id: 6,
      title: "Position Alert — SMCI",
      body: "SMCI up 6.2% today. Your unrealized gain on this position is now $1,400.",
      read: true,
      created_at: "2026-05-30T14:22:00Z",
    },
  ],
  strategy_signals: [
    { symbol: "NVDA", strategy: "Momentum-Breakout", signal: "STRONG BUY" },
    { symbol: "AMD",  strategy: "Momentum-Breakout", signal: "BUY"         },
    { symbol: "PLTR", strategy: "Trend-Follow",      signal: "HOLD"        },
  ],
};

// ── Crypto Enthusiast ─────────────────────────────────────────────────────────

export const CRYPTO_DATA: DemoData = {
  persona: "crypto",
  user: {
    id: 1003,
    email: "demo@bmgcapital.com",
    username: "crypto_demo",
    display_name: "Sam (Crypto)",
  },
  account: {
    cash: 5400,
    portfolio_value: 38200,
    day_pnl: -420,
    day_pnl_pct: -1.1,
    total_pnl: 9800,
    total_pnl_pct: 34.5,
  },
  positions: [
    { symbol: "BTC-USD",  qty: 0.25, cost_basis: 62000, current_price: 104000 },
    { symbol: "ETH-USD",  qty: 3.2,  cost_basis: 2800,  current_price: 3900   },
    { symbol: "SOL-USD",  qty: 22,   cost_basis: 145,   current_price: 182    },
    { symbol: "AVAX-USD", qty: 45,   cost_basis: 35,    current_price: 48     },
    { symbol: "LINK-USD", qty: 120,  cost_basis: 13,    current_price: 19     },
    { symbol: "NVDA",     qty: 3,    cost_basis: 580,   current_price: 950    },
    { symbol: "COIN",     qty: 12,   cost_basis: 180,   current_price: 235    },
    { symbol: "MSTR",     qty: 4,    cost_basis: 370,   current_price: 520    },
  ],
  watchlists: [
    { name: "My Holdings", symbols: ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "NVDA", "COIN", "MSTR"] },
    { name: "DeFi Tokens",  symbols: ["UNI-USD", "AAVE-USD", "MKR-USD", "CRV-USD"] },
    { name: "L2 Ecosystem", symbols: ["ARB-USD", "OP-USD", "MATIC-USD"] },
    { name: "Watchlist",    symbols: ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD"] },
  ],
  notifications: [
    {
      id: 7,
      title: "BTC Alert — Price Drop",
      body: "Bitcoin dropped below $103,000. Your BTC position is down $250 today.",
      read: false,
      created_at: "2026-05-31T08:55:00Z",
    },
    {
      id: 8,
      title: "Strategy Signal — ETH-USD",
      body: "DeFi Momentum strategy: ETH showing bearish divergence on the 4H chart.",
      read: false,
      created_at: "2026-05-31T07:30:00Z",
    },
    {
      id: 9,
      title: "Strategy Signal — SOL-USD",
      body: "SOL broke support at $178. Consider tightening stop-loss.",
      read: false,
      created_at: "2026-05-30T22:10:00Z",
    },
    {
      id: 10,
      title: "COIN Earnings",
      body: "Coinbase (COIN) beat Q1 estimates. Revenue up 22% YoY.",
      read: true,
      created_at: "2026-05-28T18:05:00Z",
    },
    {
      id: 11,
      title: "Portfolio Milestone",
      body: "Your total crypto + equity portfolio crossed $38,000.",
      read: true,
      created_at: "2026-05-26T12:00:00Z",
    },
  ],
  strategy_signals: [
    { symbol: "BTC-USD",  strategy: "Crypto-Trend",   signal: "HOLD"       },
    { symbol: "ETH-USD",  strategy: "DeFi-Momentum",  signal: "SELL"       },
    { symbol: "SOL-USD",  strategy: "Breakout",        signal: "WATCH"      },
    { symbol: "AVAX-USD", strategy: "Momentum",        signal: "HOLD"       },
    { symbol: "LINK-USD", strategy: "Trend-Follow",    signal: "BUY"        },
  ],
};

// ── Beginner Learner ──────────────────────────────────────────────────────────

export const BEGINNER_DATA: DemoData = {
  persona: "beginner",
  user: {
    id: 1004,
    email: "demo@bmgcapital.com",
    username: "beginner_demo",
    display_name: "Taylor (Beginner)",
  },
  account: {
    cash: 487,
    portfolio_value: 980,
    day_pnl: 4.2,
    day_pnl_pct: 0.43,
    total_pnl: 42,
    total_pnl_pct: 4.5,
  },
  positions: [
    { symbol: "VOO",  qty: 0.2, cost_basis: 450, current_price: 478 },
    { symbol: "AAPL", qty: 0.1, cost_basis: 195, current_price: 211 },
    { symbol: "NVDA", qty: 1,   cost_basis: 870, current_price: 950 },
  ],
  watchlists: [
    { name: "My Holdings", symbols: ["VOO", "AAPL", "NVDA"] },
  ],
  notifications: [
    {
      id: 12,
      title: "Learning Streak!",
      body: "You've completed 12 days in a row on the Investing Fundamentals track. Keep it up!",
      read: false,
      created_at: "2026-05-31T08:00:00Z",
    },
    {
      id: 13,
      title: "Quiz Complete",
      body: "You scored 90% on 'Understanding ETFs'. Check out the next lesson: Index Funds.",
      read: true,
      created_at: "2026-05-30T19:45:00Z",
    },
    {
      id: 14,
      title: "First Gain",
      body: "Your NVDA position is up $80 since you bought it. Your first unrealized gain!",
      read: true,
      created_at: "2026-05-28T09:00:00Z",
    },
  ],
  strategy_signals: [],
  learning_progress: {
    track: "Investing Fundamentals",
    completion_pct: 30,
    streak_days: 12,
    quizzes_completed: 3,
  },
};
