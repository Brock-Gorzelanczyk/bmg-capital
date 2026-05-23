import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, GraduationCap, Flame, Trophy, ChevronRight,
  Zap, CalendarCheck, Users, Lock,
} from "lucide-react";
import { getProgress, completeOnboarding, getDailyChallenge, getLeaderboard } from "@/api/learn";
import { useLearnStore } from "@/store/learnStore";
import { TRACKS, COURSES, coursesForTrack, trackProgress, nextLesson, trackTotalXP } from "@/data/curriculum";
import { xpProgressInLevel, BADGE_META } from "@/types/learn";
import LevelBar from "@/components/learn/LevelBar";
import StreakBadge from "@/components/learn/StreakBadge";
import PlacementQuiz from "@/components/learn/PlacementQuiz";
import { cn } from "@/lib/utils";

const TRACK_GRADIENT: Record<string, string> = {
  emerald: "from-emerald-500/10 to-emerald-500/5 border-emerald-500/20",
  blue: "from-blue-500/10 to-blue-500/5 border-blue-500/20",
  violet: "from-violet-500/10 to-violet-500/5 border-violet-500/20",
  amber: "from-amber-500/10 to-amber-500/5 border-amber-500/20",
  rose: "from-rose-500/10 to-rose-500/5 border-rose-500/20",
  purple: "from-purple-500/10 to-purple-500/5 border-purple-500/20",
  teal: "from-teal-500/10 to-teal-500/5 border-teal-500/20",
  orange: "from-orange-500/10 to-orange-500/5 border-orange-500/20",
  cyan: "from-cyan-500/10 to-cyan-500/5 border-cyan-500/20",
};

const TRACK_TEXT: Record<string, string> = {
  emerald: "text-[#22C55E]", blue: "text-blue-400", violet: "text-violet-400",
  amber: "text-amber-400", rose: "text-[#EF4444]", purple: "text-purple-400",
  teal: "text-teal-400", orange: "text-orange-400", cyan: "text-cyan-400",
};

const TRACK_PROGRESS_BAR: Record<string, string> = {
  emerald: "bg-[#22C55E]", blue: "bg-blue-500", violet: "bg-violet-500",
  amber: "bg-amber-500", rose: "bg-rose-500", purple: "bg-purple-500",
  teal: "bg-teal-500", orange: "bg-orange-500", cyan: "bg-cyan-500",
};

export default function LearnHome() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { progress, setProgress, hydrated } = useLearnStore();
  const [showPlacement, setShowPlacement] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["learn-progress"],
    queryFn: getProgress,
    staleTime: 30_000,
  });

  const { data: daily } = useQuery({
    queryKey: ["learn-daily"],
    queryFn: getDailyChallenge,
    staleTime: 5 * 60_000,
  });

  const { data: leaderboard } = useQuery({
    queryKey: ["learn-leaderboard"],
    queryFn: getLeaderboard,
    staleTime: 5 * 60_000,
  });

  const onboardMut = useMutation({
    mutationFn: completeOnboarding,
    onSuccess: (d) => { setProgress(d); qc.invalidateQueries({ queryKey: ["learn-progress"] }); },
  });

  useEffect(() => {
    if (data) setProgress(data);
  }, [data]);

  useEffect(() => {
    if (data && !data.onboardingComplete) setShowPlacement(true);
  }, [data]);

  const p = progress ?? data;

  if (isLoading && !p) {
    return (
      <div className="max-w-5xl mx-auto space-y-6">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 bg-[#1E293B]/50 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (showPlacement) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4">
        <div className="text-center mb-10">
          <div className="text-5xl mb-4">🎓</div>
          <h1 className="text-2xl font-bold text-white">Welcome to BMG Capital Learn</h1>
          <p className="text-[#94A3B8] mt-2">Answer 5 quick questions to get a personalized learning path.</p>
        </div>
        <PlacementQuiz
          onComplete={(trackId) => {
            onboardMut.mutate(trackId);
            setShowPlacement(false);
          }}
        />
      </div>
    );
  }

  const completedIds = p?.completedLessonIds ?? [];
  const selectedTrackId = p?.selectedTrack ?? TRACKS[0].id;
  const selectedTrack = TRACKS.find((t) => t.id === selectedTrackId) ?? TRACKS[0];
  const resumeLesson = p ? nextLesson(selectedTrackId, completedIds) : null;

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-20 md:pb-8">
      {/* Header */}
      <div className="flex items-start gap-6">
        <div className="flex-1 space-y-3">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-white">Learning Center</h1>
            {p && <StreakBadge streak={p.streak} />}
          </div>
          {p && <LevelBar xp={p.xp} className="max-w-sm" />}
        </div>

        {/* Quick stats */}
        {p && (
          <div className="hidden lg:flex items-center gap-4 shrink-0">
            <Stat label="Lessons done" value={p.completedLessonIds.length} icon={<BookOpen size={14} />} />
            <Stat label="Best streak" value={`${p.longestStreak}d`} icon={<Flame size={14} />} />
            <Stat label="Badges" value={p.badges.length} icon={<Trophy size={14} />} />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main content — 2 cols */}
        <div className="lg:col-span-2 space-y-6">
          {/* Daily challenge */}
          {daily && !daily.completed && (
            <div className="bg-gradient-to-r from-indigo-500/10 to-purple-500/10 border border-indigo-500/20 rounded-xl p-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-indigo-500/15 flex items-center justify-center">
                <CalendarCheck size={20} className="text-indigo-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-white font-semibold text-sm">Daily Challenge</p>
                <p className="text-indigo-300/70 text-xs">Complete today's challenge lesson to earn bonus XP</p>
              </div>
              <button
                onClick={() => navigate(`/learn/lesson/${daily.lessonId}`)}
                className="shrink-0 flex items-center gap-1.5 bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-indigo-500/30 transition-colors"
              >
                Start <ChevronRight size={12} />
              </button>
            </div>
          )}

          {/* Resume card */}
          {resumeLesson && (
            <div
              className={cn(
                "bg-gradient-to-br border rounded-xl p-5 cursor-pointer hover:opacity-90 transition-opacity",
                TRACK_GRADIENT[selectedTrack.colorClass]
              )}
              onClick={() => navigate(`/learn/lesson/${resumeLesson.id}`)}
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-xs font-semibold text-[#94A3B8] uppercase tracking-widest mb-1">
                    Continue · {selectedTrack.title}
                  </p>
                  <h2 className="text-lg font-bold text-white">{resumeLesson.title}</h2>
                  <p className="text-sm text-[#94A3B8] mt-1">{resumeLesson.durationMin} min · +{resumeLesson.xp} XP</p>
                </div>
                <div className={cn("text-3xl", TRACK_TEXT[selectedTrack.colorClass])}>
                  {selectedTrack.icon}
                </div>
              </div>
              <div className="mt-4">
                <div className="h-1.5 bg-[#020617]/20 rounded-full overflow-hidden">
                  <div
                    className={cn("h-full rounded-full", TRACK_PROGRESS_BAR[selectedTrack.colorClass])}
                    style={{ width: `${trackProgress(selectedTrackId, completedIds) * 100}%` }}
                  />
                </div>
                <p className="text-[10px] text-[#475569] mt-1">
                  {Math.round(trackProgress(selectedTrackId, completedIds) * 100)}% complete
                </p>
              </div>
            </div>
          )}

          {/* All tracks */}
          <div>
            <h2 className="text-xs font-semibold text-[#475569] uppercase tracking-widest mb-3">All Learning Tracks</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {TRACKS.map((track) => {
                const pct = trackProgress(track.id, completedIds);
                const courses = coursesForTrack(track.id);
                const totalXP = trackTotalXP(track.id);
                const isSelected = track.id === selectedTrackId;

                return (
                  <div
                    key={track.id}
                    onClick={() => navigate(`/learn/${track.id}`)}
                    className={cn(
                      "bg-[#0F172A] border rounded-xl p-4 cursor-pointer hover:bg-[#1E293B] transition-all group",
                      isSelected ? "border-zinc-600" : "border-[#1E293B]"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">{track.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-white text-sm truncate">{track.title}</p>
                          {isSelected && (
                            <span className="text-[9px] font-bold text-[#22C55E] bg-[#22C55E]/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                              ACTIVE
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-[#475569] mt-0.5 capitalize">{track.difficulty} · {courses.length} courses · {totalXP} XP</p>
                      </div>
                      <ChevronRight size={14} className="text-[#475569] group-hover:text-[#94A3B8] transition-colors shrink-0 mt-1" />
                    </div>
                    {pct > 0 && (
                      <div className="mt-3">
                        <div className="h-1 bg-[#334155] rounded-full overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", TRACK_PROGRESS_BAR[track.colorClass] ?? "bg-zinc-500")}
                            style={{ width: `${pct * 100}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Badges */}
          {p && p.badges.length > 0 && (
            <div>
              <h2 className="text-xs font-semibold text-[#475569] uppercase tracking-widest mb-3">Your Badges</h2>
              <div className="flex flex-wrap gap-2">
                {p.badges.map((b) => {
                  const meta = BADGE_META[b];
                  if (!meta) return null;
                  return (
                    <div key={b} title={`${meta.label}: ${meta.description}`}
                      className="flex items-center gap-2 bg-[#1E293B] border border-[#334155] rounded-xl px-3 py-2">
                      <span className="text-base">{meta.icon}</span>
                      <span className="text-xs font-medium text-[#94A3B8]">{meta.label}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar — leaderboard */}
        <div className="space-y-4">
          {leaderboard && leaderboard.length > 0 && (
            <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <Users size={13} className="text-[#475569]" />
                <h3 className="text-xs font-semibold text-[#475569] uppercase tracking-widest">XP Leaderboard</h3>
              </div>
              <div className="space-y-2">
                {leaderboard.slice(0, 8).map((entry) => (
                  <div key={entry.userId} className="flex items-center gap-2">
                    <span className="text-[10px] text-[#475569] w-4 text-right shrink-0">{entry.rank}</span>
                    <div className="w-6 h-6 rounded-full bg-[#334155] flex items-center justify-center text-[10px] font-bold text-[#94A3B8] shrink-0">
                      {entry.username[0]?.toUpperCase()}
                    </div>
                    <span className="text-xs text-[#94A3B8] flex-1 truncate">{entry.username}</span>
                    <div className="flex items-center gap-0.5 shrink-0">
                      <Zap size={10} className="text-amber-400" />
                      <span className="text-[10px] text-[#94A3B8]">{entry.xp.toLocaleString()}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Quick nav */}
          <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-4 space-y-2">
            <h3 className="text-xs font-semibold text-[#475569] uppercase tracking-widest mb-3">Quick Access</h3>
            {[
              { label: "Investing Fundamentals", id: "investing-fundamentals", icon: "📚" },
              { label: "Technical Analysis", id: "technical-analysis", icon: "📈" },
              { label: "Fundamental Analysis", id: "fundamental-analysis", icon: "🏛️" },
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => navigate(`/learn/${t.id}`)}
                className="w-full flex items-center gap-2.5 py-1.5 text-left group"
              >
                <span className="text-base">{t.icon}</span>
                <span className="text-xs text-[#94A3B8] group-hover:text-[#F8FAFC] transition-colors flex-1 truncate">{t.label}</span>
                <ChevronRight size={12} className="text-[#475569] group-hover:text-[#94A3B8]" />
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <div className="text-center">
      <div className="flex items-center justify-center gap-1 text-[#475569] mb-0.5">{icon}<span className="text-[10px] uppercase tracking-wider">{label}</span></div>
      <p className="text-lg font-bold text-white">{value}</p>
    </div>
  );
}
