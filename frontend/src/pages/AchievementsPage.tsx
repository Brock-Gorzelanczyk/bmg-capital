import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import client from "@/api/client";

// ─── Achievement definitions ────────────────────────────────────────────────

type AchievementCategory =
  | "Onboarding"
  | "Skill"
  | "Discipline"
  | "Strategy"
  | "Community"
  | "Milestones";

interface AchievementDef {
  id: string;
  name: string;
  description: string;
  category: AchievementCategory;
  icon_emoji: string;
  max_progress?: number;
}

interface AchievementAPI {
  id: string;
  unlocked: boolean;
  unlocked_at?: string;
  progress?: number;
  max_progress?: number;
}

interface MergedAchievement extends AchievementDef {
  unlocked: boolean;
  unlocked_at?: string;
  progress?: number;
}

const ACHIEVEMENTS: AchievementDef[] = [
  // Onboarding
  { id: "first_login",         name: "First Login",             description: "You opened the door",                              category: "Onboarding", icon_emoji: "🌟" },
  { id: "profile_complete",    name: "Profile Complete",         description: "Set up your investor profile",                     category: "Onboarding", icon_emoji: "✏️" },
  { id: "first_deposit",       name: "First Deposit",            description: "Made your first deposit",                          category: "Onboarding", icon_emoji: "💰" },
  { id: "watchlist_started",   name: "Watchlist Started",        description: "Added 5+ tickers to your watchlist",               category: "Onboarding", icon_emoji: "👀", max_progress: 5 },
  { id: "first_paper_trade",   name: "First Paper Trade",        description: "Placed your first simulated trade",                category: "Onboarding", icon_emoji: "📝" },
  { id: "first_real_trade",    name: "First Real Trade",         description: "Placed your first live trade",                     category: "Onboarding", icon_emoji: "⚡" },
  { id: "first_lesson",        name: "First Lesson",             description: "Completed your first learning lesson",             category: "Onboarding", icon_emoji: "📚" },

  // Skill
  { id: "investing_101",       name: "Investing 101 Graduate",   description: "Completed the Investing 101 course",               category: "Skill", icon_emoji: "🎓" },
  { id: "options_101",         name: "Options 101 Graduate",     description: "Completed the Options 101 course",                 category: "Skill", icon_emoji: "📊" },
  { id: "crypto_101",          name: "Crypto 101 Graduate",      description: "Completed the Crypto 101 course",                  category: "Skill", icon_emoji: "₿" },
  { id: "ta_chart_patterns",   name: "TA: Chart Patterns",       description: "Mastered technical chart patterns",                category: "Skill", icon_emoji: "📈" },
  { id: "ta_indicators",       name: "TA: Indicators",           description: "Mastered technical indicators",                    category: "Skill", icon_emoji: "📉" },
  { id: "strategy_explorer",   name: "Strategy Lab Explorer",    description: "Run 5 backtests",                                  category: "Skill", icon_emoji: "🔬", max_progress: 5 },
  { id: "options_explorer",    name: "Options Lab Explorer",     description: "Build 5 spreads",                                  category: "Skill", icon_emoji: "⚙️", max_progress: 5 },
  { id: "crypto_explorer",     name: "Crypto Lab Explorer",      description: "Explored the Crypto Lab",                          category: "Skill", icon_emoji: "🌐" },
  { id: "macro_literate",      name: "Macro Literate",           description: "Complete 10 econ lessons",                         category: "Skill", icon_emoji: "🌍", max_progress: 10 },
  { id: "tax_aware",           name: "Tax-Aware",                description: "Completed the tax awareness module",               category: "Skill", icon_emoji: "🧾" },
  { id: "risk_certified",      name: "Risk Management Certified",description: "Completed risk management certification",          category: "Skill", icon_emoji: "🛡️" },
  { id: "behavioral_finance",  name: "Behavioral Finance",       description: "Completed behavioral finance module",              category: "Skill", icon_emoji: "🧠" },
  { id: "glossary_master",     name: "Glossary Master",          description: "Viewed 50 terms",                                  category: "Skill", icon_emoji: "📖", max_progress: 50 },

  // Discipline
  { id: "diamond_hands",       name: "Diamond Hands",            description: "Held through a 10%+ drawdown without selling",     category: "Discipline", icon_emoji: "💎" },
  { id: "dca_master",          name: "Dollar-Cost Averager",     description: "12 consecutive scheduled buys",                    category: "Discipline", icon_emoji: "🔄", max_progress: 12 },
  { id: "diversified",         name: "Diversified",              description: "Positions in 5+ sectors",                          category: "Discipline", icon_emoji: "🌈", max_progress: 5 },
  { id: "rebalancer",          name: "Rebalancer",               description: "Used rebalance tool 3 times",                      category: "Discipline", icon_emoji: "⚖️", max_progress: 3 },
  { id: "tax_loss_harvester",  name: "Tax-Loss Harvester",       description: "Executed a tax-loss harvesting trade",             category: "Discipline", icon_emoji: "✂️" },
  { id: "journal_keeper",      name: "Journal Keeper",           description: "30 trade journals written",                        category: "Discipline", icon_emoji: "📓", max_progress: 30 },
  { id: "thesis_writer",       name: "Thesis Writer",            description: "10 documented theses before entry",                category: "Discipline", icon_emoji: "💡", max_progress: 10 },
  { id: "risk_setter",         name: "Risk Setter",              description: "Set stop-loss on 20 trades",                       category: "Discipline", icon_emoji: "🎯", max_progress: 20 },
  { id: "patient_capital",     name: "Patient Capital",          description: "Held a position for 1 year+",                      category: "Discipline", icon_emoji: "⏳" },
  { id: "recession_tested",    name: "Recession-Tested",         description: "Active during a 5%+ market drawdown",              category: "Discipline", icon_emoji: "📉" },
  { id: "cooled_off",          name: "Cooled Off",               description: "Used the 24-hour pause feature",                   category: "Discipline", icon_emoji: "❄️" },
  { id: "loss_reviewed",       name: "Loss-Reviewed",            description: "Post-mortem on 10 losing trades",                  category: "Discipline", icon_emoji: "🔍", max_progress: 10 },

  // Strategy
  { id: "backtest_apprentice", name: "Backtest Apprentice",      description: "Ran 5 backtests",                                  category: "Strategy", icon_emoji: "🧪", max_progress: 5 },
  { id: "backtest_master",     name: "Backtest Master",          description: "Ran 50 backtests",                                 category: "Strategy", icon_emoji: "🏆", max_progress: 50 },
  { id: "symphony_composer",   name: "Symphony Composer",        description: "Published a public strategy",                      category: "Strategy", icon_emoji: "🎵" },
  { id: "forked",              name: "Forked",                   description: "Forked someone else's strategy",                   category: "Strategy", icon_emoji: "🍴" },
  { id: "greek_aware",         name: "Greek-Aware",              description: "Analyzed delta, theta, and gamma",                 category: "Strategy", icon_emoji: "🇬🇷" },
  { id: "iron_condor",         name: "Iron Condor",              description: "Built an iron condor in Options Lab",              category: "Strategy", icon_emoji: "🦅" },
  { id: "pattern_recognizer",  name: "Pattern Recognizer",       description: "Identified 25 chart patterns",                     category: "Strategy", icon_emoji: "🔎", max_progress: 25 },
  { id: "indicator_builder",   name: "Indicator Builder",        description: "Built a custom indicator",                         category: "Strategy", icon_emoji: "🔧" },
  { id: "alpha_hunter",        name: "Alpha Hunter",             description: "Paper portfolio beat S&P over 90 days",            category: "Strategy", icon_emoji: "🎯" },
  { id: "drawdown_survivor",   name: "Drawdown Survivor",        description: "Paper portfolio recovered from 15% drawdown",      category: "Strategy", icon_emoji: "💪" },

  // Community
  { id: "first_comment",       name: "First Comment",            description: "Posted your first community comment",              category: "Community", icon_emoji: "💬" },
  { id: "helpful",             name: "Helpful",                  description: "Received 10 upvotes on posts",                     category: "Community", icon_emoji: "🤝", max_progress: 10 },
  { id: "thesis_shared",       name: "Thesis Shared",            description: "Shared a public investment thesis",                category: "Community", icon_emoji: "📤" },
  { id: "event_attendee",      name: "Live Event Attendee",      description: "Attended a live BMG Capital event",                category: "Community", icon_emoji: "🎙️" },
  { id: "mentor",              name: "Mentor",                   description: "Answered 5 community questions",                   category: "Community", icon_emoji: "👨‍🏫", max_progress: 5 },

  // Milestones
  { id: "streak_30",           name: "30-Day Streak",            description: "30 consecutive active days",                       category: "Milestones", icon_emoji: "🔥", max_progress: 30 },
  { id: "streak_100",          name: "100-Day Streak",           description: "100 consecutive active days",                      category: "Milestones", icon_emoji: "⚡", max_progress: 100 },
  { id: "year_one",            name: "Year-One Member",          description: "1 full year as a BMG Capital member",              category: "Milestones", icon_emoji: "🎂" },
];

const ALL_CATEGORIES: AchievementCategory[] = [
  "Onboarding", "Skill", "Discipline", "Strategy", "Community", "Milestones",
];

const CATEGORY_LABELS: Record<AchievementCategory, string> = {
  Onboarding: "Onboarding",
  Skill: "Skill",
  Discipline: "Behavior",
  Strategy: "Strategy",
  Community: "Community",
  Milestones: "Vanity",
};

// ─── Circular progress ring ──────────────────────────────────────────────────

function CircularRing({ value, max, size = 64 }: { value: number; max: number; size?: number }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = max === 0 ? 0 : Math.min(value / max, 1);
  const dash = pct * circumference;

  return (
    <svg width={size} height={size} className="rotate-[-90deg]">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth={4}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="#F59E0B"
        strokeWidth={4}
        strokeDasharray={`${dash} ${circumference}`}
        strokeLinecap="round"
      />
    </svg>
  );
}

// ─── Badge card ──────────────────────────────────────────────────────────────

function BadgeCard({ achievement }: { achievement: MergedAchievement }) {
  const { unlocked, progress, max_progress, icon_emoji, name, description } = achievement;
  const effectiveMax = max_progress ?? achievement.max_progress;
  const hasProgress = effectiveMax !== undefined && effectiveMax > 1;
  const progressVal = progress ?? 0;
  const pct = hasProgress ? Math.min(progressVal / effectiveMax!, 1) : 0;

  return (
    <div
      className={[
        "flex flex-col items-center gap-2 p-4 rounded-xl border text-center transition-all",
        unlocked
          ? "border-amber-500/40 bg-amber-500/5"
          : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] opacity-60",
      ].join(" ")}
      style={unlocked ? undefined : { filter: "grayscale(0.7)" }}
    >
      {/* Emoji */}
      <div className="relative flex items-center justify-center" style={{ width: 40, height: 40 }}>
        <span style={{ fontSize: 36, lineHeight: 1 }}>{icon_emoji}</span>
        {!unlocked && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 rounded-full">
            <Lock size={14} className="text-[var(--text-tertiary)]" />
          </div>
        )}
      </div>

      <div className="space-y-0.5">
        <p className="text-sm font-medium text-[var(--text-primary)] leading-tight">{name}</p>
        <p className="text-xs text-[var(--text-tertiary)] leading-snug">{description}</p>
      </div>

      {/* Progress bar */}
      {hasProgress && (
        <div className="w-full">
          <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mb-1">
            <span>{progressVal}</span>
            <span>{effectiveMax}</span>
          </div>
          <div className="h-1 rounded-full bg-white/10 overflow-hidden">
            <div
              className="h-full rounded-full bg-amber-500 transition-all"
              style={{ width: `${pct * 100}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Recently earned strip ───────────────────────────────────────────────────

function RecentlyEarned({ items }: { items: MergedAchievement[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mb-6">
      <h3 className="text-xs font-semibold text-amber-400 uppercase tracking-widest mb-2">
        Recently Earned
      </h3>
      <div className="flex flex-wrap gap-2">
        {items.map((a) => (
          <div
            key={a.id}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-sm"
          >
            <span>{a.icon_emoji}</span>
            <span className="text-[var(--text-primary)] font-medium">{a.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function AchievementsPage() {
  const [activeCategory, setActiveCategory] = useState<AchievementCategory | "All">("All");

  const { data: apiData } = useQuery<AchievementAPI[]>({
    queryKey: ["engagement-achievements"],
    queryFn: () => client.get("/api/engagement/achievements").then((r) => r.data),
  });

  const merged: MergedAchievement[] = useMemo(() => {
    const map = new Map<string, AchievementAPI>();
    (apiData ?? []).forEach((a) => map.set(a.id, a));

    return ACHIEVEMENTS.map((def) => {
      const api = map.get(def.id);
      return {
        ...def,
        max_progress: api?.max_progress ?? def.max_progress,
        unlocked: api?.unlocked ?? false,
        unlocked_at: api?.unlocked_at,
        progress: api?.progress,
      };
    });
  }, [apiData]);

  const unlockedCount = merged.filter((a) => a.unlocked).length;

  // Recently earned = unlocked in last 7 days
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const recentlyEarned = merged.filter(
    (a) => a.unlocked && a.unlocked_at && new Date(a.unlocked_at).getTime() > sevenDaysAgo
  );

  // Filtered list
  const filtered =
    activeCategory === "All" ? merged : merged.filter((a) => a.category === activeCategory);

  // Group by category for "All" view
  const grouped: { category: AchievementCategory; items: MergedAchievement[] }[] =
    activeCategory === "All"
      ? ALL_CATEGORIES.map((cat) => ({
          category: cat,
          items: merged.filter((a) => a.category === cat),
        }))
      : [{ category: activeCategory, items: filtered }];

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)] p-4 pb-16">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <span>🏆</span> Achievements
        </h1>
        <div className="flex items-center gap-2">
          <CircularRing value={unlockedCount} max={50} size={40} />
          <span className="font-mono text-sm text-[var(--text-secondary)]">
            {unlockedCount}/50
          </span>
        </div>
      </div>
      <p className="text-xs text-[var(--text-tertiary)] mb-4">
        {unlockedCount} of 50 unlocked
      </p>

      {/* Category tabs */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-4 scrollbar-hide">
        {(["All", ...ALL_CATEGORIES] as (AchievementCategory | "All")[]).map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={[
              "shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
              activeCategory === cat
                ? "bg-blue-500 text-white"
                : "bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)]",
            ].join(" ")}
          >
            {cat === "All" ? "All" : CATEGORY_LABELS[cat]}
          </button>
        ))}
      </div>

      {/* Recently earned */}
      <RecentlyEarned items={recentlyEarned} />

      {/* Badge groups */}
      {grouped.map(({ category, items }) => (
        <div key={category} className="mb-8">
          <h2 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">
            {CATEGORY_LABELS[category]}
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {items.map((a) => (
              <BadgeCard key={a.id} achievement={a} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
