import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Radar, AlertCircle, TrendingUp, TrendingDown, Volume2, Activity,
  Eye, Users, Zap, Target, BarChart2, Clock, RefreshCw, ChevronUp,
  ChevronDown, ExternalLink, LayoutGrid, List, Thermometer, Brain,
  Flame, DollarSign, Building2, Repeat2, ShieldAlert, Landmark,
  Bitcoin, Droplets, Wallet, AlertTriangle, Pin, Sparkles, X,
  Plus, ArrowUpRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────────

type SortDir = "asc" | "desc";
type ViewMode = "table" | "cards" | "heatmap" | "feed";
type ScannerStatus = "live" | "running" | "scheduled";
type ScannerTier = "free" | "plus" | "premium";
type ScannerCategory = "Momentum" | "Events" | "Smart Money" | "Catalyst" | "Crypto" | "Options" | "AI";

interface SortState { col: string; dir: SortDir; }

interface HeatCell { label: string; value: number; pct?: number; sub?: string; }

interface FeedEntry {
  id: number;
  ticker: string;
  strike?: string;
  expiry?: string;
  premium?: string;
  side?: string;
  oi?: string;
  amount?: string;
  wallet?: string;
  type?: string;
  time: string;
  isNew?: boolean;
}

interface MockRow {
  ticker: string;
  col2: string;
  col3: string;
  col4: string;
  col5: string;
  col6: string;
  pct: number;
  strength: number; // 0-100
}

interface ScannerDef {
  id: number;
  name: string;
  icon: React.ReactNode;
  description: string;
  trigger: string;
  refreshInterval: string;
  viewType: ViewMode;
  hits: number;
  status: ScannerStatus;
  lastRun: string;
  schedule: string;
  category: ScannerCategory;
  tier: ScannerTier;
  columns?: string[];
  rows?: MockRow[];
  heatCells?: HeatCell[];
  feedSeed?: FeedEntry[];
}

// ── Scanner Definitions ────────────────────────────────────────────────────────

const SCANNERS: ScannerDef[] = [
  // ── MOMENTUM ──
  {
    id: 1, name: "Top Movers", icon: <Flame size={14} />, tier: "free",
    description: "abs(%chg)>5%, vol>1M", trigger: "abs(%chg)>5%, vol>1M",
    refreshInterval: "30s", viewType: "heatmap", hits: 5,
    status: "live", lastRun: "10:28 AM", schedule: "Every 30s", category: "Momentum",
    heatCells: [
      { label: "SMCI", value: 8.2, pct: 8.2, sub: "+8.2%" },
      { label: "COIN", value: 7.4, pct: 7.4, sub: "+7.4%" },
      { label: "MARA", value: 6.1, pct: 6.1, sub: "+6.1%" },
      { label: "NVDA", value: 5.8, pct: 5.8, sub: "+5.8%" },
      { label: "PLTR", value: 5.1, pct: 5.1, sub: "+5.1%" },
      { label: "AMD",  value: 4.3, pct: 4.3, sub: "+4.3%" },
      { label: "TSLA", value: 3.2, pct: 3.2, sub: "+3.2%" },
      { label: "META", value: 2.1, pct: 2.1, sub: "+2.1%" },
      { label: "AMZN", value: 1.4, pct: 1.4, sub: "+1.4%" },
      { label: "QQQ",  value: 0.8, pct: 0.8, sub: "+0.8%" },
      { label: "SPY",  value: 0.4, pct: 0.4, sub: "+0.4%" },
      { label: "AAPL", value: -5.3, pct: -5.3, sub: "-5.3%" },
      { label: "INTC", value: -3.1, pct: -3.1, sub: "-3.1%" },
      { label: "PFE",  value: -2.4, pct: -2.4, sub: "-2.4%" },
      { label: "BA",   value: -1.8, pct: -1.8, sub: "-1.8%" },
    ],
    rows: [
      { ticker:"SMCI", col2:"Super Micro Computer", col3:"+8.2%", col4:"3.1M", col5:"Earnings", col6:"10:28 AM", pct:8.2, strength:82 },
      { ticker:"COIN", col2:"Coinbase Global",      col3:"+7.4%", col4:"2.8M", col5:"Momentum", col6:"10:27 AM", pct:7.4, strength:74 },
      { ticker:"MARA", col2:"Marathon Digital",     col3:"+6.1%", col4:"4.2M", col5:"Crypto",   col6:"10:25 AM", pct:6.1, strength:61 },
      { ticker:"NVDA", col2:"NVIDIA Corp",          col3:"+5.8%", col4:"38M",  col5:"AI",       col6:"10:22 AM", pct:5.8, strength:58 },
      { ticker:"AAPL", col2:"Apple Inc",            col3:"-5.3%", col4:"52M",  col5:"Downgrade", col6:"10:18 AM", pct:-5.3, strength:53 },
    ],
    columns: ["Ticker","Company","% Chg","Volume","Catalyst","Time"],
  },
  {
    id: 2, name: "52-Week Breakouts", icon: <Target size={14} />, tier: "free",
    description: "close=52wk high, vol>1.5×", trigger: "close=52wk high, vol>1.5× avg",
    refreshInterval: "1m", viewType: "cards", hits: 4,
    status: "live", lastRun: "10:29 AM", schedule: "Every 1m", category: "Momentum",
    rows: [
      { ticker:"NVDA", col2:"NVIDIA Corp",    col3:"$942.50", col4:"+2.1%", col5:"1.8×", col6:"10:29 AM", pct:2.1, strength:91 },
      { ticker:"AAPL", col2:"Apple Inc",      col3:"$221.30", col4:"+1.4%", col5:"2.1×", col6:"10:27 AM", pct:1.4, strength:78 },
      { ticker:"MSFT", col2:"Microsoft Corp", col3:"$468.20", col4:"+0.9%", col5:"1.6×", col6:"10:25 AM", pct:0.9, strength:64 },
      { ticker:"GOOGL",col2:"Alphabet Inc",   col3:"$198.80", col4:"+1.7%", col5:"1.9×", col6:"10:22 AM", pct:1.7, strength:72 },
    ],
    columns: ["Ticker","Company","Breakout Price","% Chg","Vol Ratio","Time"],
  },
  {
    id: 3, name: "Gap & Go", icon: <ArrowUpRight size={14} />, tier: "plus",
    description: "gap>2% open, premkt vol>500k", trigger: "gap>2% at open, premkt vol>500K",
    refreshInterval: "1m premarket", viewType: "table", hits: 5,
    status: "live", lastRun: "4:58 AM", schedule: "4am–9:30am", category: "Momentum",
    rows: [
      { ticker:"NVDA", col2:"+5.2%", col3:"2.4M", col4:"Earnings beat",    col5:"9:31 AM", col6:"4:48 AM", pct:5.2, strength:84 },
      { ticker:"TSLA", col2:"+3.8%", col3:"1.9M", col4:"Analyst upgrade",  col5:"9:31 AM", col6:"4:49 AM", pct:3.8, strength:68 },
      { ticker:"COIN", col2:"+4.1%", col3:"890K", col4:"Product launch",   col5:"9:31 AM", col6:"4:50 AM", pct:4.1, strength:72 },
      { ticker:"SMCI", col2:"+6.7%", col3:"1.2M", col4:"Contract win",     col5:"9:32 AM", col6:"4:51 AM", pct:6.7, strength:89 },
      { ticker:"MSTR", col2:"+3.2%", col3:"760K", col4:"BTC purchase",     col5:"9:31 AM", col6:"4:52 AM", pct:3.2, strength:61 },
    ],
    columns: ["Ticker","Gap %","Premkt Vol","Catalyst","Open Time","Premkt Time"],
  },
  {
    id: 4, name: "Pullback to 20MA", icon: <Activity size={14} />, tier: "free",
    description: "within 1% of 20MA, RSI 40-55, uptrend", trigger: "price within 1% of 20MA, RSI 40–55, above 50MA",
    refreshInterval: "5m", viewType: "cards", hits: 4,
    status: "running", lastRun: "10:25 AM", schedule: "Every 5m", category: "Momentum",
    rows: [
      { ticker:"META",  col2:"Meta Platforms",  col3:"+0.3%", col4:"RSI 47", col5:"$482.10", col6:"10:25 AM", pct:0.3, strength:72 },
      { ticker:"AMZN",  col2:"Amazon.com",       col3:"+0.1%", col4:"RSI 51", col5:"$183.40", col6:"10:23 AM", pct:0.1, strength:65 },
      { ticker:"GOOGL", col2:"Alphabet Inc",     col3:"-0.2%", col4:"RSI 44", col5:"$194.20", col6:"10:21 AM", pct:-0.2, strength:58 },
      { ticker:"MSFT",  col2:"Microsoft Corp",   col3:"+0.4%", col4:"RSI 53", col5:"$458.90", col6:"10:20 AM", pct:0.4, strength:69 },
    ],
    columns: ["Ticker","Company","% From 20MA","RSI","20MA Level","Time"],
  },
  {
    id: 5, name: "Oversold Bounce", icon: <TrendingUp size={14} />, tier: "free",
    description: "RSI<25, 2-day decline, near support", trigger: "RSI<25, 2-day decline, near key support",
    refreshInterval: "5m", viewType: "table", hits: 5,
    status: "running", lastRun: "10:20 AM", schedule: "Every 5m", category: "Momentum",
    rows: [
      { ticker:"INTC", col2:"Intel Corp",     col3:"RSI 18", col4:"-4.2% 2d", col5:"$28.40 sup", col6:"10:20 AM", pct:-4.2, strength:81 },
      { ticker:"PFE",  col2:"Pfizer Inc",     col3:"RSI 21", col4:"-3.1% 2d", col5:"$26.80 sup", col6:"10:18 AM", pct:-3.1, strength:72 },
      { ticker:"BA",   col2:"Boeing Co",      col3:"RSI 23", col4:"-5.8% 2d", col5:"$162.50 sup", col6:"10:15 AM", pct:-5.8, strength:88 },
      { ticker:"VZ",   col2:"Verizon",        col3:"RSI 19", col4:"-2.8% 2d", col5:"$39.20 sup", col6:"10:12 AM", pct:-2.8, strength:76 },
      { ticker:"T",    col2:"AT&T Inc",       col3:"RSI 22", col4:"-1.9% 2d", col5:"$16.40 sup", col6:"10:10 AM", pct:-1.9, strength:67 },
    ],
    columns: ["Ticker","Company","RSI","2d Move","Support Level","Time"],
  },
  {
    id: 6, name: "Momentum Squeeze", icon: <Zap size={14} />, tier: "plus",
    description: "TTM Squeeze fire, ADX>20", trigger: "TTM Squeeze fired, ADX>20, momentum histogram positive",
    refreshInterval: "5m", viewType: "cards", hits: 4,
    status: "live", lastRun: "10:25 AM", schedule: "Every 5m", category: "Momentum",
    rows: [
      { ticker:"TSLA", col2:"Tesla Inc",     col3:"8d squeeze", col4:"ADX 28", col5:"+momentum", col6:"10:25 AM", pct:2.4, strength:78 },
      { ticker:"ROKU", col2:"Roku Inc",      col3:"12d squeeze",col4:"ADX 24", col5:"+momentum", col6:"10:22 AM", pct:1.8, strength:71 },
      { ticker:"SQ",   col2:"Block Inc",     col3:"14d squeeze",col4:"ADX 31", col5:"+momentum", col6:"10:20 AM", pct:3.1, strength:84 },
      { ticker:"PYPL", col2:"PayPal",        col3:"9d squeeze", col4:"ADX 22", col5:"+momentum", col6:"10:18 AM", pct:1.2, strength:62 },
    ],
    columns: ["Ticker","Company","Squeeze Days","ADX","Momentum","Time"],
  },
  // ── EVENTS ──
  {
    id: 7, name: "Earnings Runners", icon: <BarChart2 size={14} />, tier: "plus",
    description: "earnings in 5d, IV rank>50, prior beat", trigger: "earnings within 5 days, IVR>50, prior EPS beat",
    refreshInterval: "1h", viewType: "table", hits: 5,
    status: "scheduled", lastRun: "9:00 AM", schedule: "Hourly", category: "Events",
    rows: [
      { ticker:"NVDA", col2:"May 28 AMC", col3:"IVR 78",  col4:"Beat 3/3", col5:"+4.8% avg", col6:"$820–$960", pct:4.8, strength:86 },
      { ticker:"PANW", col2:"May 27 AMC", col3:"IVR 62",  col4:"Beat 4/4", col5:"+6.2% avg", col6:"$340–$380", pct:6.2, strength:92 },
      { ticker:"CRWD", col2:"May 29 AMC", col3:"IVR 71",  col4:"Beat 4/4", col5:"+8.3% avg", col6:"$360–$400", pct:8.3, strength:94 },
      { ticker:"SNOW", col2:"May 30 AMC", col3:"IVR 55",  col4:"Beat 2/4", col5:"+3.1% avg", col6:"$155–$175", pct:3.1, strength:68 },
      { ticker:"MELI", col2:"May 31 BMO", col3:"IVR 58",  col4:"Beat 3/4", col5:"+5.4% avg", col6:"$1800–$2000", pct:5.4, strength:79 },
    ],
    columns: ["Ticker","Report Date","IV Rank","Prior Beats","Avg Move","Expected Range"],
  },
  {
    id: 8, name: "Post-Earnings Drift", icon: <TrendingUp size={14} />, tier: "plus",
    description: "post-earnings ±3% gap, vol confirm, 2-10d post", trigger: "gap ±3% post-earnings, volume confirmation, days 2–10",
    refreshInterval: "1h", viewType: "table", hits: 4,
    status: "scheduled", lastRun: "9:00 AM", schedule: "Hourly", category: "Events",
    rows: [
      { ticker:"PANW", col2:"+6.1% gap", col3:"Day 3", col4:"Vol 2.1×", col5:"Bullish",  col6:"May 25", pct:6.1, strength:88 },
      { ticker:"CRWD", col2:"+8.3% gap", col3:"Day 5", col4:"Vol 1.8×", col5:"Bullish",  col6:"May 23", pct:8.3, strength:92 },
      { ticker:"ZS",   col2:"+11.2% gap",col3:"Day 2", col4:"Vol 2.4×", col5:"Bullish",  col6:"May 27", pct:11.2,strength:96 },
      { ticker:"FTNT", col2:"+4.9% gap", col3:"Day 7", col4:"Vol 1.6×", col5:"Drifting", col6:"May 21", pct:4.9, strength:74 },
    ],
    columns: ["Ticker","Gap","Days Post","Vol Ratio","Signal","Report Date"],
  },
  // ── SMART MONEY ──
  {
    id: 9, name: "UOA Sweep", icon: <Eye size={14} />, tier: "premium",
    description: "premium>$250k, ask-side, OI<50% vol", trigger: "premium >$250K, ask-side fill, OI <50% of volume",
    refreshInterval: "real-time", viewType: "feed", hits: 8,
    status: "live", lastRun: "Live", schedule: "Real-time", category: "Smart Money",
    feedSeed: [
      { id:1, ticker:"NVDA", strike:"$950C", expiry:"06/21", premium:"$1.24M", side:"BUY",  oi:"12.4K", time:"10:28:42" },
      { id:2, ticker:"SPY",  strike:"$540C", expiry:"06/07", premium:"$890K",  side:"BUY",  oi:"88.2K", time:"10:27:18" },
      { id:3, ticker:"TSLA", strike:"$200P", expiry:"05/31", premium:"$612K",  side:"SELL", oi:"24.1K", time:"10:25:55" },
      { id:4, ticker:"QQQ",  strike:"$455C", expiry:"06/14", premium:"$478K",  side:"BUY",  oi:"41.8K", time:"10:24:33" },
      { id:5, ticker:"META", strike:"$480C", expiry:"07/19", premium:"$342K",  side:"BUY",  oi:"8.9K",  time:"10:22:11" },
      { id:6, ticker:"AAPL", strike:"$210P", expiry:"06/07", premium:"$289K",  side:"SELL", oi:"18.4K", time:"10:19:47" },
      { id:7, ticker:"AMD",  strike:"$165C", expiry:"06/21", premium:"$267K",  side:"BUY",  oi:"6.2K",  time:"10:17:22" },
      { id:8, ticker:"AMZN", strike:"$185C", expiry:"07/19", premium:"$251K",  side:"BUY",  oi:"3.1K",  time:"10:14:58" },
    ],
  },
  {
    id: 10, name: "Dark Pool Heat", icon: <Volume2 size={14} />, tier: "premium",
    description: ">2 prints>$5M same ticker 30min", trigger: ">2 dark pool prints >$5M same ticker within 30 min",
    refreshInterval: "1m", viewType: "heatmap", hits: 6,
    status: "live", lastRun: "10:27 AM", schedule: "Every 1m", category: "Smart Money",
    heatCells: [
      { label: "NVDA", value: 95, sub: "$52M" },
      { label: "AAPL", value: 88, sub: "$88M" },
      { label: "MSFT", value: 81, sub: "$44M" },
      { label: "SPY",  value: 76, sub: "$142M" },
      { label: "QQQ",  value: 68, sub: "$68M" },
      { label: "TSLA", value: 61, sub: "$38M" },
      { label: "META", value: 54, sub: "$22M" },
      { label: "AMD",  value: 47, sub: "$19M" },
      { label: "AMZN", value: 39, sub: "$14M" },
      { label: "GOOGL",value: 32, sub: "$11M" },
      { label: "COIN", value: 24, sub: "$8M" },
      { label: "PLTR", value: 18, sub: "$6M" },
      { label: "SOFI", value: 12, sub: "$5M" },
      { label: "MARA", value: 8,  sub: "$4M" },
      { label: "SMCI", value: 5,  sub: "$3M" },
    ],
    rows: [
      { ticker:"NVDA", col2:"3 prints", col3:"$52M total",  col4:"28 min",  col5:"8.9×",  col6:"10:27 AM", pct:2.3, strength:95 },
      { ticker:"AAPL", col2:"4 prints", col3:"$88M total",  col4:"22 min",  col5:"7.4×",  col6:"10:25 AM", pct:1.2, strength:88 },
      { ticker:"MSFT", col2:"3 prints", col3:"$44M total",  col4:"18 min",  col5:"6.1×",  col6:"10:22 AM", pct:0.8, strength:81 },
      { ticker:"SPY",  col2:"5 prints", col3:"$142M total", col4:"30 min",  col5:"5.8×",  col6:"10:20 AM", pct:0.4, strength:76 },
      { ticker:"QQQ",  col2:"3 prints", col3:"$68M total",  col4:"25 min",  col5:"5.2×",  col6:"10:19 AM", pct:0.6, strength:68 },
      { ticker:"TSLA", col2:"2 prints", col3:"$38M total",  col4:"15 min",  col5:"4.8×",  col6:"10:17 AM", pct:1.8, strength:61 },
    ],
    columns: ["Ticker","Prints","Total Vol","Time Window","vs 30d Avg","Time"],
  },
  {
    id: 11, name: "Short Squeeze Setup", icon: <TrendingUp size={14} />, tier: "plus",
    description: "SI>20%, days-to-cover>5, RSI rising", trigger: "short interest >20%, days-to-cover >5, RSI rising",
    refreshInterval: "EOD", viewType: "cards", hits: 4,
    status: "scheduled", lastRun: "4:05 PM", schedule: "EOD", category: "Smart Money",
    rows: [
      { ticker:"MARA", col2:"SI 28%", col3:"7.2d cover", col4:"RSI 61 ↑", col5:"Float 42M", col6:"Yesterday", pct:6.1, strength:82 },
      { ticker:"COIN", col2:"SI 24%", col3:"6.8d cover", col4:"RSI 58 ↑", col5:"Float 128M", col6:"Yesterday", pct:4.3, strength:74 },
      { ticker:"SOFI", col2:"SI 21%", col3:"5.4d cover", col4:"RSI 54 ↑", col5:"Float 890M", col6:"Yesterday", pct:2.8, strength:66 },
      { ticker:"SMCI", col2:"SI 31%", col3:"8.1d cover", col4:"RSI 63 ↑", col5:"Float 55M",  col6:"Yesterday", pct:7.2, strength:88 },
    ],
    columns: ["Ticker","Short Int","Days-to-Cover","RSI","Float","Date"],
  },
  {
    id: 12, name: "Insider Cluster", icon: <Users size={14} />, tier: "plus",
    description: "≥3 insiders buying 30d, >$500k total", trigger: "≥3 insiders buying in 30d, >$500K total notional",
    refreshInterval: "daily 6am", viewType: "cards", hits: 4,
    status: "scheduled", lastRun: "6:00 AM", schedule: "Daily 6am", category: "Smart Money",
    rows: [
      { ticker:"CVNA", col2:"4 insiders", col3:"$4.2M",  col4:"CEO,CFO,Dir,Dir", col5:"Form 4", col6:"May 28", pct:3.1, strength:84 },
      { ticker:"IONQ", col2:"3 insiders", col3:"$2.8M",  col4:"CEO,COO,Dir",     col5:"Form 4", col6:"May 27", pct:2.4, strength:72 },
      { ticker:"ALAB", col2:"5 insiders", col3:"$6.1M",  col4:"CEO,CFO,CTO,Dir×2",col5:"Form 4",col6:"May 26", pct:4.8, strength:91 },
      { ticker:"HIMS", col2:"3 insiders", col3:"$1.9M",  col4:"CEO,Dir,Dir",     col5:"Form 4", col6:"May 25", pct:1.9, strength:62 },
    ],
    columns: ["Ticker","# Insiders","Total $","Roles","Filing Type","Date"],
  },
  {
    id: 13, name: "Congressional Fresh", icon: <Landmark size={14} />, tier: "plus",
    description: "filings last 48h, liquid names", trigger: "Congressional disclosures last 48h, liquidity >$1M ADV",
    refreshInterval: "daily 6am", viewType: "table", hits: 5,
    status: "scheduled", lastRun: "6:00 AM", schedule: "Daily 6am", category: "Smart Money",
    rows: [
      { ticker:"NVDA", col2:"Rep. Smith (R)", col3:"$15k–$50k", col4:"Purchase", col5:"May 29", col6:"<48h ago", pct:2.1, strength:78 },
      { ticker:"AMZN", col2:"Sen. Jones (D)", col3:"$50k–$100k",col4:"Purchase", col5:"May 29", col6:"<48h ago", pct:1.4, strength:64 },
      { ticker:"MSFT", col2:"Rep. Brown (R)", col3:"$1k–$15k",  col4:"Sale",     col5:"May 28", col6:"<48h ago", pct:0.9, strength:42 },
      { ticker:"AAPL", col2:"Sen. White (D)", col3:"$15k–$50k", col4:"Purchase", col5:"May 28", col6:"<48h ago", pct:1.2, strength:58 },
      { ticker:"META", col2:"Rep. Davis (R)", col3:"$50k–$100k",col4:"Purchase", col5:"May 27", col6:"<48h ago", pct:1.8, strength:71 },
    ],
    columns: ["Ticker","Member","Amount","Type","Disclosed","Age"],
  },
  // ── CATALYST ──
  {
    id: 14, name: "Analyst Upgrades", icon: <Building2 size={14} />, tier: "plus",
    description: "Tier-1 upgrade pre-mkt", trigger: "Tier-1 analyst upgrade issued pre-market",
    refreshInterval: "real-time", viewType: "cards", hits: 4,
    status: "live", lastRun: "7:42 AM", schedule: "Real-time", category: "Catalyst",
    rows: [
      { ticker:"NVDA", col2:"Goldman Sachs", col3:"Buy→Strong Buy", col4:"$1,100 PT", col5:"Pre-mkt", col6:"7:42 AM", pct:3.4, strength:86 },
      { ticker:"META", col2:"JPMorgan",      col3:"OW→OW+",        col4:"$610 PT",   col5:"Pre-mkt", col6:"7:38 AM", pct:2.1, strength:74 },
      { ticker:"TSLA", col2:"Morgan Stanley",col3:"EW→OW",         col4:"$290 PT",   col5:"Pre-mkt", col6:"7:21 AM", pct:4.8, strength:91 },
      { ticker:"AMZN", col2:"BofA",          col3:"Buy Reiterate", col4:"$230 PT",   col5:"Pre-mkt", col6:"7:08 AM", pct:1.6, strength:67 },
    ],
    columns: ["Ticker","Analyst","Rating Change","Price Target","Session","Time"],
  },
  {
    id: 15, name: "Sector Rotation", icon: <Repeat2 size={14} />, tier: "free",
    description: "today's leading/lagging vs 20d", trigger: "sector outperforming/underperforming vs 20-day avg",
    refreshInterval: "EOD", viewType: "heatmap", hits: 11,
    status: "scheduled", lastRun: "4:02 PM", schedule: "EOD", category: "Catalyst",
    heatCells: [
      { label: "Semis",       value: 4.2, sub: "+4.2%" },
      { label: "Software",    value: 3.1, sub: "+3.1%" },
      { label: "Internet",    value: 2.8, sub: "+2.8%" },
      { label: "AI/Cloud",    value: 2.4, sub: "+2.4%" },
      { label: "Biotech",     value: 1.8, sub: "+1.8%" },
      { label: "Utilities",   value: 0.9, sub: "+0.9%" },
      { label: "Industrials", value: 0.2, sub: "+0.2%" },
      { label: "Consumer",    value: -0.4, sub: "-0.4%" },
      { label: "Financials",  value: -0.8, sub: "-0.8%" },
      { label: "Healthcare",  value: -1.2, sub: "-1.2%" },
      { label: "Energy",      value: -1.8, sub: "-1.8%" },
      { label: "Materials",   value: -2.1, sub: "-2.1%" },
      { label: "Real Estate", value: -2.6, sub: "-2.6%" },
      { label: "Telecom",     value: -3.2, sub: "-3.2%" },
      { label: "Staples",     value: -3.8, sub: "-3.8%" },
    ],
    rows: [],
    columns: [],
  },
  {
    id: 16, name: "Dividend Aristocrats", icon: <DollarSign size={14} />, tier: "free",
    description: "top yield + P/E<15 + payout<70%", trigger: "yield >3%, P/E<15, payout ratio<70%, 20+ yr div growth",
    refreshInterval: "EOD", viewType: "table", hits: 5,
    status: "scheduled", lastRun: "4:03 PM", schedule: "EOD", category: "Catalyst",
    rows: [
      { ticker:"T",   col2:"AT&T Inc",       col3:"7.1%", col4:"P/E 7.2",  col5:"Payout 51%", col6:"26 yrs", pct:0.4, strength:78 },
      { ticker:"VZ",  col2:"Verizon Comm",   col3:"6.4%", col4:"P/E 8.1",  col5:"Payout 55%", col6:"18 yrs", pct:0.2, strength:71 },
      { ticker:"MO",  col2:"Altria Group",   col3:"9.2%", col4:"P/E 9.4",  col5:"Payout 79%", col6:"53 yrs", pct:0.8, strength:84 },
      { ticker:"XOM", col2:"Exxon Mobil",    col3:"3.4%", col4:"P/E 12.8", col5:"Payout 38%", col6:"41 yrs", pct:1.1, strength:65 },
      { ticker:"JNJ", col2:"Johnson & Johnson",col3:"3.1%",col4:"P/E 14.2",col5:"Payout 44%", col6:"62 yrs", pct:0.6, strength:62 },
    ],
    columns: ["Ticker","Company","Yield","P/E","Payout Ratio","Div Growth"],
  },
  // ── CRYPTO ──
  {
    id: 17, name: "Crypto Funding Extreme", icon: <Bitcoin size={14} />, tier: "plus",
    description: "|funding|>0.05%/8h", trigger: "absolute funding rate >0.05% per 8h interval",
    refreshInterval: "5m", viewType: "table", hits: 5,
    status: "live", lastRun: "10:25 AM", schedule: "Every 5m", category: "Crypto",
    rows: [
      { ticker:"BTC",  col2:"Bitcoin",  col3:"+0.081%/8h", col4:"Long bias",  col5:"OI $28.4B", col6:"10:25 AM", pct:2.8, strength:81 },
      { ticker:"ETH",  col2:"Ethereum", col3:"+0.067%/8h", col4:"Long bias",  col5:"OI $12.1B", col6:"10:24 AM", pct:1.9, strength:67 },
      { ticker:"SOL",  col2:"Solana",   col3:"+0.094%/8h", col4:"Long bias",  col5:"OI $4.8B",  col6:"10:22 AM", pct:4.2, strength:94 },
      { ticker:"LINK", col2:"Chainlink",col3:"-0.058%/8h", col4:"Short bias", col5:"OI $840M",  col6:"10:20 AM", pct:-2.1, strength:58 },
      { ticker:"ARB",  col2:"Arbitrum", col3:"+0.072%/8h", col4:"Long bias",  col5:"OI $620M",  col6:"10:18 AM", pct:3.1, strength:72 },
    ],
    columns: ["Ticker","Asset","Funding Rate","Bias","Open Interest","Time"],
  },
  {
    id: 18, name: "Crypto Liq Bait", icon: <Droplets size={14} />, tier: "premium",
    description: "liq cluster within 3%, OI rising", trigger: "liquidation cluster within 3% of price, OI rising 10%+",
    refreshInterval: "5m", viewType: "heatmap", hits: 4,
    status: "live", lastRun: "10:25 AM", schedule: "Every 5m", category: "Crypto",
    heatCells: [
      { label: "BTC Long $62K",  value: 88, sub: "$420M liq" },
      { label: "BTC Short $68K", value: 74, sub: "$380M liq" },
      { label: "ETH Long $3.1K", value: 82, sub: "$190M liq" },
      { label: "ETH Short $3.5K",value: 67, sub: "$165M liq" },
      { label: "SOL Long $128",  value: 91, sub: "$82M liq" },
      { label: "SOL Short $148", value: 58, sub: "$61M liq" },
      { label: "LINK Long $14",  value: 45, sub: "$28M liq" },
      { label: "ARB Long $0.88", value: 52, sub: "$18M liq" },
      { label: "BTC $65K ±1%",   value: 96, sub: "$640M zone" },
    ],
    rows: [],
    columns: [],
  },
  {
    id: 19, name: "Whale Wallet Move", icon: <Wallet size={14} />, tier: "premium",
    description: "tracked wallet tx>$1M", trigger: "tracked smart-money wallet transaction >$1M",
    refreshInterval: "real-time", viewType: "feed", hits: 6,
    status: "live", lastRun: "Live", schedule: "Real-time", category: "Crypto",
    feedSeed: [
      { id:1, ticker:"BTC",  wallet:"0x71C...4aF2", type:"Transfer", amount:"$4.2M", time:"10:28:14" },
      { id:2, ticker:"ETH",  wallet:"0x3bE...9dC1", type:"Swap",     amount:"$2.8M", time:"10:26:47" },
      { id:3, ticker:"SOL",  wallet:"FhMk...Rq9J",  type:"Stake",    amount:"$1.9M", time:"10:24:22" },
      { id:4, ticker:"BTC",  wallet:"0x9aD...2fB8", type:"Exchange", amount:"$8.1M", time:"10:21:55" },
      { id:5, ticker:"ETH",  wallet:"0x52F...7gH3", type:"DeFi",     amount:"$3.4M", time:"10:19:31" },
      { id:6, ticker:"ARB",  wallet:"0x84K...1mN7", type:"Bridge",   amount:"$1.2M", time:"10:17:08" },
    ],
  },
  {
    id: 20, name: "Stablecoin Depeg", icon: <ShieldAlert size={14} />, tier: "premium",
    description: "stable <$0.995 or >$1.005 for >5m", trigger: "stablecoin deviates >0.5% from $1.00 peg for 5+ minutes",
    refreshInterval: "30s", viewType: "table", hits: 1,
    status: "live", lastRun: "10:28 AM", schedule: "Every 30s", category: "Crypto",
    rows: [
      { ticker:"USDT", col2:"Tether",      col3:"$0.9981", col4:"-0.19%", col5:"8 min",   col6:"ALERT", pct:-0.19, strength:91 },
      { ticker:"USDC", col2:"USD Coin",    col3:"$1.0002", col4:"+0.02%", col5:"Normal",  col6:"OK",    pct:0.02,  strength:8 },
      { ticker:"DAI",  col2:"Dai",         col3:"$0.9998", col4:"-0.02%", col5:"Normal",  col6:"OK",    pct:-0.02, strength:6 },
      { ticker:"FRAX", col2:"Frax",        col3:"$1.0001", col4:"+0.01%", col5:"Normal",  col6:"OK",    pct:0.01,  strength:4 },
    ],
    columns: ["Ticker","Asset","Price","Peg Delta","Duration","Status"],
  },
  // ── OPTIONS ──
  {
    id: 21, name: "Options Pin Risk", icon: <Pin size={14} />, tier: "plus",
    description: "Friday >11am, within 1% of high-OI strike", trigger: "Fridays after 11am, price within 1% of max-pain strike",
    refreshInterval: "5m", viewType: "cards", hits: 3,
    status: "running", lastRun: "10:20 AM", schedule: "Fridays 11am+", category: "Options",
    rows: [
      { ticker:"SPY",  col2:"$540 strike", col3:"OI 2.8M", col4:"0.4% away", col5:"Expiry today", col6:"10:20 AM", pct:0.4, strength:84 },
      { ticker:"QQQ",  col2:"$455 strike", col3:"OI 1.2M", col4:"0.7% away", col5:"Expiry today", col6:"10:18 AM", pct:0.7, strength:72 },
      { ticker:"AAPL", col2:"$210 strike", col3:"OI 480K", col4:"0.9% away", col5:"Expiry today", col6:"10:15 AM", pct:0.9, strength:68 },
    ],
    columns: ["Ticker","Max-Pain Strike","Open Interest","Distance","Expiry","Time"],
  },
  // ── AI ──
  {
    id: 22, name: "AI Hot Today", icon: <Sparkles size={14} />, tier: "plus",
    description: "personalized setups", trigger: "AI-personalized setups based on trading history",
    refreshInterval: "8am+12pm", viewType: "cards", hits: 4,
    status: "scheduled", lastRun: "12:00 PM", schedule: "8am & 12pm", category: "AI",
    rows: [
      { ticker:"NVDA", col2:"Momo-Breakout", col3:"BMG Score 87", col4:"3 similar wins", col5:"High conviction", col6:"12:00 PM", pct:5.8, strength:87 },
      { ticker:"TSLA", col2:"Pullback-Buy",  col3:"BMG Score 74", col4:"2 similar wins", col5:"Med conviction",  col6:"12:00 PM", pct:3.2, strength:74 },
      { ticker:"AMD",  col2:"Vol-Squeeze",   col3:"BMG Score 81", col4:"4 similar wins", col5:"High conviction", col6:"12:00 PM", pct:4.1, strength:81 },
      { ticker:"META", col2:"Gap-Fill",      col3:"BMG Score 69", col4:"2 similar wins", col5:"Med conviction",  col6:"12:00 PM", pct:2.4, strength:69 },
    ],
    columns: ["Ticker","Strategy Match","BMG Score","Similar Trades","Conviction","Generated"],
  },
];

// ── Category groups ────────────────────────────────────────────────────────────

const CATEGORIES: { name: ScannerCategory; ids: number[] }[] = [
  { name: "Momentum",    ids: [1,2,3,4,5,6] },
  { name: "Events",      ids: [7,8] },
  { name: "Smart Money", ids: [9,10,11,12,13] },
  { name: "Catalyst",    ids: [14,15,16] },
  { name: "Crypto",      ids: [17,18,19,20] },
  { name: "Options",     ids: [21] },
  { name: "AI",          ids: [22] },
];

// ── AI Explain data ────────────────────────────────────────────────────────────

const EXPLAIN_DATA: Record<number, { plain: string; fires: number; avgReturn: string; winRate: string }> = {
  1:  { plain: "Finds stocks moving more than 5% in either direction on at least 1M shares of volume — the most active movers in the market right now.", fires: 248, avgReturn: "+4.2%", winRate: "61%" },
  2:  { plain: "Identifies stocks hitting a fresh 52-week high with above-average volume, signaling institutional accumulation and momentum continuation.", fires: 112, avgReturn: "+6.8%", winRate: "68%" },
  3:  { plain: "Catches stocks gapping up more than 2% at the open with strong premarket volume, the classic 'gap and go' setup favored by day traders.", fires: 189, avgReturn: "+3.1%", winRate: "59%" },
  4:  { plain: "Finds trending stocks that have pulled back to their 20-day moving average with RSI in the neutral zone — prime entries in uptrends.", fires: 143, avgReturn: "+5.4%", winRate: "64%" },
  5:  { plain: "Spots stocks with RSI under 25 after a 2-day decline near a known support level — high-probability mean-reversion setups.", fires: 167, avgReturn: "+4.8%", winRate: "66%" },
  6:  { plain: "Detects the TTM Squeeze firing (Bollinger Bands inside Keltner Channels) with ADX above 20, indicating explosive directional moves are coming.", fires: 98, avgReturn: "+7.2%", winRate: "71%" },
  7:  { plain: "Finds stocks reporting earnings within 5 days with elevated implied volatility rank and a track record of beating estimates — pre-earnings runners.", fires: 201, avgReturn: "+3.9%", winRate: "58%" },
  8:  { plain: "Tracks stocks that gapped big on earnings and are continuing to drift in the same direction with volume confirmation — the PEAD effect.", fires: 134, avgReturn: "+8.1%", winRate: "67%" },
  9:  { plain: "Streams unusual options activity where a single trader spent over $250K on ask-side contracts with open interest well below volume — fresh, directional bets.", fires: 892, avgReturn: "+5.6%", winRate: "63%" },
  10: { plain: "Detects tickers with multiple large dark pool prints (>$5M each) within 30 minutes — a signal that institutions are quietly building or exiting positions.", fires: 441, avgReturn: "+4.1%", winRate: "59%" },
  11: { plain: "Identifies heavily shorted stocks where short interest exceeds 20% of float, days-to-cover is high, and momentum is turning up — squeeze fuel.", fires: 76, avgReturn: "+12.4%", winRate: "54%" },
  12: { plain: "Finds companies where three or more insiders all bought shares in the same 30-day window with a combined value over $500K — a strong alignment signal.", fires: 88, avgReturn: "+9.3%", winRate: "72%" },
  13: { plain: "Surfaces Congressional stock disclosures filed in the last 48 hours for liquid names — tracking what lawmakers are buying and selling.", fires: 312, avgReturn: "+4.7%", winRate: "61%" },
  14: { plain: "Catches Tier-1 analyst upgrades issued before the market opens — when Goldman, JPMorgan, or Morgan Stanley upgrades, it moves stocks.", fires: 224, avgReturn: "+3.8%", winRate: "69%" },
  15: { plain: "Shows which sectors are leading and lagging vs. their 20-day trend today — ideal for rotating into strength and out of weakness.", fires: 251, avgReturn: "+3.2%", winRate: "62%" },
  16: { plain: "Screens for dividend aristocrats with yields above 3%, P/E under 15, and sustainable payout ratios — income plays with value characteristics.", fires: 94, avgReturn: "+2.8%", winRate: "74%" },
  17: { plain: "Flags crypto perpetual futures where the 8-hour funding rate exceeds 0.05% in either direction — a sign of crowded longs or shorts about to unwind.", fires: 178, avgReturn: "+5.9%", winRate: "58%" },
  18: { plain: "Identifies liquidation clusters (large concentrations of leveraged positions) within 3% of current price with rising open interest — where the market hunts stops.", fires: 203, avgReturn: "+6.4%", winRate: "62%" },
  19: { plain: "Tracks real-time on-chain transactions over $1M from wallets flagged as smart money — whale wallet movements often precede price action.", fires: 541, avgReturn: "+7.1%", winRate: "55%" },
  20: { plain: "Monitors stablecoins continuously for any deviation beyond 0.5% from their $1.00 peg lasting more than 5 minutes — early warning for depegging events.", fires: 29, avgReturn: "N/A", winRate: "N/A" },
  21: { plain: "On Fridays after 11am, flags stocks trading within 1% of the highest open-interest options strike — the pin risk zone where market makers hedge.", fires: 156, avgReturn: "+1.9%", winRate: "71%" },
  22: { plain: "Combines your personal trading history, win/loss patterns, and favorite setups with real-time market conditions to surface the setups most likely to match your style.", fires: 481, avgReturn: "+6.2%", winRate: "68%" },
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: ScannerStatus }) {
  return (
    <span className={cn(
      "inline-block w-2 h-2 rounded-full flex-shrink-0",
      status === "live" && "bg-lime-400 shadow-[0_0_5px_var(--accent-positive)]",
      status === "running" && "bg-amber-400 animate-pulse",
      status === "scheduled" && "bg-white/25",
    )} />
  );
}

function TierBadge({ tier }: { tier: ScannerTier }) {
  if (tier === "free") return null;
  return (
    <span className={cn(
      "px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide flex-shrink-0",
      tier === "plus" && "bg-blue-500/20 text-blue-300",
      tier === "premium" && "bg-purple-500/20 text-purple-300",
    )}>
      {tier}
    </span>
  );
}

function SignalBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  const positive = value >= 0;
  return (
    <div className="w-full h-1.5 rounded-full bg-white/10 overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all", positive ? "bg-lime-400" : "bg-red-400")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function SortIcon({ col, sort }: { col: string; sort: SortState }) {
  if (sort.col !== col) return <ChevronUp size={11} className="opacity-20" />;
  return sort.dir === "asc"
    ? <ChevronUp size={11} className="text-blue-400" />
    : <ChevronDown size={11} className="text-blue-400" />;
}

// Tiny SVG equity curve for explain modal
function EquityCurve() {
  const pts = [0,2,1,4,3,5,4,7,6,8,7,9,8,10,9,12,10,11,11,13,12,15];
  const xs = pts.filter((_,i) => i%2===0);
  const ys = pts.filter((_,i) => i%2!==0);
  const maxY = Math.max(...ys);
  const minY = Math.min(...ys);
  const W = 200; const H = 48;
  const points = xs.map((x,i) => {
    const px = (x / (xs.length-1)) * W;
    const py = H - ((ys[i]-minY) / (maxY-minY)) * H;
    return `${px},${py}`;
  }).join(" ");
  return (
    <svg width={W} height={H} className="w-full">
      <polyline points={points} fill="none" stroke="var(--accent-positive)" strokeWidth="1.5" />
    </svg>
  );
}

// ── Explain Modal ──────────────────────────────────────────────────────────────

function ExplainModal({ scanner, onClose }: { scanner: ScannerDef; onClose: () => void }) {
  const data = EXPLAIN_DATA[scanner.id];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }}>
      <div className="w-full max-w-md rounded-2xl border p-6 relative"
        style={{ background: "var(--bg-elevated)", borderColor: "var(--border-emphasis)" }}>
        <button onClick={onClose} className="absolute top-4 right-4 p-1 rounded hover:bg-white/10 transition-colors"
          style={{ color: "var(--text-tertiary)" }}>
          <X size={16} />
        </button>
        <div className="flex items-center gap-2 mb-4">
          <Brain size={18} className="text-blue-400" />
          <span className="font-semibold" style={{ color: "var(--text-primary)" }}>AI Explains: {scanner.name}</span>
        </div>
        <p className="text-sm mb-4 leading-relaxed" style={{ color: "var(--text-secondary)" }}>{data.plain}</p>
        <div className="rounded-lg p-3 mb-4" style={{ background: "var(--bg-elevated-2)", border: "1px solid var(--border-subtle)" }}>
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-secondary)" }}>Last 12 months performance</p>
          <div className="flex gap-4 text-xs mb-3">
            <div><span style={{ color: "var(--text-tertiary)" }}>Fired </span><span className="font-semibold" style={{ color: "var(--text-primary)" }}>{data.fires}×</span></div>
            <div><span style={{ color: "var(--text-tertiary)" }}>Avg 5d return </span><span className="font-semibold" style={{ color: "var(--accent-positive)" }}>{data.avgReturn}</span></div>
            <div><span style={{ color: "var(--text-tertiary)" }}>Win rate </span><span className="font-semibold" style={{ color: "var(--text-primary)" }}>{data.winRate}</span></div>
          </div>
          <EquityCurve />
        </div>
        <button className="w-full py-2 rounded-lg text-sm font-semibold transition-opacity hover:opacity-90"
          style={{ background: "rgba(59,130,246,0.25)", color: "var(--text-primary)", border: "1px solid rgba(59,130,246,0.4)" }}>
          Subscribe to alerts from this scanner
        </button>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function ScannersPage() {
  const navigate = useNavigate();
  const [activeId, setActiveId] = useState(1);
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [explainOpen, setExplainOpen] = useState(false);
  const [sort, setSort] = useState<SortState>({ col: "pct", dir: "desc" });
  const [feedEntries, setFeedEntries] = useState<FeedEntry[]>([]);
  const feedIdRef = useRef(100);

  const active = SCANNERS.find(s => s.id === activeId)!;

  // When scanner changes, set default view and seed feed
  useEffect(() => {
    setViewMode(active.viewType === "feed" ? "feed"
      : active.viewType === "heatmap" ? "heatmap"
      : active.viewType === "cards" ? "cards"
      : "table");
    if (active.feedSeed) setFeedEntries(active.feedSeed.map(e => ({ ...e, isNew: false })));
    else setFeedEntries([]);
  }, [activeId]);

  // Live feed interval for UOA (9) and Whale (19)
  useEffect(() => {
    if (active.id !== 9 && active.id !== 19) return;
    const uoaPool: Omit<FeedEntry,"id"|"isNew">[] = [
      { ticker:"NVDA", strike:"$960C", expiry:"06/21", premium:"$1.1M",  side:"BUY",  oi:"9.2K",  time:"" },
      { ticker:"TSLA", strike:"$195C", expiry:"06/07", premium:"$540K",  side:"BUY",  oi:"14.4K", time:"" },
      { ticker:"AMZN", strike:"$190P", expiry:"05/31", premium:"$310K",  side:"SELL", oi:"7.8K",  time:"" },
      { ticker:"SOFI", strike:"$10C",  expiry:"06/21", premium:"$262K",  side:"BUY",  oi:"22.1K", time:"" },
    ];
    const whalePool: Omit<FeedEntry,"id"|"isNew">[] = [
      { ticker:"BTC",  wallet:"0x22A...8bC4", type:"Transfer", amount:"$6.8M", time:"" },
      { ticker:"ETH",  wallet:"0x7fD...3aE9", type:"Swap",     amount:"$3.1M", time:"" },
      { ticker:"SOL",  wallet:"Bm9K...Tk4R",  type:"Stake",    amount:"$2.2M", time:"" },
    ];
    const pool = active.id === 9 ? uoaPool : whalePool;
    const interval = setInterval(() => {
      const now = new Date();
      const t = `${now.getHours().toString().padStart(2,"0")}:${now.getMinutes().toString().padStart(2,"0")}:${now.getSeconds().toString().padStart(2,"0")}`;
      const base = pool[Math.floor(Math.random() * pool.length)];
      const newEntry: FeedEntry = { ...base, id: ++feedIdRef.current, time: t, isNew: true };
      setFeedEntries(prev => {
        const updated = [newEntry, ...prev.slice(0, 29)];
        // Clear isNew flag after 3s
        setTimeout(() => {
          setFeedEntries(p => p.map(e => e.id === newEntry.id ? { ...e, isNew: false } : e));
        }, 3000);
        return updated;
      });
    }, 8000);
    return () => clearInterval(interval);
  }, [activeId]);

  function toggleSort(col: string) {
    setSort(prev => prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "desc" });
  }

  const sortedRows = [...(active.rows ?? [])].sort((a, b) => {
    if (sort.col === "ticker") return sort.dir === "asc" ? a.ticker.localeCompare(b.ticker) : b.ticker.localeCompare(a.ticker);
    if (sort.col === "pct") return sort.dir === "asc" ? a.pct - b.pct : b.pct - a.pct;
    if (sort.col === "strength") return sort.dir === "asc" ? a.strength - b.strength : b.strength - a.strength;
    if (sort.col === "col3") return sort.dir === "asc" ? a.col3.localeCompare(b.col3) : b.col3.localeCompare(a.col3);
    return 0;
  });

  // Determine which view toggles are available
  const hasHeatmap = !!active.heatCells?.length;
  const hasFeed = active.viewType === "feed";
  const hasCards = !hasFeed;
  const hasTable = !hasFeed && active.id !== 15 && active.id !== 18;

  // Stablecoin depeg alert
  const isDepegScanner = active.id === 20;
  const depegAlert = isDepegScanner
    ? active.rows?.find(r => Math.abs(r.pct) > 0.1)
    : null;

  // AI scanner
  const isAI = active.id === 22;

  return (
    <div className="flex flex-col h-full min-h-screen" style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}>

      {/* ── Header ── */}
      <div className="px-6 pt-5 pb-4 border-b flex-shrink-0" style={{ borderColor: "var(--border-subtle)" }}>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: "var(--bg-elevated-2)" }}>
              <Radar size={18} className="text-blue-400" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Market Scanners</h1>
              <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>
                22 scanners · real-time + EOD · AI-powered
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
              <Clock size={12} /><span>Last scan: <span style={{ color: "var(--text-secondary)" }}>10:29 AM</span></span>
            </div>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
              style={{ background: "rgba(163,230,53,0.12)", color: "var(--accent-positive)", border: "1px solid rgba(163,230,53,0.25)" }}>
              <span className="w-1.5 h-1.5 rounded-full bg-lime-400 animate-pulse" />Live
            </span>
            <button
              onClick={() => navigate("/alerts/builder")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-opacity hover:opacity-90"
              style={{ background: "rgba(59,130,246,0.25)", color: "var(--text-primary)", border: "1px solid rgba(59,130,246,0.4)" }}>
              <Plus size={13} />Create Scanner
            </button>
            {/* Refresh button removed — scanners render from hardcoded SCANNERS
                + EXPLAIN_DATA, nothing to refetch yet. Re-add when wired. */}
          </div>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Sidebar ── */}
        <aside className="w-64 flex-shrink-0 overflow-y-auto border-r flex flex-col"
          style={{ borderColor: "var(--border-subtle)", background: "var(--bg-base)" }}>
          <div className="flex-1 py-1">
            {CATEGORIES.map(cat => (
              <div key={cat.name}>
                <div className="px-4 pt-3 pb-1">
                  <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: "var(--text-tertiary)" }}>
                    {cat.name}
                  </span>
                </div>
                {SCANNERS.filter(s => cat.ids.includes(s.id)).map(s => (
                  <button
                    key={s.id}
                    onClick={() => setActiveId(s.id)}
                    className={cn(
                      "w-full text-left px-3 py-2.5 flex items-start gap-2.5 transition-colors border-l-2 group",
                      activeId === s.id ? "border-blue-500" : "border-transparent hover:border-white/10",
                    )}
                    style={{ background: activeId === s.id ? "var(--bg-elevated)" : "transparent" }}
                  >
                    <div className={cn("mt-0.5 flex-shrink-0 opacity-50 group-hover:opacity-70 transition-opacity",
                      activeId === s.id && "!opacity-100 text-blue-400")}>
                      {s.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={cn("text-xs font-medium truncate flex-1",
                          activeId === s.id ? "text-blue-300" : "")}
                          style={{ color: activeId === s.id ? undefined : "var(--text-primary)" }}>
                          {s.name}
                        </span>
                        <TierBadge tier={s.tier} />
                        <span className={cn(
                          "flex-shrink-0 px-1.5 py-0.5 rounded-full text-[10px] font-semibold",
                          s.hits > 0 ? "bg-lime-400/15 text-lime-400" : "bg-white/8 text-white/25",
                        )}>
                          {s.hits}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <StatusDot status={s.status} />
                        <span className="text-[10px] truncate" style={{ color: "var(--text-tertiary)" }}>
                          {s.lastRun} · {s.schedule}
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ))}
          </div>
          {/* Build Custom button */}
          <div className="p-3 border-t flex-shrink-0" style={{ borderColor: "var(--border-subtle)" }}>
            <button
              onClick={() => navigate("/alerts/builder")}
              className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-semibold transition-opacity hover:opacity-90"
              style={{ background: "var(--bg-elevated-2)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}>
              <Plus size={13} />Build Custom Scanner
            </button>
          </div>
        </aside>

        {/* ── Results Panel ── */}
        <main className="flex-1 overflow-y-auto flex flex-col min-w-0">

          {/* Toolbar */}
          <div className="flex items-center justify-between gap-3 px-5 py-3 border-b flex-wrap flex-shrink-0"
            style={{ borderColor: "var(--border-subtle)", background: "var(--bg-elevated)" }}>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{active.name}</span>
                <StatusDot status={active.status} />
                <span className="text-xs px-2 py-0.5 rounded"
                  style={{ background: "var(--bg-elevated-2)", color: "var(--text-tertiary)" }}>
                  {active.schedule}
                </span>
                <TierBadge tier={active.tier} />
              </div>
              <p className="text-xs mt-0.5 truncate" style={{ color: "var(--text-tertiary)" }}>{active.description}</p>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Explain button */}
              <button
                onClick={() => setExplainOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{ background: "var(--bg-elevated-2)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}>
                <Brain size={13} />Explain
              </button>
              {/* View toggles */}
              <div className="flex items-center rounded-lg overflow-hidden border"
                style={{ borderColor: "var(--border-subtle)", background: "var(--bg-elevated-2)" }}>
                {hasTable && (
                  <button onClick={() => setViewMode("table")}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium transition-colors"
                    style={{ background: viewMode === "table" ? "var(--bg-elevated)" : "transparent",
                      color: viewMode === "table" ? "var(--text-primary)" : "var(--text-tertiary)" }}>
                    <List size={12} />Table
                  </button>
                )}
                {hasCards && (
                  <button onClick={() => setViewMode("cards")}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium transition-colors"
                    style={{ background: viewMode === "cards" ? "var(--bg-elevated)" : "transparent",
                      color: viewMode === "cards" ? "var(--text-primary)" : "var(--text-tertiary)" }}>
                    <LayoutGrid size={12} />Cards
                  </button>
                )}
                {hasHeatmap && (
                  <button onClick={() => setViewMode("heatmap")}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium transition-colors"
                    style={{ background: viewMode === "heatmap" ? "var(--bg-elevated)" : "transparent",
                      color: viewMode === "heatmap" ? "var(--text-primary)" : "var(--text-tertiary)" }}>
                    <Thermometer size={12} />Heatmap
                  </button>
                )}
                {hasFeed && (
                  <button onClick={() => setViewMode("feed")}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium transition-colors"
                    style={{ background: viewMode === "feed" ? "var(--bg-elevated)" : "transparent",
                      color: viewMode === "feed" ? "var(--text-primary)" : "var(--text-tertiary)" }}>
                    <Activity size={12} />Feed
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Stablecoin Depeg Banner */}
          {isDepegScanner && depegAlert && (
            <div className="px-5 py-3 flex items-center gap-2 flex-shrink-0"
              style={{ background: "rgba(251,113,133,0.1)", borderBottom: "1px solid rgba(251,113,133,0.3)" }}>
              <AlertTriangle size={15} style={{ color: "var(--accent-negative)" }} />
              <span className="text-sm font-semibold" style={{ color: "var(--accent-negative)" }}>
                USDT trading at $0.9981 — -0.19% from peg for 8 minutes
              </span>
            </div>
          )}

          {/* AI Hot Today Header */}
          {isAI && (
            <div className="px-5 py-3 flex items-center gap-2 flex-shrink-0"
              style={{ background: "rgba(59,130,246,0.07)", borderBottom: "1px solid rgba(59,130,246,0.2)" }}>
              <Brain size={15} className="text-blue-400" />
              <span className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                Personalized for you based on your trading history
              </span>
              <span className="ml-auto text-xs px-2 py-0.5 rounded"
                style={{ background: "rgba(59,130,246,0.2)", color: "var(--text-secondary)" }}>
                8am &amp; 12pm
              </span>
            </div>
          )}

          {/* ── Table View ── */}
          {viewMode === "table" && sortedRows.length > 0 && (
            <div className="overflow-x-auto flex-1">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr style={{ background: "var(--bg-elevated)", borderBottom: "1px solid var(--border-subtle)" }}>
                    {(active.columns ?? []).map((col, i) => {
                      const key = i === 0 ? "ticker" : i === 4 ? "strength" : i === 3 ? "pct" : `col${i+2}`;
                      return (
                        <th key={col}
                          onClick={() => toggleSort(key)}
                          className="px-4 py-2.5 text-left text-xs font-medium cursor-pointer select-none whitespace-nowrap"
                          style={{ color: "var(--text-secondary)" }}>
                          <div className="flex items-center gap-1">
                            {col}<SortIcon col={key} sort={sort} />
                          </div>
                        </th>
                      );
                    })}
                    <th className="px-4 py-2.5 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((row, i) => (
                    <tr key={row.ticker + i}
                      className="border-b transition-colors hover:bg-white/3"
                      style={{ borderColor: "var(--border-subtle)" }}>
                      <td className="px-4 py-3 font-bold text-blue-300 text-xs">{row.ticker}</td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-secondary)" }}>{row.col2}</td>
                      <td className="px-4 py-3 text-xs font-medium"
                        style={{ color: row.col3.startsWith("+") ? "var(--accent-positive)" : row.col3.startsWith("-") ? "var(--accent-negative)" : "var(--text-primary)" }}>
                        {row.col3}
                      </td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-secondary)" }}>{row.col4}</td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-secondary)" }}>{row.col5}</td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-tertiary)" }}>{row.col6}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => navigate(`/chart?symbol=${row.ticker}`)}
                          className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors hover:bg-white/10"
                          style={{ color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}>
                          <ExternalLink size={10} />Chart
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Cards View ── */}
          {viewMode === "cards" && sortedRows.length > 0 && (
            <div className="p-5 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {sortedRows.map((row, i) => (
                <div key={row.ticker + i}
                  className="rounded-xl p-4 border transition-all hover:border-white/20"
                  style={{ background: "var(--bg-elevated)", borderColor: "var(--border-subtle)" }}>
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-blue-300">{row.ticker}</span>
                        <span className="text-sm font-semibold"
                          style={{ color: row.pct >= 0 ? "var(--accent-positive)" : "var(--accent-negative)" }}>
                          {row.pct >= 0 ? "+" : ""}{row.pct.toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>{row.col2}</p>
                    </div>
                    <button onClick={() => navigate(`/chart?symbol=${row.ticker}`)}
                      className="text-blue-400 hover:text-blue-300 transition-colors" title="View Chart">
                      <ExternalLink size={14} />
                    </button>
                  </div>
                  <div className="mb-3">
                    <div className="flex justify-between text-xs mb-1" style={{ color: "var(--text-tertiary)" }}>
                      <span>Signal strength</span>
                      <span style={{ color: "var(--text-secondary)" }}>{row.strength}/100</span>
                    </div>
                    <SignalBar value={row.strength} max={100} />
                  </div>
                  {/* AI "Why this?" tooltip */}
                  {isAI && (
                    <div className="text-xs rounded-lg p-2 mb-2"
                      style={{ background: "rgba(59,130,246,0.08)", color: "var(--text-secondary)", border: "1px solid rgba(59,130,246,0.2)" }}>
                      <span className="font-medium text-blue-300">Why this?</span>{" "}
                      {row.col3} · {row.col4} · {row.col5}
                    </div>
                  )}
                  <div className="flex items-center justify-between mt-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-medium"
                      style={{ background: "var(--bg-elevated-2)", color: "var(--text-secondary)" }}>
                      {row.col3}
                    </span>
                    <button
                      onClick={() => navigate(`/chart?symbol=${row.ticker}`)}
                      className="px-3 py-1 rounded-lg text-xs font-semibold transition-opacity hover:opacity-80"
                      style={{ background: "rgba(59,130,246,0.25)", color: "var(--text-primary)", border: "1px solid rgba(59,130,246,0.35)" }}>
                      View Chart
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── Heatmap View ── */}
          {viewMode === "heatmap" && active.heatCells && (
            <div className="p-5 flex-1">
              <p className="text-xs font-medium mb-3" style={{ color: "var(--text-secondary)" }}>
                {active.id === 1 ? "% Change — green=up, red=down" :
                 active.id === 10 ? "Dark pool print density — intensity = volume" :
                 active.id === 15 ? "Sector performance vs 20-day average" :
                 "Liquidation cluster density — intensity = size"}
              </p>
              <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2">
                {active.heatCells.map((cell) => {
                  const isDpOrLiq = active.id === 10 || active.id === 18;
                  const intensity = isDpOrLiq ? cell.value / 100 : Math.abs(cell.value ?? 0) / 15;
                  const isPos = (cell.value ?? 0) >= 0;
                  const bgColor = isDpOrLiq
                    ? `rgba(59,130,246,${0.1 + intensity * 0.6})`
                    : isPos
                      ? `rgba(163,230,53,${0.12 + intensity * 0.55})`
                      : `rgba(251,113,133,${0.12 + intensity * 0.55})`;
                  return (
                    <button
                      key={cell.label}
                      onClick={() => {
                        const ticker = cell.label.split(" ")[0];
                        navigate(`/chart?symbol=${ticker}`);
                      }}
                      className="rounded-lg p-3 text-center hover:opacity-80 transition-opacity cursor-pointer"
                      style={{ background: bgColor, border: "1px solid rgba(255,255,255,0.06)" }}>
                      <div className="text-xs font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                        {cell.label}
                      </div>
                      {cell.sub && (
                        <div className="text-[10px] mt-0.5 font-medium"
                          style={{ color: isDpOrLiq ? "var(--text-secondary)" : isPos ? "var(--accent-positive)" : "var(--accent-negative)" }}>
                          {cell.sub}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Feed View ── */}
          {viewMode === "feed" && (
            <div className="flex-1 overflow-y-auto">
              <div className="px-5 py-3 flex items-center gap-2"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                <span className="w-2 h-2 rounded-full bg-lime-400 animate-pulse" />
                <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
                  {active.id === 9 ? "Live unusual options flow — new sweeps appear automatically" : "Live whale wallet transactions — tracked smart-money wallets"}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr style={{ background: "var(--bg-elevated)", borderBottom: "1px solid var(--border-subtle)" }}>
                      {active.id === 9 ? (
                        <>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Ticker</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Strike</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Expiry</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Premium</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Side</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>OI</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Time</th>
                        </>
                      ) : (
                        <>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Asset</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Wallet</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Type</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Amount</th>
                          <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Time</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {feedEntries.map((entry) => (
                      <tr key={entry.id}
                        className={cn("border-b transition-all duration-500",
                          entry.isNew && "bg-lime-400/8")}
                        style={{ borderColor: "var(--border-subtle)" }}>
                        {entry.isNew && (
                          <td colSpan={0} className="sr-only" />
                        )}
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            {entry.isNew && (
                              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-lime-400/20 text-lime-400 animate-pulse">
                                NEW
                              </span>
                            )}
                            <span className="font-bold text-blue-300 text-xs">{entry.ticker}</span>
                          </div>
                        </td>
                        {active.id === 9 ? (
                          <>
                            <td className="px-4 py-2.5 text-xs font-medium" style={{ color: "var(--text-primary)" }}>{entry.strike}</td>
                            <td className="px-4 py-2.5 text-xs" style={{ color: "var(--text-secondary)" }}>{entry.expiry}</td>
                            <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: "var(--accent-positive)" }}>{entry.premium}</td>
                            <td className="px-4 py-2.5">
                              <span className={cn("px-2 py-0.5 rounded text-[10px] font-bold",
                                entry.side === "BUY" ? "bg-lime-400/15 text-lime-400" : "bg-red-400/15 text-red-400")}>
                                {entry.side}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-xs" style={{ color: "var(--text-secondary)" }}>{entry.oi}</td>
                          </>
                        ) : (
                          <>
                            <td className="px-4 py-2.5 text-xs font-mono" style={{ color: "var(--text-secondary)" }}>{entry.wallet}</td>
                            <td className="px-4 py-2.5">
                              <span className="px-2 py-0.5 rounded text-[10px] font-medium"
                                style={{ background: "var(--bg-elevated-2)", color: "var(--text-secondary)" }}>
                                {entry.type}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: "var(--accent-positive)" }}>{entry.amount}</td>
                          </>
                        )}
                        <td className="px-4 py-2.5 text-xs" style={{ color: "var(--text-tertiary)" }}>{entry.time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </main>
      </div>

      {/* ── Bottom Banner ── */}
      <div className="px-5 py-3 flex items-center justify-between gap-4 flex-wrap flex-shrink-0"
        style={{ background: "rgba(251,191,36,0.07)", borderTop: "1px solid rgba(251,191,36,0.2)" }}>
        <div className="flex items-center gap-2 text-xs" style={{ color: "#f59e0b" }}>
          <AlertCircle size={13} />
          <span>Scanner data is delayed 15 min for Free tier. Upgrade to Plus for real-time alerts and all 22 scanners.</span>
        </div>
        <button className="px-4 py-1.5 rounded-lg text-xs font-semibold transition-opacity hover:opacity-90"
          style={{ background: "#f59e0b", color: "#000" }}>
          Upgrade to Plus
        </button>
      </div>

      {/* ── Explain Modal ── */}
      {explainOpen && <ExplainModal scanner={active} onClose={() => setExplainOpen(false)} />}
    </div>
  );
}
