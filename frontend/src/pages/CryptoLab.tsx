import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Star, RotateCw, X, ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
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
  type CoinGeckoData,
  type CryptoOverview,
  type CryptoTrade,
  type StrategyDefinition,
} from "@/api/crypto";
import { getAccount, placeOrder } from "@/api/paper";
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
      {/* Market Cap */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex flex-col gap-0.5 min-w-[160px]">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Market Cap</span>
        <span className="text-base font-bold font-mono text-[var(--text-primary)]">{fmtLarge(data.total_market_cap_usd)}</span>
        <span className={cn("text-xs font-mono font-semibold", mcapColor)}>
          {fmtPct(data.market_cap_change_24h_pct)} 24h
        </span>
      </div>
      {/* BTC Dominance */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex flex-col gap-0.5 min-w-[140px]">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">BTC Dominance</span>
        <span className="text-base font-bold font-mono text-[var(--text-primary)]">{data.btc_dominance.toFixed(1)}%</span>
        <span className="text-xs text-[var(--text-tertiary)]">{data.active_coins.toLocaleString()} coins</span>
      </div>
      {/* Fear & Greed */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex items-center gap-3 min-w-[140px]">
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Fear & Greed</span>
        </div>
        <FearGauge value={data.fear_greed.value} label={data.fear_greed.label} />
      </div>
    </div>
  );
}

// ── Order Modal ────────────────────────────────────────────────────────────────

function OrderModal({
  coin, cash, onClose, onFilled,
}: {
  coin: CoinGeckoData;
  cash: number;
  onClose: () => void;
  onFilled: () => void;
}) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [mode, setMode] = useState<"notional" | "qty">("notional");
  const [notional, setNotional] = useState("100");
  const [qty, setQty] = useState("");

  const price = coin.current_price ?? 0;
  const paperSymbol = `${coin.symbol}-USD`;
  const qtyPreview = mode === "notional" && notional && price
    ? (parseFloat(notional) / price).toFixed(8) : null;
  const notionalPreview = mode === "qty" && qty && price
    ? (parseFloat(qty) * price).toFixed(2) : null;

  const mutation = useMutation({
    mutationFn: () => {
      const body: Parameters<typeof placeOrder>[0] = {
        symbol: paperSymbol,
        side,
        order_type: "market",
        tif: "gtc",
      };
      if (mode === "notional") body.notional = parseFloat(notional);
      else body.qty = parseFloat(qty);
      return placeOrder(body);
    },
    onSuccess: () => {
      toast.success(`${side === "buy" ? "Bought" : "Sold"} ${coin.symbol}`);
      onFilled();
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Order failed"),
  });

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-sm bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl shadow-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {coin.image && <img src={coin.image} alt={coin.symbol} className="w-8 h-8 rounded-full" />}
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-widest mb-0.5">Trade Crypto</div>
              <div className="text-base font-bold text-[var(--text-primary)]">{coin.name} <span className="text-[var(--text-tertiary)]">{coin.symbol}</span></div>
            </div>
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer"><X size={16} /></button>
        </div>

        <div className="text-2xl font-bold font-mono text-[var(--text-primary)] mb-4">
          {fmtPrice(coin.current_price)}
          {coin.pct_24h != null && (
            <span className={cn("text-sm ml-2 font-normal", pctColor(coin.pct_24h))}>
              {fmtPct(coin.pct_24h)}
            </span>
          )}
        </div>

        <div className="flex gap-1 mb-4 bg-[var(--bg-elevated-2)] p-1 rounded-lg">
          {(["buy", "sell"] as const).map((s) => (
            <button key={s} onClick={() => setSide(s)} className={cn(
              "flex-1 py-1.5 rounded-md text-sm font-semibold transition-all capitalize",
              side === s
                ? s === "buy" ? "bg-emerald-600 text-[var(--text-primary)]" : "bg-red-600 text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            )}>{s}</button>
          ))}
        </div>

        <div className="flex gap-2 mb-3 text-xs">
          {(["notional", "qty"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={cn(
              "px-3 py-1 rounded-full border transition-colors",
              mode === m
                ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive-bg)]"
                : "border-[var(--border-subtle)] text-[var(--text-tertiary)]"
            )}>{m === "notional" ? "$ Amount" : "Coin Qty"}</button>
          ))}
        </div>

        {mode === "notional" ? (
          <div className="mb-1">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm">$</span>
              <input type="number" value={notional} onChange={(e) => setNotional(e.target.value)}
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg pl-7 pr-4 py-2.5 text-[var(--text-primary)] text-sm font-mono focus:outline-none focus:border-[var(--accent-positive)]"
                placeholder="100" min="1" />
            </div>
            {qtyPreview && <p className="text-xs text-[var(--text-tertiary)] mt-1 font-mono">≈ {qtyPreview} {coin.symbol}</p>}
          </div>
        ) : (
          <div className="mb-1">
            <div className="relative">
              <input type="number" value={qty} onChange={(e) => setQty(e.target.value)}
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg pl-4 pr-16 py-2.5 text-[var(--text-primary)] text-sm font-mono focus:outline-none focus:border-[var(--accent-positive)]"
                placeholder="0.001" step="0.0001" min="0" />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-xs">{coin.symbol}</span>
            </div>
            {notionalPreview && <p className="text-xs text-[var(--text-tertiary)] mt-1 font-mono">≈ ${notionalPreview}</p>}
          </div>
        )}

        <p className="text-xs text-[var(--text-tertiary)] mb-4">
          Cash available: ${cash.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>

        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || (mode === "notional" ? !notional || parseFloat(notional) <= 0 : !qty || parseFloat(qty) <= 0)}
          className={cn(
            "w-full py-2.5 rounded-xl text-sm font-bold transition-all",
            side === "buy"
              ? "bg-emerald-600 hover:bg-emerald-500 text-[var(--text-primary)] disabled:opacity-40"
              : "bg-red-600 hover:bg-red-500 text-[var(--text-primary)] disabled:opacity-40",
            mutation.isPending && "opacity-60 cursor-wait"
          )}
        >
          {mutation.isPending ? "Placing…" : `Place ${side.toUpperCase()} Order`}
        </button>
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

  const handleSort = useCallback((key: SortKey) => {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "market_cap_rank" ? "asc" : "desc" }
    );
  }, []);

  const sorted = useMemo(() => {
    return [...coins].sort((a, b) => {
      const av = a[sort.key] ?? (sort.dir === "asc" ? Infinity : -Infinity);
      const bv = b[sort.key] ?? (sort.dir === "asc" ? Infinity : -Infinity);
      return sort.dir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [coins, sort]);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-[var(--border-subtle)]">
            <th className="px-3 py-2.5 text-left w-8"></th>
            <SortableTH col="market_cap_rank" label="#" sort={sort} onSort={handleSort} className="text-left w-12" />
            <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Coin</th>
            <SortableTH col="current_price" label="Price" sort={sort} onSort={handleSort} />
            <SortableTH col="pct_1h" label="1h %" sort={sort} onSort={handleSort} />
            <SortableTH col="pct_24h" label="24h %" sort={sort} onSort={handleSort} />
            <SortableTH col="pct_7d" label="7d %" sort={sort} onSort={handleSort} />
            <SortableTH col="market_cap" label="Mkt Cap" sort={sort} onSort={handleSort} className="hidden md:table-cell" />
            <SortableTH col="total_volume" label="Volume 24h" sort={sort} onSort={handleSort} className="hidden lg:table-cell" />
            <th className="px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] hidden sm:table-cell">7d</th>
            <th className="px-3 py-2.5 w-16"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((coin) => (
            <tr
              key={coin.id}
              className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated-2)] transition-colors"
            >
              {/* Star */}
              <td className="px-3 py-2.5">
                <button
                  onClick={() => onToggleWatch(coin.id)}
                  className={cn(
                    "transition-colors cursor-pointer",
                    watchlist.has(coin.id)
                      ? "text-yellow-400"
                      : "text-[var(--text-tertiary)] hover:text-yellow-400"
                  )}
                >
                  <Star size={13} fill={watchlist.has(coin.id) ? "currentColor" : "none"} />
                </button>
              </td>

              {/* Rank */}
              <td className="px-3 py-2.5 text-[var(--text-tertiary)] text-xs font-mono text-right">
                {coin.market_cap_rank ?? "—"}
              </td>

              {/* Name + Logo */}
              <td className="px-3 py-2.5">
                <button
                  onClick={() => onChart(coin)}
                  className="flex items-center gap-2.5 text-left hover:opacity-80 transition-opacity cursor-pointer"
                >
                  {coin.image
                    ? <img src={coin.image} alt={coin.symbol} className="w-6 h-6 rounded-full flex-shrink-0" />
                    : <div className="w-6 h-6 rounded-full bg-[var(--bg-elevated-2)] flex-shrink-0" />}
                  <div>
                    <span className="font-semibold text-[var(--text-primary)] text-xs">{coin.name}</span>
                    <span className="ml-1.5 text-[var(--text-tertiary)] text-[10px] font-mono">{coin.symbol}</span>
                  </div>
                </button>
              </td>

              {/* Price */}
              <td className="px-3 py-2.5 text-right font-mono text-[var(--text-primary)] text-xs whitespace-nowrap">
                {fmtPrice(coin.current_price)}
              </td>

              {/* 1h% */}
              <td className={cn("px-3 py-2.5 text-right font-mono text-xs", pctColor(coin.pct_1h))}>
                {fmtPct(coin.pct_1h)}
              </td>

              {/* 24h% */}
              <td className={cn("px-3 py-2.5 text-right font-mono text-xs", pctColor(coin.pct_24h))}>
                {fmtPct(coin.pct_24h)}
              </td>

              {/* 7d% */}
              <td className={cn("px-3 py-2.5 text-right font-mono text-xs", pctColor(coin.pct_7d))}>
                {fmtPct(coin.pct_7d)}
              </td>

              {/* Market Cap */}
              <td className="px-3 py-2.5 text-right text-[var(--text-secondary)] text-xs font-mono hidden md:table-cell">
                {fmtLarge(coin.market_cap)}
              </td>

              {/* Volume */}
              <td className="px-3 py-2.5 text-right text-[var(--text-tertiary)] text-xs font-mono hidden lg:table-cell">
                {fmtLarge(coin.total_volume)}
              </td>

              {/* Sparkline */}
              <td className="px-3 py-2.5 hidden sm:table-cell">
                <div className="flex justify-end">
                  {showSparklineUrl && coin.sparkline_url ? (
                    <img src={coin.sparkline_url} alt="7d" className="h-6 w-[72px] object-contain opacity-80" />
                  ) : (
                    <SparkLine prices={coin.sparkline} />
                  )}
                </div>
              </td>

              {/* Buy */}
              <td className="px-3 py-2.5">
                <button
                  onClick={() => onTrade(coin)}
                  disabled={coin.current_price == null}
                  className="text-[10px] px-2.5 py-1 rounded-lg bg-[var(--bg-elevated-2)] hover:bg-[#334155] text-[var(--text-secondary)] hover:text-[var(--text-primary)] font-semibold transition-colors disabled:opacity-30 cursor-pointer whitespace-nowrap"
                >
                  Trade
                </button>
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={11} className="px-3 py-10 text-center text-[var(--text-tertiary)] text-sm">
                No coins to display
              </td>
            </tr>
          )}
        </tbody>
      </table>
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
  const { data: account } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
  });

  const cryptoPositions = (account?.positions ?? []).filter((p) => p.symbol.includes("-USD"));
  const totalValue = cryptoPositions.reduce((s, p) => s + p.market_value, 0);
  const totalPnl   = cryptoPositions.reduce((s, p) => s + p.unrealized_pnl, 0);

  const findCoin = (sym: string) => coins.find((c) => `${c.symbol}-USD` === sym);

  if (!cryptoPositions.length) {
    return (
      <div className="py-16 text-center text-[var(--text-tertiary)] text-sm">
        No crypto holdings yet — trade from the Top or Trending tab to get started
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          {cryptoPositions.length} position{cryptoPositions.length !== 1 ? "s" : ""}
        </span>
        <div className="flex gap-4 text-xs font-mono">
          <span className="text-[var(--text-secondary)]">Value: <span className="text-[var(--text-primary)] font-semibold">{fmtLarge(totalValue)}</span></span>
          <span className={cn("font-semibold", pctColor(totalPnl))}>
            {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)} unrealized
          </span>
        </div>
      </div>
      {cryptoPositions.map((p) => {
        const coin = findCoin(p.symbol);
        return (
          <div
            key={p.id}
            className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex items-center gap-3"
          >
            {coin?.image && <img src={coin.image} alt={p.symbol} className="w-8 h-8 rounded-full flex-shrink-0" />}
            <div className="flex-1 min-w-0">
              <div className="font-bold text-[var(--text-primary)] text-sm font-mono">{p.symbol.replace("-USD", "")}</div>
              <div className="text-[11px] text-[var(--text-tertiary)] font-mono">
                {p.qty.toFixed(p.qty < 1 ? 6 : 4)} coins · avg {fmtPrice(p.avg_cost)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-mono text-[var(--text-primary)] font-semibold">{fmtLarge(p.market_value)}</div>
              <div className={cn("text-xs font-mono", pctColor(p.unrealized_pnl))}>
                {p.unrealized_pnl >= 0 ? "+" : ""}{p.unrealized_pnl_pct.toFixed(2)}%
              </div>
            </div>
            {coin && (
              <button
                onClick={() => onTrade(coin)}
                className="text-[10px] px-2.5 py-1 rounded-lg bg-red-900/30 text-red-400 hover:bg-red-900/50 cursor-pointer font-semibold whitespace-nowrap"
              >
                Sell
              </button>
            )}
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

function fmt$(n: number | null | undefined): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const s = n < 0 ? "-$" : "$";
  if (abs >= 1e9)  return s + (abs / 1e9).toFixed(2) + "B";
  if (abs >= 1e6)  return s + (abs / 1e6).toFixed(2) + "M";
  if (abs >= 1000) return s + abs.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return s + abs.toFixed(2);
}

function CryptoStrategyPanel() {
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);
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

  const open = (tradesData?.trades ?? []).filter((t) => t.status === "open");
  const closed = (tradesData?.trades ?? []).filter((t) => t.status === "closed");
  const candidates = candidatesData?.candidates ?? [];
  const summary = summaryData?.overall;

  const handleRunNow = async () => {
    setRunning(true);
    try {
      await runCryptoStrategyNow();
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["crypto-strategy-trades"] }),
        qc.invalidateQueries({ queryKey: ["crypto-strategy-candidates"] }),
        qc.invalidateQueries({ queryKey: ["crypto-strategy-summary"] }),
      ]);
      toast.success("Crypto automation run queued");
    } catch {
      toast.error("Run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Summary strip */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Open", value: summary.open_positions.toString() },
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

      {/* Sub-tabs + Run Now */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl">
          {([["open", `Open (${open.length})`], ["watch", `Watching (${candidates.length})`], ["closed", `Closed (${closed.length})`]] as [typeof stratTab, string][]).map(([id, label]) => (
            <button key={id} onClick={() => setStratTab(id)} className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap",
              stratTab === id
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            )}>{label}</button>
          ))}
        </div>
        <button
          onClick={handleRunNow}
          disabled={running}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-[var(--accent-positive)] text-black font-semibold hover:opacity-90 disabled:opacity-50 transition-all cursor-pointer"
        >
          <RotateCw size={11} className={running ? "animate-spin" : ""} />
          Run Now
        </button>
      </div>

      {/* Open positions */}
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
                  <div className={cn("text-xs font-mono font-semibold", pctColor(pct))}>
                    {fmtPct(pct)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Watching / candidates */}
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

      {/* Closed trades */}
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
  coingecko:   "CoinGecko",
  glassnode:   "Glassnode",
  cryptoquant: "CryptoQuant",
  coinglass:   "Coinglass",
  arkham:      "Arkham",
};

function StrategyCard({
  def,
  byPreset,
}: {
  def: StrategyDefinition;
  byPreset: Record<string, { wins: number; losses: number; total_pnl: number; trades: number }>;
}) {
  const tier = TIER_BADGE[def.tier_required] ?? TIER_BADGE.free;
  const stats = byPreset[def.strategy_key];
  const winRate = stats && stats.trades > 0
    ? Math.round(stats.wins / stats.trades * 100) : null;

  return (
    <div className={cn(
      "relative flex flex-col bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden transition-all duration-200",
      def.is_active ? "hover:border-[var(--border-emphasis)] hover:shadow-lg" : "opacity-60"
    )}>
      {/* Gradient bar */}
      <div
        className="h-1 w-full flex-shrink-0"
        style={{ background: `linear-gradient(90deg, ${def.category_accent_from}, ${def.category_accent_to})` }}
      />

      <div className="flex flex-col gap-3 p-4 flex-1">
        {/* Header row */}
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

        {/* Description */}
        <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed line-clamp-3 flex-1">
          {def.description}
        </p>

        {/* Data sources */}
        <div className="flex flex-wrap gap-1">
          {def.required_data_sources.map((src) => (
            <span
              key={src}
              className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] font-mono border border-[var(--border-subtle)]"
            >
              {SOURCE_BADGE[src] ?? src}
            </span>
          ))}
          {def.structure_type !== "simple" && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-amber-400 font-mono border border-amber-800/50 capitalize">
              {def.structure_type}
            </span>
          )}
        </div>

        {/* Stats strip */}
        <div className="border-t border-[var(--border-subtle)] pt-2.5 mt-auto">
          {def.is_active && stats ? (
            <div className="flex gap-4 text-[10px] font-mono">
              <span>
                <span className="text-[var(--text-tertiary)]">Trades </span>
                <span className="text-[var(--text-primary)] font-semibold">{stats.trades}</span>
              </span>
              {winRate !== null && (
                <span>
                  <span className="text-[var(--text-tertiary)]">Win </span>
                  <span className="font-semibold" style={{ color: winRate >= 50 ? "var(--accent-positive)" : "var(--accent-negative)" }}>
                    {winRate}%
                  </span>
                </span>
              )}
              <span className={cn("font-semibold", stats.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                {stats.total_pnl >= 0 ? "+" : ""}{fmt$(stats.total_pnl)}
              </span>
            </div>
          ) : def.is_active ? (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[10px] text-emerald-400 font-semibold">Active · No trades yet</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-tertiary)]" />
              <span className="text-[10px] text-[var(--text-tertiary)]">Coming Soon</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const CATEGORY_ORDER = [
  "Trend Following", "Mean Reversion", "Momentum", "Cycle",
  "Market Structure", "On-Chain", "Derivatives", "Whale Activity",
];

function StrategyCardGrid() {
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
      {grouped.map(({ category, defs }) => (
        <div key={category}>
          <div className="flex items-center gap-2 mb-3">
            <h3 className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">{category}</h3>
            <div className="flex-1 h-px bg-[var(--border-subtle)]" />
            <span className="text-[10px] text-[var(--text-tertiary)] font-mono">{defs.length}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {defs.map((d) => (
              <StrategyCard key={d.strategy_key} def={d} byPreset={byPreset} />
            ))}
          </div>
        </div>
      ))}
      {grouped.length === 0 && (
        <p className="text-center text-[var(--text-tertiary)] text-sm py-12">
          Strategy library loading…
        </p>
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

  const coins = market?.coins ?? [];
  const trendingCoins = trending?.coins ?? [];
  const watchlistCoins = useMemo(() => coins.filter((c) => watchlist.has(c.id)), [coins, watchlist]);
  const cash = account?.cash ?? 0;

  const handleChart = useCallback((coin: CoinGeckoData) => {
    navigate(`/chart?symbol=${coin.symbol}-USD`);
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
      <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap",
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
            <StrategyCardGrid />
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

      {/* Order modal */}
      {tradingCoin && (
        <OrderModal
          coin={tradingCoin}
          cash={cash}
          onClose={() => setTradingCoin(null)}
          onFilled={() => qc.invalidateQueries({ queryKey: ["paper-account"] })}
        />
      )}
    </div>
  );
}
