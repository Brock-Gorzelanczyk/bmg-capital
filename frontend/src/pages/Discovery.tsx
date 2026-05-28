import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { TrendingUp, TrendingDown, ExternalLink, RefreshCw, AlertTriangle, Vote, Zap, Flame } from "lucide-react";
import { cn } from "@/lib/utils";
import { getThemes, getIPOs, getInsiders, getSectorPerformance, getCryptoLaunches, getNarratives, getIdoCalendar, getMemecoins } from "@/api/discovery";
import { getGovernanceProposals } from "@/api/governance";
import type { Theme, IPO, InsiderTrade, CryptoLaunch, Narrative, IdoEvent } from "@/api/discovery";

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
      <p className="text-[var(--text-tertiary)] text-sm">Upcoming and recent IPOs via Nasdaq.</p>
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
        <p className="text-[var(--text-tertiary)] text-sm">Recent Form 4 filings via OpenInsider (SEC data).</p>
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

// ── Crypto Launches Tab ─────────────────────────────────────────────────────

function fmtLiquidity(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function CryptoLaunchCard({ token }: { token: CryptoLaunch }) {
  const pos = token.price_change_24h >= 0;
  const riskColor = !token.risk_score ? "" : token.risk_score >= 7 ? "border-red-800" : token.risk_score >= 4 ? "border-amber-800" : "border-emerald-800";
  return (
    <div className={cn("bg-[var(--bg-elevated-2)] border rounded-xl p-3 flex items-center gap-3", riskColor || "border-[var(--border)]")}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-bold text-[var(--text-primary)] font-mono text-sm">{token.symbol}</span>
          <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated)] px-1.5 py-0.5 rounded">{token.chain}</span>
          <span className="text-[10px] text-[var(--text-tertiary)] hidden sm:inline">{token.dex}</span>
          {token.risk_score !== undefined && token.risk_score >= 7 && (
            <span className="text-[10px] font-semibold text-red-400 flex items-center gap-0.5"><AlertTriangle size={9} /> High risk</span>
          )}
        </div>
        <div className="text-xs text-[var(--text-tertiary)] truncate mt-0.5">{token.name}</div>
        <div className="text-[10px] text-[var(--text-tertiary)] mt-1">
          Vol {fmtLiquidity(token.volume_24h)} · Liq {fmtLiquidity(token.liquidity_usd)} · {token.age_hours < 24 ? `${token.age_hours.toFixed(0)}h old` : `${(token.age_hours/24).toFixed(0)}d old`}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="font-mono text-sm text-[var(--text-primary)]">${token.price_usd < 0.001 ? token.price_usd.toExponential(2) : token.price_usd < 1 ? token.price_usd.toFixed(6) : token.price_usd.toFixed(3)}</div>
        <div className={cn("text-xs font-mono font-semibold", pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
          {pos ? "+" : ""}{token.price_change_24h.toFixed(1)}%
        </div>
      </div>
      <a href={token.url} target="_blank" rel="noopener noreferrer" className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors ml-1">
        <ExternalLink size={13} />
      </a>
    </div>
  );
}

function CryptoLaunchesTab() {
  const [subTab, setSubTab] = useState<"new" | "trending" | "meme">("new");
  const { data: newData, isLoading: loadingNew } = useQuery({ queryKey: ["crypto-launches"], queryFn: () => getCryptoLaunches(), staleTime: 5 * 60_000 });
  const { data: memeData, isLoading: loadingMeme } = useQuery({ queryKey: ["crypto-memecoins"], queryFn: () => getMemecoins(), staleTime: 5 * 60_000 });

  const tokens = subTab === "new" ? (newData?.launches ?? []) : subTab === "meme" ? (memeData?.tokens ?? []) : [];
  const isLoading = subTab === "new" ? loadingNew : subTab === "meme" ? loadingMeme : false;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 justify-between flex-wrap">
        <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl">
          {([["new","⚡ New Launches"],["meme","🔥 Memecoins"]] as const).map(([id,label]) => (
            <button key={id} onClick={() => setSubTab(id)} className={cn("px-3 py-1 rounded-lg text-xs font-semibold transition-colors", subTab===id?"bg-[var(--bg-elevated)] text-[var(--text-primary)]":"text-[var(--text-tertiary)]")}>{label}</button>
          ))}
        </div>
        {subTab === "meme" && (
          <div className="text-xs text-amber-400 flex items-center gap-1"><AlertTriangle size={11} />High risk — most memecoins fail</div>
        )}
      </div>
      {isLoading ? (
        <div className="space-y-2">{[...Array(8)].map((_,i)=><div key={i} className="h-16 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse"/>)}</div>
      ) : tokens.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">No tokens found — data refreshes every 5 minutes</div>
      ) : (
        <div className="space-y-2">{tokens.map((t,i)=><CryptoLaunchCard key={t.address || i} token={t}/>)}</div>
      )}
    </div>
  );
}

// ── Narratives Tab ───────────────────────────────────────────────────────────

function NarrativesTab() {
  const { data, isLoading } = useQuery({ queryKey: ["crypto-narratives"], queryFn: getNarratives, staleTime: 10 * 60_000 });
  const narratives = data?.narratives ?? [];

  return (
    <div className="space-y-3">
      <p className="text-[var(--text-tertiary)] text-sm">Thematic crypto baskets — performance reflects current 24h change of constituent tokens</p>
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{[...Array(6)].map((_,i)=><div key={i} className="h-36 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse"/>)}</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {narratives.map((n: Narrative) => {
            const pos = n.avg_pct_24h >= 0;
            return (
              <div key={n.id} className="bg-[var(--bg-elevated-2)] border border-[var(--border)] rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{n.emoji}</span>
                    <span className="font-semibold text-[var(--text-primary)] text-sm">{n.name}</span>
                  </div>
                  <span className={cn("text-sm font-bold font-mono", pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                    {pos ? "+" : ""}{n.avg_pct_24h.toFixed(2)}%
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {n.coins_data.slice(0, 6).map((c) => (
                    <span key={c.id} className={cn(
                      "text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border",
                      (c.pct_24h ?? 0) >= 0 ? "bg-emerald-950/50 border-emerald-800 text-[var(--accent-positive)]" : "bg-rose-950/50 border-rose-800 text-[var(--accent-negative)]"
                    )}>
                      {c.symbol || c.id} {c.pct_24h !== 0 && <span className="opacity-70">{(c.pct_24h >= 0 ? "+" : "")}{c.pct_24h.toFixed(1)}%</span>}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── IDO Calendar Tab ─────────────────────────────────────────────────────────

function IdoCalendarTab() {
  const { data, isLoading } = useQuery({ queryKey: ["ido-calendar"], queryFn: getIdoCalendar, staleTime: 30 * 60_000 });
  const events = data?.events ?? [];

  return (
    <div className="space-y-3">
      <p className="text-[var(--text-tertiary)] text-sm">Upcoming token sales, IDOs, and launchpad events</p>
      {isLoading ? (
        <div className="space-y-2">{[...Array(4)].map((_,i)=><div key={i} className="h-24 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse"/>)}</div>
      ) : events.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">No upcoming events</div>
      ) : (
        <div className="space-y-2">
          {events.map((e: IdoEvent) => (
            <div key={e.project + e.date} className={cn("bg-[var(--bg-elevated-2)] border rounded-xl p-4", e.status === "upcoming" ? "border-violet-800/50" : "border-[var(--border)]")}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-bold text-[var(--text-primary)] text-sm">{e.project}</span>
                    <span className="font-mono text-xs text-violet-400">{e.token}</span>
                    <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded", e.status==="upcoming"?"bg-violet-950/60 text-violet-400":"bg-[var(--bg-elevated)] text-[var(--text-tertiary)]")}>
                      {e.status === "upcoming" ? "Upcoming" : "Priced"}
                    </span>
                  </div>
                  <div className="text-xs text-[var(--text-tertiary)] mb-1">{e.description}</div>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {e.tags.map(t=><span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-tertiary)]">{t}</span>)}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xs text-[var(--text-secondary)] font-mono">{e.date}</div>
                  <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{e.type}</div>
                  <div className="text-[10px] text-[var(--text-tertiary)]">{e.platform}</div>
                  {e.est_raise_usd && <div className="text-[10px] text-violet-400 mt-1">${(e.est_raise_usd/1_000_000).toFixed(0)}M raise</div>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Governance Tab ───────────────────────────────────────────────────────────

function GovernanceTab() {
  const { data, isLoading } = useQuery({ queryKey: ["governance-proposals"], queryFn: () => getGovernanceProposals("active"), staleTime: 5 * 60_000 });
  const proposals = data?.proposals ?? [];

  return (
    <div className="space-y-3">
      <p className="text-[var(--text-tertiary)] text-sm">Active DAO governance proposals — Uniswap, Aave, Compound, and more</p>
      {isLoading ? (
        <div className="space-y-2">{[...Array(5)].map((_,i)=><div key={i} className="h-28 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse"/>)}</div>
      ) : proposals.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">No active proposals right now</div>
      ) : (
        <div className="space-y-2">
          {proposals.map((p) => {
            const daysLeft = Math.max(0, Math.ceil((p.end * 1000 - Date.now()) / 86_400_000));
            const topPct = p.scores_total > 0 ? Math.round((Math.max(...p.scores) / p.scores_total) * 100) : 0;
            const winIdx = p.scores.indexOf(Math.max(...p.scores));
            return (
              <div key={p.id} className="bg-[var(--bg-elevated-2)] border border-[var(--border)] rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] font-semibold text-blue-400 bg-blue-950/40 px-1.5 py-0.5 rounded">{p.space_name}</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">{daysLeft}d left</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">{p.votes.toLocaleString()} votes</span>
                    </div>
                    <div className="font-medium text-sm text-[var(--text-primary)] line-clamp-2 mb-1">{p.title}</div>
                    <div className="text-xs text-[var(--text-tertiary)] line-clamp-2">{p.summary}</div>
                    {p.choices.length > 0 && (
                      <div className="mt-2 flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
                          <div className="h-full bg-[var(--accent-positive)] rounded-full" style={{width:`${topPct}%`}}/>
                        </div>
                        <span className="text-[10px] font-mono text-[var(--accent-positive)]">{p.choices[winIdx]} {topPct}%</span>
                      </div>
                    )}
                  </div>
                  <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] mt-0.5">
                    <ExternalLink size={13} />
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

const TABS = [
  { id: "themes",    label: "🎯 Themes" },
  { id: "sectors",   label: "🗺️ Sector Map" },
  { id: "ipos",      label: "🚀 IPO Calendar" },
  { id: "insiders",  label: "👤 Insiders" },
  { id: "launches",  label: "⚡ Crypto Launches" },
  { id: "narratives",label: "🌐 Narratives" },
  { id: "ido",       label: "🪙 IDO Calendar" },
  { id: "governance",label: "🗳️ Governance" },
] as const;

type Tab = typeof TABS[number]["id"];

export default function Discovery() {
  const [tab, setTab] = useState<Tab>("themes");

  return (
    <div className="space-y-5 pb-8">
      <div>
        <h1 className="text-xl font-bold text-[var(--text-primary)]">Discovery</h1>
        <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Explore themes, sectors, IPOs, crypto launches, narratives, and governance</p>
      </div>

      <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl w-fit flex-wrap">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap",
              tab === id ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div>
        {tab === "themes"     && <ThemesTab />}
        {tab === "sectors"    && <SectorHeatmap />}
        {tab === "ipos"       && <IPOsTab />}
        {tab === "insiders"   && <InsidersTab />}
        {tab === "launches"   && <CryptoLaunchesTab />}
        {tab === "narratives" && <NarrativesTab />}
        {tab === "ido"        && <IdoCalendarTab />}
        {tab === "governance" && <GovernanceTab />}
      </div>
    </div>
  );
}
