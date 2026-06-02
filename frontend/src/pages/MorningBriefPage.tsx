import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Clipboard, Check, Headphones, X, Play, Pause, TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import client from "@/api/client";
import type { DailyRecap } from "@/api/recap";
import type { IndexSnapshot, EarningsEvent } from "@/types/market";
import type { Watchlist } from "@/types/watchlist";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn, formatPercent } from "@/lib/utils";

// ── Greeting helper ────────────────────────────────────────────────────────────

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

// ── Section header ─────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-bold tracking-widest text-[var(--text-tertiary)] uppercase mb-2">
      {children}
    </div>
  );
}

// ── Market move card ───────────────────────────────────────────────────────────

interface MarketCardProps {
  symbol: string;
  change_pct: number | null;
  loading?: boolean;
}

function MarketCard({ symbol, change_pct, loading }: MarketCardProps) {
  if (loading) {
    return (
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-1">
        <Skeleton height={14} className="w-10" />
        <Skeleton height={22} className="w-16" />
      </div>
    );
  }

  const pct = change_pct ?? 0;
  const isPos = pct > 0;
  const isNeg = pct < 0;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-1">
      <span className="text-xs font-semibold text-[var(--text-tertiary)] font-mono">{symbol}</span>
      <div className="flex items-center gap-1">
        {isPos ? (
          <TrendingUp size={14} className="text-[#22C55E]" />
        ) : isNeg ? (
          <TrendingDown size={14} className="text-[#EF4444]" />
        ) : (
          <Minus size={14} className="text-[var(--text-tertiary)]" />
        )}
        <span
          className={cn(
            "text-sm font-bold font-mono tabular-nums",
            isPos ? "text-[#22C55E]" : isNeg ? "text-[#EF4444]" : "text-[var(--text-tertiary)]"
          )}
        >
          {change_pct != null ? formatPercent(pct) : "—"}
        </span>
      </div>
    </div>
  );
}

// ── Watchlist ticker chip ─────────────────────────────────────────────────────

interface TickerChipProps {
  symbol: string;
  change_pct: number | null;
}

function TickerChip({ symbol, change_pct }: TickerChipProps) {
  const pct = change_pct ?? 0;
  const isPos = pct > 0;
  const isNeg = pct < 0;

  return (
    <div className="flex-shrink-0 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 flex flex-col gap-0.5">
      <span className="text-xs font-bold font-mono text-[var(--text-primary)]">{symbol}</span>
      <span
        className={cn(
          "text-xs font-mono tabular-nums",
          isPos ? "text-[#22C55E]" : isNeg ? "text-[#EF4444]" : "text-[var(--text-tertiary)]"
        )}
      >
        {change_pct != null ? formatPercent(pct) : "—"}
      </span>
    </div>
  );
}

// ── Audio mode modal ──────────────────────────────────────────────────────────

interface AudioModalProps {
  text: string;
  onClose: () => void;
}

function AudioModal({ text, onClose }: AudioModalProps) {
  const [playing, setPlaying] = useState(false);

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-end md:items-center justify-center p-4">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 w-full max-w-md space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Headphones size={16} className="text-[#3B82F6]" />
            <span className="text-sm font-semibold text-[var(--text-primary)]">Audio Mode</span>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            <X size={16} />
          </button>
        </div>

        {/* Waveform animation */}
        <div className="flex items-center justify-center gap-1 h-10">
          {Array.from({ length: 16 }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "w-1 rounded-full transition-all",
                playing ? "bg-[#3B82F6]" : "bg-[var(--border-subtle)]"
              )}
              style={{
                height: playing ? `${20 + Math.sin(i * 0.8) * 14}px` : "8px",
                animation: playing ? `pulse ${0.4 + (i % 4) * 0.1}s ease-in-out infinite alternate` : "none",
              }}
            />
          ))}
        </div>

        {/* Play / pause */}
        <button
          onClick={() => setPlaying((p) => !p)}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-[#3B82F6] text-white text-sm font-semibold hover:bg-blue-600 transition-colors cursor-pointer"
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
          {playing ? "Pause" : "Play Brief"}
        </button>

        {/* Brief text */}
        <div className="max-h-48 overflow-y-auto rounded-xl bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] p-3">
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-line">
            {text || "No brief text available."}
          </p>
        </div>

        <p className="text-[10px] text-center text-[var(--text-tertiary)]">
          Audio playback coming soon — UI preview only
        </p>
      </div>
    </div>
  );
}

// ── Interfaces for API responses ──────────────────────────────────────────────

interface MarketOverviewItem extends IndexSnapshot {
  symbol: string;
  change_pct: number;
}

interface EarningsToday {
  earnings: EarningsEvent[];
}

interface WatchlistResponse {
  watchlists: Watchlist[];
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MorningBriefPage() {
  const [copied, setCopied] = useState(false);
  const [audioOpen, setAudioOpen] = useState(false);

  const now = new Date();
  const dateLabel = now.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const timeLabel = now.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  const greeting = getGreeting();

  // ── Queries ───────────────────────────────────────────────────────────────

  const { data: recap, isLoading: recapLoading } = useQuery<DailyRecap | null>({
    queryKey: ["recap-latest"],
    queryFn: () => client.get("/api/recap/latest").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const { data: marketRaw, isLoading: marketLoading } = useQuery<MarketOverviewItem[]>({
    queryKey: ["market-overview"],
    queryFn: () => client.get("/api/market/overview").then(r => r.data?.indices ?? r.data ?? []),
    staleTime: 60_000,
  });

  const { data: watchlistRaw, isLoading: watchlistLoading } = useQuery<WatchlistResponse>({
    queryKey: ["watchlist"],
    queryFn: () => client.get("/api/watchlist").then(r => r.data),
    staleTime: 60_000,
  });

  const { data: earningsRaw, isLoading: earningsLoading } = useQuery<EarningsToday>({
    queryKey: ["earnings-today"],
    queryFn: () => client.get("/api/earnings/today").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  // ── Derived data ──────────────────────────────────────────────────────────

  const marketIndices = Array.isArray(marketRaw) ? marketRaw : [];
  const FEATURED_SYMBOLS = ["SPY", "QQQ", "BTC", "VIX"];

  const getMarketItem = (sym: string): MarketOverviewItem | undefined =>
    marketIndices.find(
      (m) => m.symbol.toUpperCase() === sym || m.symbol.toUpperCase().startsWith(sym)
    );

  // Flatten watchlist items
  const watchlistItems = watchlistRaw?.watchlists?.flatMap((wl) => wl.items) ?? [];

  // Deduplicate by symbol
  const seenSymbols = new Set<string>();
  const uniqueWatchlistItems = watchlistItems.filter((item) => {
    if (seenSymbols.has(item.symbol)) return false;
    seenSymbols.add(item.symbol);
    return true;
  });

  const earnings = earningsRaw?.earnings ?? [];

  // ── Copy summary builder ──────────────────────────────────────────────────

  const buildSummaryMarkdown = () => {
    const marketLines = FEATURED_SYMBOLS.map((sym) => {
      const item = getMarketItem(sym);
      const pct = item ? formatPercent(item.change_pct) : "—";
      return `- ${sym}: ${pct}`;
    }).join(" | ");

    const watchlistLines = uniqueWatchlistItems
      .map((item) => {
        const marketItem = getMarketItem(item.symbol);
        const pct = marketItem ? formatPercent(marketItem.change_pct) : "—";
        return `- ${item.symbol}: ${pct}`;
      })
      .join("\n");

    const earningsLines =
      earnings.length > 0
        ? earnings
            .map((e) => `- ${e.symbol} (${e.time === "pre" ? "before open" : "after close"})`)
            .join("\n")
        : "- No earnings on your watchlist today";

    return [
      `# BMG Capital Morning Brief — ${now.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}`,
      "",
      "## Overnight Moves",
      marketLines,
      "",
      "## Your Watchlist",
      watchlistLines || "- No watchlist items",
      "",
      "## Earnings Today",
      earningsLines,
      "",
      "## Market Narrative",
      recap?.narrative ?? "AI brief not yet generated for today.",
      "",
      "---",
      "*Generated by BMG Capital*",
    ].join("\n");
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(buildSummaryMarkdown()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const audioText = [
    `${greeting}. Here's your BMG Capital Morning Brief for ${dateLabel}.`,
    "",
    "Overnight Moves:",
    FEATURED_SYMBOLS.map((sym) => {
      const item = getMarketItem(sym);
      const pct = item ? formatPercent(item.change_pct) : "no data";
      return `${sym}: ${pct}`;
    }).join(". "),
    "",
    recap?.narrative ?? "AI narrative not available.",
  ].join("\n");

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <>
      <div className="max-w-xl mx-auto space-y-5 pb-8">
        {/* Header */}
        <div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">☀️</span>
              <h1 className="text-base font-semibold text-[var(--text-primary)]">Morning Brief</h1>
            </div>
            <span className="text-xs text-[var(--text-tertiary)] font-mono">{dateLabel} · {timeLabel}</span>
          </div>
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
            {greeting} · Personalized for you
          </p>
        </div>

        <div className="border-t border-[var(--border-subtle)]" />

        {/* Overnight moves */}
        <div>
          <SectionLabel>Overnight Moves</SectionLabel>
          <div className="grid grid-cols-2 gap-2">
            {FEATURED_SYMBOLS.map((sym) => {
              const item = getMarketItem(sym);
              return (
                <MarketCard
                  key={sym}
                  symbol={sym}
                  change_pct={item?.change_pct ?? null}
                  loading={marketLoading}
                />
              );
            })}
          </div>
        </div>

        {/* Watchlist */}
        <div>
          <SectionLabel>Your Watchlist</SectionLabel>
          {watchlistLoading ? (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex-shrink-0">
                  <Skeleton height={52} className="w-20 rounded-lg" />
                </div>
              ))}
            </div>
          ) : uniqueWatchlistItems.length === 0 ? (
            <p className="text-xs text-[var(--text-tertiary)]">No watchlist items yet.</p>
          ) : (
            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
              {uniqueWatchlistItems.map((item) => {
                const marketItem = getMarketItem(item.symbol);
                return (
                  <TickerChip
                    key={item.symbol}
                    symbol={item.symbol}
                    change_pct={marketItem?.change_pct ?? null}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* Earnings today */}
        <div>
          <SectionLabel>Earnings Today</SectionLabel>
          {earningsLoading ? (
            <Skeleton height={40} />
          ) : earnings.length === 0 ? (
            <p className="text-xs text-[var(--text-tertiary)]">No earnings on your watchlist today.</p>
          ) : (
            <div className="space-y-2">
              {earnings.map((e) => (
                <div
                  key={e.symbol}
                  className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-2.5 flex items-center justify-between"
                >
                  <span className="text-sm font-bold font-mono text-[var(--text-primary)]">
                    {e.symbol}
                  </span>
                  <span className="text-xs text-[var(--text-tertiary)]">
                    {e.time === "pre" ? "before open" : "after close"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Macro headline from recap */}
        {(recapLoading || recap?.market_summary) && (
          <div>
            <SectionLabel>Macro Headline</SectionLabel>
            {recapLoading ? (
              <Skeleton height={40} />
            ) : recap?.market_summary ? (
              <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
                <div className="flex gap-4 text-xs font-mono tabular-nums text-[var(--text-secondary)]">
                  {recap.market_summary.spy != null && (
                    <span>
                      SPY{" "}
                      <span className={recap.market_summary.spy >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}>
                        {formatPercent(recap.market_summary.spy)}
                      </span>
                    </span>
                  )}
                  {recap.market_summary.qqq != null && (
                    <span>
                      QQQ{" "}
                      <span className={recap.market_summary.qqq >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}>
                        {formatPercent(recap.market_summary.qqq)}
                      </span>
                    </span>
                  )}
                  {recap.market_summary.vix != null && (
                    <span>
                      VIX{" "}
                      <span className={recap.market_summary.vix >= 0 ? "text-[#F59E0B]" : "text-[#22C55E]"}>
                        {formatPercent(recap.market_summary.vix)}
                      </span>
                    </span>
                  )}
                  {recap.market_summary.breadth && (
                    <span className="capitalize text-[var(--text-tertiary)]">
                      {recap.market_summary.breadth}
                    </span>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* AI Narrative */}
        <div>
          <SectionLabel>AI Narrative</SectionLabel>
          {recapLoading ? (
            <Skeleton rows={3} height={14} />
          ) : recap?.narrative ? (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                {recap.narrative}
              </p>
            </div>
          ) : (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
              <p className="text-xs text-[var(--text-tertiary)] italic">
                AI brief not yet generated for today — check back after 7:30am.
              </p>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 pt-2">
          <button
            onClick={handleCopy}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            {copied ? (
              <>
                <Check size={14} className="text-[#22C55E]" />
                Copied!
              </>
            ) : (
              <>
                <Clipboard size={14} />
                Copy summary
              </>
            )}
          </button>
          <button
            onClick={() => setAudioOpen(true)}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            <Headphones size={14} />
            Audio mode
          </button>
        </div>
      </div>

      {/* Audio modal */}
      {audioOpen && (
        <AudioModal text={audioText} onClose={() => setAudioOpen(false)} />
      )}
    </>
  );
}
