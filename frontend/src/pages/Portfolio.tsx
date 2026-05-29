import { useState, useMemo, useRef, useEffect } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  getAccount,
  getSnapshots,
  getTransactions,
  seedDemo,
} from "@/api/paper";
import type { PaperPosition, PaperAccount, DailySnapshot, PaperTransaction } from "@/api/paper";
import { fetchBars } from "@/api/bars";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { TICKER_NAMES } from "@/data/tickerNames";
import SectorPill from "@/components/ui/SectorPill";
import ExplainButton from "@/components/explain/ExplainButton";
import {
  TrendingUp,
  TrendingDown,
  ChevronDown,
  ChevronUp,
  X,
  Layers,
  PieChart,
  ShieldAlert,
  ArrowUpRight,
  ArrowDownRight,
  Wallet,
  BarChart2,
  Clock,
  Sprout,
} from "lucide-react";

// ─── Constants ──────────────────────────────────────────────────────────────

const ONE_YEAR_AGO = new Date(Date.now() - 365 * 86400_000).toISOString().slice(0, 10);
const SEVEN_DAYS_AGO = new Date(Date.now() - 10 * 86400_000).toISOString().slice(0, 10);
const RF = 0.05;

const SECTOR_MAP: Record<string, string> = {
  AAPL: "Technology",  MSFT: "Technology",  NVDA: "Technology",
  GOOGL: "Technology", GOOG: "Technology",  META: "Technology",
  AMD: "Technology",   INTC: "Technology",  AVGO: "Technology",
  ADBE: "Technology",  CRM: "Technology",   ORCL: "Technology",
  AMZN: "Consumer Disc.", TSLA: "Consumer Disc.", NFLX: "Consumer Disc.",
  NKE: "Consumer Disc.",  SBUX: "Consumer Disc.", TGT: "Consumer Disc.",
  JPM: "Financials",  BAC: "Financials",  GS: "Financials",
  WFC: "Financials",  MS: "Financials",   BLK: "Financials",
  JNJ: "Healthcare",  PFE: "Healthcare",  UNH: "Healthcare",
  ABBV: "Healthcare", MRK: "Healthcare",  LLY: "Healthcare",
  XOM: "Energy",      CVX: "Energy",      COP: "Energy",
  SPY: "ETF",         QQQ: "ETF",         IWM: "ETF",
  DIA: "ETF",         GLD: "ETF",         SLV: "ETF",
};

const SECTOR_COLORS: Record<string, string> = {
  Technology:         "#3B82F6",
  "Consumer Disc.":   "#F59E0B",
  Financials:         "#8B5CF6",
  Healthcare:         "#22C55E",
  Energy:             "#EF4444",
  ETF:                "#94A3B8",
  Other:              "#475569",
};

const PIE_COLORS = [
  "#3B82F6", "#8B5CF6", "#22C55E", "#F59E0B",
  "#EF4444", "#06B6D4", "#EC4899", "#F97316",
  "#A3E635", "#14B8A6",
];

type HoldingsSort = "symbol" | "shares" | "avg_cost" | "current_price" | "market_value" | "day_pnl" | "unrealized_pnl";
type SortDir = "asc" | "desc";
type ActiveTab = "holdings" | "allocation" | "risk";

// ─── Helpers ────────────────────────────────────────────────────────────────

function pnlColor(v: number) {
  return v >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]";
}

function pnlSign(v: number) {
  return v >= 0 ? "+" : "";
}

function buildSvgPath(values: number[], w: number, h: number): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values
    .map((v, i) => {
      const x = ((i / (values.length - 1)) * w).toFixed(2);
      const y = (h - ((v - min) / range) * (h - 2) - 1).toFixed(2);
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
}

function computeMetrics(closes: number[], spyCloses: number[]) {
  if (closes.length < 10) return null;
  const returns = closes.slice(1).map((c, i) => (c - closes[i]) / closes[i]);
  const meanR = returns.reduce((a, b) => a + b, 0) / returns.length;
  const varR = returns.reduce((a, b) => a + (b - meanR) ** 2, 0) / returns.length;
  const annVol = Math.sqrt(varR * 252);
  const totalReturn = closes[closes.length - 1] / closes[0] - 1;
  const annReturn = Math.pow(1 + totalReturn, 252 / returns.length) - 1;
  const sharpe = annVol > 0 ? (annReturn - RF) / annVol : 0;
  let peak = closes[0], maxDD = 0;
  for (const c of closes) {
    if (c > peak) peak = c;
    const dd = (peak - c) / peak;
    if (dd > maxDD) maxDD = dd;
  }
  let beta: number | null = null;
  if (spyCloses.length >= 10) {
    const n = Math.min(returns.length, spyCloses.length - 1);
    const spyRets = spyCloses.slice(1, n + 1).map((c, i) => (c - spyCloses[i]) / spyCloses[i]);
    const posRets = returns.slice(0, n);
    const mPos = posRets.reduce((a, b) => a + b, 0) / n;
    const mSpy = spyRets.reduce((a, b) => a + b, 0) / n;
    const cov = posRets.reduce((a, b, i) => a + (b - mPos) * (spyRets[i] - mSpy), 0) / n;
    const varSpy = spyRets.reduce((a, b) => a + (b - mSpy) ** 2, 0) / n;
    beta = varSpy > 0 ? cov / varSpy : null;
  }
  return { annReturn, annVol, sharpe, maxDD, beta };
}

function formatDateShort(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse bg-[var(--bg-elevated-2)] rounded", className)} />;
}

// ─── Mini Sparkline (inline in table) ────────────────────────────────────────

function MiniSparkline({ symbol }: { symbol: string }) {
  const { data } = useQuery({
    queryKey: ["sparkline-portfolio", symbol],
    queryFn: () => fetchBars(symbol, "1Day", undefined, SEVEN_DAYS_AGO),
    staleTime: 3_600_000,
    gcTime: 7_200_000,
  });

  const closes = data?.bars.map((b) => b.c) ?? [];
  if (closes.length < 2) return <div className="w-10 h-5 shrink-0" />;

  const isUp = closes[closes.length - 1] >= closes[0];
  const stroke = isUp ? "#22C55E" : "#EF4444";
  const path = buildSvgPath(closes, 40, 20);

  return (
    <svg width={40} height={20} className="shrink-0 overflow-visible">
      <path d={path} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Performance Chart (SVG, pure math) ──────────────────────────────────────

interface PerfChartProps {
  snapshots: DailySnapshot[];
  spyBars: number[];
  spyDates: string[];
  loading: boolean;
}

function PerfChart({ snapshots, spyBars, spyDates, loading }: PerfChartProps) {
  const W = 800;
  const H = 200;
  const PAD = { top: 12, right: 56, bottom: 28, left: 52 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  if (loading) {
    return <Skeleton className="w-full h-[200px]" />;
  }

  if (snapshots.length < 2) {
    return (
      <div className="flex items-center justify-center h-[200px] text-[var(--text-tertiary)] text-sm">
        Not enough data for chart yet
      </div>
    );
  }

  // Normalize portfolio to 100
  const portVals = snapshots.map((s) => s.equity);
  const portBase = portVals[0];
  const portNorm = portVals.map((v) => (v / portBase) * 100);

  // Align SPY to same date range
  const startDate = snapshots[0].date;
  const endDate = snapshots[snapshots.length - 1].date;
  const alignedSpy: number[] = [];
  spyDates.forEach((d, i) => {
    if (d >= startDate && d <= endDate && spyBars[i] != null) {
      alignedSpy.push(spyBars[i]);
    }
  });

  const spyNorm = alignedSpy.length >= 2
    ? alignedSpy.map((v) => (v / alignedSpy[0]) * 100)
    : [];

  const allVals = [...portNorm, ...spyNorm];
  const minY = Math.min(...allVals);
  const maxY = Math.max(...allVals);
  const rangeY = maxY - minY || 1;

  function toX(i: number, len: number) {
    return PAD.left + (len <= 1 ? 0 : (i / (len - 1)) * plotW);
  }
  function toY(val: number) {
    return PAD.top + plotH - ((val - minY) / rangeY) * plotH;
  }

  const portPath = portNorm.map((v, i) => `${i === 0 ? "M" : "L"}${toX(i, portNorm.length).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
  const spyPath = spyNorm.length >= 2
    ? spyNorm.map((v, i) => `${i === 0 ? "M" : "L"}${toX(i, spyNorm.length).toFixed(1)},${toY(v).toFixed(1)}`).join(" ")
    : "";

  // Y-axis ticks
  const yTicks = 5;
  const yTickVals = Array.from({ length: yTicks }, (_, i) => minY + (i / (yTicks - 1)) * rangeY);

  // X-axis ticks (up to 6 labels)
  const xTickCount = Math.min(6, snapshots.length);
  const xTickIndices = Array.from({ length: xTickCount }, (_, i) =>
    Math.round((i / (xTickCount - 1)) * (snapshots.length - 1))
  );

  const portReturn = portNorm[portNorm.length - 1] - 100;
  const spyReturn = spyNorm.length > 0 ? spyNorm[spyNorm.length - 1] - 100 : null;

  return (
    <div className="relative w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[200px]" preserveAspectRatio="none">
        {/* Grid lines */}
        {yTickVals.map((v, i) => (
          <line
            key={i}
            x1={PAD.left} y1={toY(v)}
            x2={W - PAD.right} y2={toY(v)}
            stroke="var(--border-subtle)" strokeWidth={1}
          />
        ))}
        {/* Baseline at 100 */}
        {minY < 100 && maxY > 100 && (
          <line x1={PAD.left} y1={toY(100)} x2={W - PAD.right} y2={toY(100)} stroke="var(--border-emphasis)" strokeWidth={1} strokeDasharray="4,4" />
        )}

        {/* SPY line */}
        {spyPath && (
          <path d={spyPath} fill="none" stroke="#475569" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
        )}

        {/* Portfolio line */}
        <path d={portPath} fill="none" stroke="var(--accent-positive)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {/* Y-axis labels */}
        {yTickVals.map((v, i) => (
          <text key={i} x={PAD.left - 6} y={toY(v)} textAnchor="end" dominantBaseline="middle"
            fill="var(--text-tertiary)" fontSize={10} fontFamily="JetBrains Mono, monospace">
            {(v - 100).toFixed(1)}%
          </text>
        ))}

        {/* X-axis labels */}
        {xTickIndices.map((idx) => (
          <text key={idx} x={toX(idx, snapshots.length)} y={H - 6} textAnchor="middle"
            fill="var(--text-tertiary)" fontSize={10} fontFamily="Inter, sans-serif">
            {formatDateShort(snapshots[idx].date)}
          </text>
        ))}

        {/* End labels */}
        <text x={W - PAD.right + 4} y={toY(portNorm[portNorm.length - 1])} dominantBaseline="middle"
          fill="var(--accent-positive)" fontSize={10} fontFamily="JetBrains Mono, monospace">
          {portReturn >= 0 ? "+" : ""}{portReturn.toFixed(1)}%
        </text>
        {spyNorm.length > 0 && (
          <text x={W - PAD.right + 4} y={toY(spyNorm[spyNorm.length - 1])} dominantBaseline="middle"
            fill="var(--text-tertiary)" fontSize={10} fontFamily="JetBrains Mono, monospace">
            {spyReturn! >= 0 ? "+" : ""}{spyReturn!.toFixed(1)}%
          </text>
        )}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-1 px-1">
        <span className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <span className="inline-block w-4 h-0.5 bg-[var(--accent-positive)]" /> Portfolio
        </span>
        {spyPath && (
          <span className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
            <span className="inline-block w-4 h-0.5 bg-[#475569]" /> SPY
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Pie Chart (pure SVG) ────────────────────────────────────────────────────

interface PieSlice {
  label: string;
  value: number;
  color: string;
}

function PieChart_({ slices, size = 140 }: { slices: PieSlice[]; size?: number }) {
  const total = slices.reduce((a, s) => a + s.value, 0);
  if (total <= 0) return null;

  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 4;
  const innerR = r * 0.55;

  let currentAngle = -Math.PI / 2;

  const paths = slices.map((slice) => {
    const frac = slice.value / total;
    const angle = frac * 2 * Math.PI;
    const x1 = cx + r * Math.cos(currentAngle);
    const y1 = cy + r * Math.sin(currentAngle);
    const x2 = cx + r * Math.cos(currentAngle + angle);
    const y2 = cy + r * Math.sin(currentAngle + angle);
    const ix1 = cx + innerR * Math.cos(currentAngle);
    const iy1 = cy + innerR * Math.sin(currentAngle);
    const ix2 = cx + innerR * Math.cos(currentAngle + angle);
    const iy2 = cy + innerR * Math.sin(currentAngle + angle);
    const large = angle > Math.PI ? 1 : 0;
    const d = `M${ix1.toFixed(2)},${iy1.toFixed(2)} L${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large},1 ${x2.toFixed(2)},${y2.toFixed(2)} L${ix2.toFixed(2)},${iy2.toFixed(2)} A${innerR},${innerR} 0 ${large},0 ${ix1.toFixed(2)},${iy1.toFixed(2)} Z`;
    const result = { ...slice, d, frac };
    currentAngle += angle;
    return result;
  });

  return (
    <svg width={size} height={size} className="shrink-0">
      {paths.map((s, i) => (
        <path key={i} d={s.d} fill={s.color} opacity={0.9} />
      ))}
    </svg>
  );
}

// ─── Position Drawer ─────────────────────────────────────────────────────────

interface DrawerProps {
  position: PaperPosition | null;
  onClose: () => void;
  onTrade: (symbol: string, side: "buy" | "sell") => void;
}

function PositionDrawer({ position, onClose, onTrade }: DrawerProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!position) return null;

  const pnlPct = position.unrealized_pnl_pct;
  const dayPct = position.day_pnl_pct;
  const barWidth = Math.min(Math.abs(pnlPct) / 50, 1) * 100; // cap at 50% for bar

  return (
    <>
      {/* Backdrop */}
      <div
        ref={overlayRef}
        className="fixed inset-0 bg-black/50 z-40 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Drawer panel */}
      <div className="fixed right-0 top-0 bottom-0 w-80 bg-[var(--bg-elevated)] border-l border-[var(--border-subtle)] z-50 flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-[var(--text-primary)] text-lg">{position.symbol}</span>
            <SectorPill symbol={position.symbol} />
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
          {/* Company name */}
          {TICKER_NAMES[position.symbol] && (
            <p className="text-xs text-[var(--text-tertiary)]">{TICKER_NAMES[position.symbol]}</p>
          )}

          {/* Current price */}
          <div>
            <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">
              {formatCurrency(position.current_price)}
            </div>
            <div className={cn("text-sm font-mono mt-0.5", pnlColor(position.day_pnl))}>
              {pnlSign(position.day_pnl)}{formatCurrency(position.day_pnl)} today ({dayPct >= 0 ? "+" : ""}{dayPct.toFixed(2)}%)
            </div>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "Shares", value: position.qty.toString() },
              { label: "Avg Cost", value: formatCurrency(position.avg_cost) },
              { label: "Market Value", value: formatCurrency(position.market_value) },
              { label: "Cost Basis", value: formatCurrency(position.cost_basis) },
              { label: "Prev Close", value: formatCurrency(position.prev_close) },
            ].map(({ label, value }) => (
              <div key={label} className="bg-[var(--bg-elevated-2)] rounded-lg px-3 py-2.5">
                <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">{label}</div>
                <div className="font-mono text-[var(--text-primary)] text-sm mt-0.5">{value}</div>
              </div>
            ))}
          </div>

          {/* Unrealized P&L bar */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider">Total Return</span>
              <span className={cn("font-mono text-sm font-semibold", pnlColor(position.unrealized_pnl))}>
                {pnlSign(position.unrealized_pnl)}{formatCurrency(position.unrealized_pnl)}
                {" "}({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
              </span>
            </div>
            <div className="h-2 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", position.unrealized_pnl >= 0 ? "bg-[#22C55E]" : "bg-[#EF4444]")}
                style={{ width: `${barWidth}%`, marginLeft: position.unrealized_pnl >= 0 ? "50%" : `${50 - barWidth}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-0.5">
              <span>-50%</span>
              <span>0</span>
              <span>+50%</span>
            </div>
          </div>

          {/* Opened at */}
          <div className="text-xs text-[var(--text-tertiary)]">
            Position opened: {new Date(position.opened_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </div>
        </div>

        {/* Action buttons */}
        <div className="border-t border-[var(--border-subtle)] px-4 py-3 grid grid-cols-2 gap-2">
          <button
            onClick={() => onTrade(position.symbol, "buy")}
            className="flex items-center justify-center gap-1.5 bg-[var(--accent-positive-bg)] hover:bg-[#22C55E]/20 border border-[#22C55E]/30 text-[var(--accent-positive)] font-semibold text-sm py-2 rounded-lg transition-colors cursor-pointer"
          >
            <ArrowUpRight size={14} /> Buy More
          </button>
          <button
            onClick={() => onTrade(position.symbol, "sell")}
            className="flex items-center justify-center gap-1.5 bg-[var(--accent-negative-bg)] hover:bg-[#EF4444]/20 border border-[#EF4444]/30 text-[var(--accent-negative)] font-semibold text-sm py-2 rounded-lg transition-colors cursor-pointer"
          >
            <ArrowDownRight size={14} /> Sell
          </button>
        </div>
      </div>
    </>
  );
}

// ─── Holdings Tab ────────────────────────────────────────────────────────────

function HoldingsTab({
  positions,
  onSelectPosition,
  onSeedDemo,
}: {
  positions: PaperPosition[];
  onSelectPosition: (p: PaperPosition) => void;
  onSeedDemo: () => void;
}) {
  const [sortBy, setSortBy] = useState<HoldingsSort>("market_value");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(col: HoldingsSort) {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
  }

  const sorted = useMemo(() => {
    return [...positions].sort((a, b) => {
      let av: number | string = 0;
      let bv: number | string = 0;
      switch (sortBy) {
        case "symbol": av = a.symbol; bv = b.symbol; break;
        case "shares": av = a.qty; bv = b.qty; break;
        case "avg_cost": av = a.avg_cost; bv = b.avg_cost; break;
        case "current_price": av = a.current_price; bv = b.current_price; break;
        case "market_value": av = a.market_value; bv = b.market_value; break;
        case "day_pnl": av = a.day_pnl; bv = b.day_pnl; break;
        case "unrealized_pnl": av = a.unrealized_pnl; bv = b.unrealized_pnl; break;
      }
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [positions, sortBy, sortDir]);

  function SortHeader({ col, children, className }: { col: HoldingsSort; children: React.ReactNode; className?: string }) {
    const active = sortBy === col;
    return (
      <th
        className={cn("py-2.5 text-[10px] uppercase tracking-wider cursor-pointer select-none transition-colors", active ? "text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]", className)}
        onClick={() => handleSort(col)}
      >
        <span className="inline-flex items-center gap-0.5">
          {children}
          {active ? (sortDir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />) : null}
        </span>
      </th>
    );
  }

  if (positions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4 text-center">
        <div className="w-16 h-16 rounded-full bg-[var(--bg-elevated-2)] flex items-center justify-center">
          <Layers size={28} className="text-[var(--text-tertiary)]" />
        </div>
        <div>
          <p className="text-[var(--text-primary)] font-semibold">No positions yet</p>
          <p className="text-[var(--text-tertiary)] text-sm mt-1">Start trading to build your portfolio</p>
        </div>
        <button
          onClick={onSeedDemo}
          className="flex items-center gap-2 bg-[var(--accent-positive)] hover:brightness-110 text-[var(--text-primary)] font-semibold text-sm px-4 py-2 rounded-lg transition-colors cursor-pointer"
        >
          <Sprout size={14} /> Seed demo account →
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Mobile card list */}
      <div className="md:hidden divide-y divide-[#1E293B]">
        {sorted.map((pos) => {
          const dayPct = pos.day_pnl_pct;
          const totalPct = pos.unrealized_pnl_pct;
          return (
            <div
              key={pos.id}
              onClick={() => onSelectPosition(pos)}
              className="p-4 cursor-pointer active:bg-[var(--bg-elevated-2)]/40 transition-colors"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <MiniSparkline symbol={pos.symbol} />
                  <div>
                    <div className="font-mono font-bold text-[var(--text-primary)]">{pos.symbol}</div>
                    {TICKER_NAMES[pos.symbol] && (
                      <div className="text-[11px] text-[var(--text-tertiary)] truncate max-w-[120px]">{TICKER_NAMES[pos.symbol]}</div>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-mono font-semibold text-[var(--text-primary)]">{formatCurrency(pos.market_value)}</div>
                  <div className="text-[11px] text-[var(--text-tertiary)]">{pos.qty} sh @ {formatCurrency(pos.avg_cost)}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
                  <div className="text-[9px] text-[var(--text-tertiary)] uppercase tracking-wide mb-0.5">Day P&L</div>
                  <div className={cn("text-xs font-mono font-medium", pnlColor(pos.day_pnl))}>
                    {pnlSign(pos.day_pnl)}{formatCurrency(Math.abs(pos.day_pnl))}
                  </div>
                  <div className={cn("text-[9px]", pnlColor(pos.day_pnl))}>
                    {dayPct >= 0 ? "+" : ""}{dayPct.toFixed(2)}%
                  </div>
                </div>
                <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
                  <div className="text-[9px] text-[var(--text-tertiary)] uppercase tracking-wide mb-0.5">Total Return</div>
                  <div className={cn("text-xs font-mono font-medium", pnlColor(pos.unrealized_pnl))}>
                    {pnlSign(pos.unrealized_pnl)}{formatCurrency(Math.abs(pos.unrealized_pnl))}
                  </div>
                  <div className={cn("text-[9px]", pnlColor(pos.unrealized_pnl))}>
                    {totalPct >= 0 ? "+" : ""}{totalPct.toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border-subtle)]">
              <SortHeader col="symbol" className="text-left px-4">Symbol</SortHeader>
              <SortHeader col="shares" className="text-right px-3">Shares</SortHeader>
              <SortHeader col="avg_cost" className="text-right px-3">Avg Cost</SortHeader>
              <SortHeader col="current_price" className="text-right px-3">Current</SortHeader>
              <SortHeader col="market_value" className="text-right px-3">Mkt Value</SortHeader>
              <SortHeader col="day_pnl" className="text-right px-3">Day P&L</SortHeader>
              <SortHeader col="unrealized_pnl" className="text-right px-4">Total Return</SortHeader>
            </tr>
          </thead>
          <tbody>
            {sorted.map((pos) => {
              const dayPct = pos.day_pnl_pct;
              const totalPct = pos.unrealized_pnl_pct;
              return (
                <tr
                  key={pos.id}
                  onClick={() => onSelectPosition(pos)}
                  className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/40 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <MiniSparkline symbol={pos.symbol} />
                      <div>
                        <div className="font-mono font-bold text-[var(--text-primary)]">{pos.symbol}</div>
                        {TICKER_NAMES[pos.symbol] && (
                          <div className="text-[11px] text-[var(--text-tertiary)] max-w-[120px] truncate">{TICKER_NAMES[pos.symbol]}</div>
                        )}
                      </div>
                      <SectorPill symbol={pos.symbol} />
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[var(--text-secondary)]">{pos.qty}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[var(--text-secondary)]">{formatCurrency(pos.avg_cost)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[var(--text-primary)]">{formatCurrency(pos.current_price)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[var(--text-primary)] font-medium">{formatCurrency(pos.market_value)}</td>
                  <td className={cn("px-3 py-2.5 text-right font-mono", pnlColor(pos.day_pnl))}>
                    <div className="font-medium">{pnlSign(pos.day_pnl)}{formatCurrency(pos.day_pnl)}</div>
                    <div className="text-xs opacity-80">{dayPct >= 0 ? "+" : ""}{dayPct.toFixed(2)}%</div>
                  </td>
                  <td className={cn("px-4 py-2.5 text-right font-mono", pnlColor(pos.unrealized_pnl))}>
                    <div className="font-medium">{pnlSign(pos.unrealized_pnl)}{formatCurrency(pos.unrealized_pnl)}</div>
                    <div className="text-xs opacity-80">{totalPct >= 0 ? "+" : ""}{totalPct.toFixed(2)}%</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Allocation Tab ───────────────────────────────────────────────────────────

function AllocationTab({ positions }: { positions: PaperPosition[] }) {
  const totalValue = positions.reduce((a, p) => a + p.market_value, 0);

  if (positions.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--text-tertiary)] text-sm">
        No positions to allocate
      </div>
    );
  }

  // By symbol
  const symbolSlices: PieSlice[] = positions.map((p, i) => ({
    label: p.symbol,
    value: p.market_value,
    color: PIE_COLORS[i % PIE_COLORS.length],
  }));

  // By sector
  const sectorMap: Record<string, number> = {};
  positions.forEach((p) => {
    const sector = SECTOR_MAP[p.symbol] ?? "Other";
    sectorMap[sector] = (sectorMap[sector] ?? 0) + p.market_value;
  });
  const sectorSlices: PieSlice[] = Object.entries(sectorMap).map(([label, value]) => ({
    label, value, color: SECTOR_COLORS[label] ?? SECTOR_COLORS.Other,
  }));

  return (
    <div className="px-4 py-5 space-y-8">
      {/* By Symbol */}
      <div>
        <h3 className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider mb-4">By Symbol</h3>
        <div className="flex gap-8 items-center flex-wrap">
          <PieChart_ slices={symbolSlices} size={140} />
          <div className="flex-1 min-w-[200px] space-y-2">
            {symbolSlices.map((s) => {
              const pct = totalValue > 0 ? (s.value / totalValue) * 100 : 0;
              return (
                <div key={s.label} className="flex items-center gap-2.5">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                  <span className="font-mono font-bold text-[var(--text-primary)] text-sm w-12 shrink-0">{s.label}</span>
                  <div className="flex-1 h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: s.color }} />
                  </div>
                  <span className="font-mono text-xs text-[var(--text-secondary)] w-12 text-right">{pct.toFixed(1)}%</span>
                  <span className="font-mono text-xs text-[var(--text-tertiary)] w-24 text-right">{formatCurrency(s.value)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* By Sector */}
      <div>
        <h3 className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider mb-4">By Sector</h3>
        <div className="flex gap-8 items-center flex-wrap">
          <PieChart_ slices={sectorSlices} size={140} />
          <div className="flex-1 min-w-[200px] space-y-2">
            {sectorSlices.map((s) => {
              const pct = totalValue > 0 ? (s.value / totalValue) * 100 : 0;
              return (
                <div key={s.label} className="flex items-center gap-2.5">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                  <span className="font-medium text-[var(--text-primary)] text-sm w-32 shrink-0">{s.label}</span>
                  <div className="flex-1 h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: s.color }} />
                  </div>
                  <span className="font-mono text-xs text-[var(--text-secondary)] w-12 text-right">{pct.toFixed(1)}%</span>
                  <span className="font-mono text-xs text-[var(--text-tertiary)] w-24 text-right">{formatCurrency(s.value)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Risk Tab ─────────────────────────────────────────────────────────────────

function RiskTab({ positions }: { positions: PaperPosition[] }) {
  const symbols = positions.map((p) => p.symbol);
  const allSymbols = [...new Set([...symbols, "SPY"])];

  const results = useQueries({
    queries: allSymbols.map((sym) => ({
      queryKey: ["bars", sym, "1Day", undefined, ONE_YEAR_AGO],
      queryFn: () => fetchBars(sym, "1Day", undefined, ONE_YEAR_AGO),
      staleTime: 3_600_000,
    })),
  });

  const loaded = results.every((r) => !r.isLoading);

  if (!loaded) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
      </div>
    );
  }

  if (positions.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--text-tertiary)] text-sm">
        No positions to analyze
      </div>
    );
  }

  const barsMap: Record<string, number[]> = {};
  allSymbols.forEach((sym, i) => {
    barsMap[sym] = results[i].data?.bars.map((b) => b.c) ?? [];
  });
  const spyCloses = barsMap["SPY"] ?? [];

  const rows = positions.map((pos) => ({
    pos,
    metrics: computeMetrics(barsMap[pos.symbol] ?? [], spyCloses),
  }));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider border-b border-[var(--border-subtle)]">
            <th className="text-left px-4 py-2.5">Symbol</th>
            <th className="text-right px-3 py-2.5">Ann. Return</th>
            <th className="text-right px-3 py-2.5">Volatility</th>
            <th className="text-right px-3 py-2.5">
              <span className="inline-flex items-center gap-1">Sharpe <ExplainButton term="Sharpe Ratio" size={11} /></span>
            </th>
            <th className="text-right px-3 py-2.5">
              <span className="inline-flex items-center gap-1">Max DD <ExplainButton term="Max Drawdown" size={11} /></span>
            </th>
            <th className="text-right px-4 py-2.5">
              <span className="inline-flex items-center gap-1">Beta (SPY) <ExplainButton term="Beta" size={11} /></span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ pos, metrics }) => (
            <tr key={pos.id} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/30 transition-colors">
              <td className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-[var(--text-primary)]">{pos.symbol}</span>
                  <SectorPill symbol={pos.symbol} />
                </div>
              </td>
              {metrics ? (
                <>
                  <td className={cn("px-3 py-2.5 text-right font-medium font-mono tabular-nums", metrics.annReturn >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                    {metrics.annReturn >= 0 ? "+" : ""}{formatPercent(metrics.annReturn * 100)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-[var(--text-secondary)] font-mono tabular-nums">{formatPercent(metrics.annVol * 100)}</td>
                  <td className={cn("px-3 py-2.5 text-right font-medium font-mono tabular-nums", metrics.sharpe >= 1 ? "text-[var(--accent-positive)]" : metrics.sharpe >= 0 ? "text-[var(--text-secondary)]" : "text-[var(--accent-negative)]")}>
                    {metrics.sharpe.toFixed(2)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-[var(--accent-negative)] font-mono tabular-nums">-{formatPercent(metrics.maxDD * 100)}</td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-secondary)] font-mono tabular-nums">
                    {metrics.beta != null ? metrics.beta.toFixed(2) : "—"}
                  </td>
                </>
              ) : (
                <td colSpan={5} className="px-3 py-2.5 text-center text-[var(--text-tertiary)] text-xs">Insufficient data</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-4 py-2.5 text-[10px] text-[var(--text-tertiary)] border-t border-[var(--border-subtle)]">
        Based on 1-year daily returns · Risk-free rate: {(RF * 100).toFixed(0)}% · Sharpe ≥ 1 = good
      </div>
    </div>
  );
}

// ─── Recent Activity ──────────────────────────────────────────────────────────

function RecentActivity({ transactions }: { transactions: PaperTransaction[] }) {
  const [open, setOpen] = useState(false);
  const recent = transactions.slice(0, 5);

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[var(--bg-elevated-2)]/30 transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
          <Clock size={14} /> Recent Activity
          {recent.length > 0 && (
            <span className="bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] text-[10px] font-mono rounded-full px-1.5 py-0.5">{recent.length}</span>
          )}
        </span>
        {open ? <ChevronUp size={14} className="text-[var(--text-tertiary)]" /> : <ChevronDown size={14} className="text-[var(--text-tertiary)]" />}
      </button>

      {open && (
        <div className="border-t border-[var(--border-subtle)]">
          {recent.length === 0 ? (
            <div className="px-4 py-6 text-center text-[var(--text-tertiary)] text-sm">No filled orders yet</div>
          ) : (
            <div className="divide-y divide-[#1E293B]/50">
              {recent.map((tx) => (
                <div key={tx.id} className="flex items-center justify-between px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      "w-1 h-8 rounded-full shrink-0",
                      tx.side === "buy" ? "bg-[#22C55E]" : "bg-[#EF4444]"
                    )} />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{tx.symbol}</span>
                        <span className={cn("text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded", tx.side === "buy" ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]" : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]")}>
                          {tx.side}
                        </span>
                      </div>
                      <div className="text-xs text-[var(--text-tertiary)]">
                        {tx.qty} shares @ {formatCurrency(tx.fill_price)}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    {tx.realized_pnl !== 0 && (
                      <div className={cn("font-mono text-sm font-medium", pnlColor(tx.realized_pnl))}>
                        {pnlSign(tx.realized_pnl)}{formatCurrency(tx.realized_pnl)}
                      </div>
                    )}
                    <div className="text-xs text-[var(--text-tertiary)]">
                      {new Date(tx.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Hero P&L Bar ─────────────────────────────────────────────────────────────

function HeroBar({ account, loading }: { account: PaperAccount | undefined; loading: boolean }) {
  if (loading) {
    return (
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 grid grid-cols-1 sm:grid-cols-3 gap-5">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-9 w-40" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </div>
    );
  }

  if (!account) return null;

  const dayPct = account.day_pnl_pct;
  const totalPct = account.total_pnl_pct;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        {/* Equity */}
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
            <TrendingUp size={11} /> Portfolio Value
          </div>
          <div className="text-4xl font-bold text-[var(--text-primary)] font-mono tracking-tight">
            {formatCurrency(account.equity)}
          </div>
          <div className={cn("text-sm font-mono mt-1 font-medium", pnlColor(account.total_pnl))}>
            {pnlSign(account.total_pnl)}{formatCurrency(account.total_pnl)} all-time
          </div>
          <div className="flex items-center gap-1.5 mt-1.5">
            <Wallet size={11} className="text-[var(--text-tertiary)]" />
            <span className="text-xs text-[var(--text-tertiary)] font-mono">
              Buying power: {formatCurrency(account.cash)}
            </span>
          </div>
        </div>

        {/* Day P&L */}
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
            {account.day_pnl >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />} Day's P&L
          </div>
          <div className={cn("text-3xl font-bold font-mono tracking-tight transition-colors", pnlColor(account.day_pnl))}>
            {pnlSign(account.day_pnl)}{formatCurrency(account.day_pnl)}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <span className={cn(
              "inline-flex items-center gap-1 text-xs font-semibold font-mono px-2 py-0.5 rounded-full",
              account.day_pnl >= 0
                ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)] border border-[var(--accent-positive)]/20"
                : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)] border border-[var(--accent-negative)]/20"
            )}>
              {dayPct >= 0 ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
              {dayPct >= 0 ? "+" : ""}{dayPct.toFixed(2)}%
            </span>
            <span className="text-xs text-[var(--text-tertiary)]">vs yesterday</span>
          </div>
        </div>

        {/* Total Return */}
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
            <BarChart2 size={11} /> Total Return
          </div>
          <div className={cn("text-3xl font-bold font-mono tracking-tight transition-colors", pnlColor(account.total_pnl))}>
            {pnlSign(account.total_pnl)}{formatCurrency(account.total_pnl)}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <span className={cn(
              "inline-flex items-center gap-1 text-xs font-semibold font-mono px-2 py-0.5 rounded-full",
              account.total_pnl >= 0
                ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)] border border-[var(--accent-positive)]/20"
                : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)] border border-[var(--accent-negative)]/20"
            )}>
              {totalPct >= 0 ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
              {totalPct >= 0 ? "+" : ""}{totalPct.toFixed(2)}%
            </span>
            <span className="text-xs text-[var(--text-tertiary)]">
              since {new Date(account.created_at).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Portfolio() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<ActiveTab>("holdings");
  const [selectedPosition, setSelectedPosition] = useState<PaperPosition | null>(null);

  const { data: account, isLoading: accountLoading } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 10_000,
  });

  const { data: snapshots = [], isLoading: snapshotsLoading } = useQuery({
    queryKey: ["paper-snapshots"],
    queryFn: getSnapshots,
    staleTime: 60_000,
  });

  const { data: transactions = [] } = useQuery({
    queryKey: ["paper-transactions"],
    queryFn: getTransactions,
    staleTime: 10_000,
  });

  // SPY data for perf chart — use account created_at as start
  const spyStart = account?.created_at
    ? new Date(account.created_at).toISOString().slice(0, 10)
    : ONE_YEAR_AGO;

  const { data: spyData, isLoading: spyLoading } = useQuery({
    queryKey: ["bars", "SPY", "1Day", undefined, spyStart],
    queryFn: () => fetchBars("SPY", "1Day", undefined, spyStart),
    staleTime: 3_600_000,
    enabled: !!account,
  });

  const spyCloses = spyData?.bars.map((b) => b.c) ?? [];
  const spyDates = spyData?.bars.map((b) => b.t.slice(0, 10)) ?? [];

  const positions = account?.positions ?? [];

  const seedMut = {
    isPending: false,
    mutate: async () => {
      try {
        await seedDemo();
        window.location.reload();
      } catch {
        // swallow
      }
    },
  };

  const tabs: { key: ActiveTab; label: string; icon: React.ReactNode }[] = [
    { key: "holdings",   label: "Holdings",   icon: <Layers size={13} /> },
    { key: "allocation", label: "Allocation", icon: <PieChart size={13} /> },
    { key: "risk",       label: "Risk",       icon: <ShieldAlert size={13} /> },
  ];

  return (
    <div className="space-y-4 pb-20 md:pb-8">
      {/* Section 1: Hero P&L Bar */}
      <HeroBar account={account} loading={accountLoading} />

      {/* Section 2: Performance Chart */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-[var(--text-secondary)]">Performance vs SPY</h3>
          {account && (
            <span className="text-xs text-[var(--text-tertiary)] font-mono">
              Since {new Date(account.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
            </span>
          )}
        </div>
        <PerfChart
          snapshots={snapshots}
          spyBars={spyCloses}
          spyDates={spyDates}
          loading={accountLoading || snapshotsLoading || spyLoading}
        />
      </div>

      {/* Section 3: Tabs */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b border-[var(--border-subtle)]">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "flex items-center gap-1.5 px-5 py-3 text-xs font-medium transition-colors cursor-pointer",
                activeTab === tab.key
                  ? "text-[var(--text-primary)] border-b-2 border-[#3B82F6] -mb-px"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              )}
            >
              {tab.icon}
              {tab.label}
              {tab.key === "holdings" && positions.length > 0 && (
                <span className="bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] text-[10px] font-mono rounded-full px-1.5 ml-0.5">
                  {positions.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {accountLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
          </div>
        ) : (
          <>
            {activeTab === "holdings" && (
              <HoldingsTab
                positions={positions}
                onSelectPosition={setSelectedPosition}
                onSeedDemo={() => seedMut.mutate()}
              />
            )}
            {activeTab === "allocation" && <AllocationTab positions={positions} />}
            {activeTab === "risk" && <RiskTab positions={positions} />}
          </>
        )}
      </div>

      {/* Section 4: Recent Activity */}
      <RecentActivity transactions={transactions} />

      {/* Position Drawer */}
      <PositionDrawer
        position={selectedPosition}
        onClose={() => setSelectedPosition(null)}
        onTrade={(symbol, side) => navigate(`/paper?symbol=${symbol}&side=${side}`)}
      />
    </div>
  );
}
