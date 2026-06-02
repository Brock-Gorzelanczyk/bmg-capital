import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, X } from "lucide-react";
import client from "@/api/client";

// ─── Embedded achievement definitions (subset of emoji) ──────────────────────

const ACHIEVEMENT_EMOJIS: Record<string, string> = {
  first_login: "🌟",        profile_complete: "✏️",    first_deposit: "💰",
  watchlist_started: "👀",  first_paper_trade: "📝",   first_real_trade: "⚡",
  first_lesson: "📚",       investing_101: "🎓",        options_101: "📊",
  crypto_101: "₿",          ta_chart_patterns: "📈",    ta_indicators: "📉",
  strategy_explorer: "🔬",  options_explorer: "⚙️",     crypto_explorer: "🌐",
  macro_literate: "🌍",     tax_aware: "🧾",            risk_certified: "🛡️",
  behavioral_finance: "🧠", glossary_master: "📖",      diamond_hands: "💎",
  dca_master: "🔄",         diversified: "🌈",          rebalancer: "⚖️",
  tax_loss_harvester: "✂️", journal_keeper: "📓",       thesis_writer: "💡",
  risk_setter: "🎯",        patient_capital: "⏳",      recession_tested: "📉",
  cooled_off: "❄️",         loss_reviewed: "🔍",        backtest_apprentice: "🧪",
  backtest_master: "🏆",    symphony_composer: "🎵",    forked: "🍴",
  greek_aware: "🇬🇷",       iron_condor: "🦅",          pattern_recognizer: "🔎",
  indicator_builder: "🔧",  alpha_hunter: "🎯",         drawdown_survivor: "💪",
  first_comment: "💬",      helpful: "🤝",              thesis_shared: "📤",
  event_attendee: "🎙️",    mentor: "👨‍🏫",             streak_30: "🔥",
  streak_100: "⚡",          year_one: "🎂",
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface AnnualRecapData {
  total_trades: number;
  learning_hours: number;
  total_active_days: number;
  achievements_count: number;
  most_watched_ticker: string;
  best_symbol: string;
  best_pct_gain: number;
  best_hold_days: number;
  avg_hold_days: number;
  sector_personality: string;
  longest_streak: number;
  journal_entries: number;
  thesis_count: number;
  unlocked_achievement_ids: string[];
  shareable_text?: string;
}

interface Props {
  onClose: () => void;
}

// ─── Progress dots ───────────────────────────────────────────────────────────

function ProgressDots({ total, current }: { total: number; current: number }) {
  return (
    <div className="flex gap-1.5 justify-center">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={`rounded-full transition-all duration-300 ${
            i <= current ? "w-4 h-2 bg-white" : "w-2 h-2 bg-white/30"
          }`}
        />
      ))}
    </div>
  );
}

// ─── Card wrapper ─────────────────────────────────────────────────────────────

interface CardProps {
  gradient: string;
  children: React.ReactNode;
  visible: boolean;
}

function Card({ gradient, children, visible }: CardProps) {
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center px-8 text-center transition-opacity duration-300"
      style={{
        background: gradient,
        opacity: visible ? 1 : 0,
        pointerEvents: visible ? "auto" : "none",
      }}
    >
      {children}
    </div>
  );
}

// ─── Individual cards ────────────────────────────────────────────────────────

function Card1({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="text-white/60 text-sm uppercase tracking-[0.2em] mb-6">2025 in review</p>
      <div className="grid grid-cols-2 gap-x-12 gap-y-6">
        {[
          { value: data.total_trades,      label: "trades" },
          { value: `${data.learning_hours}h`, label: "learned" },
          { value: data.total_active_days, label: "active days" },
          { value: data.achievements_count, label: "badges" },
        ].map(({ value, label }) => (
          <div key={label} className="flex flex-col items-center">
            <span className="font-mono text-5xl font-bold text-white">{value}</span>
            <span className="text-white/60 text-sm mt-1">{label}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function Card2({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="text-white/60 text-2xl mb-4">👀 You watched</p>
      <p className="font-mono text-7xl font-bold text-white mb-4">{data.most_watched_ticker}</p>
      <p className="text-white/70 text-lg">more than anything else this year</p>
    </>
  );
}

function Card3({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="text-white/80 text-xl mb-2">🏆 Your Best Call</p>
      <p className="font-mono text-6xl font-bold text-white mb-2">{data.best_symbol}</p>
      <p className="font-mono text-3xl font-bold text-green-300 mb-4">
        +{data.best_pct_gain.toFixed(1)}%
      </p>
      <p className="text-white/70 text-base">
        You held for{" "}
        <span className="font-semibold text-white">{data.best_hold_days} days</span>
      </p>
    </>
  );
}

function Card4({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="text-white/60 text-xl mb-3">⏳ You held positions for</p>
      <p className="font-mono text-7xl font-bold text-white mb-2">{data.avg_hold_days}</p>
      <p className="text-white/60 text-xl mb-6">days on average</p>
      <div className="border-t border-white/20 pt-4">
        <p className="text-white/50 text-sm">vs. retail average: 11 days</p>
      </div>
    </>
  );
}

function Card5({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="text-white/60 text-xl mb-4">🧬 You are a</p>
      <p className="text-4xl font-bold text-white leading-tight">{data.sector_personality}</p>
    </>
  );
}

function Card6({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="font-mono text-7xl font-bold text-white mb-2">{data.learning_hours}</p>
      <p className="text-white/70 text-2xl mb-6">hours invested</p>
      <p className="text-white/60 text-base">in financial education</p>
      <div className="border-t border-white/20 mt-6 pt-4 w-full">
        <p className="text-white/50 text-sm italic">
          "Knowledge compounds faster than capital"
        </p>
      </div>
    </>
  );
}

function Card7({ data }: { data: AnnualRecapData }) {
  return (
    <>
      <p className="text-white/80 text-2xl mb-3">🔥 Longest streak</p>
      <p className="font-mono text-8xl font-bold text-white mb-1">{data.longest_streak}</p>
      <p className="text-white/60 text-xl mb-6">days</p>
      <p className="text-white/50 text-sm">
        {data.total_active_days} total active days
      </p>
    </>
  );
}

function Card8({ data, journalTotal }: { data: AnnualRecapData; journalTotal: number }) {
  return (
    <>
      <p className="text-white/60 text-xl mb-6">📓 Your Discipline</p>
      <div className="flex flex-col gap-6">
        <div>
          <p className="font-mono text-6xl font-bold text-white">{journalTotal}</p>
          <p className="text-white/60 text-base mt-1">trade journals</p>
        </div>
        <div>
          <p className="font-mono text-6xl font-bold text-white">{data.thesis_count}</p>
          <p className="text-white/60 text-base mt-1">documented theses</p>
        </div>
      </div>
    </>
  );
}

function Card9({ data }: { data: AnnualRecapData }) {
  const emojis = data.unlocked_achievement_ids
    .slice(0, 8)
    .map((id) => ACHIEVEMENT_EMOJIS[id] ?? "🏅");

  return (
    <>
      <p className="text-white/80 text-2xl mb-2">🏆 Achievements</p>
      <p className="font-mono text-6xl font-bold text-white mb-6">{data.achievements_count}</p>
      <div className="grid grid-cols-4 gap-3">
        {emojis.map((emoji, i) => (
          <div
            key={i}
            className="flex items-center justify-center w-12 h-12 rounded-xl bg-white/10 text-2xl"
          >
            {emoji}
          </div>
        ))}
      </div>
    </>
  );
}

function Card10({
  data,
  onClose,
}: {
  data: AnnualRecapData;
  onClose: () => void;
}) {
  const shareText = [
    "My 2025 in BMG Capital:",
    data.sector_personality,
    `🔥 ${data.longest_streak} day streak · 📚 ${data.learning_hours}h learned · 🏆 ${data.achievements_count} badges`,
    "",
    "No P&L shown — consistency is the metric.",
    "bmgcapital.com",
  ].join("\n");

  const handleCopy = () => {
    navigator.clipboard.writeText(shareText).catch(() => {});
  };

  return (
    <>
      <p className="text-4xl font-bold text-white mb-6 leading-snug whitespace-pre-wrap">
        {data.shareable_text ?? "You showed up.\nEvery day."}
      </p>
      <p className="text-white/50 text-base italic mb-10">
        "Consistency over intensity."
      </p>
      <div className="flex flex-col gap-3 w-full">
        <button
          onClick={handleCopy}
          className="w-full py-3 rounded-xl bg-white text-black font-semibold text-sm hover:bg-white/90 transition-colors"
        >
          Copy Your Card
        </button>
        <button
          onClick={onClose}
          className="w-full py-3 rounded-xl border border-white/30 text-white/80 font-medium text-sm hover:bg-white/10 transition-colors"
        >
          Done
        </button>
      </div>
    </>
  );
}

// ─── Gradients ───────────────────────────────────────────────────────────────

const CARD_GRADIENTS = [
  "linear-gradient(135deg, #1e3a5f 0%, #0f2044 100%)",         // 1 dark blue
  "linear-gradient(135deg, #92400e 0%, #78350f 100%)",         // 2 amber
  "linear-gradient(135deg, #14532d 0%, #052e16 100%)",         // 3 green
  "linear-gradient(135deg, #1e3a5f 0%, #0c1a3a 100%)",         // 4 navy
  "linear-gradient(135deg, #4c1d95 0%, #2e1065 100%)",         // 5 purple
  "linear-gradient(135deg, #134e4a 0%, #042f2e 100%)",         // 6 teal
  "linear-gradient(135deg, #7c2d12 0%, #431407 100%)",         // 7 orange
  "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",         // 8 slate
  "linear-gradient(135deg, #713f12 0%, #451a03 100%)",         // 9 gold
  "linear-gradient(135deg, #09090b 0%, #18181b 100%)",         // 10 dark
];

// ─── Mock / fallback ─────────────────────────────────────────────────────────

const MOCK_DATA: AnnualRecapData = {
  total_trades: 147,
  learning_hours: 32,
  total_active_days: 214,
  achievements_count: 23,
  most_watched_ticker: "NVDA",
  best_symbol: "NVDA",
  best_pct_gain: 34.7,
  best_hold_days: 112,
  avg_hold_days: 24,
  sector_personality: "Tech Growth Investor",
  longest_streak: 47,
  journal_entries: 18,
  thesis_count: 9,
  unlocked_achievement_ids: [
    "first_login", "profile_complete", "first_deposit", "first_lesson",
    "investing_101", "diamond_hands", "streak_30", "backtest_apprentice",
  ],
  shareable_text: "You showed up.\nEvery day.",
};

// ─── Main component ───────────────────────────────────────────────────────────

export default function YearInCapital({ onClose }: Props) {
  const [cardIndex, setCardIndex] = useState(0);
  const TOTAL_CARDS = 10;

  const { data: annualData } = useQuery<AnnualRecapData>({
    queryKey: ["engagement-annual-recap"],
    queryFn: () => client.get("/api/engagement/recap/annual").then((r) => r.data),
  });

  const { data: journalTotal } = useQuery<number>({
    queryKey: ["journal-total"],
    queryFn: () =>
      client.get("/api/journal?limit=1").then((r) => r.data.total ?? 0),
  });

  const data = annualData ?? MOCK_DATA;
  const journalCount = journalTotal ?? data.journal_entries;

  const goNext = useCallback(() => {
    setCardIndex((i) => Math.min(i + 1, TOTAL_CARDS - 1));
  }, []);

  const goBack = useCallback(() => {
    setCardIndex((i) => Math.max(i - 1, 0));
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") goNext();
      if (e.key === "ArrowLeft") goBack();
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goNext, goBack, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80">
      <div
        className="relative w-full h-full max-w-sm mx-auto overflow-hidden cursor-pointer select-none"
        onClick={goNext}
      >
        {/* Cards */}
        {CARD_GRADIENTS.map((gradient, i) => (
          <Card key={i} gradient={gradient} visible={cardIndex === i}>
            {i === 0 && <Card1 data={data} />}
            {i === 1 && <Card2 data={data} />}
            {i === 2 && <Card3 data={data} />}
            {i === 3 && <Card4 data={data} />}
            {i === 4 && <Card5 data={data} />}
            {i === 5 && <Card6 data={data} />}
            {i === 6 && <Card7 data={data} />}
            {i === 7 && <Card8 data={data} journalTotal={journalCount} />}
            {i === 8 && <Card9 data={data} />}
            {i === 9 && <Card10 data={data} onClose={onClose} />}
          </Card>
        ))}

        {/* Top HUD — progress dots + close */}
        <div
          className="absolute top-0 left-0 right-0 z-10 flex flex-col gap-3 px-4 pt-safe-area-inset-top pb-4"
          style={{ paddingTop: "max(env(safe-area-inset-top), 16px)" }}
          onClick={(e) => e.stopPropagation()}
        >
          <ProgressDots total={TOTAL_CARDS} current={cardIndex} />
          <div className="flex justify-between items-center">
            <button
              onClick={goBack}
              disabled={cardIndex === 0}
              className="text-white/60 hover:text-white transition-colors disabled:opacity-20"
            >
              <ChevronLeft size={24} />
            </button>
            <button
              onClick={onClose}
              className="text-white/60 hover:text-white transition-colors"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Bottom tap hint (card 1 only) */}
        {cardIndex === 0 && (
          <div className="absolute bottom-8 left-0 right-0 flex justify-center pointer-events-none">
            <p className="text-white/30 text-xs animate-pulse">Tap to continue</p>
          </div>
        )}
      </div>
    </div>
  );
}
