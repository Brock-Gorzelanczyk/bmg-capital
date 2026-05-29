import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Star, RotateCw, X, ChevronUp, ChevronDown, ChevronsUpDown,
  ArrowLeft, Search, ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import {
  getCryptoMarket,
  getCryptoOverview,
  getCryptoTrending,
  refreshCryptoMarket,
  getCryptoStrategyTrades,
  getCryptoStrategyCandidates,
  getCryptoStrategySummary,
  getCryptoStrategyDefinitions,
  runCryptoStrategyNow,
  getCryptoOHLCV,
  getCryptoQuizStatus,
  completeCryptoQuiz,
  toggleCryptoStrategy,
  type CoinGeckoData,
  type CryptoOverview,
  type CryptoTrade,
  type StrategyDefinition,
  type OHLCVBar,
} from "@/api/crypto";
import { getAccount, placeOrder, type PaperPosition, type PlaceOrderBody } from "@/api/paper";
import { cn } from "@/lib/utils";

// ── Formatters ─────────────────────────────────────────────────────────────────

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 0.0001) return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 8, maximumFractionDigits: 8 });
  if (n < 0.01)   return "$" + n.toFixed(6);
  if (n < 1)      return "$" + n.toFixed(4);
  if (n >= 10_000) return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtLarge(n: number | null | undefined): string {
  if (!n) return "—";
  if (n >= 1e12) return "$" + (n / 1e12).toFixed(2) + "T";
  if (n >= 1e9)  return "$" + (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6)  return "$" + (n / 1e6).toFixed(1) + "M";
  return "$" + n.toLocaleString();
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function pctColor(n: number | null | undefined): string {
  if (n == null) return "text-[var(--text-tertiary)]";
  return n >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]";
}

function fmt$(n: number | null | undefined): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const s = n < 0 ? "-$" : "$";
  if (abs >= 1e9)  return s + (abs / 1e9).toFixed(2) + "B";
  if (abs >= 1e6)  return s + (abs / 1e6).toFixed(2) + "M";
  if (abs >= 1000) return s + abs.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return s + abs.toFixed(2);
}

// ── Watchlist (localStorage) ───────────────────────────────────────────────────

const WL_KEY = "crypto_watchlist_v1";

function loadWatchlist(): Set<string> {
  try {
    const raw = localStorage.getItem(WL_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function saveWatchlist(s: Set<string>): void {
  try {
    localStorage.setItem(WL_KEY, JSON.stringify([...s]));
  } catch {}
}

// ── SparkLine ──────────────────────────────────────────────────────────────────

function SparkLine({ prices }: { prices: number[] }) {
  if (!prices || prices.length < 2) {
    return <div className="w-[72px] h-6 flex items-center justify-center text-[var(--text-tertiary)] text-[9px]">—</div>;
  }
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const W = 72, H = 24;
  const pts = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * W;
    const y = H - ((p - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const isUp = prices[prices.length - 1] >= prices[0];
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
      <polyline
        points={pts}
        fill="none"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        style={{ stroke: isUp ? "var(--accent-positive)" : "var(--accent-negative)" }}
      />
    </svg>
  );
}

// ── PriceChart ─────────────────────────────────────────────────────────────────

function PriceChart({ bars, timeframe }: { bars: OHLCVBar[]; timeframe: 7 | 30 | 90 }) {
  const sliced = bars.slice(-timeframe);
  if (sliced.length < 2) {
    return (
      <div className="h-[110px] flex items-center justify-center text-[var(--text-tertiary)] text-xs bg-[var(--bg-elevated-2)] rounded-xl">
        No chart data
      </div>
    );
  }
  const closes = sliced.map((b) => b.c);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const isUp = closes[closes.length - 1] >= closes[0];
  const color = isUp ? "#10b981" : "#f43f5e";
  const gradId = `pcg_${timeframe}`;

  const W = 400, H = 110;
  const PL = 4, PR = 64, PT = 6, PB = 20;
  const plotW = W - PL - PR;
  const plotH = H - PT - PB;

  const pts = sliced.map((b, i) => ({
    x: PL + (i / (sliced.length - 1)) * plotW,
    y: PT + (1 - (b.c - min) / range) * plotH,
  }));

  const linePath = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${pts[pts.length - 1].x.toFixed(1)},${(PT + plotH).toFixed(1)} L ${pts[0].x.toFixed(1)},${(PT + plotH).toFixed(1)} Z`;

  const startLabel = new Date(sliced[0].t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const endLabel   = new Date(sliced[sliced.length - 1].t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const midIdx = Math.floor(sliced.length / 2);
  const midLabel = sliced.length > 14
    ? new Date(sliced[midIdx].t).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : null;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[110px]" preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
      {/* Y-axis price labels */}
      <text x={W - 2} y={PT + 5} textAnchor="end" fontSize="8" fill="rgba(148,163,184,0.8)">{fmtPrice(max)}</text>
      <text x={W - 2} y={PT + plotH + 1} textAnchor="end" fontSize="8" fill="rgba(148,163,184,0.8)">{fmtPrice(min)}</text>
      {/* Last price label */}
      <text x={W - 2} y={pts[pts.length - 1].y + 1} textAnchor="end" fontSize="8.5" fontWeight="600" fill={color}>
        {fmtPrice(closes[closes.length - 1])}
      </text>
      {/* X-axis date labels */}
      <text x={PL} y={H - 3} textAnchor="start" fontSize="8" fill="rgba(148,163,184,0.7)">{startLabel}</text>
      {midLabel && (
        <text x={PL + plotW / 2} y={H - 3} textAnchor="middle" fontSize="8" fill="rgba(148,163,184,0.7)">{midLabel}</text>
      )}
      <text x={PL + plotW} y={H - 3} textAnchor="end" fontSize="8" fill="rgba(148,163,184,0.7)">{endLabel}</text>
    </svg>
  );
}

// ── Fear & Greed Arc Gauge ─────────────────────────────────────────────────────

function FearGauge({ value, label }: { value: number; label: string }) {
  const r = 18, cx = 28, cy = 26;
  const startAngle = -180, endAngle = 0;
  const angle = startAngle + (value / 100) * 180;
  const toRad = (a: number) => (a * Math.PI) / 180;
  const arcX = cx + r * Math.cos(toRad(angle));
  const arcY = cy + r * Math.sin(toRad(angle));
  const trackColor = "#1e293b";
  const fillColor = value <= 25 ? "#FB7185" : value <= 50 ? "#F97316" : value <= 75 ? "#EAB308" : "#BEF264";

  const describeArc = (fromDeg: number, toDeg: number) => {
    const x1 = cx + r * Math.cos(toRad(fromDeg));
    const y1 = cy + r * Math.sin(toRad(fromDeg));
    const x2 = cx + r * Math.cos(toRad(toDeg));
    const y2 = cy + r * Math.sin(toRad(toDeg));
    const large = toDeg - fromDeg > 180 ? 1 : 0;
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };

  return (
    <div className="flex flex-col items-center gap-0.5">
      <svg width="56" height="30" viewBox="0 0 56 30">
        <path d={describeArc(-180, 0)} fill="none" stroke={trackColor} strokeWidth="4" strokeLinecap="round" />
        <path d={describeArc(-180, angle)} fill="none" stroke={fillColor} strokeWidth="4" strokeLinecap="round" />
        <circle cx={arcX.toFixed(2)} cy={arcY.toFixed(2)} r="3" fill={fillColor} />
      </svg>
      <span className="text-xs font-bold font-mono" style={{ color: fillColor }}>{value}</span>
      <span className="text-[9px] text-[var(--text-tertiary)] leading-none whitespace-nowrap">{label}</span>
    </div>
  );
}

// ── Overview Bar ───────────────────────────────────────────────────────────────

function OverviewBar({ data }: { data: CryptoOverview | undefined }) {
  if (!data) {
    return (
      <div className="flex gap-3 flex-wrap">
        {[0, 1, 2].map(i => (
          <div key={i} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 h-16 w-40 animate-pulse" />
        ))}
      </div>
    );
  }
  const mcapColor = data.market_cap_change_24h_pct >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]";
  return (
    <div className="flex gap-3 flex-wrap">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex flex-col gap-0.5 min-w-[160px]">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Market Cap</span>
        <span className="text-base font-bold font-mono text-[var(--text-primary)]">{fmtLarge(data.total_market_cap_usd)}</span>
        <span className={cn("text-xs font-mono font-semibold", mcapColor)}>
          {fmtPct(data.market_cap_change_24h_pct)} 24h
        </span>
      </div>
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex flex-col gap-0.5 min-w-[140px]">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">BTC Dominance</span>
        <span className="text-base font-bold font-mono text-[var(--text-primary)]">{data.btc_dominance.toFixed(1)}%</span>
        <span className="text-xs text-[var(--text-tertiary)]">{data.active_coins.toLocaleString()} coins</span>
      </div>
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex items-center gap-3 min-w-[140px]">
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Fear & Greed</span>
        </div>
        <FearGauge value={data.fear_greed.value} label={data.fear_greed.label} />
      </div>
    </div>
  );
}

// ── Coin Trading Panel (slide-over) ────────────────────────────────────────────

function CoinTradingPanel({
  coin, cash, position, onClose, onFilled,
}: {
  coin: CoinGeckoData;
  cash: number;
  position: PaperPosition | null;
  onClose: () => void;
  onFilled: () => void;
}) {
  const navigate = useNavigate();
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [mode, setMode] = useState<"notional" | "qty">("notional");
  const [notional, setNotional] = useState("500");
  const [qty, setQty] = useState("");
  const [tf, setTf] = useState<7 | 30 | 90>(30);

  const price = coin.current_price ?? 0;
  const paperSymbol = `${coin.symbol.toUpperCase()}-USD`;

  const { data: ohlcvData, isLoading: chartLoading } = useQuery({
    queryKey: ["crypto-ohlcv", paperSymbol],
    queryFn: () => getCryptoOHLCV(paperSymbol, 90),
    staleTime: 5 * 60_000,
  });

  const bars = ohlcvData?.bars ?? [];

  const qtyPreview = mode === "notional" && notional && price
    ? (parseFloat(notional) / price).toFixed(8) : null;
  const notionalPreview = mode === "qty" && qty && price
    ? (parseFloat(qty) * price).toFixed(2) : null;

  const QUICK_AMOUNTS = [100, 500, 1000, 5000];

  const mutation = useMutation({
    mutationFn: () => {
      const body: PlaceOrderBody = { symbol: paperSymbol, side, order_type: "market", tif: "gtc" };
      if (mode === "notional") body.notional = parseFloat(notional);
      else body.qty = parseFloat(qty);
      return placeOrder(body);
    },
    onSuccess: () => {
      toast.success(`${side === "buy" ? "Bought" : "Sold"} ${coin.symbol}`);
      onFilled();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Order failed"),
  });

  const isShort = position && position.qty < 0;

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 w-full max-w-[440px] bg-[var(--bg-elevated)] border-l border-[var(--border-subtle)] shadow-2xl z-50 flex flex-col overflow-y-auto">

        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[var(--border-subtle)] sticky top-0 bg-[var(--bg-elevated)] z-10">
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors p-1 rounded-lg hover:bg-[var(--bg-elevated-2)] cursor-pointer flex-shrink-0">
            <ArrowLeft size={16} />
          </button>
          {coin.image && <img src={coin.image} alt={coin.symbol} className="w-9 h-9 rounded-full flex-shrink-0" />}
          <div className="flex-1 min-w-0">
            <div className="font-bold text-[var(--text-primary)] text-sm leading-tight truncate">{coin.name}</div>
            <div className="text-[11px] text-[var(--text-tertiary)] font-mono">{coin.symbol} · #{coin.market_cap_rank}</div>
          </div>
          <div className="text-right flex-shrink-0">
            <div className="text-xl font-bold font-mono text-[var(--text-primary)]">{fmtPrice(price)}</div>
            <div className={cn("text-xs font-mono font-semibold", pctColor(coin.pct_24h))}>{fmtPct(coin.pct_24h)} 24h</div>
          </div>
        </div>

        {/* Chart section */}
        <div className="px-5 pt-4 pb-0">
          <div className="flex items-center justify-between mb-2">
            <div className="flex gap-0.5 bg-[var(--bg-elevated-2)] p-0.5 rounded-lg">
              {([7, 30, 90] as const).map((t) => (
                <button key={t} onClick={() => setTf(t)} className={cn(
                  "px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors cursor-pointer",
                  tf === t ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                )}>{t}D</button>
              ))}
            </div>
            <button
              onClick={() => navigate(`/chart?symbol=${paperSymbol}`)}
              className="text-[10px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] flex items-center gap-1 transition-colors cursor-pointer"
            >
              Full Chart <ExternalLink size={10} />
            </button>
          </div>
          {chartLoading ? (
            <div className="h-[110px] bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
          ) : (
            <PriceChart bars={bars} timeframe={tf} />
          )}
        </div>

        {/* 24h stats */}
        <div className="px-5 py-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { label: "24h High",   val: fmtPrice(coin.high_24h) },
              { label: "24h Low",    val: fmtPrice(coin.low_24h) },
              { label: "Volume 24h", val: fmtLarge(coin.total_volume) },
              { label: "Market Cap", val: fmtLarge(coin.market_cap) },
            ].map((s) => (
              <div key={s.label} className="bg-[var(--bg-elevated-2)] rounded-lg px-3 py-2">
                <div className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] mb-0.5">{s.label}</div>
                <div className="text-xs font-bold font-mono text-[var(--text-primary)]">{s.val}</div>
              </div>
            ))}
          </div>
          {coin.ath != null && (
            <div className="mt-2 text-[10px] text-[var(--text-tertiary)] font-mono">
              ATH {fmtPrice(coin.ath)}
              {coin.ath_change_percentage != null && (
                <span className={cn("ml-1.5 font-semibold", pctColor(coin.ath_change_percentage))}>
                  {fmtPct(coin.ath_change_percentage)} from ATH
                </span>
              )}
            </div>
          )}
        </div>

        {/* Order form */}
        <div className="px-5 pb-5 border-t border-[var(--border-subtle)] pt-4 flex-shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-3">Place Order</div>

          {/* Buy / Sell toggle */}
          <div className="flex gap-1 mb-4 bg-[var(--bg-elevated-2)] p-1 rounded-xl">
            {(["buy", "sell"] as const).map((s) => (
              <button key={s} onClick={() => setSide(s)} className={cn(
                "flex-1 py-2 rounded-lg text-sm font-bold transition-all capitalize cursor-pointer",
                side === s
                  ? s === "buy" ? "bg-emerald-600 text-white shadow-sm" : "bg-red-600 text-white shadow-sm"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              )}>{s}</button>
            ))}
          </div>

          {/* Mode toggle */}
          <div className="flex gap-2 mb-3 text-xs">
            {(["notional", "qty"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className={cn(
                "px-3 py-1 rounded-full border transition-colors cursor-pointer",
                mode === m
                  ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive-bg)]"
                  : "border-[var(--border-subtle)] text-[var(--text-tertiary)]"
              )}>{m === "notional" ? "$ Amount" : "Coin Qty"}</button>
            ))}
          </div>

          {/* Quick amounts (notional mode only) */}
          {mode === "notional" && (
            <div className="flex gap-1.5 mb-3">
              {QUICK_AMOUNTS.map((a) => (
                <button
                  key={a}
                  onClick={() => setNotional(String(a))}
                  className={cn(
                    "flex-1 py-1 rounded-lg text-[11px] font-semibold border transition-colors cursor-pointer",
                    notional === String(a)
                      ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive-bg)]"
                      : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-[var(--border-emphasis)]"
                  )}
                >
                  ${a >= 1000 ? `${a / 1000}k` : a}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          {mode === "notional" ? (
            <div className="mb-1">
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm">$</span>
                <input
                  type="number"
                  value={notional}
                  onChange={(e) => setNotional(e.target.value)}
                  className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-xl pl-7 pr-4 py-3 text-[var(--text-primary)] text-sm font-mono focus:outline-none focus:border-[var(--accent-positive)]"
                  placeholder="500" min="1"
                />
              </div>
              {qtyPreview && <p className="text-[11px] text-[var(--text-tertiary)] mt-1.5 font-mono px-1">≈ {qtyPreview} {coin.symbol}</p>}
            </div>
          ) : (
            <div className="mb-1">
              <div className="relative">
                <input
                  type="number"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-xl pl-4 pr-16 py-3 text-[var(--text-primary)] text-sm font-mono focus:outline-none focus:border-[var(--accent-positive)]"
                  placeholder="0.001" step="0.0001" min="0"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-xs font-mono">{coin.symbol}</span>
              </div>
              {notionalPreview && <p className="text-[11px] text-[var(--text-tertiary)] mt-1.5 font-mono px-1">≈ ${notionalPreview}</p>}
            </div>
          )}

          <p className="text-[11px] text-[var(--text-tertiary)] mb-4 px-1 font-mono">
            Cash: <span className="text-[var(--text-secondary)]">${cash.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </p>

          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || (mode === "notional" ? !notional || parseFloat(notional) <= 0 : !qty || parseFloat(qty) <= 0)}
            className={cn(
              "w-full py-3 rounded-xl text-sm font-bold transition-all cursor-pointer",
              side === "buy"
                ? "bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40"
                : "bg-red-600 hover:bg-red-500 text-white disabled:opacity-40",
              mutation.isPending && "opacity-60 cursor-wait"
            )}
          >
            {mutation.isPending ? "Placing…" : `Place ${side.toUpperCase()} Order`}
          </button>
        </div>

        {/* My Position */}
        {position && (
          <div className="px-5 pb-6 border-t border-[var(--border-subtle)] pt-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-3">
              My Position {isShort && <span className="ml-1.5 text-orange-400 bg-orange-900/30 px-1.5 py-0.5 rounded">SHORT</span>}
            </div>
            <div className="bg-[var(--bg-elevated-2)] rounded-xl px-4 py-3 space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-[var(--text-secondary)] font-mono">{Math.abs(position.qty).toFixed(position.qty < 1 ? 6 : 4)} {coin.symbol}</span>
                <span className="font-bold font-mono text-[var(--text-primary)]">{fmtLarge(position.market_value)}</span>
              </div>
              <div className="flex justify-between text-xs font-mono">
                <span className="text-[var(--text-tertiary)]">Avg cost <span className="text-[var(--text-secondary)]">{fmtPrice(position.avg_cost)}</span></span>
                <span className={cn("font-semibold", pctColor(position.unrealized_pnl))}>
                  {position.unrealized_pnl >= 0 ? "+" : ""}{position.unrealized_pnl.toFixed(2)} ({fmtPct(position.unrealized_pnl_pct)})
                </span>
              </div>
              {/* P&L bar */}
              <div className="h-1.5 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all", position.unrealized_pnl >= 0 ? "bg-emerald-500" : "bg-red-500")}
                  style={{ width: `${Math.min(Math.abs(position.unrealized_pnl_pct) * 3, 100)}%` }}
                />
              </div>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => { setSide("sell"); }}
                  className="flex-1 py-1.5 rounded-lg text-[11px] font-semibold bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors cursor-pointer"
                >
                  {isShort ? "Cover Short" : "Sell / Close"}
                </button>
                <button
                  onClick={() => { setSide("buy"); }}
                  className="flex-1 py-1.5 rounded-lg text-[11px] font-semibold bg-emerald-900/20 text-emerald-400 hover:bg-emerald-900/40 transition-colors cursor-pointer"
                >
                  Add More
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ── Quiz definitions ──────────────────────────────────────────────────────────

const QUIZ_CONTENT: Record<string, {
  title: string;
  subtitle: string;
  questions: Array<{
    q: string;
    options: string[];
    correct: number;
  }>;
}> = {
  funding_rate_contrarian: {
    title: "Funding Rate Contrarian — Comprehension Check",
    subtitle: "This strategy uses perpetual futures funding mechanics. Confirm you understand before enabling.",
    questions: [
      {
        q: "When perpetual funding is deeply negative, who pays who?",
        options: ["Longs pay shorts", "Shorts pay longs", "No payments — it's synthetic"],
        correct: 1,
      },
      {
        q: "This strategy takes a position in which direction?",
        options: ["Short (ride the momentum down)", "Long (contrarian — bet shorts will cover)", "Neutral / market-neutral"],
        correct: 1,
      },
      {
        q: "What is the primary risk of this strategy?",
        options: [
          "The exchange getting hacked",
          "Funding can stay extreme negative far longer than expected",
          "Low volatility means no moves",
        ],
        correct: 1,
      },
    ],
  },
  basis_carry: {
    title: "Cash & Carry Basis — Comprehension Check",
    subtitle: "This strategy earns funding yield. Confirm you understand the mechanics and risks.",
    questions: [
      {
        q: "Positive perpetual funding rate means:",
        options: [
          "Longs pay shorts to hold their long position",
          "Shorts pay longs — you earn yield by being long spot",
          "The exchange is charging extra fees",
        ],
        correct: 0,
      },
      {
        q: "When should you exit the basis carry trade?",
        options: [
          "When spot price drops 10% from entry",
          "When funding rate falls near zero or turns negative",
          "After exactly 30 days regardless of conditions",
        ],
        correct: 1,
      },
      {
        q: "The main risk of this strategy is:",
        options: [
          "Spot price rising faster than expected",
          "Funding flipping negative — your 'yield' becomes a cost",
          "Low trading volume on the exchange",
        ],
        correct: 1,
      },
    ],
  },
};

function QuizModal({
  strategyKey,
  strategyName,
  onPass,
  onClose,
}: {
  strategyKey: string;
  strategyName: string;
  onPass: () => void;
  onClose: () => void;
}) {
  const content = QUIZ_CONTENT[strategyKey];
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);
  const [allCorrect, setAllCorrect] = useState(false);

  if (!content) return null;

  const totalQ = content.questions.length;
  const answered = Object.keys(answers).length;

  function handleSubmit() {
    const correct = content.questions.every((q, i) => answers[i] === q.correct);
    setSubmitted(true);
    setAllCorrect(correct);
    if (correct) {
      setTimeout(onPass, 1200);
    }
  }

  function handleRetry() {
    setAnswers({});
    setSubmitted(false);
    setAllCorrect(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[var(--bg-card)] border border-[var(--border-subtle)] rounded-2xl w-full max-w-lg shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-[var(--border-subtle)]">
          <div>
            <div className="text-xs font-semibold text-[var(--accent-blue)] uppercase tracking-widest mb-1">
              Strategy Gate
            </div>
            <h2 className="text-base font-bold text-[var(--text-primary)]">{content.title}</h2>
            <p className="text-xs text-[var(--text-tertiary)] mt-1">{content.subtitle}</p>
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] ml-4 mt-0.5">
            <X size={18} />
          </button>
        </div>

        {/* Questions */}
        <div className="p-6 space-y-5">
          {content.questions.map((q, qi) => {
            const chosen = answers[qi];
            const isCorrect = q.correct === chosen;
            return (
              <div key={qi}>
                <p className="text-sm font-medium text-[var(--text-primary)] mb-2">
                  {qi + 1}. {q.q}
                </p>
                <div className="space-y-1.5">
                  {q.options.map((opt, oi) => {
                    let cls =
                      "w-full text-left px-3 py-2 rounded-lg border text-xs transition-all ";
                    if (!submitted) {
                      cls +=
                        chosen === oi
                          ? "border-[var(--accent-blue)] bg-[var(--accent-blue)]/10 text-[var(--text-primary)]"
                          : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--accent-blue)]/50";
                    } else {
                      if (oi === q.correct) {
                        cls += "border-[var(--accent-positive)] bg-[var(--accent-positive)]/10 text-[var(--accent-positive)]";
                      } else if (chosen === oi && oi !== q.correct) {
                        cls += "border-[var(--accent-negative)] bg-[var(--accent-negative)]/10 text-[var(--accent-negative)]";
                      } else {
                        cls += "border-[var(--border-subtle)] text-[var(--text-tertiary)] opacity-50";
                      }
                    }
                    return (
                      <button
                        key={oi}
                        className={cls}
                        disabled={submitted}
                        onClick={() => !submitted && setAnswers((a) => ({ ...a, [qi]: oi }))}
                      >
                        {opt}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-6 pb-6">
          {submitted ? (
            allCorrect ? (
              <div className="flex items-center gap-2 text-[var(--accent-positive)] text-sm font-semibold">
                <span>✓</span> All correct — enabling strategy…
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <span className="text-[var(--accent-negative)] text-sm">Some answers were incorrect. Review and retry.</span>
                <button
                  onClick={handleRetry}
                  className="px-4 py-1.5 rounded-lg bg-[var(--bg-hover)] text-[var(--text-primary)] text-xs font-medium hover:bg-[var(--border-subtle)] transition-colors"
                >
                  Retry
                </button>
              </div>
            )
          ) : (
            <button
              onClick={handleSubmit}
              disabled={answered < totalQ}
              className={cn(
                "w-full py-2.5 rounded-lg text-sm font-semibold transition-all",
                answered >= totalQ
                  ? "bg-[var(--accent-blue)] text-white hover:opacity-90"
                  : "bg-[var(--bg-hover)] text-[var(--text-tertiary)] cursor-not-allowed"
              )}
            >
              Submit Answers ({answered}/{totalQ})
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Strategy Apply Modal ───────────────────────────────────────────────────────

function StrategyApplyModal({
  def, coins, onClose,
}: {
  def: StrategyDefinition;
  coins: CoinGeckoData[];
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");

  // Default: first coin from the strategy's default_universe
  const defaultSymbol = useMemo(() => {
    const first = def.default_universe?.[0];
    if (!first) return null;
    const ticker = first.split("/")[0]; // "BTC/USDT" → "BTC"
    return `${ticker}-USD`;
  }, [def]);

  const [selected, setSelected] = useState<string | null>(defaultSymbol);

  // Coins from universe first, then market coins filtered by search
  const universeSymbols = useMemo(() =>
    new Set((def.default_universe ?? []).map((u) => u.split("/")[0])),
    [def.default_universe]
  );

  const filteredCoins = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) {
      // Show universe coins + first few market coins
      const univ = coins.filter((c) => universeSymbols.has(c.symbol));
      const others = coins.filter((c) => !universeSymbols.has(c.symbol)).slice(0, 8);
      return [...univ, ...others];
    }
    return coins.filter((c) =>
      c.symbol.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)
    ).slice(0, 20);
  }, [coins, search, universeSymbols]);

  const handleView = () => {
    if (!selected) return;
    navigate(`/chart?symbol=${selected}&preset=${def.strategy_key}`);
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl shadow-2xl overflow-hidden">
        {/* Gradient bar */}
        <div className="h-1 w-full" style={{ background: `linear-gradient(90deg, ${def.category_accent_from}, ${def.category_accent_to})` }} />

        <div className="p-5">
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] mb-0.5">{def.category}</div>
              <div className="text-base font-bold text-[var(--text-primary)]">{def.name}</div>
            </div>
            <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer p-1">
              <X size={16} />
            </button>
          </div>

          <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed mb-4 line-clamp-2">{def.description}</p>

          {/* Coin search */}
          <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-2">Select Coin</div>
          <div className="relative mb-3">
            <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search coins…"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg pl-8 pr-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-none focus:border-[var(--border-emphasis)]"
            />
          </div>

          {/* Coin grid */}
          <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto mb-4">
            {filteredCoins.map((c) => {
              const sym = `${c.symbol.toUpperCase()}-USD`;
              const inUniverse = universeSymbols.has(c.symbol);
              return (
                <button
                  key={c.id}
                  onClick={() => setSelected(sym)}
                  className={cn(
                    "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-all cursor-pointer",
                    selected === sym
                      ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive-bg)]"
                      : inUniverse
                        ? "border-[var(--border-emphasis)] text-[var(--text-primary)] bg-[var(--bg-elevated-2)] hover:border-[var(--accent-positive)]"
                        : "border-[var(--border-subtle)] text-[var(--text-secondary)] bg-[var(--bg-elevated-2)] hover:border-[var(--border-emphasis)]"
                  )}
                >
                  {c.image && <img src={c.image} alt="" className="w-4 h-4 rounded-full flex-shrink-0" />}
                  {c.symbol}
                  {inUniverse && <span className="text-[8px] opacity-60 ml-0.5">★</span>}
                </button>
              );
            })}
          </div>

          {/* Action */}
          <button
            onClick={handleView}
            disabled={!selected}
            className="w-full py-2.5 rounded-xl text-sm font-bold bg-[var(--accent-positive)] text-black hover:opacity-90 disabled:opacity-40 transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            View Chart with Strategy
            <ExternalLink size={13} />
          </button>
          {selected && (
            <p className="text-center text-[10px] text-[var(--text-tertiary)] mt-2 font-mono">
              {selected} with {def.name} indicators
            </p>
          )}
        </div>
      </div>
    </>
  );
}

// ── Sortable Column Header ─────────────────────────────────────────────────────

type SortKey = "market_cap_rank" | "current_price" | "pct_1h" | "pct_24h" | "pct_7d" | "market_cap" | "total_volume";

function SortableTH({
  col, label, sort, onSort, className = "",
}: {
  col: SortKey;
  label: string;
  sort: { key: SortKey; dir: "asc" | "desc" };
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  const active = sort.key === col;
  return (
    <th
      onClick={() => onSort(col)}
      className={cn(
        "px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-widest cursor-pointer select-none whitespace-nowrap",
        active ? "text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
        className
      )}
    >
      <span className="inline-flex items-center gap-1 justify-end">
        {label}
        {active
          ? sort.dir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />
          : <ChevronsUpDown size={10} className="opacity-30" />}
      </span>
    </th>
  );
}

// ── Coin Table ─────────────────────────────────────────────────────────────────

function CoinTable({
  coins,
  watchlist,
  onToggleWatch,
  onTrade,
  onChart,
  showSparklineUrl = false,
}: {
  coins: CoinGeckoData[];
  watchlist: Set<string>;
  onToggleWatch: (id: string) => void;
  onTrade: (coin: CoinGeckoData) => void;
  onChart: (coin: CoinGeckoData) => void;
  showSparklineUrl?: boolean;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "market_cap_rank",
    dir: "asc",
  });
  const [search, setSearch] = useState("");

  const handleSort = useCallback((key: SortKey) => {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "market_cap_rank" ? "asc" : "desc" }
    );
  }, []);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return coins;
    return coins.filter((c) =>
      c.symbol.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)
    );
  }, [coins, search]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sort.key] ?? (sort.dir === "asc" ? Infinity : -Infinity);
      const bv = b[sort.key] ?? (sort.dir === "asc" ? Infinity : -Infinity);
      return sort.dir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [filtered, sort]);

  return (
    <div>
      {/* Search bar */}
      <div className="px-4 pt-3 pb-2 border-b border-[var(--border-subtle)]">
        <div className="relative max-w-xs">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search coins…"
            className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg pl-8 pr-8 py-1.5 text-xs text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-none focus:border-[var(--border-emphasis)]"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer">
              <X size={11} />
            </button>
          )}
        </div>
        {search && (
          <div className="text-[10px] text-[var(--text-tertiary)] mt-1.5 pl-1">
            {sorted.length} result{sorted.length !== 1 ? "s" : ""}
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]">
              <th className="px-3 py-2.5 w-8" />
              <SortableTH col="market_cap_rank" label="#" sort={sort} onSort={handleSort} className="text-left w-12" />
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Coin</th>
              <SortableTH col="current_price" label="Price" sort={sort} onSort={handleSort} />
              <SortableTH col="pct_1h" label="1h %" sort={sort} onSort={handleSort} />
              <SortableTH col="pct_24h" label="24h %" sort={sort} onSort={handleSort} />
              <SortableTH col="pct_7d" label="7d %" sort={sort} onSort={handleSort} />
              <SortableTH col="market_cap" label="Mkt Cap" sort={sort} onSort={handleSort} className="hidden md:table-cell" />
              <SortableTH col="total_volume" label="Volume 24h" sort={sort} onSort={handleSort} className="hidden lg:table-cell" />
              <th className="px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] hidden sm:table-cell">7d</th>
              <th className="px-3 py-2.5 w-20" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((coin) => (
              <tr
                key={coin.id}
                className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated-2)] transition-colors cursor-pointer group"
                onClick={() => onTrade(coin)}
              >
                {/* Star */}
                <td className="px-3 py-2.5" onClick={(e) => { e.stopPropagation(); onToggleWatch(coin.id); }}>
                  <Star
                    size={13}
                    className={cn("cursor-pointer transition-colors", watchlist.has(coin.id) ? "fill-yellow-400 text-yellow-400" : "text-[var(--text-tertiary)] hover:text-yellow-400")}
                  />
                </td>
                {/* Rank */}
                <td className="px-3 py-2.5 text-left text-[var(--text-tertiary)] text-xs font-mono">{coin.market_cap_rank}</td>
                {/* Name */}
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2.5">
                    {coin.image && <img src={coin.image} alt={coin.symbol} className="w-7 h-7 rounded-full flex-shrink-0" />}
                    <div className="min-w-0">
                      <div className="font-semibold text-[var(--text-primary)] text-sm leading-tight truncate max-w-[120px]">{coin.name}</div>
                      <div className="text-[10px] font-mono text-[var(--text-tertiary)]">{coin.symbol}</div>
                    </div>
                  </div>
                </td>
                {/* Price */}
                <td className="px-3 py-2.5 text-right font-mono font-semibold text-[var(--text-primary)] text-sm">{fmtPrice(coin.current_price)}</td>
                {/* 1h % */}
                <td className={cn("px-3 py-2.5 text-right text-xs font-mono font-semibold", pctColor(coin.pct_1h))}>{fmtPct(coin.pct_1h)}</td>
                {/* 24h % */}
                <td className={cn("px-3 py-2.5 text-right text-xs font-mono font-semibold", pctColor(coin.pct_24h))}>{fmtPct(coin.pct_24h)}</td>
                {/* 7d % */}
                <td className={cn("px-3 py-2.5 text-right text-xs font-mono font-semibold", pctColor(coin.pct_7d))}>{fmtPct(coin.pct_7d)}</td>
                {/* Market cap */}
                <td className="px-3 py-2.5 text-right text-[var(--text-secondary)] text-xs font-mono hidden md:table-cell">{fmtLarge(coin.market_cap)}</td>
                {/* Volume */}
                <td className="px-3 py-2.5 text-right text-[var(--text-tertiary)] text-xs font-mono hidden lg:table-cell">{fmtLarge(coin.total_volume)}</td>
                {/* Sparkline */}
                <td className="px-3 py-2.5 hidden sm:table-cell">
                  {showSparklineUrl && coin.sparkline_url
                    ? <img src={coin.sparkline_url} alt="7d" className="w-[72px] h-6 object-contain" />
                    : <SparkLine prices={coin.sparkline} />}
                </td>
                {/* Trade button */}
                <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => onTrade(coin)}
                    className="text-[10px] px-3 py-1.5 rounded-lg bg-[var(--accent-positive)] text-black font-bold hover:opacity-90 transition-opacity cursor-pointer whitespace-nowrap opacity-0 group-hover:opacity-100"
                  >
                    Trade
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length === 0 && (
          <div className="py-12 text-center text-[var(--text-tertiary)] text-sm">
            No coins match "{search}"
          </div>
        )}
      </div>
    </div>
  );
}

// ── My Holdings Tab ────────────────────────────────────────────────────────────

function MyHoldingsTab({
  coins,
  onTrade,
}: {
  coins: CoinGeckoData[];
  onTrade: (coin: CoinGeckoData) => void;
}) {
  const qc = useQueryClient();
  const { data: account, isLoading } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
  });

  const cryptoPositions = (account?.positions ?? []).filter((p) => p.symbol.includes("-USD"));
  const totalValue   = cryptoPositions.reduce((s, p) => s + p.market_value, 0);
  const totalPnl     = cryptoPositions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const dayPnl       = cryptoPositions.reduce((s, p) => s + p.day_pnl, 0);
  const totalCost    = cryptoPositions.reduce((s, p) => s + Math.abs(p.cost_basis), 0);
  const totalPnlPct  = totalCost > 0 ? totalPnl / totalCost * 100 : 0;

  const findCoin = (sym: string) => coins.find((c) => `${c.symbol.toUpperCase()}-USD` === sym);

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => <div key={i} className="h-20 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />)}
      </div>
    );
  }

  if (!cryptoPositions.length) {
    return (
      <div className="py-16 text-center space-y-3">
        <div className="text-4xl">₿</div>
        <div className="text-[var(--text-primary)] font-semibold">No crypto holdings yet</div>
        <p className="text-[var(--text-tertiary)] text-sm">Trade from the Top 100 or Trending tab to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Portfolio summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: "Portfolio Value",  val: fmtLarge(totalValue),      color: "" },
          { label: "Unrealized P&L",   val: `${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}`, color: pctColor(totalPnl) },
          { label: "P&L %",            val: fmtPct(totalPnlPct),       color: pctColor(totalPnlPct) },
          { label: "Day P&L",          val: `${dayPnl >= 0 ? "+" : ""}${dayPnl.toFixed(2)}`,     color: pctColor(dayPnl) },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--bg-elevated-2)] rounded-xl px-3 py-2.5 text-center">
            <div className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{s.label}</div>
            <div className={cn("text-sm font-bold font-mono text-[var(--text-primary)]", s.color)}>{s.val}</div>
          </div>
        ))}
      </div>

      {/* Position count */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          {cryptoPositions.length} position{cryptoPositions.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ["paper-account"] })}
          className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] flex items-center gap-1 cursor-pointer"
        >
          <RotateCw size={11} /> Refresh
        </button>
      </div>

      {/* Position cards */}
      {[...cryptoPositions].sort((a, b) => b.unrealized_pnl - a.unrealized_pnl).map((p) => {
        const coin = findCoin(p.symbol);
        const isShort = p.qty < 0;
        const pnlPct = p.unrealized_pnl_pct;
        const barWidth = Math.min(Math.abs(pnlPct) * 2.5, 100);
        return (
          <div
            key={p.id}
            className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 hover:border-[var(--border-emphasis)] transition-all cursor-pointer"
            onClick={() => coin && onTrade(coin)}
          >
            <div className="flex items-center gap-3">
              {coin?.image
                ? <img src={coin.image} alt={p.symbol} className="w-9 h-9 rounded-full flex-shrink-0" />
                : <div className="w-9 h-9 rounded-full bg-[var(--bg-elevated-2)] flex items-center justify-center text-xs font-bold text-[var(--text-tertiary)]">{p.symbol.replace("-USD", "").slice(0, 2)}</div>}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="font-bold text-[var(--text-primary)] text-sm font-mono">{p.symbol.replace("-USD", "")}</span>
                  {isShort && <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-orange-900/30 text-orange-400 border border-orange-800/40">SHORT</span>}
                </div>
                <div className="text-[11px] text-[var(--text-tertiary)] font-mono">
                  {Math.abs(p.qty).toFixed(p.qty < 1 ? 6 : 4)} coins · avg {fmtPrice(p.avg_cost)}
                </div>
                {/* P&L bar */}
                <div className="mt-1.5 h-1 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                  <div
                    className={cn("h-full rounded-full transition-all", pnlPct >= 0 ? "bg-emerald-500" : "bg-red-500")}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
              <div className="text-right flex-shrink-0 ml-2">
                <div className="text-sm font-bold font-mono text-[var(--text-primary)]">{fmtLarge(p.market_value)}</div>
                <div className={cn("text-xs font-mono font-semibold", pctColor(pnlPct))}>
                  {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                </div>
                <div className={cn("text-[10px] font-mono", pctColor(p.unrealized_pnl))}>
                  {p.unrealized_pnl >= 0 ? "+" : ""}{p.unrealized_pnl.toFixed(2)}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Crypto Strategy Panel ──────────────────────────────────────────────────────

const EXIT_BADGE: Record<string, { label: string; cls: string }> = {
  stop_loss:     { label: "Stop",   cls: "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]" },
  profit_target: { label: "Target", cls: "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]" },
  time_stop:     { label: "Time",   cls: "bg-blue-900/30 text-blue-400" },
  expired:       { label: "Exp",    cls: "bg-zinc-800 text-zinc-400" },
};

function CryptoStrategyPanel() {
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [stratTab, setStratTab] = useState<"open" | "watch" | "closed">("open");

  const { data: tradesData } = useQuery({
    queryKey: ["crypto-strategy-trades"],
    queryFn: getCryptoStrategyTrades,
    staleTime: Infinity,
  });
  const { data: candidatesData } = useQuery({
    queryKey: ["crypto-strategy-candidates"],
    queryFn: getCryptoStrategyCandidates,
    staleTime: Infinity,
  });
  const { data: summaryData } = useQuery({
    queryKey: ["crypto-strategy-summary"],
    queryFn: getCryptoStrategySummary,
    staleTime: Infinity,
  });

  const open      = (tradesData?.trades ?? []).filter((t) => t.status === "open");
  const closed    = (tradesData?.trades ?? []).filter((t) => t.status === "closed");
  const candidates = candidatesData?.candidates ?? [];
  const summary   = summaryData?.overall;

  const handleRunNow = async () => {
    setRunning(true);
    setRunStatus(null);
    try {
      await runCryptoStrategyNow();
      setRunStatus({ ok: true, msg: "Scan started — data refreshes in ~2 min" });
      toast.success("Crypto scan started — results update in ~2 minutes", { duration: 8000 });
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["crypto-strategy-trades"] });
        qc.invalidateQueries({ queryKey: ["crypto-strategy-candidates"] });
        qc.invalidateQueries({ queryKey: ["crypto-strategy-summary"] });
        setRunStatus(null);
      }, 120_000);
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? e?.message ?? "Unknown error";
      setRunStatus({ ok: false, msg: `Scan failed: ${detail}` });
      toast.error(`Failed to start scan: ${detail}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Open",     value: summary.open_positions.toString() },
            { label: "Watching", value: summary.candidates.toString() },
            { label: "Win Rate", value: summary.total_closed > 0 ? `${summary.win_rate}%` : "—" },
            { label: "Total P&L", value: fmt$(summary.total_pnl), color: summary.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]" },
          ].map((s) => (
            <div key={s.label} className="bg-[var(--bg-elevated-2)] rounded-xl p-3 text-center">
              <div className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{s.label}</div>
              <div className={cn("text-lg font-bold font-mono text-[var(--text-primary)]", s.color)}>{s.value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl">
          {([["open", `Open (${open.length})`], ["watch", `Watching (${candidates.length})`], ["closed", `Closed (${closed.length})`]] as [typeof stratTab, string][]).map(([id, label]) => (
            <button key={id} onClick={() => setStratTab(id)} className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap cursor-pointer",
              stratTab === id ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            )}>{label}</button>
          ))}
        </div>
        <button
          onClick={handleRunNow}
          disabled={running}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-[var(--accent-positive)] text-black font-semibold hover:opacity-90 disabled:opacity-50 transition-all cursor-pointer"
        >
          <RotateCw size={11} className={running ? "animate-spin" : ""} />
          {running ? "Screening…" : "Run Now"}
        </button>
      </div>

      {runStatus && (
        <div className={cn(
          "text-xs px-4 py-2.5 rounded-xl font-medium",
          runStatus.ok
            ? "bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] border border-[var(--accent-positive)]/20"
            : "bg-[var(--accent-negative)]/10 text-[var(--accent-negative)] border border-[var(--accent-negative)]/20"
        )}>
          {runStatus.msg}
        </div>
      )}

      {stratTab === "open" && (
        <div className="space-y-2">
          {open.length === 0 ? (
            <p className="text-center text-[var(--text-tertiary)] text-sm py-8">No open crypto positions yet</p>
          ) : open.map((t) => {
            const pct = t.pnl_pct ?? 0;
            return (
              <div key={t.id} className="bg-[var(--bg-elevated-2)] rounded-xl px-4 py-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="font-bold text-[var(--text-primary)] text-sm font-mono">{t.symbol.replace("/USDT", "")}</span>
                    <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated)] px-1.5 py-0.5 rounded">{t.preset_label}</span>
                    <span className="text-[10px] text-[var(--text-tertiary)]">{t.days_held}d</span>
                  </div>
                  <div className="text-[10px] font-mono text-[var(--text-tertiary)]">
                    Entry {fmtPrice(t.entry_price)} · Stop {fmtPrice(t.stop_price)} · Target {fmtPrice(t.target_price)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-mono text-[var(--text-primary)]">{fmtPrice(t.current_price)}</div>
                  <div className={cn("text-xs font-mono font-semibold", pctColor(pct))}>{fmtPct(pct)}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {stratTab === "watch" && (
        <div className="space-y-2">
          {candidates.length === 0 ? (
            <p className="text-center text-[var(--text-tertiary)] text-sm py-8">No coins being watched right now</p>
          ) : candidates.map((t) => (
            <div key={t.id} className="bg-[var(--bg-elevated-2)] rounded-xl px-4 py-3 flex items-center gap-3">
              <div className="flex-1">
                <span className="font-bold text-[var(--text-primary)] text-sm font-mono mr-2">{t.symbol.replace("/USDT", "")}</span>
                <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated)] px-1.5 py-0.5 rounded">{t.preset_label}</span>
              </div>
              <span className="text-xs text-blue-400 font-mono">{t.days_held}d watching</span>
            </div>
          ))}
        </div>
      )}

      {stratTab === "closed" && (
        <div className="space-y-2">
          {closed.length === 0 ? (
            <p className="text-center text-[var(--text-tertiary)] text-sm py-8">No closed crypto trades yet</p>
          ) : closed.slice(0, 25).map((t) => {
            const badge = EXIT_BADGE[t.exit_reason ?? ""] ?? { label: "Manual", cls: "bg-zinc-800 text-zinc-400" };
            return (
              <div key={t.id} className="bg-[var(--bg-elevated-2)] rounded-xl px-4 py-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-[var(--text-primary)] text-sm font-mono">{t.symbol.replace("/USDT", "")}</span>
                    <span className={cn("text-[9px] font-semibold px-1.5 py-0.5 rounded", badge.cls)}>{badge.label}</span>
                    <span className="text-[10px] text-[var(--text-tertiary)]">{t.preset_label}</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className={cn("text-sm font-mono font-semibold", pctColor(t.pnl_pct))}>{fmtPct(t.pnl_pct)}</div>
                  <div className={cn("text-xs font-mono", pctColor(t.pnl))}>{fmt$(t.pnl)}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Strategy Library Card Grid ─────────────────────────────────────────────────

const TIER_BADGE: Record<string, { label: string; cls: string }> = {
  free: { label: "Free",  cls: "bg-emerald-900/40 text-emerald-400 border-emerald-800/60" },
  plus: { label: "Plus",  cls: "bg-violet-900/40 text-violet-300 border-violet-700/60" },
  pro:  { label: "Pro",   cls: "bg-amber-900/40 text-amber-300 border-amber-700/60" },
};

const SOURCE_BADGE: Record<string, string> = {
  coingecko:       "CoinGecko",
  coinmetrics:     "CoinMetrics",
  binance_futures: "Binance",
  glassnode:       "Glassnode",
  cryptoquant:     "CryptoQuant",
  coinglass:       "Coinglass",
  arkham:          "Arkham",
};

function StrategyCard({
  def, byPreset, onApply, onToggle, quizPassed,
}: {
  def: StrategyDefinition;
  byPreset: Record<string, { wins: number; losses: number; total_pnl: number; trades: number }>;
  onApply: (def: StrategyDefinition) => void;
  onToggle: (def: StrategyDefinition) => void;
  quizPassed: boolean;
}) {
  const tier = TIER_BADGE[def.tier_required] ?? TIER_BADGE.free;
  const stats = byPreset[def.strategy_key];
  const winRate = stats && stats.trades > 0
    ? Math.round(stats.wins / stats.trades * 100) : null;

  return (
    <div
      onClick={() => def.is_active && onApply(def)}
      className={cn(
        "relative flex flex-col bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden transition-all duration-200",
        def.is_active
          ? "hover:border-[var(--border-emphasis)] hover:shadow-lg cursor-pointer hover:translate-y-[-1px]"
          : "opacity-60"
      )}
    >
        {/* Kill switch toggle */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(def); }}
          title={def.is_active ? "Pause strategy" : "Enable strategy"}
          className={cn(
            "absolute top-3 right-3 w-9 h-5 rounded-full transition-all flex items-center",
            def.is_active
              ? "bg-[var(--accent-positive)]/20 border border-[var(--accent-positive)]/40"
              : "bg-[var(--bg-hover)] border border-[var(--border-subtle)]"
          )}
        >
          <span
            className={cn(
              "w-3.5 h-3.5 rounded-full transition-all mx-0.5",
              def.is_active ? "bg-[var(--accent-positive)] translate-x-4" : "bg-[var(--text-tertiary)] translate-x-0"
            )}
          />
        </button>
      <div
        className="h-1 w-full flex-shrink-0"
        style={{ background: `linear-gradient(90deg, ${def.category_accent_from}, ${def.category_accent_to})` }}
      />

      <div className="flex flex-col gap-3 p-4 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="font-bold text-[var(--text-primary)] text-sm leading-tight">{def.name}</div>
            <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5 font-medium">{def.category}</div>
          </div>
          <div className="flex flex-col items-end gap-1 flex-shrink-0">
            <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider", tier.cls)}>
              {tier.label}
            </span>
            {def.comprehension_quiz_required && (
              <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded border border-orange-700/60 bg-orange-900/30 text-orange-400 uppercase tracking-wider whitespace-nowrap">
                Quiz
              </span>
            )}
          </div>
        </div>

        <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed line-clamp-3 flex-1">{def.description}</p>

        <div className="flex flex-wrap gap-1">
          {def.required_data_sources.map((src) => (
            <span key={src} className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] font-mono border border-[var(--border-subtle)]">
              {SOURCE_BADGE[src] ?? src}
            </span>
          ))}
          {def.structure_type !== "simple" && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-amber-400 font-mono border border-amber-800/50 capitalize">
              {def.structure_type}
            </span>
          )}
        </div>

        <div className="border-t border-[var(--border-subtle)] pt-2.5 mt-auto">
          {def.is_active && stats ? (
            <div className="flex gap-4 text-[10px] font-mono">
              <span><span className="text-[var(--text-tertiary)]">Trades </span><span className="text-[var(--text-primary)] font-semibold">{stats.trades}</span></span>
              {winRate !== null && (
                <span><span className="text-[var(--text-tertiary)]">Win </span><span className="font-semibold" style={{ color: winRate >= 50 ? "var(--accent-positive)" : "var(--accent-negative)" }}>{winRate}%</span></span>
              )}
              <span className={cn("font-semibold", stats.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                {stats.total_pnl >= 0 ? "+" : ""}{fmt$(stats.total_pnl)}
              </span>
            </div>
          ) : def.is_active ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-[10px] text-emerald-400 font-semibold">Active · No trades yet</span>
              </div>
              <span className="text-[9px] text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100">Click to apply →</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-tertiary)]" />
              <span className="text-[10px] text-[var(--text-tertiary)]">Coming Soon</span>
            </div>
          )}
        </div>
      </div>

      {/* Hover overlay for active cards */}
      {def.is_active && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/10 transition-all pointer-events-none rounded-2xl">
          <div className="opacity-0 group-hover:opacity-100 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-lg px-3 py-1.5 text-xs font-semibold text-[var(--text-primary)] shadow-lg">
            Apply to coin →
          </div>
        </div>
      )}
    </div>
  );
}

const CATEGORY_ORDER = [
  "Trend Following", "Mean Reversion", "Momentum", "Cycle",
  "Market Structure", "On-Chain", "Derivatives", "Whale Activity",
];

function StrategyCardGrid({
  onApply,
  onToggle,
  quizPassedKeys,
}: {
  onApply: (def: StrategyDefinition) => void;
  onToggle: (def: StrategyDefinition) => void;
  quizPassedKeys: Set<string>;
}) {
  const { data: defsData, isLoading } = useQuery({
    queryKey: ["crypto-strategy-definitions"],
    queryFn: getCryptoStrategyDefinitions,
    staleTime: Infinity,
  });
  const { data: summaryData } = useQuery({
    queryKey: ["crypto-strategy-summary"],
    queryFn: getCryptoStrategySummary,
    staleTime: Infinity,
  });

  const byPreset = useMemo(() => {
    const map: Record<string, { wins: number; losses: number; total_pnl: number; trades: number }> = {};
    for (const s of summaryData?.by_preset ?? []) {
      map[s.preset_key] = { wins: s.wins, losses: s.losses, total_pnl: s.total_pnl, trades: s.trades };
    }
    return map;
  }, [summaryData]);

  const grouped = useMemo(() => {
    const defs = defsData?.definitions ?? [];
    const groups: Record<string, StrategyDefinition[]> = {};
    for (const d of defs) {
      (groups[d.category] ??= []).push(d);
    }
    return CATEGORY_ORDER
      .filter((cat) => groups[cat]?.length)
      .map((cat) => ({ category: cat, defs: groups[cat] }));
  }, [defsData]);

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-52 bg-[var(--bg-elevated-2)] rounded-2xl animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <p className="text-xs text-[var(--text-tertiary)]">Click any active strategy to apply it to a coin and view the chart with indicators.</p>
      {grouped.map(({ category, defs }) => (
        <div key={category}>
          <div className="flex items-center gap-2 mb-3">
            <h3 className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">{category}</h3>
            <div className="flex-1 h-px bg-[var(--border-subtle)]" />
            <span className="text-[10px] text-[var(--text-tertiary)] font-mono">{defs.length}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {defs.map((d) => (
              <StrategyCard
                  key={d.strategy_key}
                  def={d}
                  byPreset={byPreset}
                  onApply={onApply}
                  onToggle={onToggle}
                  quizPassed={quizPassedKeys.has(d.strategy_key)}
                />
            ))}
          </div>
        </div>
      ))}
      {grouped.length === 0 && (
        <p className="text-center text-[var(--text-tertiary)] text-sm py-12">Strategy library loading…</p>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

type Tab = "top" | "trending" | "watchlist" | "holdings" | "library" | "strategies";

export default function CryptoLab() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("top");
  const [tradingCoin, setTradingCoin] = useState<CoinGeckoData | null>(null);
  const [applyStrategy, setApplyStrategy] = useState<StrategyDefinition | null>(null);
  const [quizStrategy, setQuizStrategy] = useState<StrategyDefinition | null>(null);
  const [watchlist, setWatchlist] = useState<Set<string>>(loadWatchlist);
  const [lastRefreshed, setLastRefreshed] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const { data: market, isLoading: marketLoading } = useQuery({
    queryKey: ["crypto-market-v2"],
    queryFn: getCryptoMarket,
    staleTime: Infinity,
  });

  const { data: overview } = useQuery({
    queryKey: ["crypto-overview-v1"],
    queryFn: getCryptoOverview,
    staleTime: Infinity,
  });

  const { data: trending, isLoading: trendingLoading } = useQuery({
    queryKey: ["crypto-trending-v1"],
    queryFn: getCryptoTrending,
    staleTime: Infinity,
  });

  const { data: account } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
  });

  const { data: quizStatusData, refetch: refetchQuiz } = useQuery({
    queryKey: ["crypto-quiz-status"],
    queryFn: getCryptoQuizStatus,
    staleTime: Infinity,
  });
  const quizPassedKeys = useMemo(
    () => new Set(quizStatusData?.completed ?? []),
    [quizStatusData]
  );

  const quizMutation = useMutation({
    mutationFn: completeCryptoQuiz,
    onSuccess: () => refetchQuiz(),
  });

  const toggleMutation = useMutation({
    mutationFn: toggleCryptoStrategy,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crypto-definitions"] }),
  });

  const handleToggle = useCallback((def: StrategyDefinition) => {
    if (!def.is_active && def.comprehension_quiz_required && !quizPassedKeys.has(def.strategy_key)) {
      // Show quiz first
      setQuizStrategy(def);
    } else {
      toggleMutation.mutate(def.strategy_key);
    }
  }, [quizPassedKeys, toggleMutation]);

  const coins = market?.coins ?? [];
  const trendingCoins = trending?.coins ?? [];
  const watchlistCoins = useMemo(() => coins.filter((c) => watchlist.has(c.id)), [coins, watchlist]);
  const cash = account?.cash ?? 0;

  // Find the paper position for the currently selected trading coin
  const tradingPosition = useMemo<PaperPosition | null>(() => {
    if (!tradingCoin || !account) return null;
    const sym = `${tradingCoin.symbol.toUpperCase()}-USD`;
    return account.positions.find((p) => p.symbol === sym) ?? null;
  }, [tradingCoin, account]);

  const handleChart = useCallback((coin: CoinGeckoData) => {
    navigate(`/chart?symbol=${coin.symbol.toUpperCase()}-USD`);
  }, [navigate]);

  const toggleWatch = useCallback((id: string) => {
    setWatchlist((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      saveWatchlist(next);
      return next;
    });
  }, []);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refreshCryptoMarket();
      await qc.invalidateQueries({ queryKey: ["crypto-market-v2"] });
      await qc.invalidateQueries({ queryKey: ["crypto-overview-v1"] });
      await qc.invalidateQueries({ queryKey: ["crypto-trending-v1"] });
      setLastRefreshed(Date.now());
    } catch {
      toast.error("Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }, [qc]);

  const refreshLabel = useMemo(() => {
    if (!lastRefreshed) return null;
    const secs = Math.floor((Date.now() - lastRefreshed) / 1000);
    if (secs < 60) return `${secs}s ago`;
    return `${Math.floor(secs / 60)}m ago`;
  }, [lastRefreshed]);

  const TABS: { id: Tab; label: string; count?: number }[] = [
    { id: "top",        label: "Top 100",   count: coins.length },
    { id: "trending",   label: "Trending",  count: trendingCoins.length },
    { id: "watchlist",  label: "Watchlist", count: watchlist.size },
    { id: "holdings",   label: "My Holdings" },
    { id: "library",    label: "Library" },
    { id: "strategies", label: "Strategies" },
  ];

  const isLoading = tab === "top" ? marketLoading : tab === "trending" ? trendingLoading : false;

  return (
    <div className="space-y-5 pb-8">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Crypto Lab</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Market data via CoinGecko · Paper trading 24/7</p>
        </div>
        <div className="flex items-center gap-2">
          {refreshLabel && (
            <span className="text-xs text-[var(--text-tertiary)]">Updated {refreshLabel}</span>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer px-3 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] hover:bg-[#334155] disabled:opacity-50"
          >
            <RotateCw size={12} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Overview bar */}
      <OverviewBar data={overview} />

      {/* Tabs */}
      <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl w-fit overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap cursor-pointer",
              tab === t.id
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-sm"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            )}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className="ml-1.5 text-[9px] font-mono opacity-60">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        {tab === "library" ? (
          <div className="p-5">
            <StrategyCardGrid
              onApply={setApplyStrategy}
              onToggle={handleToggle}
              quizPassedKeys={quizPassedKeys}
            />
          </div>
        ) : tab === "strategies" ? (
          <div className="p-4">
            <CryptoStrategyPanel />
          </div>
        ) : tab === "holdings" ? (
          <div className="p-4">
            <MyHoldingsTab coins={coins} onTrade={setTradingCoin} />
          </div>
        ) : isLoading ? (
          <div className="p-8 space-y-3">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-10 bg-[var(--bg-elevated-2)] rounded-lg animate-pulse" />
            ))}
          </div>
        ) : (
          <CoinTable
            coins={tab === "top" ? coins : tab === "trending" ? trendingCoins : watchlistCoins}
            watchlist={watchlist}
            onToggleWatch={toggleWatch}
            onTrade={setTradingCoin}
            onChart={handleChart}
            showSparklineUrl={tab === "trending"}
          />
        )}
      </div>

      {/* Coin trading panel (slide-over) */}
      {tradingCoin && (
        <CoinTradingPanel
          coin={tradingCoin}
          cash={cash}
          position={tradingPosition}
          onClose={() => setTradingCoin(null)}
          onFilled={() => qc.invalidateQueries({ queryKey: ["paper-account"] })}
        />
      )}

      {/* Strategy apply modal */}
      {applyStrategy && (
        <StrategyApplyModal
          def={applyStrategy}
          coins={coins}
          onClose={() => setApplyStrategy(null)}
        />
      )}

      {/* Quiz modal */}
      {quizStrategy && (
        <QuizModal
          strategyKey={quizStrategy.strategy_key}
          strategyName={quizStrategy.name}
          onPass={() => {
            quizMutation.mutate(quizStrategy.strategy_key, {
              onSuccess: () => {
                toggleMutation.mutate(quizStrategy.strategy_key);
                setQuizStrategy(null);
              },
            });
          }}
          onClose={() => setQuizStrategy(null)}
        />
      )}
    </div>
  );
}
