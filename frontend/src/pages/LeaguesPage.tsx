import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import client from "@/api/client";

// ─── Types ───────────────────────────────────────────────────────────────────

type LeagueTier = "Bronze" | "Silver" | "Gold" | "Platinum" | "Diamond";

interface LeaguePlayer {
  rank: number;
  username: string;
  points: number;
  is_me?: boolean;
}

interface LeagueData {
  tier: LeagueTier;
  week_number: number;
  rank: number;
  total_in_league: number;
  points_this_week: number;
  standings: LeaguePlayer[];
  promotion_zone: number;   // top N get promoted
  demotion_zone: number;    // bottom N get demoted
}

// ─── Tier config ─────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<LeagueTier, { emoji: string; className: string; label: string }> = {
  Bronze:   { emoji: "🥉", className: "text-amber-700",  label: "BRONZE" },
  Silver:   { emoji: "🥈", className: "text-slate-300",  label: "SILVER" },
  Gold:     { emoji: "🥇", className: "text-amber-400",  label: "GOLD" },
  Platinum: { emoji: "💎", className: "text-cyan-300",   label: "PLATINUM" },
  Diamond:  { emoji: "✨", className: "text-purple-400", label: "DIAMOND" },
};

// ─── Countdown to next Monday 9:30am ET ──────────────────────────────────────

function useNextResetCountdown() {
  return useMemo(() => {
    const now = new Date();
    // Get current time in ET (UTC-4 in EDT, UTC-5 in EST)
    // We use a simple approach: find next Monday in ET
    const etOffset = -4 * 60; // EDT minutes offset
    const nowET = new Date(now.getTime() + (now.getTimezoneOffset() + etOffset) * 60_000);

    const day = nowET.getDay(); // 0=Sun, 1=Mon
    const daysUntilMonday = day === 0 ? 1 : 8 - day;
    const nextMonday = new Date(nowET);
    nextMonday.setDate(nowET.getDate() + daysUntilMonday);
    nextMonday.setHours(9, 30, 0, 0);

    const diffMs = nextMonday.getTime() - nowET.getTime();
    const totalMinutes = Math.floor(diffMs / 60_000);
    const days = Math.floor(totalMinutes / (60 * 24));
    const hours = Math.floor((totalMinutes % (60 * 24)) / 60);

    return `${days}d ${hours}h`;
  }, []);
}

// ─── Standings row ───────────────────────────────────────────────────────────

function StandingsRow({
  player,
  isPromo,
  isDemotion,
}: {
  player: LeaguePlayer;
  isPromo: boolean;
  isDemotion: boolean;
}) {
  const arrow = isPromo ? "↑" : isDemotion ? "↓" : "→";
  const arrowColor = isPromo
    ? "text-green-400"
    : isDemotion
    ? "text-red-400"
    : "text-[var(--text-tertiary)]";
  const dot = isPromo
    ? "bg-green-400"
    : isDemotion
    ? "bg-red-400"
    : "bg-[var(--text-tertiary)]";

  return (
    <div
      className={[
        "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors",
        player.is_me
          ? "border-l-2 border-blue-500 bg-blue-500/5 pl-2.5"
          : "border-l-2 border-transparent",
      ].join(" ")}
    >
      {/* Arrow */}
      <span className={`text-sm font-bold w-4 shrink-0 ${arrowColor}`}>{arrow}</span>

      {/* Rank */}
      <span className="font-mono text-sm text-[var(--text-tertiary)] w-5 shrink-0 text-right">
        {player.rank}
      </span>

      {/* Name */}
      <span
        className={`flex-1 text-sm truncate ${
          player.is_me ? "font-semibold text-blue-400" : "text-[var(--text-primary)]"
        }`}
      >
        {player.username}
      </span>

      {/* Points */}
      <span className="font-mono text-sm text-[var(--text-secondary)]">
        {player.points} pts
      </span>

      {/* Status dot */}
      <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />

      {/* YOU tag */}
      {player.is_me && (
        <span className="text-[10px] font-bold text-blue-400 bg-blue-500/15 px-1.5 py-0.5 rounded shrink-0">
          YOU
        </span>
      )}
    </div>
  );
}

// ─── Mock data fallback ───────────────────────────────────────────────────────

const MOCK: LeagueData = {
  tier: "Silver",
  week_number: 22,
  rank: 8,
  total_in_league: 30,
  points_this_week: 247,
  promotion_zone: 7,
  demotion_zone: 5,
  standings: [
    { rank: 1,  username: "AlphaInvestor",   points: 412 },
    { rank: 2,  username: "MarketMaven",      points: 387 },
    { rank: 3,  username: "BullishBrenda",    points: 354 },
    { rank: 4,  username: "QuantKing",        points: 321 },
    { rank: 5,  username: "OptionOwl",        points: 308 },
    { rank: 6,  username: "DCADave",          points: 290 },
    { rank: 7,  username: "ValueVince",       points: 271 },
    { rank: 8,  username: "You",              points: 247, is_me: true },
    { rank: 9,  username: "SwingTrade99",     points: 231 },
    { rank: 10, username: "EarningsHunter",   points: 215 },
    { rank: 11, username: "MomoMike",         points: 198 },
    { rank: 12, username: "PatientPaula",     points: 174 },
    { rank: 26, username: "LateNightTrader",  points: 89 },
    { rank: 27, username: "RedCandleRaj",     points: 72 },
    { rank: 28, username: "FOMOFred",         points: 61 },
    { rank: 29, username: "Leveraged_Leo",    points: 44 },
    { rank: 30, username: "ZeroToHero",       points: 31 },
  ],
};

// ─── Page ────────────────────────────────────────────────────────────────────

export default function LeaguesPage() {
  const navigate = useNavigate();
  const countdown = useNextResetCountdown();

  const { data, isLoading } = useQuery<LeagueData>({
    queryKey: ["engagement-league"],
    queryFn: () => client.get("/api/engagement/leagues/me").then((r) => r.data),
  });

  const league = data ?? MOCK;
  const tierCfg = TIER_CONFIG[league.tier];

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)] p-4 pb-20 max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <span>🏅</span> Skill Leagues
        </h1>
        <span className="font-mono text-sm text-[var(--text-secondary)] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-2.5 py-1 rounded-lg">
          Week {league.week_number}
        </span>
      </div>

      {/* Your league card */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 mb-4">
        <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-widest mb-1">
          Your League
        </p>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-3xl">{tierCfg.emoji}</span>
          <span className={`text-2xl font-bold ${tierCfg.className}`}>{tierCfg.label}</span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--text-secondary)]">
          <span>
            Rank{" "}
            <span className="font-mono font-semibold text-[var(--text-primary)]">
              #{league.rank}
            </span>{" "}
            of{" "}
            <span className="font-mono font-semibold text-[var(--text-primary)]">
              {league.total_in_league}
            </span>
          </span>
          <span>·</span>
          <span>
            <span className="font-mono font-semibold text-[var(--text-primary)]">
              {league.points_this_week}
            </span>{" "}
            pts this week
          </span>
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
          <span>Next reset: Mon 9:30am ET</span>
          <span>·</span>
          <span className="font-mono text-amber-400">{countdown}</span>
        </div>
      </div>

      {/* Points explanation */}
      <div
        className="rounded-xl p-3 mb-4 text-sm"
        style={{ background: "var(--bg-elevated-2)" }}
      >
        <p className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-widest mb-2">
          📈 How to earn points
        </p>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[var(--text-secondary)]">
          <span>📚 Lesson completed</span>
          <span className="font-mono text-right text-[var(--text-primary)]">10 pts</span>
          <span>🎯 Daily challenge</span>
          <span className="font-mono text-right text-[var(--text-primary)]">5 pts</span>
          <span>📓 Journal entry</span>
          <span className="font-mono text-right text-[var(--text-primary)]">3 pts</span>
          <span>🧪 Backtest run</span>
          <span className="font-mono text-right text-[var(--text-primary)]">2 pts</span>
        </div>
        <p className="text-xs text-[var(--text-tertiary)] mt-2 italic">
          Points never come from trades — only learning and reflection.
        </p>
      </div>

      {/* Standings */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden mb-4">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">League Standings</h2>
        </div>
        <div className="divide-y divide-[var(--border-subtle)]">
          {isLoading
            ? Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="px-3 py-2.5 animate-pulse">
                  <div className="h-4 bg-white/10 rounded w-3/4" />
                </div>
              ))
            : league.standings.map((player) => {
                const isPromo = player.rank <= league.promotion_zone;
                const isDemotion =
                  player.rank > league.total_in_league - league.demotion_zone;
                return (
                  <StandingsRow
                    key={player.rank}
                    player={player}
                    isPromo={isPromo}
                    isDemotion={isDemotion}
                  />
                );
              })}
        </div>
        {/* Zone legend */}
        <div className="px-4 py-2 border-t border-[var(--border-subtle)] flex gap-4 text-[10px] text-[var(--text-tertiary)]">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-400 inline-block" /> Promotion zone (Top {league.promotion_zone})
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400 inline-block" /> Demotion zone (Bottom {league.demotion_zone})
          </span>
        </div>
      </div>

      {/* Monthly tournament */}
      <div
        className="rounded-xl p-4 border border-amber-500/20"
        style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.08) 0%, rgba(59,130,246,0.06) 100%)" }}
      >
        <p className="text-xs font-semibold text-amber-400 uppercase tracking-widest mb-1">
          🏆 Monthly Tournament
        </p>
        <h3 className="text-base font-bold text-[var(--text-primary)] mb-1">
          Earnings Season Showdown
        </h3>
        <p className="text-xs text-[var(--text-secondary)] mb-1">
          Starts: Jun 3 &nbsp;·&nbsp; Risk-adjusted (Sharpe-weighted) scoring
        </p>
        <p className="text-xs text-[var(--text-tertiary)] italic mb-3">
          YOLOs don't win here.
        </p>
        <button
          onClick={() => navigate("/paper")}
          className="px-4 py-2 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium transition-colors"
        >
          View Tournament
        </button>
      </div>
    </div>
  );
}
