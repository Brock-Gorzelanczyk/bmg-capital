import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Radar,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  Volume2,
  Activity,
  Eye,
  Users,
  Zap,
  Target,
  BarChart2,
  Clock,
  RefreshCw,
  ChevronUp,
  ChevronDown,
  ExternalLink,
  LayoutGrid,
  List,
  Thermometer,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type SortDir = "asc" | "desc";

interface SortState {
  col: string;
  dir: SortDir;
}

interface ScannerHit {
  ticker: string;
  name: string;
  signal: string;
  keyMetric: string;
  keyMetricRaw: number;
  volume: string;
  pctChange: number;
  time: string;
  extra?: Record<string, string | number>;
}

interface Scanner {
  id: number;
  name: string;
  description: string;
  schedule: string;
  icon: React.ReactNode;
  hits: ScannerHit[];
  columns: string[];
  lastRun: string;
  status: "live" | "running" | "scheduled";
  hasSectorHeatmap?: boolean;
}

// ── Mock Data ─────────────────────────────────────────────────────────────────

const SCANNERS: Scanner[] = [
  {
    id: 1,
    name: "Premarket Gappers",
    description: "Gap ≥3%, premkt vol ≥150K, news <18h",
    schedule: "4:00am – 9:30am",
    icon: <TrendingUp size={15} />,
    lastRun: "4:52 AM",
    status: "live",
    columns: ["Ticker", "Signal", "Gap %", "Premkt Vol", "Catalyst", "Time"],
    hits: [
      { ticker: "NVDA", name: "NVIDIA Corp", signal: "Gap Up", keyMetric: "+5.2%", keyMetricRaw: 5.2, volume: "2.4M", pctChange: 5.2, time: "4:48 AM", extra: { catalyst: "Earnings beat" } },
      { ticker: "TSLA", name: "Tesla Inc", signal: "Gap Up", keyMetric: "+3.8%", keyMetricRaw: 3.8, volume: "1.9M", pctChange: 3.8, time: "4:49 AM", extra: { catalyst: "Analyst upgrade" } },
      { ticker: "COIN", name: "Coinbase Global", signal: "Gap Up", keyMetric: "+4.1%", keyMetricRaw: 4.1, volume: "890K", pctChange: 4.1, time: "4:50 AM", extra: { catalyst: "Product launch" } },
      { ticker: "SMCI", name: "Super Micro Computer", signal: "Gap Up", keyMetric: "+6.7%", keyMetricRaw: 6.7, volume: "1.2M", pctChange: 6.7, time: "4:51 AM", extra: { catalyst: "FDA approval" } },
      { ticker: "MSTR", name: "MicroStrategy", signal: "Gap Up", keyMetric: "+3.2%", keyMetricRaw: 3.2, volume: "760K", pctChange: 3.2, time: "4:52 AM", extra: { catalyst: "Partnership" } },
    ],
  },
  {
    id: 2,
    name: "Unusual Volume",
    description: "Vol >2× 20-day avg by 10:30 AM + move >2%",
    schedule: "Intraday",
    icon: <Volume2 size={15} />,
    lastRun: "10:12 AM",
    status: "live",
    columns: ["Ticker", "Signal", "Vol (today)", "Vol Ratio", "% Change", "Time"],
    hits: [
      { ticker: "PLTR", name: "Palantir Technologies", signal: "Volume Surge", keyMetric: "4.1×", keyMetricRaw: 4.1, volume: "8.2M", pctChange: 4.3, time: "10:08 AM" },
      { ticker: "AMD", name: "Advanced Micro Devices", signal: "Volume Surge", keyMetric: "2.3×", keyMetricRaw: 2.3, volume: "42M", pctChange: 2.1, time: "10:09 AM" },
      { ticker: "RIVN", name: "Rivian Automotive", signal: "Volume Surge", keyMetric: "3.8×", keyMetricRaw: 3.8, volume: "12M", pctChange: 5.8, time: "10:11 AM" },
      { ticker: "HOOD", name: "Robinhood Markets", signal: "Volume Surge", keyMetric: "2.9×", keyMetricRaw: 2.9, volume: "5.1M", pctChange: 3.2, time: "10:12 AM" },
    ],
  },
  {
    id: 3,
    name: "52-Wk High Breakout",
    description: "New 252d high + vol ≥1.5× 50d + close top 25% of range",
    schedule: "EOD",
    icon: <Target size={15} />,
    lastRun: "4:01 PM",
    status: "scheduled",
    hasSectorHeatmap: true,
    columns: ["Ticker", "Signal", "% Above Prior High", "Vol Ratio", "% Change", "Date"],
    hits: [
      { ticker: "GOOGL", name: "Alphabet Inc", signal: "Breakout", keyMetric: "+1.4%", keyMetricRaw: 1.4, volume: "28M", pctChange: 2.1, time: "Yesterday", extra: { volRatio: "1.8×" } },
      { ticker: "META", name: "Meta Platforms", signal: "Breakout", keyMetric: "+2.1%", keyMetricRaw: 2.1, volume: "21M", pctChange: 1.9, time: "Yesterday", extra: { volRatio: "2.1×" } },
      { ticker: "AMZN", name: "Amazon.com", signal: "Breakout", keyMetric: "+0.9%", keyMetricRaw: 0.9, volume: "33M", pctChange: 1.5, time: "Yesterday", extra: { volRatio: "1.6×" } },
      { ticker: "ORCL", name: "Oracle Corp", signal: "Breakout", keyMetric: "+3.2%", keyMetricRaw: 3.2, volume: "14M", pctChange: 3.7, time: "Yesterday", extra: { volRatio: "2.4×" } },
      { ticker: "LLY", name: "Eli Lilly", signal: "Breakout", keyMetric: "+1.7%", keyMetricRaw: 1.7, volume: "6.2M", pctChange: 2.4, time: "Yesterday", extra: { volRatio: "1.9×" } },
    ],
  },
  {
    id: 4,
    name: "200-DMA Breakdown Risk",
    description: "Close within 2% of 200-SMA from above + declining vol",
    schedule: "EOD",
    icon: <TrendingDown size={15} />,
    lastRun: "4:02 PM",
    status: "scheduled",
    columns: ["Ticker", "Signal", "% From 200-DMA", "Vol Trend", "% Change", "Date"],
    hits: [
      { ticker: "INTC", name: "Intel Corp", signal: "Breakdown Risk", keyMetric: "-1.2%", keyMetricRaw: -1.2, volume: "38M", pctChange: -1.8, time: "Yesterday", extra: { volTrend: "Declining" } },
      { ticker: "PFE", name: "Pfizer Inc", signal: "Breakdown Risk", keyMetric: "-0.7%", keyMetricRaw: -0.7, volume: "44M", pctChange: -1.1, time: "Yesterday", extra: { volTrend: "Declining" } },
      { ticker: "VZ", name: "Verizon Communications", signal: "Breakdown Risk", keyMetric: "-1.9%", keyMetricRaw: -1.9, volume: "22M", pctChange: -0.9, time: "Yesterday", extra: { volTrend: "Declining" } },
      { ticker: "T", name: "AT&T Inc", signal: "Breakdown Risk", keyMetric: "-0.4%", keyMetricRaw: -0.4, volume: "55M", pctChange: -0.6, time: "Yesterday", extra: { volTrend: "Declining" } },
      { ticker: "BA", name: "Boeing Co", signal: "Breakdown Risk", keyMetric: "-1.6%", keyMetricRaw: -1.6, volume: "18M", pctChange: -2.2, time: "Yesterday", extra: { volTrend: "Declining" } },
    ],
  },
  {
    id: 5,
    name: "Earnings Beat Drift",
    description: "SUE >75th pct + day-1 gap >3% + guidance raised",
    schedule: "EOD post-earnings",
    icon: <BarChart2 size={15} />,
    lastRun: "4:05 PM",
    status: "scheduled",
    columns: ["Ticker", "Signal", "EPS Beat %", "Day-1 Gap", "% Change", "Date"],
    hits: [
      { ticker: "PANW", name: "Palo Alto Networks", signal: "PEAD Setup", keyMetric: "+18.4%", keyMetricRaw: 18.4, volume: "9.2M", pctChange: 4.2, time: "3 days ago", extra: { gap: "+6.1%" } },
      { ticker: "CRWD", name: "CrowdStrike", signal: "PEAD Setup", keyMetric: "+22.7%", keyMetricRaw: 22.7, volume: "7.8M", pctChange: 5.5, time: "5 days ago", extra: { gap: "+8.3%" } },
      { ticker: "FTNT", name: "Fortinet", signal: "PEAD Setup", keyMetric: "+14.1%", keyMetricRaw: 14.1, volume: "8.1M", pctChange: 3.7, time: "6 days ago", extra: { gap: "+4.9%" } },
      { ticker: "ZS", name: "Zscaler", signal: "PEAD Setup", keyMetric: "+31.2%", keyMetricRaw: 31.2, volume: "5.4M", pctChange: 7.1, time: "1 week ago", extra: { gap: "+11.2%" } },
      { ticker: "SNOW", name: "Snowflake Inc", signal: "PEAD Setup", keyMetric: "+11.8%", keyMetricRaw: 11.8, volume: "12M", pctChange: 3.1, time: "1 week ago", extra: { gap: "+3.8%" } },
    ],
  },
  {
    id: 6,
    name: "Dark Pool Prints",
    description: "DP vol >500% of 30d avg over 3–5 sessions",
    schedule: "Hourly",
    icon: <Eye size={15} />,
    lastRun: "10:00 AM",
    status: "live",
    columns: ["Ticker", "Signal", "DP Vol", "vs 30d Avg", "% Change", "Time"],
    hits: [
      { ticker: "AAPL", name: "Apple Inc", signal: "Dark Pool Surge", keyMetric: "7.4×", keyMetricRaw: 7.4, volume: "88M", pctChange: 1.2, time: "9:45 AM" },
      { ticker: "MSFT", name: "Microsoft Corp", signal: "Dark Pool Surge", keyMetric: "6.1×", keyMetricRaw: 6.1, volume: "44M", pctChange: 0.8, time: "9:50 AM" },
      { ticker: "SPY", name: "SPDR S&P 500 ETF", signal: "Dark Pool Surge", keyMetric: "5.8×", keyMetricRaw: 5.8, volume: "142M", pctChange: 0.4, time: "9:58 AM" },
      { ticker: "QQQ", name: "Invesco QQQ Trust", signal: "Dark Pool Surge", keyMetric: "5.2×", keyMetricRaw: 5.2, volume: "68M", pctChange: 0.6, time: "9:59 AM" },
      { ticker: "NVDA", name: "NVIDIA Corp", signal: "Dark Pool Surge", keyMetric: "8.9×", keyMetricRaw: 8.9, volume: "52M", pctChange: 2.3, time: "10:00 AM" },
    ],
  },
  {
    id: 7,
    name: "Insider Cluster Buy",
    description: "≥3 insiders + ≥$1M total + 30-day window",
    schedule: "Daily",
    icon: <Users size={15} />,
    lastRun: "8:00 AM",
    status: "live",
    columns: ["Ticker", "Company", "# Insiders", "Total $", "Roles", "Date"],
    hits: [
      { ticker: "CVNA", name: "Carvana Co", signal: "Cluster Buy", keyMetric: "$4.2M", keyMetricRaw: 4200000, volume: "—", pctChange: 3.1, time: "May 28", extra: { insiders: 4, roles: "CEO, CFO, Dir, Dir" } },
      { ticker: "IONQ", name: "IonQ Inc", signal: "Cluster Buy", keyMetric: "$2.8M", keyMetricRaw: 2800000, volume: "—", pctChange: 2.4, time: "May 27", extra: { insiders: 3, roles: "CEO, COO, Dir" } },
      { ticker: "ALAB", name: "Astera Labs", signal: "Cluster Buy", keyMetric: "$6.1M", keyMetricRaw: 6100000, volume: "—", pctChange: 4.8, time: "May 26", extra: { insiders: 5, roles: "CEO, CFO, CTO, Dir, Dir" } },
      { ticker: "HIMS", name: "Hims & Hers Health", signal: "Cluster Buy", keyMetric: "$1.9M", keyMetricRaw: 1900000, volume: "—", pctChange: 1.9, time: "May 25", extra: { insiders: 3, roles: "CEO, Dir, Dir" } },
    ],
  },
  {
    id: 8,
    name: "VWAP Reclaim",
    description: "Reclaim anchored VWAP from last earnings + vol ≥1.5×",
    schedule: "5-min bars",
    icon: <Activity size={15} />,
    lastRun: "10:15 AM",
    status: "live",
    columns: ["Ticker", "Signal", "Reclaim Strength", "Anchor Date", "% Change", "Time"],
    hits: [
      { ticker: "NFLX", name: "Netflix Inc", signal: "AVWAP Reclaim", keyMetric: "+2.8%", keyMetricRaw: 2.8, volume: "6.1M", pctChange: 2.8, time: "10:09 AM", extra: { anchor: "Apr 18" } },
      { ticker: "UBER", name: "Uber Technologies", signal: "AVWAP Reclaim", keyMetric: "+1.4%", keyMetricRaw: 1.4, volume: "14M", pctChange: 1.4, time: "10:11 AM", extra: { anchor: "May 7" } },
      { ticker: "SHOP", name: "Shopify Inc", signal: "AVWAP Reclaim", keyMetric: "+3.1%", keyMetricRaw: 3.1, volume: "8.7M", pctChange: 3.1, time: "10:13 AM", extra: { anchor: "May 9" } },
      { ticker: "SPOT", name: "Spotify Technology", signal: "AVWAP Reclaim", keyMetric: "+2.2%", keyMetricRaw: 2.2, volume: "4.4M", pctChange: 2.2, time: "10:15 AM", extra: { anchor: "Apr 29" } },
    ],
  },
  {
    id: 9,
    name: "RS Leaders Hot Sectors",
    description: "Stock RS ≥90 AND sector RS ≥80 vs SPY",
    schedule: "EOD",
    icon: <Zap size={15} />,
    lastRun: "4:03 PM",
    status: "scheduled",
    hasSectorHeatmap: true,
    columns: ["Ticker", "Signal", "Stock RS", "Sector RS", "% Change", "Date"],
    hits: [
      { ticker: "NVDA", name: "NVIDIA Corp", signal: "RS Leader", keyMetric: "98", keyMetricRaw: 98, volume: "44M", pctChange: 3.2, time: "Yesterday", extra: { sectorRs: 94, sector: "Semiconductors" } },
      { ticker: "META", name: "Meta Platforms", signal: "RS Leader", keyMetric: "95", keyMetricRaw: 95, volume: "18M", pctChange: 2.1, time: "Yesterday", extra: { sectorRs: 88, sector: "Internet" } },
      { ticker: "AVGO", name: "Broadcom Inc", signal: "RS Leader", keyMetric: "93", keyMetricRaw: 93, volume: "11M", pctChange: 1.9, time: "Yesterday", extra: { sectorRs: 94, sector: "Semiconductors" } },
      { ticker: "CEG", name: "Constellation Energy", signal: "RS Leader", keyMetric: "91", keyMetricRaw: 91, volume: "4.8M", pctChange: 2.7, time: "Yesterday", extra: { sectorRs: 85, sector: "Utilities" } },
      { ticker: "VST", name: "Vistra Corp", signal: "RS Leader", keyMetric: "90", keyMetricRaw: 90, volume: "6.2M", pctChange: 2.4, time: "Yesterday", extra: { sectorRs: 85, sector: "Utilities" } },
    ],
  },
  {
    id: 10,
    name: "Oversold Bounce (Connors)",
    description: "Above 200-SMA + 2-period RSI <5",
    schedule: "EOD",
    icon: <TrendingUp size={15} />,
    lastRun: "4:04 PM",
    status: "scheduled",
    columns: ["Ticker", "Signal", "2-Period RSI", "vs 200-SMA", "% Change", "Date"],
    hits: [
      { ticker: "XOM", name: "Exxon Mobil", signal: "Connors RSI2", keyMetric: "3.1", keyMetricRaw: 3.1, volume: "19M", pctChange: -1.4, time: "Yesterday", extra: { vsSma: "+4.2%" } },
      { ticker: "JPM", name: "JPMorgan Chase", signal: "Connors RSI2", keyMetric: "2.4", keyMetricRaw: 2.4, volume: "12M", pctChange: -2.1, time: "Yesterday", extra: { vsSma: "+6.8%" } },
      { ticker: "GS", name: "Goldman Sachs", signal: "Connors RSI2", keyMetric: "4.7", keyMetricRaw: 4.7, volume: "4.1M", pctChange: -1.8, time: "Yesterday", extra: { vsSma: "+8.1%" } },
      { ticker: "BAC", name: "Bank of America", signal: "Connors RSI2", keyMetric: "1.9", keyMetricRaw: 1.9, volume: "58M", pctChange: -2.6, time: "Yesterday", extra: { vsSma: "+3.4%" } },
      { ticker: "WFC", name: "Wells Fargo", signal: "Connors RSI2", keyMetric: "3.8", keyMetricRaw: 3.8, volume: "22M", pctChange: -1.9, time: "Yesterday", extra: { vsSma: "+5.7%" } },
    ],
  },
  {
    id: 11,
    name: "Bollinger/Keltner Squeeze",
    description: "BB width 6-mo low + close inside Keltner",
    schedule: "EOD + intraday",
    icon: <BarChart2 size={15} />,
    lastRun: "10:05 AM",
    status: "live",
    columns: ["Ticker", "Signal", "Squeeze Days", "BB Width %", "% Change", "Time"],
    hits: [
      { ticker: "TSLA", name: "Tesla Inc", signal: "BB Squeeze", keyMetric: "8d", keyMetricRaw: 8, volume: "62M", pctChange: 0.4, time: "10:01 AM", extra: { bbWidth: "3.2%" } },
      { ticker: "ROKU", name: "Roku Inc", signal: "BB Squeeze", keyMetric: "12d", keyMetricRaw: 12, volume: "7.8M", pctChange: -0.2, time: "10:02 AM", extra: { bbWidth: "2.8%" } },
      { ticker: "MELI", name: "MercadoLibre", signal: "BB Squeeze", keyMetric: "6d", keyMetricRaw: 6, volume: "1.4M", pctChange: 0.1, time: "10:03 AM", extra: { bbWidth: "4.1%" } },
      { ticker: "SQ", name: "Block Inc", signal: "BB Squeeze", keyMetric: "14d", keyMetricRaw: 14, volume: "8.9M", pctChange: -0.3, time: "10:04 AM", extra: { bbWidth: "2.4%" } },
      { ticker: "PYPL", name: "PayPal Holdings", signal: "BB Squeeze", keyMetric: "9d", keyMetricRaw: 9, volume: "12M", pctChange: 0.2, time: "10:05 AM", extra: { bbWidth: "3.7%" } },
    ],
  },
  {
    id: 12,
    name: "ORB Stocks-in-Play",
    description: "Gap >2% + news + ADV >1M + premkt vol >100K",
    schedule: "9:30–9:40am",
    icon: <Clock size={15} />,
    lastRun: "9:41 AM",
    status: "live",
    columns: ["Ticker", "Signal", "ORB Range", "Premkt Vol", "% Change", "Time"],
    hits: [
      { ticker: "ARM", name: "Arm Holdings", signal: "ORB Candidate", keyMetric: "$2.14", keyMetricRaw: 2.14, volume: "4.8M", pctChange: 3.6, time: "9:35 AM", extra: { premktVol: "312K" } },
      { ticker: "SOUN", name: "SoundHound AI", signal: "ORB Candidate", keyMetric: "$0.44", keyMetricRaw: 0.44, volume: "18M", pctChange: 5.2, time: "9:36 AM", extra: { premktVol: "780K" } },
      { ticker: "LUNR", name: "Intuitive Machines", signal: "ORB Candidate", keyMetric: "$0.88", keyMetricRaw: 0.88, volume: "9.4M", pctChange: 4.1, time: "9:38 AM", extra: { premktVol: "210K" } },
      { ticker: "RKLB", name: "Rocket Lab USA", signal: "ORB Candidate", keyMetric: "$0.62", keyMetricRaw: 0.62, volume: "11M", pctChange: 3.8, time: "9:40 AM", extra: { premktVol: "148K" } },
    ],
  },
];

// ── Sector heatmap data ───────────────────────────────────────────────────────

const SECTOR_HEATMAP = [
  { sector: "Semiconductors", hits: 4, color: "bg-lime-500/80" },
  { sector: "Software", hits: 3, color: "bg-lime-400/70" },
  { sector: "Internet", hits: 3, color: "bg-lime-400/70" },
  { sector: "Biotech", hits: 2, color: "bg-yellow-400/70" },
  { sector: "Utilities", hits: 2, color: "bg-yellow-400/70" },
  { sector: "Financials", hits: 1, color: "bg-yellow-300/50" },
  { sector: "Energy", hits: 1, color: "bg-yellow-300/50" },
  { sector: "Industrials", hits: 0, color: "bg-white/5" },
  { sector: "Consumer", hits: 0, color: "bg-white/5" },
];

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: Scanner["status"] }) {
  return (
    <span
      className={cn(
        "inline-block w-2 h-2 rounded-full flex-shrink-0",
        status === "live" && "bg-lime-400 shadow-[0_0_6px_var(--accent-positive)]",
        status === "running" && "bg-amber-400 animate-pulse",
        status === "scheduled" && "bg-white/25"
      )}
    />
  );
}

function SortIcon({ col, sort }: { col: string; sort: SortState }) {
  if (sort.col !== col) return <ChevronUp size={12} className="opacity-20" />;
  return sort.dir === "asc" ? <ChevronUp size={12} className="text-blue-400" /> : <ChevronDown size={12} className="text-blue-400" />;
}

function SignalBar({ value, max = 10 }: { value: number; max?: number }) {
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  const positive = value >= 0;
  return (
    <div className="w-full h-1.5 rounded-full bg-white/10 overflow-hidden">
      <div
        className={cn("h-full rounded-full", positive ? "bg-lime-400" : "bg-red-400")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScannersPage() {
  const navigate = useNavigate();
  const [activeId, setActiveId] = useState(1);
  const [viewMode, setViewMode] = useState<"table" | "card">("table");
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [sort, setSort] = useState<SortState>({ col: "pctChange", dir: "desc" });

  const activeScanner = useMemo(
    () => SCANNERS.find((s) => s.id === activeId)!,
    [activeId]
  );

  const totalHits = useMemo(
    () => SCANNERS.reduce((acc, s) => acc + s.hits.length, 0),
    []
  );

  const sortedHits = useMemo(() => {
    return [...activeScanner.hits].sort((a, b) => {
      let va: string | number = 0;
      let vb: string | number = 0;
      if (sort.col === "ticker") { va = a.ticker; vb = b.ticker; }
      else if (sort.col === "pctChange") { va = a.pctChange; vb = b.pctChange; }
      else if (sort.col === "keyMetric") { va = a.keyMetricRaw; vb = b.keyMetricRaw; }
      else if (sort.col === "volume") { va = a.volume; vb = b.volume; }
      else if (sort.col === "time") { va = a.time; vb = b.time; }
      if (typeof va === "string" && typeof vb === "string") {
        return sort.dir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      return sort.dir === "asc" ? (va as number) - (vb as number) : (vb as number) - (va as number);
    });
  }, [activeScanner, sort]);

  function toggleSort(col: string) {
    setSort((prev) =>
      prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "desc" }
    );
  }

  const canHeatmap = activeScanner.hasSectorHeatmap;

  return (
    <div className="flex flex-col h-full min-h-screen" style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}>
      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-4 border-b" style={{ borderColor: "var(--border-subtle)" }}>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: "var(--bg-elevated-2)" }}>
              <Radar size={18} className="text-blue-400" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
                Market Scanners
              </h1>
              <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>
                12 real-time scanners · auto-refreshes every 5 min
              </p>
            </div>
          </div>

          {/* Status bar */}
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
              <Clock size={12} />
              <span>Last scan: <span style={{ color: "var(--text-secondary)" }}>10:15 AM</span></span>
            </div>
            <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
              <AlertCircle size={12} />
              <span><span style={{ color: "var(--text-secondary)" }}>{totalHits}</span> total hits</span>
            </div>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
              style={{ background: "rgba(163,230,53,0.12)", color: "var(--accent-positive)", border: "1px solid rgba(163,230,53,0.25)" }}>
              <span className="w-1.5 h-1.5 rounded-full bg-lime-400 animate-pulse" />
              Live
            </span>
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}>
              <RefreshCw size={12} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Scanner List ── */}
        <aside className="w-72 flex-shrink-0 overflow-y-auto border-r py-2"
          style={{ borderColor: "var(--border-subtle)", background: "var(--bg-base)" }}>
          {SCANNERS.map((s) => (
            <button
              key={s.id}
              onClick={() => { setActiveId(s.id); setShowHeatmap(false); }}
              className={cn(
                "w-full text-left px-4 py-3 flex items-start gap-3 transition-colors border-l-2 group",
                activeId === s.id
                  ? "border-blue-500"
                  : "border-transparent hover:border-white/10"
              )}
              style={{
                background: activeId === s.id ? "var(--bg-elevated)" : "transparent",
              }}
            >
              <div className={cn("mt-0.5 flex-shrink-0 opacity-60 group-hover:opacity-80", activeId === s.id && "opacity-100 text-blue-400")}>
                {s.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className={cn("text-sm font-medium truncate", activeId === s.id ? "text-blue-300" : "")}
                    style={{ color: activeId === s.id ? undefined : "var(--text-primary)" }}>
                    {s.name}
                  </span>
                  <span className={cn(
                    "flex-shrink-0 px-1.5 py-0.5 rounded-full text-xs font-semibold",
                    s.hits.length > 0 ? "bg-lime-400/15 text-lime-400" : "bg-white/8 text-white/30"
                  )}>
                    {s.hits.length}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <StatusDot status={s.status} />
                  <span className="text-xs truncate" style={{ color: "var(--text-tertiary)" }}>
                    {s.lastRun} · {s.schedule}
                  </span>
                </div>
              </div>
            </button>
          ))}
        </aside>

        {/* ── Results Panel ── */}
        <main className="flex-1 overflow-y-auto flex flex-col">
          {/* Toolbar */}
          <div className="flex items-center justify-between gap-4 px-5 py-3 border-b flex-wrap"
            style={{ borderColor: "var(--border-subtle)", background: "var(--bg-elevated)" }}>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{activeScanner.name}</span>
                <StatusDot status={activeScanner.status} />
                <span className="text-xs px-2 py-0.5 rounded" style={{ background: "var(--bg-elevated-2)", color: "var(--text-tertiary)" }}>
                  {activeScanner.schedule}
                </span>
              </div>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>{activeScanner.description}</p>
            </div>
            <div className="flex items-center gap-2">
              {canHeatmap && (
                <button
                  onClick={() => setShowHeatmap((v) => !v)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border",
                    showHeatmap
                      ? "border-blue-500/50 text-blue-300"
                      : "border-transparent"
                  )}
                  style={{
                    background: showHeatmap ? "rgba(59,130,246,0.12)" : "var(--bg-elevated-2)",
                    color: showHeatmap ? undefined : "var(--text-secondary)",
                    borderColor: showHeatmap ? undefined : "var(--border-subtle)",
                  }}
                >
                  <Thermometer size={13} />
                  Heatmap
                </button>
              )}
              <div className="flex items-center rounded-lg overflow-hidden border" style={{ borderColor: "var(--border-subtle)", background: "var(--bg-elevated-2)" }}>
                <button
                  onClick={() => setViewMode("table")}
                  className={cn("flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors")}
                  style={{
                    background: viewMode === "table" ? "var(--bg-elevated)" : "transparent",
                    color: viewMode === "table" ? "var(--text-primary)" : "var(--text-tertiary)",
                  }}
                >
                  <List size={13} />
                  Table
                </button>
                <button
                  onClick={() => setViewMode("card")}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors"
                  style={{
                    background: viewMode === "card" ? "var(--bg-elevated)" : "transparent",
                    color: viewMode === "card" ? "var(--text-primary)" : "var(--text-tertiary)",
                  }}
                >
                  <LayoutGrid size={13} />
                  Cards
                </button>
              </div>
            </div>
          </div>

          {/* Heatmap */}
          {showHeatmap && canHeatmap && (
            <div className="px-5 py-4 border-b" style={{ borderColor: "var(--border-subtle)" }}>
              <p className="text-xs font-medium mb-3" style={{ color: "var(--text-secondary)" }}>
                Sector Hit Density
              </p>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-5">
                {SECTOR_HEATMAP.map((sec) => (
                  <div key={sec.sector}
                    className={cn("rounded-lg p-2.5 text-center text-xs font-medium", sec.color)}>
                    <div className="truncate mb-1" style={{ color: "var(--text-primary)" }}>{sec.sector}</div>
                    <div className="font-bold text-sm">{sec.hits}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Table View */}
          {viewMode === "table" && (
            <div className="overflow-x-auto flex-1">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr style={{ background: "var(--bg-elevated)", borderBottom: "1px solid var(--border-subtle)" }}>
                    {[
                      { key: "ticker", label: "Ticker" },
                      { key: "signal", label: "Signal" },
                      { key: "keyMetric", label: activeScanner.columns[2] ?? "Key Metric" },
                      { key: "volume", label: "Volume" },
                      { key: "pctChange", label: "% Chg" },
                      { key: "time", label: "Time" },
                    ].map((col) => (
                      <th key={col.key}
                        onClick={() => toggleSort(col.key)}
                        className="px-4 py-2.5 text-left font-medium cursor-pointer select-none whitespace-nowrap group"
                        style={{ color: "var(--text-secondary)" }}>
                        <div className="flex items-center gap-1">
                          {col.label}
                          <SortIcon col={col.key} sort={sort} />
                        </div>
                      </th>
                    ))}
                    <th className="px-4 py-2.5 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedHits.map((hit, i) => (
                    <tr key={hit.ticker + i}
                      className="border-b transition-colors hover:bg-white/3"
                      style={{ borderColor: "var(--border-subtle)" }}>
                      <td className="px-4 py-3 font-semibold text-blue-300">{hit.ticker}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs font-medium"
                          style={{ background: "var(--bg-elevated-2)", color: "var(--text-secondary)" }}>
                          {hit.signal}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-medium"
                        style={{ color: hit.keyMetricRaw >= 0 ? "var(--accent-positive)" : "var(--accent-negative)" }}>
                        {hit.keyMetric}
                      </td>
                      <td className="px-4 py-3" style={{ color: "var(--text-secondary)" }}>{hit.volume}</td>
                      <td className={cn("px-4 py-3 font-medium")}
                        style={{ color: hit.pctChange >= 0 ? "var(--accent-positive)" : "var(--accent-negative)" }}>
                        {hit.pctChange >= 0 ? "+" : ""}{hit.pctChange.toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-tertiary)" }}>{hit.time}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => navigate(`/chart?symbol=${hit.ticker}`)}
                          className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors hover:bg-white/10"
                          style={{ color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}>
                          <ExternalLink size={11} />
                          Chart
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Card View */}
          {viewMode === "card" && (
            <div className="p-5 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {sortedHits.map((hit, i) => (
                <div key={hit.ticker + i}
                  className="rounded-xl p-4 border transition-colors hover:border-white/20"
                  style={{ background: "var(--bg-elevated)", borderColor: "var(--border-subtle)" }}>
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-blue-300">{hit.ticker}</span>
                        <span className={cn("text-sm font-semibold")}
                          style={{ color: hit.pctChange >= 0 ? "var(--accent-positive)" : "var(--accent-negative)" }}>
                          {hit.pctChange >= 0 ? "+" : ""}{hit.pctChange.toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-xs mt-0.5 truncate max-w-[160px]" style={{ color: "var(--text-tertiary)" }}>
                        {hit.name}
                      </p>
                    </div>
                    <button
                      onClick={() => navigate(`/chart?symbol=${hit.ticker}`)}
                      className="text-blue-400 hover:text-blue-300 transition-colors"
                      title="View Chart">
                      <ExternalLink size={14} />
                    </button>
                  </div>
                  <div className="mb-2">
                    <div className="flex justify-between text-xs mb-1" style={{ color: "var(--text-tertiary)" }}>
                      <span>Signal strength</span>
                      <span style={{ color: "var(--text-secondary)" }}>{hit.keyMetric}</span>
                    </div>
                    <SignalBar value={hit.pctChange} max={10} />
                  </div>
                  <div className="flex items-center justify-between mt-3">
                    <span className="px-2 py-0.5 rounded text-xs"
                      style={{ background: "var(--bg-elevated-2)", color: "var(--text-secondary)" }}>
                      {hit.signal}
                    </span>
                    <button
                      className="px-3 py-1 rounded-lg text-xs font-semibold text-white transition-opacity hover:opacity-80"
                      style={{ background: "rgba(59,130,246,0.25)", border: "1px solid rgba(59,130,246,0.35)" }}>
                      Trade
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </main>
      </div>

      {/* ── Bottom Banner ── */}
      <div className="px-5 py-3 flex items-center justify-between gap-4 flex-wrap"
        style={{
          background: "rgba(251,191,36,0.07)",
          borderTop: "1px solid rgba(251,191,36,0.2)",
        }}>
        <div className="flex items-center gap-2 text-xs" style={{ color: "#f59e0b" }}>
          <AlertCircle size={14} />
          <span>
            Scanner data is delayed 15 min for Free tier. Upgrade to Plus for real-time alerts.
          </span>
        </div>
        <button
          className="px-4 py-1.5 rounded-lg text-xs font-semibold transition-opacity hover:opacity-90"
          style={{ background: "#f59e0b", color: "#000" }}>
          Upgrade to Plus
        </button>
      </div>
    </div>
  );
}
