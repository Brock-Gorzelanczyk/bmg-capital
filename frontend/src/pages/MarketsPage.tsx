import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── API ───────────────────────────────────────────────────────────────────────

interface CoinRow {
  id: string;
  symbol: string;
  name: string;
  image?: string;
  current_price: number | null;
  market_cap: number;
  total_volume: number;
  pct_1h: number | null;
  pct_24h: number | null;
  pct_7d: number | null;
  sparkline: number[];
}

interface StockRow {
  symbol: string;
  name: string;
  price: number | null;
  change_1d: number | null;
  change_5d: number | null;
  change_1m: number | null;
  market_cap: number | null;
  volume: number | null;
  sparkline_1m: number[];
  private?: boolean;
}

const getCryptoMarkets = (limit = 100): Promise<{ coins: CoinRow[] }> =>
  client.get("/markets/crypto", { params: { limit } }).then((r) => r.data);

const getStockMarkets = (limit = 100): Promise<{ stocks: StockRow[] }> =>
  client.get("/markets/stocks", { params: { limit } }).then((r) => r.data);

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPrice(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (v >= 1) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(6)}`;
}

function fmtBig(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toLocaleString()}`;
}

function fmtPct(v: number | null): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function pclr(v: number | null): string {
  if (v == null) return "text-t-muted";
  return v >= 0 ? "text-t-green" : "text-t-red";
}

// ── Sparkline SVG ─────────────────────────────────────────────────────────────

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  if (!data || data.length < 2) return <span className="text-t-dim text-xs">—</span>;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 64, h = 24;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline points={pts} fill="none" stroke={positive ? "#34d399" : "#f87171"} strokeWidth="1.5" />
    </svg>
  );
}

// ── Scout action button ────────────────────────────────────────────────────────

function ScoutButton({ symbol }: { symbol: string }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={(e) => { e.stopPropagation(); navigate(`/strategy/scout?ticker=${symbol}`); }}
      title="Open in Strategy Scout"
      className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-bold bg-violet-500/10 border border-violet-500/20 text-violet-400 hover:bg-violet-500/20 transition-colors whitespace-nowrap"
    >
      ⚒ Scout
    </button>
  );
}

// ── Private companies ─────────────────────────────────────────────────────────

interface PrivateCo {
  ticker: string;
  name: string;
  valuation: number;
  last_round: string;
  category: string;
  ipo_status: string;
  notes: string;
}

const PRIVATE_COMPANIES: PrivateCo[] = [
  {
    ticker: "OPENAI",
    name: "OpenAI",
    valuation: 1_000_000_000_000,
    last_round: "Pre-IPO bankers engaged, $25B annualized revenue",
    category: "AI",
    ipo_status: "Q4 2026 IPO planned",
    notes: "Preparing bankers for Q4 2026 listing at ~$1T valuation.",
  },
  {
    ticker: "ANTHROPIC",
    name: "Anthropic",
    valuation: 61_500_000_000,
    last_round: "Filed confidential S-1 June 1, 2026",
    category: "AI",
    ipo_status: "October 2026 target listing on NASDAQ or NYSE",
    notes: "S-1 filing confidential. Listing as early as October 2026 per FT.",
  },
  {
    ticker: "STRIPE",
    name: "Stripe",
    valuation: 70_000_000_000,
    last_round: "Mar 2023 tender",
    category: "Fintech",
    ipo_status: "Private — exploring IPO options",
    notes: "2021 peak valuation was $95B. Secondary market trades around $70B.",
  },
  {
    ticker: "DATABRICKS",
    name: "Databricks",
    valuation: 134_000_000_000,
    last_round: "Series L December 2025 ($4B raised at $134B post-money)",
    category: "Data/AI",
    ipo_status: "Private — CEO said NOT 2026",
    notes: "$4.8B ARR. Ali Ghodsi (CEO) told Bloomberg June 4: '2026 is a terrible year to go public.'",
  },
];

function PrivateCompaniesSection() {
  return (
    <div className="space-y-3 mt-6">
      <div className="flex items-center gap-2">
        <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest">
          // PRIVATE COMPANIES — TRACKED
        </p>
        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-500/10 border border-amber-500/20 text-amber-400 uppercase">
          No public market data
        </span>
      </div>
      <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[700px]">
            <thead>
              <tr className="border-b border-t-dim bg-t-bg1/80">
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-4">Company</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3">Est. Valuation</th>
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-3">Last Round</th>
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-3">Category</th>
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-3">IPO Status</th>
                <th className="text-center text-[10px] text-t-muted uppercase py-2 px-3">Watch</th>
              </tr>
            </thead>
            <tbody>
              {PRIVATE_COMPANIES.map((co) => (
                <tr key={co.ticker} className="border-b border-t-dim/40 last:border-0 hover:bg-t-bg2/30 transition-colors">
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[9px] font-bold shrink-0">
                        {co.ticker[0]}
                      </span>
                      <div>
                        <div className="text-t-hi font-semibold">{co.name}</div>
                        <div className="text-t-muted text-[10px]">{co.notes}</div>
                      </div>
                    </div>
                  </td>
                  <td className="py-3 px-3 text-right font-mono-t tabular-nums text-t-hi font-semibold">
                    {fmtBig(co.valuation)}
                  </td>
                  <td className="py-3 px-3 text-t-mid2">{co.last_round}</td>
                  <td className="py-3 px-3">
                    <span className="px-1.5 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-semibold">
                      {co.category}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-t-muted text-[10px]">{co.ipo_status}</td>
                  <td className="py-3 px-3 text-center">
                    <button
                      onClick={() => { import("sonner").then(({ toast }) => toast.success(`Watching ${co.name} for IPO news`)); }}
                      className="px-2 py-1 rounded-lg text-[10px] font-bold bg-amber-500/10 border border-amber-500/20 text-amber-400 hover:bg-amber-500/20 transition-colors whitespace-nowrap"
                    >
                      Notify on IPO
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Crypto table ──────────────────────────────────────────────────────────────

type CryptoFilter = "top100" | "trending" | "movers";

function CryptoTab() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<CryptoFilter>("top100");
  const [search, setSearch] = useState("");
  const [sortCol, setSortCol] = useState<"market_cap" | "pct_1h" | "pct_24h" | "pct_7d" | "total_volume">("market_cap");

  const { data, isLoading } = useQuery({
    queryKey: ["markets-crypto"],
    queryFn: () => getCryptoMarkets(100),
    staleTime: 60_000,
    retry: 0,
  });

  let coins = data?.coins ?? [];

  if (filter === "movers") coins = coins.filter((c) => Math.abs(c.pct_24h ?? 0) >= 5);
  if (search) {
    const q = search.toLowerCase();
    coins = coins.filter((c) => c.symbol.toLowerCase().includes(q) || c.name.toLowerCase().includes(q));
  }
  coins = [...coins].sort((a, b) => (b[sortCol] ?? 0) - (a[sortCol] ?? 0));

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="flex gap-1 bg-t-bg1 border border-t-dim rounded-xl p-1">
          {(["top100","trending","movers"] as CryptoFilter[]).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors capitalize",
                filter === f ? "bg-t-bg2 text-t-hi" : "text-t-muted hover:text-t-mid2")}>
              {f === "top100" ? "Top 100" : f === "movers" ? "Movers (>5%)" : "Trending"}
            </button>
          ))}
        </div>
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search coin…"
          className="flex-1 bg-t-bg1 border border-t-dim rounded-xl px-4 py-2 text-sm text-t-hi placeholder-t-muted focus:outline-none focus:border-t-mid" />
      </div>

      {/* Table */}
      <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[800px]">
            <thead>
              <tr className="border-b border-t-dim bg-t-bg1/80">
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-4 w-8">#</th>
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-2">Coin</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3">Price</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3 cursor-pointer hover:text-t-mid2"
                  onClick={() => setSortCol("pct_1h")}>1H {sortCol === "pct_1h" ? "▼" : ""}</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3 cursor-pointer hover:text-t-mid2"
                  onClick={() => setSortCol("pct_24h")}>24H {sortCol === "pct_24h" ? "▼" : ""}</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3 cursor-pointer hover:text-t-mid2"
                  onClick={() => setSortCol("pct_7d")}>7D {sortCol === "pct_7d" ? "▼" : ""}</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3 cursor-pointer hover:text-t-mid2"
                  onClick={() => setSortCol("market_cap")}>Mkt Cap {sortCol === "market_cap" ? "▼" : ""}</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3 cursor-pointer hover:text-t-mid2"
                  onClick={() => setSortCol("total_volume")}>Volume {sortCol === "total_volume" ? "▼" : ""}</th>
                <th className="text-center text-[10px] text-t-muted uppercase py-2 px-3">7D Chart</th>
                <th className="text-center text-[10px] text-t-muted uppercase py-2 px-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                [0,1,2,3,4,5,6,7,8,9].map((i) => (
                  <tr key={i} className="border-b border-t-dim/50">
                    <td colSpan={10} className="py-3 px-4">
                      <div className="h-4 bg-t-bg2 rounded animate-pulse" />
                    </td>
                  </tr>
                ))
              ) : coins.map((coin, i) => (
                <tr key={coin.id} className="border-b border-t-dim/40 hover:bg-t-bg2/30 transition-colors cursor-pointer"
                  onClick={() => navigate(`/chart?symbol=${coin.symbol}/USD`)}>
                  <td className="py-2.5 px-4 text-t-muted">{i + 1}</td>
                  <td className="py-2.5 px-2">
                    <div className="flex items-center gap-2">
                      {coin.image && <img src={coin.image} alt={coin.symbol} className="w-5 h-5 rounded-full" loading="lazy" />}
                      <div>
                        <span className="text-t-hi font-semibold">{coin.symbol}</span>
                        <span className="text-t-muted ml-1.5 hidden sm:inline">{coin.name}</span>
                      </div>
                    </div>
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono-t tabular-nums text-t-hi">{fmtPrice(coin.current_price)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", pclr(coin.pct_1h))}>{fmtPct(coin.pct_1h)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", pclr(coin.pct_24h))}>{fmtPct(coin.pct_24h)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", pclr(coin.pct_7d))}>{fmtPct(coin.pct_7d)}</td>
                  <td className="py-2.5 px-3 text-right font-mono-t tabular-nums text-t-mid2">{fmtBig(coin.market_cap)}</td>
                  <td className="py-2.5 px-3 text-right font-mono-t tabular-nums text-t-mid2">{fmtBig(coin.total_volume)}</td>
                  <td className="py-2.5 px-3 text-center">
                    <Sparkline data={coin.sparkline.slice(-48)} positive={(coin.pct_7d ?? 0) >= 0} />
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <ScoutButton symbol={coin.symbol} />
                  </td>
                </tr>
              ))}
              {!isLoading && coins.length === 0 && (
                <tr>
                  <td colSpan={10} className="py-10 text-center text-t-muted text-sm">No results</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Stock logo ────────────────────────────────────────────────────────────────

// Hand-mapped static logos — for tickers that don't resolve via logo.dev
// (synthetic private-company tickers, etc.). Checked BEFORE the API call.
const HAND_MAPPED_LOGOS: Record<string, string> = {
  SPCX: "/logos/spcx.svg",
};

const LOGO_TOKEN = "pk_X-1ZO13GSgeOoUrIuJ6GMQ";

const AVATAR_COLORS = [
  "bg-violet-500", "bg-blue-500", "bg-emerald-500", "bg-amber-500",
  "bg-rose-500", "bg-cyan-500", "bg-indigo-500", "bg-teal-500",
];

function stockColor(sym: string) {
  let h = 0;
  for (let i = 0; i < sym.length; i++) h = (h * 31 + sym.charCodeAt(i)) & 0xffff;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function StockLogo({ symbol }: { symbol: string }) {
  const [failed, setFailed] = useState(false);
  const handMapped = HAND_MAPPED_LOGOS[symbol];
  const logoUrl = handMapped ?? `https://img.logo.dev/ticker/${symbol}?token=${LOGO_TOKEN}&size=32`;
  if (failed) {
    return (
      <span className={cn("inline-flex items-center justify-center w-6 h-6 rounded-full text-[9px] font-bold text-white shrink-0", stockColor(symbol))}>
        {symbol[0]}
      </span>
    );
  }
  return (
    <img
      src={logoUrl}
      alt={symbol}
      width={24}
      height={24}
      className="rounded w-6 h-6 object-contain shrink-0"
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

// ── Stocks table ──────────────────────────────────────────────────────────────

type StockSort = "market_cap" | "change_1d" | "change_5d" | "change_1m" | "volume";

const SORT_TABS: { key: StockSort; label: string }[] = [
  { key: "market_cap", label: "Mkt Cap" },
  { key: "change_1d",  label: "Today %" },
  { key: "change_5d",  label: "5D %" },
  { key: "change_1m",  label: "1M %" },
  { key: "volume",     label: "Volume" },
];

function StocksTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [sortCol, setSortCol] = useState<StockSort>("market_cap");

  const { data, isLoading } = useQuery({
    queryKey: ["markets-stocks"],
    queryFn: () => getStockMarkets(100),
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 0,
  });

  let stocks = data?.stocks ?? [];

  if (search) {
    const q = search.toLowerCase();
    stocks = stocks.filter((s) => s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q));
  }
  stocks = [...stocks].sort((a, b) => (b[sortCol] ?? 0) - (a[sortCol] ?? 0));

  const activeCol = (col: StockSort) =>
    col === sortCol ? "bg-t-bg2 text-t-hi" : "text-t-muted hover:text-t-mid2";

  return (
    <div className="space-y-3">
      {/* Controls row */}
      <div className="flex flex-col sm:flex-row gap-2 items-start sm:items-center">
        {/* Sort tabs */}
        <div className="flex gap-1 bg-t-bg1 border border-t-dim rounded-xl p-1 flex-wrap">
          <span className="px-2 py-1.5 text-[10px] text-t-muted uppercase font-semibold self-center">Rank by</span>
          {SORT_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setSortCol(t.key)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors", activeCol(t.key))}
            >
              {t.label}
            </button>
          ))}
        </div>
        {/* Search */}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search symbol or company…"
          className="flex-1 max-w-xs bg-t-bg1 border border-t-dim rounded-xl px-4 py-2 text-sm text-t-hi placeholder-t-muted focus:outline-none focus:border-t-mid"
        />
      </div>

      <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[820px]">
            <thead>
              <tr className="border-b border-t-dim bg-t-bg1/80">
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-4 w-8">#</th>
                <th className="text-left text-[10px] text-t-muted uppercase py-2 px-2">Symbol</th>
                <th className="text-right text-[10px] text-t-muted uppercase py-2 px-3">Price</th>
                <th
                  className={cn("text-right text-[10px] uppercase py-2 px-3 cursor-pointer transition-colors", sortCol === "change_1d" ? "text-t-hi" : "text-t-muted hover:text-t-mid2")}
                  onClick={() => setSortCol("change_1d")}
                >
                  1D {sortCol === "change_1d" && "▼"}
                </th>
                <th
                  className={cn("text-right text-[10px] uppercase py-2 px-3 cursor-pointer transition-colors", sortCol === "change_5d" ? "text-t-hi" : "text-t-muted hover:text-t-mid2")}
                  onClick={() => setSortCol("change_5d")}
                >
                  5D {sortCol === "change_5d" && "▼"}
                </th>
                <th
                  className={cn("text-right text-[10px] uppercase py-2 px-3 cursor-pointer transition-colors", sortCol === "change_1m" ? "text-t-hi" : "text-t-muted hover:text-t-mid2")}
                  onClick={() => setSortCol("change_1m")}
                >
                  1M {sortCol === "change_1m" && "▼"}
                </th>
                <th
                  className={cn("text-right text-[10px] uppercase py-2 px-3 cursor-pointer transition-colors", sortCol === "market_cap" ? "text-t-hi" : "text-t-muted hover:text-t-mid2")}
                  onClick={() => setSortCol("market_cap")}
                >
                  Mkt Cap {sortCol === "market_cap" && "▼"}
                </th>
                <th
                  className={cn("text-right text-[10px] uppercase py-2 px-3 cursor-pointer transition-colors", sortCol === "volume" ? "text-t-hi" : "text-t-muted hover:text-t-mid2")}
                  onClick={() => setSortCol("volume")}
                >
                  Volume {sortCol === "volume" && "▼"}
                </th>
                <th className="text-center text-[10px] text-t-muted uppercase py-2 px-3">1M Chart</th>
                <th className="text-center text-[10px] text-t-muted uppercase py-2 px-3">Action</th>
                <th className="text-center text-[10px] text-t-muted uppercase py-2 px-2 hidden sm:table-cell">Mkt</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                [0,1,2,3,4,5,6,7,8,9].map((i) => (
                  <tr key={i} className="border-b border-t-dim/50">
                    <td colSpan={11} className="py-3 px-4">
                      <div className="h-4 bg-t-bg2 rounded animate-pulse" />
                    </td>
                  </tr>
                ))
              ) : stocks.map((stock, i) => (
                <tr key={stock.symbol} className="border-b border-t-dim/40 hover:bg-t-bg2/30 transition-colors cursor-pointer"
                  onClick={() => navigate(`/chart?symbol=${stock.symbol}`)}>
                  <td className="py-2.5 px-4 text-t-muted">{i + 1}</td>
                  <td className="py-2.5 px-2">
                    <div className="flex items-center gap-2">
                      <StockLogo symbol={stock.symbol} />
                      <div>
                        <span className="text-t-hi font-semibold">{stock.symbol}</span>
                        <span className="text-t-muted ml-1.5 text-[10px] hidden sm:inline">{stock.name}</span>
                      </div>
                    </div>
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono-t tabular-nums text-t-hi">{fmtPrice(stock.price)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", sortCol === "change_1d" ? "text-t-hi font-semibold" : pclr(stock.change_1d))}>{fmtPct(stock.change_1d)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", sortCol === "change_5d" ? "text-t-hi font-semibold" : pclr(stock.change_5d))}>{fmtPct(stock.change_5d)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", sortCol === "change_1m" ? "text-t-hi font-semibold" : pclr(stock.change_1m))}>{fmtPct(stock.change_1m)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", sortCol === "market_cap" ? "text-t-hi font-semibold" : "text-t-mid2")}>{fmtBig(stock.market_cap)}</td>
                  <td className={cn("py-2.5 px-3 text-right font-mono-t tabular-nums", sortCol === "volume" ? "text-t-hi font-semibold" : "text-t-mid2")}>{fmtBig(stock.volume)}</td>
                  <td className="py-2.5 px-3 text-center">
                    <Sparkline data={stock.sparkline_1m ?? []} positive={(stock.change_1m ?? 0) >= 0} />
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <ScoutButton symbol={stock.symbol} />
                  </td>
                  <td className="py-2.5 px-2 text-center hidden sm:table-cell text-sm">🇺🇸</td>
                </tr>
              ))}
              {!isLoading && stocks.length === 0 && (
                <tr>
                  <td colSpan={11} className="py-10 text-center text-t-muted text-sm">No results</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <PrivateCompaniesSection />
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

type MarketTab = "stocks" | "crypto";

export default function MarketsPage() {
  const [tab, setTab] = useState<MarketTab>("stocks");

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5 animate-page-in">
      {/* Header */}
      <div>
        <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5">
          // MARKETS
        </p>
        <h1 className="text-2xl font-bold text-t-hi">Markets</h1>
        <p className="text-t-muted text-sm mt-1">
          Top stocks and crypto. Click any row to open its chart. Click ⚒ Scout to scan with Strategy Scout.
        </p>
      </div>

      {/* Tab selector */}
      <div className="flex gap-1 bg-t-bg1 border border-t-dim rounded-xl p-1 w-fit">
        {([
          { key: "stocks", label: "// STOCKS" },
          { key: "crypto", label: "// CRYPTO" },
        ] as { key: MarketTab; label: string }[]).map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={cn("px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors",
              tab === t.key ? "bg-t-bg2 text-t-hi" : "text-t-muted hover:text-t-mid2")}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "stocks" && <StocksTab />}
      {tab === "crypto" && <CryptoTab />}
    </div>
  );
}
