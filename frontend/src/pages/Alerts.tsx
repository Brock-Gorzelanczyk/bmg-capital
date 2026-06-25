import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { cn, timeAgo } from "@/lib/utils";
import { toast } from "sonner";
import {
  Bell, BellOff, AlertTriangle, Activity,
  Filter, Search, ChevronDown, ChevronRight, X, Check, Eye, VolumeX,
  Clock, Settings, BarChart2, ExternalLink,
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

const MOCK_ALERTS: Alert[] = [];

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
    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-zinc-700/60 text-zinc-400">
      🔥 {score}
    </span>
  );
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-zinc-700/60 text-zinc-400">
      {score}
    </span>
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
  const navigate = useNavigate();

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
            <button onClick={() => navigate(`/strategy/scout/chart/${encodeURIComponent(alert.ticker)}/turtle_donchian_s2`)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--text-secondary)] bg-[var(--border-subtle)]/60 hover:bg-[var(--border-emphasis)] transition-colors">
              <BarChart2 size={10} /> View Chart
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
  const navigate = useNavigate();
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

        <button onClick={() => navigate(`/strategy/scout/chart/${encodeURIComponent(alert.ticker)}/turtle_donchian_s2`)}
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
  const [dismissedCount, setDismissedCount] = useState(0);
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
    setDismissedCount((c) => c + 1);
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

  const received = alerts.length + dismissedCount;
  const actedOn = alerts.filter((a) => a.is_read).length;
  const dismissed = dismissedCount;

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
                You've received {received} alerts today. Acting on {actedOn}. Want to tune?
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
              {alerts.length === 0 ? (
                <>
                  <p className="text-[var(--text-secondary)] text-sm font-medium">No alerts yet</p>
                  <p className="text-[var(--text-tertiary)] text-xs mt-1">Alerts fire when bots detect setups in your universe.</p>
                </>
              ) : (
                <>
                  <p className="text-[var(--text-secondary)] text-sm font-medium">No alerts match your filters</p>
                  <p className="text-[var(--text-tertiary)] text-xs mt-1">Try removing filters</p>
                </>
              )}
              <button
                onClick={() => { setSearch(""); setImportanceFilter("All"); setSourceFilter("All"); setDateFilter("Today"); }}
                className={cn("mt-3 text-xs text-[var(--accent-positive)] hover:underline", alerts.length === 0 && "hidden")}>
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
            <span><span className="font-bold text-[var(--text-primary)]">{received}</span> received</span>
            <span><span className="font-bold text-[var(--accent-positive)]">{actedOn}</span> acted on</span>
            <span><span className="font-bold text-[var(--text-tertiary)]">{dismissed}</span> dismissed</span>
          </div>
          <div className="w-full bg-[var(--bg-elevated-2)] rounded-full h-1.5 mb-3">
            <div className="bg-[var(--accent-positive)] h-1.5 rounded-full" style={{ width: received > 0 ? `${(actedOn / received) * 100}%` : "0%" }} />
          </div>
          {received > 0 && (
            <p className="text-[10px] text-[var(--text-tertiary)]">
              <AlertTriangle size={9} className="inline text-amber-400 mr-1" />
              Your dismiss rate on &apos;Routine&apos; alerts is 89%. Consider quieting them.
            </p>
          )}
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
