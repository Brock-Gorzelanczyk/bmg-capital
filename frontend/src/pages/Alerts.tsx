import { useState, useMemo } from "react";
import { cn, timeAgo } from "@/lib/utils";
import { toast } from "sonner";
import {
  Bell, BellOff, TrendingUp, TrendingDown, Zap, AlertTriangle, Activity,
  Filter, Search, ChevronDown, ChevronRight, X, Check, Eye, VolumeX,
  Star, Clock, Trash2, Settings, BarChart2, ExternalLink,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

type Importance = "Routine" | "Significant" | "Breaking";
type AlertType =
  | "price_cross" | "pct_move" | "rsi_extreme" | "ma_cross" | "macd_signal"
  | "breakout" | "pattern_detected" | "unusual_volume" | "iv_expansion"
  | "strategy_fires" | "strategy_forming" | "news_breaking" | "earnings_reminder"
  | "post_earnings" | "insider_buy" | "congressional" | "options_uoa"
  | "dark_pool" | "risk_drawdown" | "risk_concentration" | "fill"
  | "dividend" | "macro" | "crypto_funding" | "crypto_liquidation";

interface Alert {
  id: string;
  ticker: string;
  type: AlertType;
  title: string;
  body: string;
  importance: Importance;
  source: string;
  timestamp: string;
  is_read: boolean;
  ai_priority: number;
  tags: string[];
}

// ─── Mock Data ────────────────────────────────────────────────────────────────

function hoursAgo(h: number, m = 0): string {
  const d = new Date(Date.now() - h * 3_600_000 - m * 60_000);
  return d.toISOString();
}

const MOCK_ALERTS: Alert[] = [
  {
    id: "1", ticker: "PORT", type: "risk_drawdown",
    title: "Portfolio down 5.2% — drawdown threshold breached",
    body: "Total portfolio value dropped to $94,800. Your 5% max drawdown rule was triggered at 10:14 AM. Consider reviewing open positions.",
    importance: "Breaking", source: "Risk", timestamp: hoursAgo(0, 18),
    is_read: false, ai_priority: 97, tags: ["risk", "drawdown"],
  },
  {
    id: "2", ticker: "NVDA", type: "strategy_fires",
    title: "Momentum Surge entered at $924.50",
    body: "Strategy fired long on NVDA. RSI momentum crossed 60 on daily, MACD positive, volume 1.8× average. Entry at $924.50, stop $908.",
    importance: "Breaking", source: "Strategy: Momo", timestamp: hoursAgo(0, 32),
    is_read: false, ai_priority: 92, tags: ["strategy", "long"],
  },
  {
    id: "3", ticker: "TSLA", type: "breakout",
    title: "Closed above 52-week high on 2.1× volume",
    body: "TSLA broke out above its $299.29 52-week high, closing at $302.15 on volume of 68M shares — 2.1× the 20-day average. Bullish continuation signal.",
    importance: "Significant", source: "Scanner: Breakouts", timestamp: hoursAgo(1, 5),
    is_read: false, ai_priority: 88, tags: ["breakout", "volume"],
  },
  {
    id: "4", ticker: "SPY", type: "options_uoa",
    title: "$1.8M sweep on SPY $545C Jun 20",
    body: "Unusual options activity detected: 1,420 contracts of SPY $545 call expiring Jun 20 swept at the ask for $1.8M total premium. Bullish institutional bet.",
    importance: "Significant", source: "Scanner: Options Flow", timestamp: hoursAgo(1, 44),
    is_read: false, ai_priority: 85, tags: ["options", "sweep"],
  },
  {
    id: "5", ticker: "AAPL", type: "earnings_reminder",
    title: "Earnings in 7 days — implied move ±5.2%",
    body: "Apple reports Q2 FY2025 earnings in 7 days. Options pricing a ±5.2% move. IV rank is 68th percentile. Consider positioning before the event.",
    importance: "Routine", source: "Calendar", timestamp: hoursAgo(2, 10),
    is_read: true, ai_priority: 62, tags: ["earnings", "iv"],
  },
  {
    id: "6", ticker: "QQQ", type: "unusual_volume",
    title: "Volume 3.4× 20-day average",
    body: "QQQ traded 94M shares by noon — 3.4× its 20-day average of 27M. Price action flat, suggesting large rebalancing or hedging activity.",
    importance: "Significant", source: "Scanner: Volume", timestamp: hoursAgo(2, 55),
    is_read: false, ai_priority: 79, tags: ["volume", "etf"],
  },
  {
    id: "7", ticker: "NVDA", type: "rsi_extreme",
    title: "RSI touched 78 — approaching overbought",
    body: "NVDA 14-day RSI reached 78.2 on the daily chart. Historically, readings above 75 precede 2-5% pullbacks within 5 sessions. Monitor for reversal.",
    importance: "Significant", source: "Scanner: RSI", timestamp: hoursAgo(3, 20),
    is_read: true, ai_priority: 74, tags: ["rsi", "overbought"],
  },
  {
    id: "8", ticker: "BTC", type: "crypto_funding",
    title: "Funding rate spiked to +0.08% — longs crowded",
    body: "BTC perpetual funding rate hit +0.08% on Binance, the highest in 30 days. Crowded longs increase cascade liquidation risk. Consider reducing exposure.",
    importance: "Significant", source: "Crypto: Funding", timestamp: hoursAgo(3, 48),
    is_read: false, ai_priority: 82, tags: ["crypto", "funding"],
  },
  {
    id: "9", ticker: "ETH", type: "crypto_liquidation",
    title: "$42M in ETH longs liquidated in 1 hour",
    body: "A cascade of ETH long liquidations totaling $42M occurred between 8:00-9:00 AM as price dropped 3.1% from $3,420 to $3,314. Volatility may persist.",
    importance: "Breaking", source: "Crypto: Liquidations", timestamp: hoursAgo(4, 5),
    is_read: true, ai_priority: 89, tags: ["crypto", "liquidation"],
  },
  {
    id: "10", ticker: "NVDA", type: "dark_pool",
    title: "Dark pool print: 250K shares @ $921",
    body: "Large block trade of 250,000 NVDA shares printed off-exchange at $921.00, totaling ~$230M. Could indicate institutional accumulation ahead of a catalyst.",
    importance: "Significant", source: "Scanner: Dark Pool", timestamp: hoursAgo(4, 30),
    is_read: true, ai_priority: 77, tags: ["darkpool", "institutional"],
  },
  {
    id: "11", ticker: "AAPL", type: "insider_buy",
    title: "CFO bought $2.1M in AAPL shares",
    body: "Luca Maestri (CFO) filed Form 4 disclosing purchase of 12,500 AAPL shares at $168.30 on May 28. Insider buying near 52-week lows is historically bullish.",
    importance: "Significant", source: "SEC: Form 4", timestamp: hoursAgo(5, 0),
    is_read: true, ai_priority: 72, tags: ["insider", "buy"],
  },
  {
    id: "12", ticker: "SPY", type: "macro",
    title: "Fed minutes released — 2 cuts expected in 2025",
    body: "May FOMC minutes signal committee sees 2 rate cuts in 2025 if inflation continues trending down. 10Y yield dropped 6bps to 4.31%. Equities rallied.",
    importance: "Breaking", source: "News: Macro", timestamp: hoursAgo(5, 22),
    is_read: true, ai_priority: 91, tags: ["macro", "fed"],
  },
  {
    id: "13", ticker: "TSLA", type: "news_breaking",
    title: "Reuters: Tesla Robotaxi launch confirmed for Q3",
    body: "Reuters reports Tesla confirmed commercial Robotaxi service launch in Austin TX for Q3 2025. CEO confirmed on X. Stock up 4.2% in after-hours trading.",
    importance: "Breaking", source: "News: Reuters", timestamp: hoursAgo(5, 50),
    is_read: false, ai_priority: 93, tags: ["news", "catalyst"],
  },
  {
    id: "14", ticker: "QQQ", type: "ma_cross",
    title: "QQQ 20-day crossed above 50-day MA",
    body: "The 20-day moving average on QQQ crossed above the 50-day MA at $460.30, forming a bullish short-term cross. Trend momentum improving.",
    importance: "Routine", source: "Scanner: MA", timestamp: hoursAgo(6, 15),
    is_read: true, ai_priority: 55, tags: ["ma", "trend"],
  },
  {
    id: "15", ticker: "AAPL", type: "iv_expansion",
    title: "AAPL IV rank jumped to 72 — options premium elevated",
    body: "Implied volatility rank on AAPL surged from 41 to 72 in one session. Premium sellers may find favorable conditions. Check near-term catalysts.",
    importance: "Routine", source: "Scanner: IV", timestamp: hoursAgo(6, 40),
    is_read: true, ai_priority: 58, tags: ["iv", "options"],
  },
  {
    id: "16", ticker: "BTC", type: "pct_move",
    title: "BTC up 4.8% in last 4 hours",
    body: "Bitcoin surged 4.8% from $68,200 to $71,470 over the last 4 hours on above-average volume. Breakout above key $70K resistance with momentum indicators positive.",
    importance: "Significant", source: "Scanner: Price", timestamp: hoursAgo(7, 0),
    is_read: true, ai_priority: 80, tags: ["price", "breakout"],
  },
  {
    id: "17", ticker: "SPY", type: "risk_concentration",
    title: "Top 3 positions = 58% of portfolio",
    body: "Portfolio concentration alert: NVDA (24%), TSLA (18%), and AAPL (16%) together represent 58% of total equity. Diversification risk elevated.",
    importance: "Routine", source: "Risk", timestamp: hoursAgo(7, 30),
    is_read: true, ai_priority: 65, tags: ["risk", "concentration"],
  },
  {
    id: "18", ticker: "NVDA", type: "pattern_detected",
    title: "Bull flag forming on 4H chart",
    body: "NVDA has formed a textbook bull flag on the 4-hour timeframe after a strong pole from $895 to $930. Flag consolidating between $918-$928. Breakout target ~$963.",
    importance: "Significant", source: "Scanner: Patterns", timestamp: hoursAgo(7, 55),
    is_read: true, ai_priority: 76, tags: ["pattern", "bullish"],
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────


function tickerColor(ticker: string): string {
  const colors = [
    "bg-violet-500/20 text-violet-300",
    "bg-blue-500/20 text-blue-300",
    "bg-emerald-500/20 text-emerald-300",
    "bg-amber-500/20 text-amber-300",
    "bg-rose-500/20 text-rose-300",
    "bg-cyan-500/20 text-cyan-300",
    "bg-orange-500/20 text-orange-300",
  ];
  let hash = 0;
  for (const c of ticker) hash = (hash * 31 + c.charCodeAt(0)) & 0xffff;
  return colors[hash % colors.length];
}

function sourceCategory(source: string): string {
  if (source.startsWith("Strategy")) return "Strategies";
  if (source.startsWith("Scanner")) return "Patterns";
  if (source.startsWith("News") || source.startsWith("Calendar") || source.startsWith("SEC")) return "News";
  if (source === "Risk") return "Risk";
  return "Account";
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function AIPill({ score }: { score: number }) {
  if (score >= 85) return (
    <div className="flex flex-col items-center">
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[var(--accent-positive)]/20 text-[var(--accent-positive)]">
        🔥 {score}
      </span>
      <span className="text-[9px] text-[var(--text-tertiary)] mt-0.5">AI Score</span>
    </div>
  );
  if (score >= 70) return (
    <div className="flex flex-col items-center">
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400">
        {score}
      </span>
      <span className="text-[9px] text-[var(--text-tertiary)] mt-0.5">AI Score</span>
    </div>
  );
  return (
    <div className="flex flex-col items-center">
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-zinc-700/60 text-zinc-400">
        {score}
      </span>
      <span className="text-[9px] text-[var(--text-tertiary)] mt-0.5">AI Score</span>
    </div>
  );
}

function ImportanceBadge({ importance }: { importance: Importance }) {
  if (importance === "Breaking") return (
    <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">
      <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse inline-block" />
      BREAKING
    </span>
  );
  if (importance === "Significant") return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">
      SIGNIFICANT
    </span>
  );
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-zinc-700/60 text-zinc-400 border border-zinc-600/40">
      ROUTINE
    </span>
  );
}

function importanceBar(importance: Importance): string {
  if (importance === "Breaking") return "bg-rose-500";
  if (importance === "Significant") return "bg-amber-500";
  return "bg-zinc-600";
}

// Minimal SVG sparkline placeholder
function Sparkline({ up }: { up: boolean }) {
  const color = up ? "var(--accent-positive)" : "var(--accent-negative)";
  const path = up
    ? "M0,30 L10,22 L20,25 L30,15 L40,18 L50,10 L60,5"
    : "M0,5 L10,12 L20,8 L30,18 L40,15 L50,25 L60,30";
  return (
    <svg width="60" height="36" viewBox="0 0 60 36" fill="none">
      <path d={path} stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Snooze Dropdown ──────────────────────────────────────────────────────────

const SNOOZE_OPTIONS = ["1h", "Until market open", "Until tomorrow", "1 week", "Until I trade this ticker"];

function SnoozeMenu({ onSelect, onClose }: { onSelect: (v: string) => void; onClose: () => void }) {
  return (
    <div className="absolute z-50 right-0 top-full mt-1 bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg shadow-xl min-w-[180px]">
      {SNOOZE_OPTIONS.map((o) => (
        <button key={o} onClick={() => { onSelect(o); onClose(); }}
          className="w-full text-left px-3 py-2 text-xs text-[var(--text-secondary)] hover:bg-[var(--border-subtle)]/40 hover:text-[var(--text-primary)] first:rounded-t-lg last:rounded-b-lg transition-colors">
          {o}
        </button>
      ))}
    </div>
  );
}

// ─── Alert Row ────────────────────────────────────────────────────────────────

function AlertRow({
  alert, selected, onSelect, onRead, onDismiss, onSnooze, onMute, checked, onCheck,
}: {
  alert: Alert;
  selected: boolean;
  onSelect: () => void;
  onRead: (id: string) => void;
  onDismiss: (id: string) => void;
  onSnooze: (id: string, opt: string) => void;
  onMute: (ticker: string) => void;
  checked: boolean;
  onCheck: () => void;
}) {
  const [hover, setHover] = useState(false);
  const [snoozeOpen, setSnoozeOpen] = useState(false);

  return (
    <div
      className={cn(
        "relative flex items-stretch border-b border-[var(--border-subtle)]/50 last:border-0 transition-colors cursor-pointer group",
        selected ? "bg-[var(--bg-elevated-2)]" : "hover:bg-[var(--bg-elevated-2)]/50",
        !alert.is_read && "bg-[var(--accent-positive)]/[0.03]"
      )}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setSnoozeOpen(false); }}
      onClick={onSelect}
    >
      {/* Left importance bar */}
      <div className={cn("w-[3px] shrink-0 rounded-l", importanceBar(alert.importance))} />

      {/* Checkbox */}
      <div className="flex items-center px-2" onClick={(e) => { e.stopPropagation(); onCheck(); }}>
        <div className={cn(
          "w-4 h-4 rounded border flex items-center justify-center transition-all",
          checked ? "bg-[var(--accent-positive)] border-[var(--accent-positive)]" : "border-zinc-600 hover:border-zinc-400",
          !hover && !checked ? "opacity-0 group-hover:opacity-100" : "opacity-100"
        )}>
          {checked && <Check size={10} className="text-black" />}
        </div>
      </div>

      {/* Unread dot */}
      <div className="flex items-center w-3 shrink-0">
        {!alert.is_read && <div className="w-2 h-2 rounded-full bg-[var(--accent-positive)] shrink-0" />}
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0 py-3 pr-3">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <span className={cn("font-mono text-xs font-bold px-1.5 py-0.5 rounded", tickerColor(alert.ticker))}>
            {alert.ticker}
          </span>
          <ImportanceBadge importance={alert.importance} />
          <span className="text-[10px] text-[var(--text-tertiary)]">{alert.source}</span>
          <span className="text-[10px] text-[var(--text-tertiary)] ml-auto">{timeAgo(alert.timestamp)}</span>
        </div>
        <p className={cn("text-sm font-medium leading-snug", alert.is_read ? "text-[var(--text-secondary)]" : "text-[var(--text-primary)]")}>
          {alert.title}
        </p>
        <p className="text-xs text-[var(--text-tertiary)] mt-0.5 line-clamp-1">{alert.body}</p>

        {/* Hover action row */}
        {hover && (
          <div className="flex items-center gap-1.5 mt-2" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => toast.info("Opening chart…")}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--text-secondary)] bg-[var(--border-subtle)]/60 hover:bg-[var(--border-emphasis)] transition-colors">
              <BarChart2 size={10} /> View Chart
            </button>
            <button onClick={() => toast.success("Trade panel opening…")}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--text-primary)] bg-[var(--accent-positive)]/20 hover:bg-[var(--accent-positive)]/30 transition-colors">
              <TrendingUp size={10} /> Trade
            </button>
            <div className="relative">
              <button onClick={() => setSnoozeOpen((o) => !o)}
                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--text-secondary)] bg-[var(--border-subtle)]/60 hover:bg-[var(--border-emphasis)] transition-colors">
                <Clock size={10} /> Snooze <ChevronDown size={8} />
              </button>
              {snoozeOpen && (
                <SnoozeMenu onSelect={(v) => onSnooze(alert.id, v)} onClose={() => setSnoozeOpen(false)} />
              )}
            </div>
            <button onClick={() => onMute(alert.ticker)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--text-secondary)] bg-[var(--border-subtle)]/60 hover:bg-[var(--border-emphasis)] transition-colors">
              <VolumeX size={10} /> Mute {alert.ticker}
            </button>
            <button onClick={() => onDismiss(alert.id)}
              className="ml-auto p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors">
              <X size={12} />
            </button>
          </div>
        )}
      </div>

      {/* AI Score */}
      <div className="flex items-center pr-3 shrink-0">
        <AIPill score={alert.ai_priority} />
      </div>
    </div>
  );
}

// ─── Detail Panel ─────────────────────────────────────────────────────────────

function DetailPanel({ alert, onClose, onMuteType }: { alert: Alert; onClose: () => void; onMuteType: (type: string) => void }) {
  const isUp = alert.importance !== "Breaking" || alert.type !== "risk_drawdown";
  return (
    <div className="flex flex-col h-full bg-[var(--bg-elevated)] border-l border-[var(--border-subtle)]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2">
          <span className={cn("font-mono text-xs font-bold px-1.5 py-0.5 rounded", tickerColor(alert.ticker))}>
            {alert.ticker}
          </span>
          <ImportanceBadge importance={alert.importance} />
        </div>
        <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] p-1">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <h2 className="text-base font-bold text-[var(--text-primary)] leading-snug">{alert.title}</h2>

        <div className="flex items-center gap-3">
          <AIPill score={alert.ai_priority} />
          <div>
            <div className="text-xs text-[var(--text-tertiary)]">Source</div>
            <div className="text-xs text-[var(--text-secondary)] font-medium">{alert.source}</div>
          </div>
          <div className="ml-auto">
            <Sparkline up={isUp} />
          </div>
        </div>

        <div className="bg-[var(--bg-elevated-2)] rounded-lg p-3">
          <div className="text-xs font-semibold text-[var(--text-tertiary)] mb-1.5 uppercase tracking-wider">What fired this</div>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{alert.body}</p>
        </div>

        <div className="bg-[var(--bg-elevated-2)] rounded-lg p-3">
          <div className="text-xs font-semibold text-[var(--text-tertiary)] mb-1.5 uppercase tracking-wider">Provenance</div>
          <p className="text-xs text-[var(--text-tertiary)]">
            Alert type: <span className="text-[var(--text-secondary)]">{alert.type.replace(/_/g, " ")}</span> ·
            Fired at <span className="text-[var(--text-secondary)]">{new Date(alert.timestamp).toLocaleTimeString()}</span>
          </p>
          <div className="flex flex-wrap gap-1 mt-2">
            {alert.tags.map((t) => (
              <span key={t} className="px-1.5 py-0.5 rounded text-[10px] bg-zinc-700/50 text-zinc-400">{t}</span>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <button onClick={() => toast.success("Trade panel opening…")}
            className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold bg-[var(--accent-positive)]/20 text-[var(--accent-positive)] hover:bg-[var(--accent-positive)]/30 transition-colors">
            <TrendingUp size={13} /> Trade
          </button>
          <button onClick={() => toast.success(`${alert.ticker} added to watchlist`)}
            className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold bg-zinc-700/50 text-[var(--text-secondary)] hover:bg-zinc-700 transition-colors">
            <Star size={13} /> Add to Watchlist
          </button>
          <button onClick={() => toast.info(`${alert.ticker} muted`)}
            className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold bg-zinc-700/50 text-[var(--text-secondary)] hover:bg-zinc-700 transition-colors">
            <VolumeX size={13} /> Mute Ticker
          </button>
          <button onClick={() => onMuteType(alert.type)}
            className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold bg-zinc-700/50 text-[var(--text-secondary)] hover:bg-zinc-700 transition-colors">
            <BellOff size={13} /> Mute Alert Type
          </button>
        </div>

        <button
          onClick={() => toast.success(`AI tuning updated — you'll see fewer ${alert.type.replace(/_/g, " ")} alerts`)}
          className="w-full py-2 rounded-lg text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] transition-colors flex items-center justify-center gap-1.5">
          <Settings size={11} /> Show me fewer like this
        </button>

        <button onClick={() => toast.info("Opening external chart…")}
          className="w-full py-2 rounded-lg text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] flex items-center justify-center gap-1.5 transition-colors">
          <ExternalLink size={11} /> View on Chart Page
        </button>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

type TabId = "all" | "unread" | "critical" | "Strategies" | "Patterns" | "News" | "Risk" | "Account";

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>(MOCK_ALERTS);
  const [activeTab, setActiveTab] = useState<TabId>("all");
  const [search, setSearch] = useState("");
  const [importanceFilter, setImportanceFilter] = useState<Importance | "All">("All");
  const [sourceFilter, setSourceFilter] = useState<string>("All");
  const [dateFilter, setDateFilter] = useState<"Today" | "7d" | "30d">("Today");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [selectAll, setSelectAll] = useState(false);
  const [groupByTicker, setGroupByTicker] = useState(true);
  const [expandedTickers, setExpandedTickers] = useState<Set<string>>(new Set());

  // Derived
  const unreadCount = alerts.filter((a) => !a.is_read).length;
  const criticalCount = alerts.filter((a) => a.importance === "Breaking").length;

  const tabs: { id: TabId; label: string; badge?: number }[] = [
    { id: "all", label: "All" },
    { id: "unread", label: "Unread", badge: unreadCount },
    { id: "critical", label: "Critical", badge: criticalCount },
    { id: "Strategies", label: "Strategies" },
    { id: "Patterns", label: "Patterns" },
    { id: "News", label: "News" },
    { id: "Risk", label: "Risk" },
    { id: "Account", label: "Account" },
  ];

  const filtered = useMemo(() => {
    let out = [...alerts];
    if (activeTab === "unread") out = out.filter((a) => !a.is_read);
    else if (activeTab === "critical") out = out.filter((a) => a.importance === "Breaking");
    else if (!["all"].includes(activeTab)) out = out.filter((a) => sourceCategory(a.source) === activeTab);
    if (search) {
      const q = search.toLowerCase();
      out = out.filter((a) => a.title.toLowerCase().includes(q) || a.ticker.toLowerCase().includes(q));
    }
    if (importanceFilter !== "All") out = out.filter((a) => a.importance === importanceFilter);
    if (sourceFilter !== "All") out = out.filter((a) => sourceCategory(a.source) === sourceFilter);
    const cutoff = dateFilter === "Today" ? 86_400_000 : dateFilter === "7d" ? 7 * 86_400_000 : 30 * 86_400_000;
    out = out.filter((a) => Date.now() - new Date(a.timestamp).getTime() < cutoff);
    return out.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [alerts, activeTab, search, importanceFilter, sourceFilter, dateFilter]);

  const activeFilterCount = [importanceFilter !== "All", sourceFilter !== "All", dateFilter !== "Today"].filter(Boolean).length;

  // Grouped
  const grouped = useMemo(() => {
    if (!groupByTicker) return null;
    const map = new Map<string, Alert[]>();
    for (const a of filtered) {
      const arr = map.get(a.ticker) ?? [];
      arr.push(a);
      map.set(a.ticker, arr);
    }
    return map;
  }, [filtered, groupByTicker]);

  const selectedAlert = alerts.find((a) => a.id === selectedId) ?? null;

  function markRead(id: string) {
    setAlerts((prev) => prev.map((a) => a.id === id ? { ...a, is_read: true } : a));
  }
  function dismiss(id: string) {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
    if (selectedId === id) setSelectedId(null);
  }
  function snooze(id: string, opt: string) {
    toast.success(`Snoozed: ${opt}`);
    dismiss(id);
  }
  function muteTicker(ticker: string) {
    toast.info(`${ticker} muted — no more alerts`);
    setAlerts((prev) => prev.filter((a) => a.ticker !== ticker));
  }
  function muteType(type: string) {
    toast.success(`AI tuning updated — you'll see fewer ${type.replace(/_/g, " ")} alerts`);
    setAlerts((prev) => prev.filter((a) => a.type !== type));
  }
  function markAllRead() {
    if (checkedIds.size > 0) {
      setAlerts((prev) => prev.map((a) => checkedIds.has(a.id) ? { ...a, is_read: true } : a));
      setCheckedIds(new Set());
    } else {
      setAlerts((prev) => prev.map((a) => ({ ...a, is_read: true })));
    }
    toast.success("Marked as read");
  }
  function toggleCheck(id: string) {
    setCheckedIds((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }
  function handleSelectAll() {
    if (selectAll) {
      setCheckedIds(new Set());
      setSelectAll(false);
    } else {
      setCheckedIds(new Set(filtered.map((a) => a.id)));
      setSelectAll(true);
    }
  }
  function handleRowClick(id: string) {
    setSelectedId((prev) => (prev === id ? null : id));
    markRead(id);
  }
  function toggleExpandTicker(ticker: string) {
    setExpandedTickers((prev) => {
      const n = new Set(prev);
      n.has(ticker) ? n.delete(ticker) : n.add(ticker);
      return n;
    });
  }

  const totalToday = MOCK_ALERTS.length;
  const actedOn = 2;
  const dismissed = totalToday - actedOn - unreadCount;

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* Main column */}
      <div className={cn("flex flex-col min-h-0 flex-1", selectedAlert ? "hidden md:flex md:w-[60%]" : "w-full")}>
        {/* Header */}
        <div className="px-4 pt-4 pb-0 shrink-0">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Bell size={18} className="text-[var(--accent-positive)]" />
              <h1 className="text-lg font-bold text-[var(--text-primary)]">Alerts Inbox</h1>
              {unreadCount > 0 && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-[var(--accent-positive)] text-black">{unreadCount}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setGroupByTicker((g) => !g)}
                className={cn("text-xs px-2.5 py-1.5 rounded-lg border transition-colors",
                  groupByTicker
                    ? "border-[var(--accent-positive)]/40 text-[var(--accent-positive)] bg-[var(--accent-positive)]/10"
                    : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-[var(--border-emphasis)]"
                )}>
                {groupByTicker ? "Grouped" : "Ungrouped"}
              </button>
              {(checkedIds.size > 0 || unreadCount > 0) && (
                <button onClick={markAllRead}
                  className="text-xs px-2.5 py-1.5 rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-emphasis)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1">
                  <Check size={11} /> Mark {checkedIds.size > 0 ? `${checkedIds.size} ` : "all "}read
                </button>
              )}
            </div>
          </div>

          {/* Fatigue banner */}
          {filtered.length > 8 && (
            <div className="flex items-center justify-between bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 mb-3 text-xs">
              <span className="text-amber-400">
                <AlertTriangle size={11} className="inline mr-1" />
                You've received {totalToday} alerts today. Acting on {actedOn}. Want to tune?
              </span>
              <button onClick={() => toast.info("Alert tuning panel coming soon")}
                className="text-amber-300 font-semibold hover:text-amber-200 transition-colors ml-3 shrink-0">
                Tune Alerts
              </button>
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 overflow-x-auto pb-2 scrollbar-hide">
            {tabs.map((t) => (
              <button key={t.id} onClick={() => setActiveTab(t.id)}
                className={cn(
                  "flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors shrink-0",
                  activeTab === t.id
                    ? "bg-[var(--accent-positive)]/15 text-[var(--accent-positive)] border border-[var(--accent-positive)]/30"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--border-subtle)]/40"
                )}>
                {t.label}
                {t.badge != null && t.badge > 0 && (
                  <span className={cn(
                    "px-1 py-0 rounded-full text-[9px] font-bold",
                    activeTab === t.id ? "bg-[var(--accent-positive)] text-black" : "bg-zinc-700 text-zinc-300"
                  )}>{t.badge}</span>
                )}
              </button>
            ))}
          </div>

          {/* Search + filters */}
          <div className="flex gap-2 mt-2 mb-3 flex-wrap">
            <div className="flex-1 min-w-[160px] relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search alerts…"
                className="w-full pl-7 pr-3 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-xs text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-none focus:border-[var(--border-emphasis)]"
              />
            </div>
            <div className="flex gap-1">
              {(["All", "Breaking", "Significant", "Routine"] as const).map((imp) => (
                <button key={imp} onClick={() => setImportanceFilter(imp)}
                  className={cn(
                    "px-2 py-1.5 rounded-lg text-xs font-medium transition-colors",
                    importanceFilter === imp
                      ? "bg-[var(--accent-positive)]/15 text-[var(--accent-positive)]"
                      : "text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] hover:text-[var(--text-secondary)]"
                  )}>
                  {imp}
                </button>
              ))}
            </div>
            <div className="relative">
              <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}
                className="pl-2 pr-6 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] focus:outline-none appearance-none">
                {["All", "Strategies", "Patterns", "News", "Risk", "Account"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="flex gap-1">
              {(["Today", "7d", "30d"] as const).map((d) => (
                <button key={d} onClick={() => setDateFilter(d)}
                  className={cn(
                    "px-2 py-1.5 rounded-lg text-xs font-medium transition-colors",
                    dateFilter === d
                      ? "bg-[var(--accent-positive)]/15 text-[var(--accent-positive)]"
                      : "text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] hover:text-[var(--text-secondary)]"
                  )}>
                  {d}
                </button>
              ))}
            </div>
            {activeFilterCount > 0 && (
              <span className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs bg-[var(--accent-positive)]/10 text-[var(--accent-positive)]">
                <Filter size={10} /> {activeFilterCount} active
              </span>
            )}
          </div>
        </div>

        {/* Alert list */}
        <div className="flex-1 overflow-y-auto bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl mx-4 mb-4">
          {/* Bulk header */}
          <div className="flex items-center px-3 py-2 border-b border-[var(--border-subtle)]/50 gap-2">
            <div onClick={handleSelectAll}
              className={cn(
                "w-4 h-4 rounded border flex items-center justify-center cursor-pointer transition-all",
                selectAll ? "bg-[var(--accent-positive)] border-[var(--accent-positive)]" : "border-zinc-600 hover:border-zinc-400"
              )}>
              {selectAll && <Check size={10} className="text-black" />}
            </div>
            <span className="text-xs text-[var(--text-tertiary)] flex-1">
              {checkedIds.size > 0 ? `${checkedIds.size} selected` : `${filtered.length} alerts`}
            </span>
            {checkedIds.size > 0 && (
              <button onClick={markAllRead} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1">
                <Eye size={11} /> Mark read
              </button>
            )}
          </div>

          {filtered.length === 0 ? (
            <div className="py-16 text-center">
              <BellOff size={32} className="text-zinc-700 mx-auto mb-3" />
              <p className="text-[var(--text-secondary)] text-sm font-medium">No alerts match your filters</p>
              <p className="text-[var(--text-tertiary)] text-xs mt-1">Try removing filters</p>
              <button
                onClick={() => { setSearch(""); setImportanceFilter("All"); setSourceFilter("All"); setDateFilter("Today"); }}
                className="mt-3 text-xs text-[var(--accent-positive)] hover:underline">
                Clear all filters
              </button>
            </div>
          ) : groupByTicker && grouped ? (
            Array.from(grouped.entries()).map(([ticker, group]) => {
              const isExpanded = expandedTickers.has(ticker) || group.length === 1;
              const topAlert = group[0];
              if (group.length === 1) {
                return (
                  <AlertRow key={topAlert.id} alert={topAlert} selected={selectedId === topAlert.id}
                    onSelect={() => handleRowClick(topAlert.id)} onRead={markRead} onDismiss={dismiss}
                    onSnooze={snooze} onMute={muteTicker} checked={checkedIds.has(topAlert.id)}
                    onCheck={() => toggleCheck(topAlert.id)} />
                );
              }
              return (
                <div key={ticker}>
                  <div
                    className="flex items-center px-3 py-2.5 border-b border-[var(--border-subtle)]/50 cursor-pointer hover:bg-[var(--bg-elevated-2)]/40 transition-colors"
                    onClick={() => toggleExpandTicker(ticker)}>
                    <div className={cn("w-[3px] shrink-0 rounded mr-2", importanceBar(topAlert.importance))} />
                    <div className="flex-1 flex items-center gap-2 min-w-0">
                      <span className={cn("font-mono text-xs font-bold px-1.5 py-0.5 rounded", tickerColor(ticker))}>{ticker}</span>
                      <span className="text-xs text-[var(--text-secondary)] font-medium">{ticker} · {group.length} signals</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">{timeAgo(topAlert.timestamp)}</span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {group.filter((a) => !a.is_read).length > 0 && (
                        <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-positive)]" />
                      )}
                      {isExpanded ? <ChevronDown size={14} className="text-[var(--text-tertiary)]" /> : <ChevronRight size={14} className="text-[var(--text-tertiary)]" />}
                    </div>
                  </div>
                  {isExpanded && group.map((a) => (
                    <div key={a.id} className="pl-3">
                      <AlertRow alert={a} selected={selectedId === a.id}
                        onSelect={() => handleRowClick(a.id)} onRead={markRead} onDismiss={dismiss}
                        onSnooze={snooze} onMute={muteTicker} checked={checkedIds.has(a.id)}
                        onCheck={() => toggleCheck(a.id)} />
                    </div>
                  ))}
                </div>
              );
            })
          ) : (
            filtered.map((a) => (
              <AlertRow key={a.id} alert={a} selected={selectedId === a.id}
                onSelect={() => handleRowClick(a.id)} onRead={markRead} onDismiss={dismiss}
                onSnooze={snooze} onMute={muteTicker} checked={checkedIds.has(a.id)}
                onCheck={() => toggleCheck(a.id)} />
            ))
          )}
        </div>

        {/* Alert Health Card */}
        <div className="mx-4 mb-4 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Activity size={14} className="text-[var(--accent-positive)]" />
              <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Weekly Alert Health</span>
            </div>
            <span className="text-xs text-[var(--text-tertiary)]">This week</span>
          </div>
          <div className="flex items-center gap-4 text-xs text-[var(--text-secondary)] mb-3">
            <span><span className="font-bold text-[var(--text-primary)]">{totalToday}</span> received</span>
            <span><span className="font-bold text-[var(--accent-positive)]">{actedOn}</span> acted on</span>
            <span><span className="font-bold text-[var(--text-tertiary)]">{Math.max(0, dismissed)}</span> dismissed</span>
          </div>
          <div className="w-full bg-[var(--bg-elevated-2)] rounded-full h-1.5 mb-3">
            <div className="bg-[var(--accent-positive)] h-1.5 rounded-full" style={{ width: `${(actedOn / totalToday) * 100}%` }} />
          </div>
          <p className="text-[10px] text-[var(--text-tertiary)]">
            <AlertTriangle size={9} className="inline text-amber-400 mr-1" />
            Your dismiss rate on &apos;Routine&apos; alerts is 89%. Consider quieting them.
          </p>
        </div>
      </div>

      {/* Detail panel */}
      {selectedAlert && (
        <div className="w-full md:w-[40%] flex-shrink-0 overflow-y-auto">
          <DetailPanel alert={selectedAlert} onClose={() => setSelectedId(null)} onMuteType={muteType} />
        </div>
      )}
    </div>
  );
}
