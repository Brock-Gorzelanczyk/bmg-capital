import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { TrendingUp, TrendingDown, ExternalLink, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { getThemes, getIPOs, getInsiders, getSectorPerformance } from "@/api/discovery";
import type { Theme, IPO, InsiderTrade } from "@/api/discovery";

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtPct(n: number) {
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function fmtValue(n: number) {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n}`;
}

function ChangePill({ value, className }: { value: number; className?: string }) {
  const pos = value >= 0;
  return (
    <span className={cn(
      "text-xs font-mono font-semibold",
      pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]",
      className
    )}>
      {fmtPct(value)}
    </span>
  );
}

// ── Sector Heatmap ──────────────────────────────────────────────────────────

function SectorHeatmap() {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["sectors"],
    queryFn: getSectorPerformance,
    staleTime: 60_000,
  });

  const sectors = data?.sectors ?? [];
  const max = Math.max(...sectors.map((s) => Math.abs(s.change_pct)), 0.01);

  function heatColor(pct: number): string {
    const intensity = Math.min(Math.abs(pct) / max, 1);
    if (pct > 0) {
      const g = Math.round(100 + intensity * 100);
      return `rgb(0, ${g}, 60)`;
    }
    const r = Math.round(100 + intensity * 120);
    return `rgb(${r}, 0, 30)`;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[var(--text-tertiary)] text-sm">Daily performance of SPDR sector ETFs</p>
        <button
          onClick={() => refetch()}
          className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>
      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
          {[...Array(11)].map((_, i) => (
            <div key={i} className="h-20 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : sectors.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">
          Sector data unavailable — add Alpaca API keys to enable live data
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
          {sectors
            .slice()
            .sort((a, b) => b.change_pct - a.change_pct)
            .map((s) => (
              <div
                key={s.sector}
                className="rounded-xl p-3 flex flex-col gap-1 transition-transform hover:scale-[1.02] cursor-default"
                style={{ backgroundColor: heatColor(s.change_pct) }}
              >
                <div className="text-[var(--text-primary)] font-semibold text-sm leading-tight">{s.sector}</div>
                <div className="text-[var(--text-primary)]/70 text-[11px] font-mono">{s.symbol}</div>
                <div className="flex items-center justify-between mt-auto">
                  <span className="text-[var(--text-primary)]/80 text-xs font-mono">${s.price.toFixed(2)}</span>
                  <span className="text-[var(--text-primary)] font-bold text-sm">{fmtPct(s.change_pct)}</span>
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

// ── Theme Colors ────────────────────────────────────────────────────────────

const COLOR_MAP: Record<string, string> = {
  violet: "border-violet-800 bg-violet-950/30",
  blue: "border-blue-800 bg-blue-950/30",
  sky: "border-sky-800 bg-sky-950/30",
  emerald: "border-emerald-800 bg-emerald-950/30",
  amber: "border-amber-800 bg-amber-950/30",
  orange: "border-orange-800 bg-orange-950/30",
  green: "border-green-800 bg-green-950/30",
  rose: "border-rose-800 bg-rose-950/30",
  slate: "border-slate-700 bg-slate-900/50",
  pink: "border-pink-800 bg-pink-950/30",
};

const TEXT_MAP: Record<string, string> = {
  violet: "text-violet-400",
  blue: "text-blue-400",
  sky: "text-sky-400",
  emerald: "text-[var(--accent-positive)]",
  amber: "text-amber-400",
  orange: "text-orange-400",
  green: "text-green-400",
  rose: "text-[var(--accent-negative)]",
  slate: "text-slate-300",
  pink: "text-pink-400",
};

// ── Theme Card ──────────────────────────────────────────────────────────────

function ThemeCard({ theme, onTickerClick }: { theme: Theme; onTickerClick: (s: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const colorClass = COLOR_MAP[theme.color] ?? COLOR_MAP.blue;
  const textClass = TEXT_MAP[theme.color] ?? TEXT_MAP.blue;
  const pos = theme.avg_change_pct >= 0;

  return (
    <div className={cn("border rounded-xl p-4 transition-colors hover:border-opacity-60 cursor-pointer", colorClass)}
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="text-2xl">{theme.emoji}</span>
          <div>
            <div className={cn("font-semibold text-sm", textClass)}>{theme.name}</div>
            <div className="text-[var(--text-tertiary)] text-xs mt-0.5 line-clamp-1">{theme.description}</div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className={cn("font-bold text-sm font-mono", pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            {fmtPct(theme.avg_change_pct)}
          </div>
          <div className="text-[var(--text-tertiary)] text-[10px]">avg today</div>
        </div>
      </div>

      {/* Constituent chips always visible */}
      <div className="flex flex-wrap gap-1.5 mt-3">
        {theme.constituents.slice(0, expanded ? undefined : 5).map((c) => (
          <button
            key={c.symbol}
            onClick={(e) => { e.stopPropagation(); onTickerClick(c.symbol); }}
            className={cn(
              "text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border transition-colors",
              c.change_pct >= 0
                ? "bg-emerald-950/50 border-emerald-800 text-[var(--accent-positive)] hover:bg-emerald-900/50"
                : "bg-rose-950/50 border-rose-800 text-[var(--accent-negative)] hover:bg-rose-900/50"
            )}
          >
            {c.symbol} {c.change_pct !== 0 && <span className="opacity-70">{fmtPct(c.change_pct)}</span>}
          </button>
        ))}
        {!expanded && theme.constituents.length > 5 && (
          <span className="text-[10px] text-[var(--text-tertiary)] self-center">+{theme.constituents.length - 5} more</span>
        )}
      </div>
    </div>
  );
}

// ── Themes Tab ──────────────────────────────────────────────────────────────

function ThemesTab() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["discovery-themes"],
    queryFn: getThemes,
    staleTime: 120_000,
  });
  const themes = data?.themes ?? [];

  return (
    <div className="space-y-3">
      <p className="text-[var(--text-tertiary)] text-sm">Curated baskets of stocks around major investment themes. Click a ticker to view its chart.</p>
      {isLoading ? (
        <div className="grid sm:grid-cols-2 gap-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-28 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-3">
          {themes.map((theme) => (
            <ThemeCard
              key={theme.id}
              theme={theme}
              onTickerClick={(s) => navigate(`/chart?symbol=${s}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── IPO Calendar Tab ────────────────────────────────────────────────────────

function IPOsTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["discovery-ipos"],
    queryFn: () => getIPOs(90),
    staleTime: 3_600_000,
  });
  const ipos: IPO[] = data?.ipos ?? [];

  const statusColor = (s: string) =>
    s === "upcoming" ? "text-[var(--accent-positive)] bg-emerald-950/50 border-emerald-800"
    : s === "priced" ? "text-blue-400 bg-blue-950/50 border-blue-800"
    : "text-amber-400 bg-amber-950/50 border-amber-800";

  return (
    <div className="space-y-3">
      <p className="text-[var(--text-tertiary)] text-sm">
        Upcoming and recent IPOs.{" "}
        {!ipos.length ? "" : <span className="text-[var(--text-tertiary)]">Showing demo data — add FMP API key for live listings.</span>}
      </p>
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-16 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="overflow-x-auto -mx-0">
          <table className="w-full text-sm min-w-[480px]">
            <thead>
              <tr className="border-b border-[var(--border-emphasis)] text-[var(--text-tertiary)] text-xs whitespace-nowrap">
                <th className="text-left px-4 py-3 font-medium">Company</th>
                <th className="text-left px-3 py-3 font-medium">Ticker</th>
                <th className="text-left px-3 py-3 font-medium hidden sm:table-cell">Exchange</th>
                <th className="text-left px-3 py-3 font-medium hidden md:table-cell">Price Range</th>
                <th className="text-left px-3 py-3 font-medium">Date</th>
                <th className="text-left px-3 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {ipos.map((ipo, i) => (
                <tr key={i} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/30 transition-colors">
                  <td className="px-4 py-3 text-[var(--text-primary)] font-medium">{ipo.company}</td>
                  <td className="px-3 py-3 font-mono text-[var(--text-secondary)]">{ipo.symbol}</td>
                  <td className="px-3 py-3 text-[var(--text-tertiary)] hidden sm:table-cell">{ipo.exchange}</td>
                  <td className="px-3 py-3 text-[var(--text-secondary)] hidden md:table-cell">{ipo.price_range}</td>
                  <td className="px-3 py-3 text-[var(--text-secondary)]">{ipo.date}</td>
                  <td className="px-3 py-3">
                    <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full border capitalize", statusColor(ipo.status))}>
                      {ipo.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {ipos.length === 0 && (
            <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">No upcoming IPOs found</div>
          )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Insider Trades Tab ──────────────────────────────────────────────────────

function InsidersTab() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"all" | "buy" | "sell">("all");

  const { data, isLoading } = useQuery({
    queryKey: ["discovery-insiders"],
    queryFn: () => getInsiders(50),
    staleTime: 300_000,
  });

  const all: InsiderTrade[] = data?.insiders ?? [];
  const filtered = filter === "all" ? all : all.filter((t) => t.transaction === filter);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[var(--text-tertiary)] text-sm">
          Recent Form 4 filings.{" "}
          <span className="text-[var(--text-tertiary)]">Showing demo data — add FMP API key for live filings.</span>
        </p>
        <div className="flex items-center gap-1 bg-[var(--bg-elevated-2)] p-0.5 rounded-lg">
          {(["all", "buy", "sell"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "text-xs px-2.5 py-1 rounded-md font-medium capitalize transition-colors",
                filter === f ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              )}
            >
              {f === "all" ? "All" : f === "buy" ? "🟢 Buys" : "🔴 Sells"}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-14 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="overflow-x-auto -mx-0">
          <table className="w-full text-sm min-w-[420px]">
            <thead>
              <tr className="border-b border-[var(--border-emphasis)] text-[var(--text-tertiary)] text-xs whitespace-nowrap">
                <th className="text-left px-4 py-3 font-medium">Symbol</th>
                <th className="text-left px-3 py-3 font-medium hidden sm:table-cell">Insider</th>
                <th className="text-left px-3 py-3 font-medium hidden md:table-cell">Title</th>
                <th className="text-center px-3 py-3 font-medium">Type</th>
                <th className="text-right px-3 py-3 font-medium hidden sm:table-cell">Shares</th>
                <th className="text-right px-3 py-3 font-medium">Value</th>
                <th className="text-right px-3 py-3 font-medium">Date</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => (
                <tr key={i} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/30 transition-colors">
                  <td className="px-4 py-3">
                    <button
                      onClick={() => navigate(`/chart?symbol=${t.symbol}`)}
                      className="font-mono font-bold text-[var(--text-primary)] hover:text-[var(--text-secondary)] transition-colors"
                    >
                      {t.symbol}
                    </button>
                  </td>
                  <td className="px-3 py-3 text-[var(--text-secondary)] hidden sm:table-cell max-w-[140px] truncate">{t.name}</td>
                  <td className="px-3 py-3 text-[var(--text-tertiary)] text-xs hidden md:table-cell">{t.title}</td>
                  <td className="px-3 py-3 text-center">
                    {t.transaction === "buy" ? (
                      <span className="inline-flex items-center gap-1 text-[var(--accent-positive)] text-xs font-semibold">
                        <TrendingUp size={11} /> Buy
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[var(--accent-negative)] text-xs font-semibold">
                        <TrendingDown size={11} /> Sell
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-[var(--text-secondary)] text-right font-mono text-xs hidden sm:table-cell">
                    {t.shares.toLocaleString()}
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-[var(--text-secondary)] text-xs">
                    {fmtValue(t.value)}
                  </td>
                  <td className="px-3 py-3 text-[var(--text-tertiary)] text-right text-xs">{t.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">No transactions found</div>
          )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

const TABS = [
  { id: "themes", label: "🎯 Themes" },
  { id: "sectors", label: "🗺️ Sector Map" },
  { id: "ipos", label: "🚀 IPO Calendar" },
  { id: "insiders", label: "👤 Insiders" },
] as const;

type Tab = typeof TABS[number]["id"];

export default function Discovery() {
  const [tab, setTab] = useState<Tab>("themes");

  return (
    <div className="space-y-5 pb-8">
      <div>
        <h1 className="text-xl font-bold text-[var(--text-primary)]">Discovery</h1>
        <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Explore themes, sector trends, IPOs, and insider activity</p>
      </div>

      <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl w-fit flex-wrap">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "px-4 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
              tab === id ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div>
        {tab === "themes" && <ThemesTab />}
        {tab === "sectors" && <SectorHeatmap />}
        {tab === "ipos" && <IPOsTab />}
        {tab === "insiders" && <InsidersTab />}
      </div>
    </div>
  );
}
