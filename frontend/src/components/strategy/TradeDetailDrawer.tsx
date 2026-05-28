import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, TrendingUp, TrendingDown } from "lucide-react";
import { fetchBars } from "@/api/bars";
import CandlestickChart from "@/components/chart/CandlestickChart";
import RsiChart from "@/components/chart/RsiChart";
import MacdChart from "@/components/chart/MacdChart";
import { TICKER_NAMES } from "@/data/tickerNames";
import { cn } from "@/lib/utils";
import type { Drawing } from "@/types/chart";

// ─── Strategy → Indicator mapping ────────────────────────────────────────────

interface TradeIndicators {
  overlays: string[];
  subPane: "rsi" | "macd" | null;
}

const TRADE_INDICATORS: Record<string, TradeIndicators> = {
  canslim_leaders:        { overlays: ["EMA_21", "SMA_50", "SMA_200"], subPane: null },
  stage2_breakout:        { overlays: ["EMA_21", "SMA_50", "SMA_200"], subPane: null },
  momentum_surge:         { overlays: ["SMA_20", "SMA_50"],            subPane: null },
  high_rs_momentum:       { overlays: ["SMA_50", "SMA_200"],           subPane: null },
  power_trend:            { overlays: ["EMA_8", "EMA_21", "EMA_55"],   subPane: null },
  turtle_breakout:        { overlays: ["SMA_50", "SMA_200"],           subPane: null },
  momentum_12m:           { overlays: ["SMA_50", "SMA_200"],           subPane: null },
  darvas_box:             { overlays: ["SMA_50"],                      subPane: null },
  mean_reversion_quality: { overlays: ["SMA_50", "SMA_200"],           subPane: "rsi" },
  deep_value_bounce:      { overlays: ["SMA_50", "SMA_200"],           subPane: "rsi" },
  rsi_oversold:           { overlays: ["SMA_50"],                      subPane: "rsi" },
  zscore_reversion:       { overlays: ["SMA_20", "SMA_50"],            subPane: "rsi" },
  volatility_contraction: { overlays: ["EMA_21", "SMA_50"],            subPane: null },
  ema_stack_uptrend:      { overlays: ["EMA_8", "EMA_21", "EMA_55"],   subPane: null },
  consecutive_gains:      { overlays: ["EMA_21", "SMA_50"],            subPane: null },
  golden_cross:           { overlays: ["SMA_50", "SMA_200"],           subPane: null },
  macd_bullish:           { overlays: ["EMA_12", "EMA_26"],            subPane: "macd" },
  volume_surge:           { overlays: ["SMA_20", "SMA_50"],            subPane: null },
  breakout_52w:           { overlays: ["SMA_50", "SMA_200"],           subPane: null },
};

// ─── Playbook descriptions ────────────────────────────────────────────────────

const PLAYBOOK: Record<string, string> = {
  canslim_leaders:        "CAN SLIM methodology: strong earnings growth (25%+ Q/Q), top-tier relative strength, institutional accumulation. Enters on base breakouts from consolidation patterns. Exits via 7-8% stop or at 20-25% profit to lock in gains before the next correction.",
  stage2_breakout:        "Stan Weinstein's Stage 2 uptrend model: stock has broken out above its 30-week moving average on volume, transitioning from a base (Stage 1) to a confirmed uptrend. Stops placed below the breakout pivot. High-probability trend-following setup.",
  momentum_surge:         "Intermediate-term momentum: price in the top decile of 6-month performance with accelerating volume. Trades in the direction of the trend, sizing into strength. Stop placed below recent swing low, targeting a 2× risk move higher.",
  high_rs_momentum:       "Focuses on stocks with the highest Relative Strength vs. the S&P 500 over the past 12 months. These leaders historically outperform during bull runs. Entry on minor pullbacks with a stop below the 50-day MA.",
  power_trend:            "IBD Power Trend: 21-day EMA above 50-day EMA, both rising, with price above all key EMAs. Indicates a stock in confirmed institutional sponsorship. Enters on brief pullbacks to the 21-day EMA.",
  turtle_breakout:        "Richard Dennis's Turtle Trading system adapted for stocks: enters on a new 55-day high with expanding volume. Uses ATR-based position sizing. Stop at 2× ATR below entry, targets 4× ATR above — a pure breakout trend-following strategy.",
  momentum_12m:           "12-month price momentum is one of the most robust market anomalies. Stocks in the top quintile of 12-month returns tend to continue outperforming for another 3–6 months. This strategy rotates into top-momentum names monthly.",
  darvas_box:             "Nicolas Darvas's Box Theory: identifies stocks making new highs while forming tight consolidation 'boxes'. Enters on a breakout above the box's upper boundary with volume confirmation. Natural stop is the bottom of the box.",
  mean_reversion_quality: "High-quality companies (strong fundamentals, above 200-day MA trend) that have pulled back to oversold RSI levels (< 35). These dips are often buy-the-dip opportunities in fundamentally sound businesses still in uptrends.",
  deep_value_bounce:      "Deeply oversold quality stocks: RSI < 32, price significantly below recent highs, but fundamental quality intact. Aims to capture the mean-reversion bounce as institutional buyers step in at support. Short holding period — exits on RSI recovery.",
  rsi_oversold:           "RSI Oversold Bounce: when RSI dips below 30, the stock is statistically stretched to the downside. This strategy bets on a snap-back rally. Tighter stops, shorter hold time. Works best in stocks with clean technical structures.",
  zscore_reversion:       "Statistical mean reversion: trades stocks that have moved more than 2 standard deviations below their 20-day moving average. Assumes price will revert toward the mean. Tight risk tolerance — exits if the anomaly extends rather than reverts.",
  volatility_contraction: "Volatility Contraction Pattern (VCP): stock has gone through 2–4 contractions in price range, with shrinking volume, forming a tight coil. The breakout from this compressed range often leads to explosive moves.",
  ema_stack_uptrend:      "EMA Stack confirmation: 8-day EMA above 21-day above 55-day EMA, all sloping upward. This 'stack' configuration indicates a strong, multi-timeframe uptrend. Enters on pullbacks to the 8-day EMA with a stop below the 21.",
  consecutive_gains:      "Momentum continuation: stocks with 3+ consecutive up days showing persistent institutional buying pressure. The strategy rides the short-term momentum burst with a tight trailing stop set below the recent consolidation low.",
  golden_cross:           "The classic Golden Cross: 50-day SMA crosses above the 200-day SMA, signaling a potential long-term trend change from bearish to bullish. Widely watched by institutions and can trigger significant buying interest.",
  macd_bullish:           "MACD Bullish Crossover: 12-day EMA crosses above the 26-day EMA, with the histogram turning positive. Confirms near-term momentum shift. Most reliable when it occurs while price is above the 200-day MA.",
  volume_surge:           "Unusual volume surge (2–3× average) signals institutional accumulation — funds can't hide their buying. When volume surges alongside a price gain, it implies conviction behind the move. Stop below the surge candle's low.",
  breakout_52w:           "52-Week High Breakout: stocks making new 52-week highs are in the strongest 2% of the market. Contrary to 'buy low, sell high' intuition, new highs often lead to more highs. Requires volume confirmation to filter false breakouts.",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt$(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function pnlColor(n: number | null | undefined) {
  if (n == null) return "text-zinc-400";
  return n >= 0 ? "text-emerald-400" : "text-red-400";
}

// ─── Component ────────────────────────────────────────────────────────────────

export interface EnrichedTrade {
  id: number;
  symbol: string;
  preset_key: string;
  preset_label: string;
  status: string;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  current_price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  shares: number | null;
  days_held: number;
  entry_date: string | null;
  risk_dollars: number | null;
  atr: number | null;
  entry_trigger: string | null;
}

interface Props {
  trade: EnrichedTrade | null;
  onClose: () => void;
}

const NOOP = () => {};

export default function TradeDetailDrawer({ trade, onClose }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const config = trade ? (TRADE_INDICATORS[trade.preset_key] ?? { overlays: ["SMA_50"], subPane: null }) : null;
  const indicatorsParam = config ? [...config.overlays, ...(config.subPane === "rsi" ? ["RSI_14"] : config.subPane === "macd" ? ["MACD"] : [])].join(",") : undefined;

  // Normalize EMA_8/EMA_12/EMA_21/EMA_26/EMA_55 to the keys the backend uses
  // Backend uses EMA_<n> and SMA_<n> so e.g. EMA_21 → EMA_21. We need to make sure the keys match.
  const normalizedParam = indicatorsParam?.replace(/EMA_8\b/g, "EMA_8").replace(/EMA_55\b/g, "EMA_55");

  const { data: barsData, isLoading } = useQuery({
    queryKey: ["trade-detail-bars", trade?.symbol, normalizedParam],
    queryFn: () => fetchBars(trade!.symbol, "1Day", normalizedParam),
    enabled: !!trade,
    staleTime: 60_000,
  });

  const bars = barsData?.bars ?? [];
  const rawIndicators = barsData?.indicators ?? {};

  // Filter to only overlay-type indicators for CandlestickChart
  const overlayIndicators = useMemo(() => {
    const out: Record<string, (number | null)[]> = {};
    Object.entries(rawIndicators).forEach(([k, v]) => {
      if (k.startsWith("SMA_") || k.startsWith("EMA_") || k.startsWith("BB_")) {
        out[k] = v;
      }
    });
    return out;
  }, [rawIndicators]);

  // Price level drawings for entry/stop/target
  const drawings = useMemo<Drawing[]>(() => {
    if (!trade) return [];
    const out: Drawing[] = [];
    if (trade.entry_price) out.push({ id: "entry", type: "hline", price: trade.entry_price, color: "#3b82f6" });
    if (trade.stop_price)  out.push({ id: "stop",  type: "hline", price: trade.stop_price,  color: "#ef4444" });
    if (trade.target_price) out.push({ id: "target", type: "hline", price: trade.target_price, color: "#10b981" });
    return out;
  }, [trade]);

  if (!trade) return null;

  const isOpen = trade.status === "open";
  const rr = trade.entry_price && trade.stop_price && trade.target_price
    ? ((trade.target_price - trade.entry_price) / (trade.entry_price - trade.stop_price))
    : null;

  const stopPct  = trade.entry_price && trade.stop_price   ? ((trade.stop_price - trade.entry_price) / trade.entry_price * 100) : null;
  const tgtPct   = trade.entry_price && trade.target_price ? ((trade.target_price - trade.entry_price) / trade.entry_price * 100) : null;
  const currPct  = trade.entry_price && trade.current_price
    ? ((trade.current_price - trade.entry_price) / trade.entry_price * 100)
    : null;

  // Progress bar: stop=0%, entry=x%, current=y%, target=100%
  const priceRange = trade.target_price && trade.stop_price ? trade.target_price - trade.stop_price : null;
  const entryProgress = priceRange && trade.entry_price && trade.stop_price
    ? ((trade.entry_price - trade.stop_price) / priceRange * 100)
    : null;
  const currProgress = priceRange && trade.current_price && trade.stop_price
    ? Math.max(0, Math.min(100, (trade.current_price - trade.stop_price) / priceRange * 100))
    : null;

  const playbook = PLAYBOOK[trade.preset_key];

  return (
    <>
      {/* Backdrop */}
      <div
        ref={overlayRef}
        className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-[820px] bg-[#0d0d0d] border-l border-zinc-800 z-50 flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-zinc-800 shrink-0">
          <div className="flex items-start gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold text-[var(--text-primary)] font-mono">{trade.symbol}</span>
                {TICKER_NAMES[trade.symbol] && (
                  <span className="text-sm text-zinc-500">{TICKER_NAMES[trade.symbol]}</span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 border border-zinc-700">
                  {trade.preset_label}
                </span>
                <span className={cn("text-xs px-2 py-0.5 rounded-full border",
                  isOpen ? "bg-emerald-400/10 text-emerald-400 border-emerald-400/20" : "bg-zinc-800 text-zinc-500 border-zinc-700"
                )}>
                  {isOpen ? "Open" : trade.status}
                </span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {trade.pnl_pct != null && (
              <div className="text-right">
                <div className={cn("text-2xl font-bold font-mono", pnlColor(trade.pnl_pct))}>
                  {fmtPct(trade.pnl_pct)}
                </div>
                <div className={cn("text-sm font-mono", pnlColor(trade.pnl))}>
                  {trade.pnl != null ? `${trade.pnl >= 0 ? "+" : ""}${fmt$(trade.pnl)}` : ""}
                </div>
              </div>
            )}
            <button onClick={onClose} className="text-zinc-500 hover:text-[var(--text-primary)] transition-colors p-1 rounded-lg hover:bg-white/5">
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* Trade metrics */}
          <div className="px-6 pt-4 pb-3">
            <div className="grid grid-cols-4 gap-3 mb-4">
              <Metric label="Entry" value={trade.entry_price ? fmt$(trade.entry_price) : "—"} sub={trade.entry_date ? new Date(trade.entry_date).toLocaleDateString() : undefined} />
              <Metric label="Current" value={trade.current_price ? fmt$(trade.current_price) : "—"}
                sub={currPct != null ? fmtPct(currPct) : undefined}
                subColor={pnlColor(currPct)} />
              <Metric label="Stop" value={trade.stop_price ? fmt$(trade.stop_price) : "—"}
                sub={stopPct != null ? `${stopPct.toFixed(1)}%` : undefined}
                subColor="text-red-400/60" />
              <Metric label="Target" value={trade.target_price ? fmt$(trade.target_price) : "—"}
                sub={tgtPct != null ? `+${tgtPct.toFixed(1)}%` : undefined}
                subColor="text-emerald-400/60" />
            </div>

            <div className="grid grid-cols-4 gap-3 mb-5">
              <Metric label="R:R Ratio" value={rr != null ? `${rr.toFixed(1)}:1` : "—"} />
              <Metric label="Shares" value={trade.shares != null ? trade.shares.toFixed(2) : "—"} />
              <Metric label="Risk" value={trade.risk_dollars ? `$${trade.risk_dollars.toFixed(0)}` : "—"} />
              <Metric label="Days Held" value={`${trade.days_held}d`} />
            </div>

            {/* Progress bar: Stop → Current → Target */}
            {priceRange && entryProgress != null && currProgress != null && (
              <div className="mb-5">
                <div className="flex justify-between text-[10px] text-zinc-600 mb-1">
                  <span className="text-red-400/70">Stop {fmt$(trade.stop_price)}</span>
                  <span>Entry {fmt$(trade.entry_price)}</span>
                  <span className="text-emerald-400/70">Target {fmt$(trade.target_price)}</span>
                </div>
                <div className="relative h-2 bg-zinc-800 rounded-full overflow-hidden">
                  {/* Fill from stop to current */}
                  <div
                    className={cn("absolute top-0 left-0 h-full rounded-full transition-all",
                      (currPct ?? 0) >= 0 ? "bg-emerald-500/60" : "bg-red-500/60"
                    )}
                    style={{ width: `${currProgress}%` }}
                  />
                  {/* Entry marker */}
                  <div
                    className="absolute top-0 h-full w-0.5 bg-blue-400"
                    style={{ left: `${entryProgress}%` }}
                  />
                  {/* Current price marker */}
                  <div
                    className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2 border-white bg-zinc-900"
                    style={{ left: `calc(${currProgress}% - 5px)` }}
                  />
                </div>
                <div
                  className="text-[10px] text-zinc-400 mt-1 font-mono"
                  style={{ marginLeft: `${Math.max(0, Math.min(90, currProgress))}%` }}
                >
                  {trade.current_price ? fmt$(trade.current_price) : ""}
                </div>
              </div>
            )}
          </div>

          {/* Chart */}
          <div className="px-6 mb-4">
            <div className="text-[10px] text-zinc-600 uppercase tracking-widest mb-2">
              90-Day Chart · Blue=Entry · Red=Stop · Green=Target
            </div>
            <div className="rounded-xl overflow-hidden border border-zinc-800" style={{ height: config?.subPane ? 280 : 340 }}>
              {isLoading ? (
                <div className="h-full flex items-center justify-center text-zinc-600 text-sm">Loading chart…</div>
              ) : bars.length > 0 ? (
                <CandlestickChart
                  bars={bars}
                  indicators={overlayIndicators}
                  chartType="candle"
                  activeTool="cursor"
                  drawings={drawings}
                  onCrosshairMove={NOOP}
                  onAddDrawing={NOOP}
                />
              ) : (
                <div className="h-full flex items-center justify-center text-zinc-600 text-sm">No chart data</div>
              )}
            </div>

            {/* Sub-pane */}
            {config?.subPane === "rsi" && bars.length > 0 && rawIndicators.RSI_14 && (
              <div className="mt-1 rounded-b-xl overflow-hidden border border-t-0 border-zinc-800" style={{ height: 90 }}>
                <RsiChart bars={bars} values={rawIndicators.RSI_14} height={90} />
              </div>
            )}
            {config?.subPane === "macd" && bars.length > 0 && rawIndicators.MACD_line && (
              <div className="mt-1 rounded-b-xl overflow-hidden border border-t-0 border-zinc-800" style={{ height: 90 }}>
                <MacdChart
                  bars={bars}
                  macdLine={rawIndicators.MACD_line}
                  macdSignal={rawIndicators.MACD_signal ?? []}
                  macdHist={rawIndicators.MACD_hist ?? []}
                  height={90}
                />
              </div>
            )}
          </div>

          {/* Indicator legend */}
          {config && config.overlays.length > 0 && (
            <div className="px-6 mb-4">
              <div className="flex items-center gap-3 text-[10px]">
                <LegendDot color="#3b82f6" label={`Entry $${trade.entry_price?.toFixed(2) ?? "—"}`} />
                <LegendDot color="#ef4444" label={`Stop $${trade.stop_price?.toFixed(2) ?? "—"}`} />
                <LegendDot color="#10b981" label={`Target $${trade.target_price?.toFixed(2) ?? "—"}`} />
              </div>
            </div>
          )}

          {/* Why this trade */}
          {playbook && (
            <div className="px-6 mb-6">
              <div className="text-[10px] text-zinc-600 uppercase tracking-widest mb-2">Why This Trade</div>
              <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4">
                <div className="flex items-start gap-2">
                  {(trade.pnl_pct ?? 0) >= 0
                    ? <TrendingUp size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                    : <TrendingDown size={14} className="text-red-400 shrink-0 mt-0.5" />
                  }
                  <p className="text-sm text-zinc-300 leading-relaxed">{playbook}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Metric({ label, value, sub, subColor }: { label: string; value: string; sub?: string; subColor?: string }) {
  return (
    <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl px-3 py-2.5">
      <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-0.5">{label}</div>
      <div className="text-sm font-bold font-mono text-[var(--text-primary)]">{value}</div>
      {sub && <div className={cn("text-[10px] font-mono mt-0.5", subColor ?? "text-zinc-500")}>{sub}</div>}
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1 text-zinc-500">
      <div className="w-2.5 h-0.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </div>
  );
}
