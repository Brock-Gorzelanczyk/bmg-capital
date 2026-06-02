import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { getMarketOverview } from "@/api/market";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn, formatPercent } from "@/lib/utils";

// ── Market pulse pill symbols ──────────────────────────────────────────────────

const PULSE_SYMBOLS = ["SPY", "QQQ", "VXX"];
const PULSE_LABELS: Record<string, string> = {
  SPY: "S&P 500",
  QQQ: "NASDAQ",
  VXX: "VIX",
};

// ── SSE streaming helper (same pattern as CopilotModal) ───────────────────────

function streamBrief(
  prompt: string,
  onDelta: (delta: string) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): () => void {
  const token = localStorage.getItem("bmg_token") ?? "";
  let cancelled = false;

  fetch("/api/copilot/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: prompt }],
      page: "Dashboard",
    }),
  })
    .then(async (resp) => {
      if (!resp.ok) {
        onError(`HTTP ${resp.status}`);
        return;
      }
      const reader = resp.body?.getReader();
      if (!reader) {
        onError("No body");
        return;
      }
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        if (cancelled) {
          reader.cancel();
          return;
        }
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const raw = trimmed.slice(5).trim();
          if (!raw) continue;
          try {
            const ev = JSON.parse(raw);
            if (ev.type === "text_delta") onDelta(ev.delta);
            else if (ev.type === "done") onDone();
            else if (ev.type === "error") onError(ev.message ?? "Error");
          } catch {
            // skip malformed
          }
        }
      }
      if (!cancelled) onDone();
    })
    .catch((e) => {
      if (!cancelled) onError(String(e));
    });

  return () => {
    cancelled = true;
  };
}

// ── Market Pulse Pills ─────────────────────────────────────────────────────────

interface PulseIndex {
  symbol: string;
  change_pct: number;
}

function MarketPulsePills({ indices }: { indices: PulseIndex[] }) {
  const pills = PULSE_SYMBOLS.map((sym) =>
    indices.find((i) => i.symbol === sym)
  ).filter(Boolean) as PulseIndex[];

  if (!pills.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mb-3">
      {pills.map((idx) => {
        const isPos = idx.change_pct > 0;
        const isNeg = idx.change_pct < 0;
        const label = PULSE_LABELS[idx.symbol] ?? idx.symbol;
        return (
          <span
            key={idx.symbol}
            className={cn(
              "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border",
              isPos
                ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)] border-[var(--accent-positive)]/30"
                : isNeg
                  ? "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)] border-[var(--accent-negative)]/30"
                  : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] border-[var(--border-subtle)]"
            )}
          >
            {isPos ? (
              <TrendingUp size={9} />
            ) : isNeg ? (
              <TrendingDown size={9} />
            ) : (
              <Minus size={9} />
            )}
            <span>{label}</span>
            <span>{formatPercent(idx.change_pct)}</span>
          </span>
        );
      })}
    </div>
  );
}

// ── Main Widget ────────────────────────────────────────────────────────────────

export default function MorningBriefWidget() {
  const [aiText, setAiText] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedAt, setGeneratedAt] = useState<Date | null>(null);
  const [genKey, setGenKey] = useState(0);
  const cancelRef = useRef<(() => void) | null>(null);

  const { data: rawIndices, isLoading: indicesLoading } = useQuery({
    queryKey: ["market-overview"],
    queryFn: getMarketOverview,
    staleTime: 60_000,
  });

  const indices: any[] = Array.isArray(rawIndices) ? rawIndices : [];
  const dataReady = !indicesLoading && indices.length > 0;

  const generateFallback = useCallback((idxList: any[]) => {
    const spy = idxList.find((i: any) => i.symbol === "SPY");
    const qqq = idxList.find((i: any) => i.symbol === "QQQ");
    const iwm = idxList.find((i: any) => i.symbol === "IWM");
    const spDir = (spy?.change_pct ?? 0) >= 0 ? "higher" : "lower";
    const spPct = spy ? `${spy.change_pct >= 0 ? "+" : ""}${spy.change_pct.toFixed(2)}%` : "flat";
    const nqPct = qqq ? `${qqq.change_pct >= 0 ? "+" : ""}${qqq.change_pct.toFixed(2)}%` : "flat";
    const spLeading = Math.abs(qqq?.change_pct ?? 0) > Math.abs(spy?.change_pct ?? 0) ? "NASDAQ leading" : "broad market holding";
    const smCap = iwm ? (iwm.change_pct >= 0 ? "small-caps participating" : "small-caps lagging — risk-off undertone") : "";
    const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    setAiText(
      `• Markets opened ${spDir} ${today} — S&P 500 ${spPct}, NASDAQ ${nqPct}. ${spLeading}.\n` +
      `• ${smCap ? smCap.charAt(0).toUpperCase() + smCap.slice(1) + ". " : ""}Watch for sector rotation into close — tech ${(qqq?.change_pct ?? 0) >= 0 ? "momentum intact" : "under pressure"}.\n` +
      `• AI brief available once ANTHROPIC_API_KEY is set in Railway — market data updates live in real time.`
    );
    setIsGenerating(false);
    setGeneratedAt(new Date());
  }, []);

  const generate = useCallback(() => {
    // Cancel any in-flight stream
    cancelRef.current?.();
    setAiText("");
    setIsGenerating(true);
    setGeneratedAt(null);

    const today = new Date().toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });

    const prompt = `In 3 bullet points (no more), summarize today's key market conditions: market direction, key economic news, and one actionable insight. Be specific and concise. Use today's date: ${today}.`;

    const cancel = streamBrief(
      prompt,
      (delta) => setAiText((prev) => prev + delta),
      () => {
        setIsGenerating(false);
        setGeneratedAt(new Date());
      },
      (_err) => {
        generateFallback(indices);
      }
    );

    cancelRef.current = cancel;
  }, [indices, generateFallback]);

  // Auto-generate once data is ready or genKey changes
  useEffect(() => {
    if (!dataReady) return;
    generate();
    return () => {
      cancelRef.current?.();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genKey, dataReady]);

  const handleRefresh = () => {
    if (!dataReady) return;
    setGenKey((k) => k + 1);
  };

  const now = new Date();
  const dateLabel = now.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  const timeLabel = now.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  const generatedAtLabel = generatedAt?.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });

  // Render bullet points with basic markdown bullet support
  const renderContent = () => {
    if (!aiText) return null;
    const lines = aiText.split("\n").filter((l) => l.trim());
    return (
      <ul className="space-y-1.5 flex-1">
        {lines.map((line, i) => {
          const clean = line.replace(/^[-•*]\s*/, "").trim();
          if (!clean) return null;
          return (
            <li
              key={i}
              className="flex gap-2 text-[var(--text-secondary)] text-sm leading-relaxed"
            >
              <span className="mt-1.5 w-1 h-1 rounded-full bg-[var(--accent-positive)] flex-shrink-0" />
              <span>
                {renderInlineMarkdown(clean)}
              </span>
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div
      className="h-full flex flex-col"
      style={{
        borderLeft: "3px solid var(--accent-positive)",
        margin: "-1rem",
        padding: "1rem",
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base shrink-0">🌅</span>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] shrink-0">
            Morning Brief
          </h2>
          <span className="text-xs text-[var(--text-tertiary)] font-mono truncate hidden sm:block">
            {dateLabel} · {timeLabel}
          </span>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isGenerating || indicesLoading}
          title="Regenerate summary"
          className={cn(
            "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] p-1 rounded cursor-pointer transition-colors",
            (isGenerating || indicesLoading) && "opacity-40 cursor-not-allowed"
          )}
        >
          <RefreshCw
            size={14}
            className={isGenerating ? "animate-spin" : ""}
          />
        </button>
      </div>

      {/* Market Pulse Pills */}
      {indicesLoading ? (
        <div className="flex gap-1.5 mb-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-5 w-20 rounded-full bg-[var(--bg-elevated)] animate-pulse"
            />
          ))}
        </div>
      ) : (
        <MarketPulsePills indices={indices} />
      )}

      {/* AI Content */}
      <div className="flex-1 min-h-0">
        {indicesLoading || (!aiText && isGenerating) ? (
          <Skeleton rows={3} height={14} />
        ) : (
          <>
            {renderContent()}
            {/* Streaming cursor */}
            {isGenerating && aiText && (
              <span className="inline-block w-0.5 h-4 bg-[var(--accent-positive)] ml-0.5 animate-pulse align-middle" />
            )}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="mt-3 pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between">
        <span className="text-[10px] text-[var(--text-tertiary)] font-medium tracking-wide">
          Powered by BMG Intelligence
        </span>
        {generatedAtLabel && !isGenerating && (
          <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
            Generated at {generatedAtLabel}
          </span>
        )}
        {isGenerating && (
          <span className="text-[10px] text-[var(--accent-positive)] font-mono animate-pulse">
            Generating…
          </span>
        )}
      </div>
    </div>
  );
}

// ── Inline markdown helper ─────────────────────────────────────────────────────

function renderInlineMarkdown(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={i} className="font-semibold text-[var(--text-primary)]">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}
