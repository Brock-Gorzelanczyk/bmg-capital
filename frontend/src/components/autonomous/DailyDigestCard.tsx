import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Sun, Share2, ExternalLink, TrendingUp, TrendingDown } from "lucide-react";
import { toast } from "sonner";
import { getLatestDigest } from "@/api/autonomous";
import { formatCurrency, cn } from "@/lib/utils";

interface DailyDigestCardProps {
  className?: string;
}

export default function DailyDigestCard({ className }: DailyDigestCardProps) {
  const navigate = useNavigate();

  const { data: digest } = useQuery({
    queryKey: ["autonomous-digest-latest"],
    queryFn: getLatestDigest,
    staleTime: 5 * 60 * 1000,
  });

  if (!digest) return null;

  // Parse highlights — backend may send as JSON string or already as array
  let highlights: string[] = [];
  try {
    highlights = Array.isArray(digest.highlights)
      ? digest.highlights
      : JSON.parse(digest.highlights as unknown as string);
  } catch {
    highlights = [];
  }

  const digestDate = new Date(digest.digest_date);
  const dateLabel = digestDate.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  const pnlPositive = digest.portfolio_delta >= 0;

  function handleShare() {
    const text = [
      `BMG Capital Daily Digest — ${dateLabel}`,
      digest!.tldr,
      "",
      `Signals: ${digest!.signals_fired} · Buys: ${digest!.paper_buys} · Net: ${pnlPositive ? "+" : ""}${formatCurrency(digest!.portfolio_delta)}`,
      digest!.market_regime_note,
      "",
      "BMG ran overnight so I didn't have to.",
      "bmgcapital.com",
    ].join("\n");

    navigator.clipboard
      .writeText(text)
      .then(() => toast.success("Digest copied to clipboard"))
      .catch(() => toast.error("Failed to copy to clipboard"));
  }

  return (
    <div
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 border-l-4",
        "border-l-[#4ade80]",
        className
      )}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sun size={16} className="text-[#4ade80]" />
          <span className="text-sm font-semibold text-[var(--text-primary)]">
            Daily Digest
          </span>
          <span className="text-xs text-[var(--text-tertiary)]">· {dateLabel}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleShare}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] transition-colors"
          >
            <Share2 size={12} />
            Share
          </button>
          <button
            onClick={() => navigate("/mission-control")}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-[#4ade80] hover:bg-[#4ade80]/10 border border-[#4ade80]/30 transition-colors"
          >
            <ExternalLink size={12} />
            View Full
          </button>
        </div>
      </div>

      {/* TL;DR */}
      <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-3">
        {digest.tldr}
      </p>

      {/* Stats row */}
      <div className="flex items-center gap-4 flex-wrap mb-4 py-2.5 px-3 bg-[var(--bg-elevated-2)] rounded-lg">
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-lg">📡</span>
          <span className="text-[var(--text-tertiary)]">Signals:</span>
          <span className="font-semibold text-[#4ade80]">{digest.signals_fired}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-lg">🟢</span>
          <span className="text-[var(--text-tertiary)]">Buys:</span>
          <span className="font-semibold text-[#22C55E]">{digest.paper_buys}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-lg">💰</span>
          <span className="text-[var(--text-tertiary)]">Exits:</span>
          <span className="font-semibold text-[#3B82F6]">{digest.paper_sells}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs ml-auto">
          {pnlPositive ? (
            <TrendingUp size={13} className="text-[#22C55E]" />
          ) : (
            <TrendingDown size={13} className="text-[#EF4444]" />
          )}
          <span
            className={cn(
              "font-bold text-sm",
              pnlPositive ? "text-[#22C55E]" : "text-[#EF4444]"
            )}
          >
            {pnlPositive ? "+" : ""}
            {formatCurrency(digest.portfolio_delta)}
          </span>
          <span className="text-[var(--text-tertiary)]">today</span>
        </div>
      </div>

      {/* Highlights */}
      {highlights.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-1.5">
            Highlights
          </p>
          <ul className="space-y-1">
            {highlights.map((h, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                <span className="text-[#4ade80] mt-0.5 shrink-0">•</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Tomorrow preview */}
      {digest.tomorrow_preview && (
        <div className="mb-3">
          <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-1">
            Tomorrow
          </p>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            {digest.tomorrow_preview}
          </p>
        </div>
      )}

      {/* Market regime */}
      {digest.market_regime_note && (
        <div>
          <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-1">
            Market Regime
          </p>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            {digest.market_regime_note}
          </p>
        </div>
      )}
    </div>
  );
}
