import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { listBots, type BotListItem } from "@/api/adminBots";
import { cn } from "@/lib/utils";

const ADMIN_EMAIL = "32bgorzelanczyk@gmail.com";

const CATEGORY_COLORS: Record<string, string> = {
  quant:   "bg-violet-500/20 text-violet-300 border-violet-500/30",
  crypto:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
  stocks:  "bg-sky-500/20 text-sky-300 border-sky-500/30",
  options: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
};

function StatusPill({ enabled, paused }: { enabled: boolean; paused: boolean }) {
  if (!enabled) return <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">DISABLED</span>;
  if (paused)   return <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">PAUSED</span>;
  return <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">ACTIVE</span>;
}

function BotCard({ bot }: { bot: BotListItem }) {
  const label = bot.bot_id.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col gap-3 hover:border-zinc-700 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-white leading-snug">{label}</p>
        <span className={cn(
          "text-[10px] font-bold px-1.5 py-0.5 rounded-full border whitespace-nowrap flex-shrink-0",
          CATEGORY_COLORS[bot.category] ?? "bg-zinc-800 text-zinc-400 border-zinc-700",
        )}>
          {bot.category.toUpperCase()}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <StatusPill enabled={bot.enabled} paused={bot.paused} />
        <span className="text-xs text-zinc-500">{bot.open_positions} open</span>
      </div>

      <Link
        to={`/admin/bots/${bot.bot_id}`}
        className="mt-auto text-xs font-semibold text-teal-400 hover:text-teal-300 transition-colors"
      >
        Configure →
      </Link>
    </div>
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
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Bot Configuration</h1>
        <p className="text-sm text-zinc-500 mt-1">Runtime knobs — no deploy required. YAML defaults remain the baseline.</p>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-xl h-32 animate-pulse" />
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
          <div className="flex gap-4 mb-5 text-xs text-zinc-500">
            <span>{data.bots.filter(b => b.enabled && !b.paused).length} active</span>
            <span>{data.bots.filter(b => b.paused).length} paused</span>
            <span>{data.bots.filter(b => !b.enabled).length} disabled</span>
            <span>{data.bots.reduce((s, b) => s + b.open_positions, 0)} total open positions</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.bots.map(bot => <BotCard key={bot.bot_id} bot={bot} />)}
          </div>
        </>
      )}
    </div>
  );
}
