import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clipboard, Check, Headphones, RefreshCw, Mic,
  TrendingUp, TrendingDown, Minus, X, Play, Pause,
  Zap, Moon, Calendar,
} from "lucide-react";
import client from "@/api/client";
import { getLatestBrief, type BriefSection, type DailyBrief } from "@/api/dailyBrief";
import type { DailyRecap } from "@/api/recap";
import type { IndexSnapshot, EarningsEvent } from "@/types/market";
import type { Watchlist } from "@/types/watchlist";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn, formatPercent } from "@/lib/utils";
import VoiceAIModal from "@/components/voice/VoiceAIModal";

// ── Greeting helper ────────────────────────────────────────────────────────────

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

// ── Reading level types ────────────────────────────────────────────────────────

type ReadingLevel = "pro" | "investor" | "beginner" | "eli5";

const READING_LEVELS: { id: ReadingLevel; label: string }[] = [
  { id: "pro", label: "Pro" },
  { id: "investor", label: "Investor" },
  { id: "beginner", label: "Beginner" },
  { id: "eli5", label: "ELI5" },
];

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

  const handlePlayPause = () => {
    if (!window.speechSynthesis) return;
    if (playing) {
      window.speechSynthesis.cancel();
      setPlaying(false);
    } else {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.onend = () => setPlaying(false);
      window.speechSynthesis.speak(utterance);
      setPlaying(true);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-end md:items-center justify-center p-4">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 w-full max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Headphones size={16} className="text-[#3B82F6]" />
            <span className="text-sm font-semibold text-[var(--text-primary)]">Listen to Brief</span>
          </div>
          <button
            onClick={() => {
              window.speechSynthesis?.cancel();
              onClose();
            }}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            <X size={16} />
          </button>
        </div>

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
                animation: playing
                  ? `pulse ${0.4 + (i % 4) * 0.1}s ease-in-out infinite alternate`
                  : "none",
              }}
            />
          ))}
        </div>

        <button
          onClick={handlePlayPause}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-[#3B82F6] text-white text-sm font-semibold hover:bg-blue-600 transition-colors cursor-pointer"
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
          {playing ? "Pause" : "Play Brief"}
        </button>

        <div className="max-h-48 overflow-y-auto rounded-xl bg-[var(--bg-elevated-2,var(--bg-base))] border border-[var(--border-subtle)] p-3">
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-line">
            {text || "No brief text available."}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Section icon helper ────────────────────────────────────────────────────────

function SectionIcon({ icon }: { icon: string }) {
  const cls = "w-4 h-4 text-[#84cc16]";
  switch (icon) {
    case "moon": return <Moon className={cls} />;
    case "zap": return <Zap className={cls} />;
    case "calendar": return <Calendar className={cls} />;
    case "trending-up": return <TrendingUp className={cls} />;
    default: return <Zap className={cls} />;
  }
}

// ── AI Brief Section Card ─────────────────────────────────────────────────────

interface BriefSectionCardProps {
  section: BriefSection;
  onAskAI: (context: string) => void;
}

function BriefSectionCard({ section, onAskAI }: BriefSectionCardProps) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SectionIcon icon={section.icon} />
          <span className="text-xs font-bold text-[var(--text-primary)]">{section.title}</span>
        </div>
        <button
          onClick={() => onAskAI(section.id)}
          className="flex items-center gap-1 text-xs text-[#84cc16] hover:text-[#a3e635] transition-colors"
          title="Ask AI about this section"
        >
          <Mic className="w-3 h-3" />
          Ask AI
        </button>
      </div>
      <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{section.content}</p>
      {section.symbols && section.symbols.length > 0 && (
        <div className="flex gap-1 flex-wrap pt-1">
          {section.symbols.map(sym => (
            <span
              key={sym}
              className="text-[10px] font-mono bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded px-1.5 py-0.5 text-[var(--text-tertiary)]"
            >
              {sym}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Interfaces for legacy API responses ───────────────────────────────────────

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
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [readingLevel, setReadingLevel] = useState<ReadingLevel>("investor");
  const queryClient = useQueryClient();

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

  const {
    data: brief,
    isLoading: briefLoading,
    isFetching: briefFetching,
  } = useQuery<DailyBrief>({
    queryKey: ["daily-brief-latest", readingLevel],
    queryFn: () => getLatestBrief(readingLevel),
    staleTime: 5 * 60_000,
  });

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
      m => m.symbol.toUpperCase() === sym || m.symbol.toUpperCase().startsWith(sym)
    );

  const watchlistItems = watchlistRaw?.watchlists?.flatMap(wl => wl.items) ?? [];
  const seenSymbols = new Set<string>();
  const uniqueWatchlistItems = watchlistItems.filter(item => {
    if (seenSymbols.has(item.symbol)) return false;
    seenSymbols.add(item.symbol);
    return true;
  });

  const earnings = earningsRaw?.earnings ?? [];

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["daily-brief-latest", readingLevel] });
  }, [queryClient, readingLevel]);

  const handleAskAI = useCallback((_context: string) => {
    setVoiceOpen(true);
  }, []);

  const buildSummaryMarkdown = () => {
    const marketLines = FEATURED_SYMBOLS.map(sym => {
      const item = getMarketItem(sym);
      return `- ${sym}: ${item ? formatPercent(item.change_pct) : "—"}`;
    }).join(" | ");

    const watchlistLines = uniqueWatchlistItems
      .map(item => {
        const marketItem = getMarketItem(item.symbol);
        return `- ${item.symbol}: ${marketItem ? formatPercent(marketItem.change_pct) : "—"}`;
      })
      .join("\n");

    const earningsLines =
      earnings.length > 0
        ? earnings
            .map(e => `- ${e.symbol} (${e.time === "pre" ? "before open" : "after close"})`)
            .join("\n")
        : "- No earnings on your watchlist today";

    const aiSections = brief?.sections?.map(s => `### ${s.title}\n${s.content}`).join("\n\n") ?? "";

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
      aiSections ? "## AI Brief" : "",
      aiSections,
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

  // Build full text for audio playback
  const buildAudioText = () => {
    const parts: string[] = [
      `${greeting}. Here's your BMG Capital Morning Brief for ${dateLabel}.`,
      "",
    ];
    if (brief?.sections) {
      for (const s of brief.sections) {
        parts.push(s.title + ": " + s.content);
      }
    } else {
      parts.push(
        "Overnight Moves: " +
          FEATURED_SYMBOLS.map(sym => {
            const item = getMarketItem(sym);
            return `${sym}: ${item ? formatPercent(item.change_pct) : "no data"}`;
          }).join(". ")
      );
      if (recap?.narrative) parts.push(recap.narrative);
    }
    return parts.join("\n");
  };

  const fmtGeneratedAt = (iso: string | undefined) => {
    if (!iso) return null;
    try {
      return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    } catch {
      return null;
    }
  };

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
            <div className="flex items-center gap-2">
              {brief?.generated_at && (
                <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
                  Generated {fmtGeneratedAt(brief.generated_at)}
                </span>
              )}
              <button
                onClick={handleRefresh}
                disabled={briefFetching}
                className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors disabled:opacity-50"
                title="Refresh brief"
              >
                <RefreshCw className={cn("w-3.5 h-3.5", briefFetching && "animate-spin")} />
              </button>
              <span className="text-xs text-[var(--text-tertiary)] font-mono">{dateLabel} · {timeLabel}</span>
            </div>
          </div>
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
            {greeting} · Personalized for you
          </p>
        </div>

        {/* Reading level selector */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-[var(--text-tertiary)] mr-1 font-medium uppercase tracking-wider">Level:</span>
          {READING_LEVELS.map(lvl => (
            <button
              key={lvl.id}
              onClick={() => setReadingLevel(lvl.id)}
              className={cn(
                "px-2.5 py-1 rounded-full text-xs font-medium transition-colors",
                readingLevel === lvl.id
                  ? "bg-[#84cc16] text-black"
                  : "border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              )}
            >
              {lvl.label}
            </button>
          ))}
        </div>

        <div className="border-t border-[var(--border-subtle)]" />

        {/* AI Brief Sections */}
        {briefLoading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map(i => (
              <Skeleton key={i} height={80} className="rounded-xl" />
            ))}
          </div>
        ) : brief?.sections && brief.sections.length > 0 ? (
          <div className="space-y-3">
            {brief.sections.map(section => (
              <BriefSectionCard
                key={section.id ?? section.title}
                section={section}
                onAskAI={handleAskAI}
              />
            ))}
          </div>
        ) : (
          <>
            {/* Fallback: legacy layout with market data */}
            {/* Overnight moves */}
            <div>
              <SectionLabel>Overnight Moves</SectionLabel>
              <div className="grid grid-cols-2 gap-2">
                {FEATURED_SYMBOLS.map(sym => {
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
                  {[1, 2, 3, 4].map(i => (
                    <div key={i} className="flex-shrink-0">
                      <Skeleton height={52} className="w-20 rounded-lg" />
                    </div>
                  ))}
                </div>
              ) : uniqueWatchlistItems.length === 0 ? (
                <p className="text-xs text-[var(--text-tertiary)]">No watchlist items yet.</p>
              ) : (
                <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
                  {uniqueWatchlistItems.map(item => {
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
                  {earnings.map(e => (
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
          </>
        )}

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
            Listen
          </button>
          <button
            onClick={() => setVoiceOpen(true)}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-[#84cc16] text-black font-semibold text-sm hover:bg-[#a3e635] transition-colors cursor-pointer"
          >
            <Mic size={14} />
            Ask AI
          </button>
        </div>
      </div>

      {/* Modals */}
      {audioOpen && (
        <AudioModal text={buildAudioText()} onClose={() => setAudioOpen(false)} />
      )}
      <VoiceAIModal open={voiceOpen} onClose={() => setVoiceOpen(false)} />
    </>
  );
}
