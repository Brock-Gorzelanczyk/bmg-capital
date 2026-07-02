import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { listBots, type BotListItem } from "@/api/adminBots";
import { cn } from "@/lib/utils";
import { BracketFrame, SectionLabel, BMGCard } from "@/components/design";

const ADMIN_EMAIL = "32bgorzelanczyk@gmail.com";

const BOT_LABELS: Record<string, string> = {
  stock_swing:                 "Stock Swing",
  stock_day:                   "Stock Day",
  stock_lt:                    "Stock Long-Term",
  crypto_swing:                "Crypto Swing",
  crypto_day:                  "Crypto Day",
  crypto_lt:                   "Crypto Long-Term",
  crypto_onchain:              "Crypto On-Chain",
  crypto_quant_aggressive:     "Quant Aggressive",
  crypto_quant_mean_reversion: "Quant Mean Rev",
  crypto_quant_scalper:        "Quant Scalper",
  crypto_quant_alt_focus:      "Quant Alt Focus",
  crypto_quant_scalp_1m:       "Quant Scalp 1m",
  crypto_dca_btc_eth:          "DCA BTC/ETH",
  crypto_quant_universe_top6:  "Quant Top 6",
  crypto_quant_defi_l2:        "Quant DeFi/L2",
  crypto_quant_meme_tier:      "Quant Meme",
  crypto_quant_10m:            "Quant 10m",
  crypto_quant_15m:            "Quant 15m",
  options_income:              "Options Income",
  options_directional:         "Options Directional",
};

const CATEGORY_COLORS: Record<string, string> = {
  quant:   "bg-violet-500/20 text-violet-300 border-violet-500/30",
  crypto:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
  stocks:  "bg-sky-500/20 text-sky-300 border-sky-500/30",
  options: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
};

function StatusPill({ enabled, paused }: { enabled: boolean; paused: boolean }) {
  if (!enabled) return <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">DISABLED</span>;
  if (paused)   return <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">PAUSED</span>;
  return <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-[var(--bmg-green-dim)] text-[var(--bmg-green)] border border-[var(--bmg-green-border)]">ACTIVE</span>;
}

function BotCard({ bot }: { bot: BotListItem }) {
  const label = BOT_LABELS[bot.bot_id] ?? bot.bot_id.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return (
    <BMGCard padding="sm" className="flex flex-col gap-3 hover:border-[var(--bmg-green)]/50 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-mono font-semibold text-[var(--bmg-text)] leading-snug">{label}</p>
        <span className={cn(
          "text-[10px] font-bold px-1.5 py-0.5 rounded-full border whitespace-nowrap flex-shrink-0",
          CATEGORY_COLORS[bot.category] ?? "bg-zinc-800 text-zinc-400 border-zinc-700",
        )}>
          {bot.category.toUpperCase()}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <StatusPill enabled={bot.enabled} paused={bot.paused} />
        <span className="text-xs text-[var(--bmg-text-muted)]">{bot.open_positions} open</span>
      </div>

      <Link
        to={`/admin/bots/${bot.bot_id}`}
        className="mt-auto text-xs font-mono font-semibold text-[var(--bmg-green)] hover:text-[var(--bmg-green)]/80 transition-colors"
      >
        Configure →
      </Link>
    </BMGCard>
  );
}

export default function AdminBotsPage() {
  const { user } = useAuthStore();

  if ((user as any)?.email !== ADMIN_EMAIL) {
    return <Navigate to="/strategy" replace />;
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin-bots"],
    queryFn: listBots,
    staleTime: 30_000,
  });

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <BracketFrame className="mb-8 p-5 rounded-xl" glow>
        <SectionLabel as="h1" className="text-base mb-1">Bot Configuration</SectionLabel>
        <p className="text-xs text-[var(--bmg-text-muted)] mt-2">Runtime knobs — no deploy required. YAML defaults remain the baseline.</p>
      </BracketFrame>

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="bg-[var(--bmg-bg-card)] border border-[var(--bmg-green-border)] rounded-xl h-32 animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
          Failed to load bots. Check that the backend is running.
        </p>
      )}

      {data && (
        <>
          {/* Summary strip */}
          <div className="flex gap-4 mb-5 text-xs text-[var(--bmg-text-muted)] font-mono">
            <span><span className="text-[var(--bmg-green)]">{data.bots.filter(b => b.enabled && !b.paused).length}</span> active</span>
            <span><span className="text-yellow-400">{data.bots.filter(b => b.paused && b.enabled).length}</span> paused</span>
            <span><span className="text-red-400">{data.bots.filter(b => !b.enabled).length}</span> disabled</span>
            <span><span className="text-white">{data.bots.reduce((s, b) => s + b.open_positions, 0)}</span> open positions</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.bots.map(bot => <BotCard key={bot.bot_id} bot={bot} />)}
          </div>
        </>
      )}
    </div>
  );
}
