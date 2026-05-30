import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ChevronLeft, CheckCircle2, Lock, Clock, Zap, BookOpen, FlaskConical, Bot } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { getProgress } from "@/api/learn";
import { useLearnStore } from "@/store/learnStore";
import {
  TRACK_MAP, COURSE_MAP, coursesForTrack, lessonsForCourse,
  courseProgress, trackProgress,
} from "@/data/curriculum";
import { cn } from "@/lib/utils";
import LevelBar from "@/components/learn/LevelBar";
import StreakBadge from "@/components/learn/StreakBadge";

const TRACK_ACCENT: Record<string, string> = {
  emerald: "text-[var(--accent-positive)] bg-[var(--accent-positive-bg)] border-emerald-500/20",
  blue: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  violet: "text-violet-400 bg-violet-500/10 border-violet-500/20",
  amber: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  rose: "text-[var(--accent-negative)] bg-rose-500/10 border-rose-500/20",
  purple: "text-purple-400 bg-purple-500/10 border-purple-500/20",
  teal: "text-teal-400 bg-teal-500/10 border-teal-500/20",
  orange: "text-orange-400 bg-orange-500/10 border-orange-500/20",
  cyan: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
};

const TRACK_BAR: Record<string, string> = {
  emerald: "bg-[#22C55E]", blue: "bg-blue-500", violet: "bg-violet-500",
  amber: "bg-amber-500", rose: "bg-rose-500", purple: "bg-purple-500",
  teal: "bg-teal-500", orange: "bg-orange-500", cyan: "bg-cyan-500",
};

export default function LearnCourse() {
  const { trackId } = useParams<{ trackId: string }>();
  const navigate = useNavigate();
  const { progress } = useLearnStore();
  const [aiOpen, setAiOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ["learn-progress"],
    queryFn: getProgress,
    staleTime: 30_000,
  });

  const p = progress ?? data;
  const completedIds = p?.completedLessonIds ?? [];
  const track = trackId ? TRACK_MAP[trackId] : null;

  if (!track) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-tertiary)]">
        Track not found. <button className="ml-2 text-[var(--text-primary)] underline" onClick={() => navigate("/learn")}>Back to Learn</button>
      </div>
    );
  }

  const courses = coursesForTrack(track.id);
  const trackPct = trackProgress(track.id, completedIds);
  const accent = TRACK_ACCENT[track.colorClass] ?? "text-[var(--text-secondary)] bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)]";
  const bar = TRACK_BAR[track.colorClass] ?? "bg-zinc-500";

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Back nav */}
      <button
        onClick={() => navigate("/learn")}
        className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm transition-colors"
      >
        <ChevronLeft size={16} /> Learning Center
      </button>

      {/* Track header */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6">
        <div className="flex items-start gap-4">
          <span className="text-4xl">{track.icon}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-xl font-bold text-[var(--text-primary)]">{track.title}</h1>
              <span className={cn("text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border", accent)}>
                {track.difficulty}
              </span>
              <button onClick={() => setAiOpen(true)} className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
                <Bot size={12} /> Ask AI
              </button>
            </div>
            <p className="text-[var(--text-secondary)] text-sm leading-relaxed">{track.description}</p>
            <div className="mt-4 space-y-1.5">
              <div className="flex items-center justify-between text-xs text-[var(--text-tertiary)]">
                <span>{courses.length} courses · {Math.round(trackPct * 100)}% complete</span>
                {p && <StreakBadge streak={p.streak} size="sm" />}
              </div>
              <div className="h-1.5 bg-[#334155] rounded-full overflow-hidden">
                <div className={cn("h-full rounded-full transition-all duration-500", bar)} style={{ width: `${trackPct * 100}%` }} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Courses */}
      <div className="space-y-4">
        {courses.map((course, courseIdx) => {
          const lessons = lessonsForCourse(course.id);
          const coursePct = courseProgress(course.id, completedIds);
          const courseComplete = coursePct === 1;
          const firstIncomplete = lessons.find((l) => !completedIds.includes(l.id));
          const isLocked = courseIdx > 0 && courseProgress(courses[courseIdx - 1].id, completedIds) < 0.5;

          return (
            <div
              key={course.id}
              className={cn(
                "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden",
                isLocked && "opacity-60"
              )}
            >
              {/* Course header */}
              <div className="p-4 border-b border-[var(--border-subtle)]">
                <div className="flex items-center gap-3">
                  {courseComplete ? (
                    <CheckCircle2 size={18} className="text-[var(--accent-positive)] shrink-0" />
                  ) : isLocked ? (
                    <Lock size={18} className="text-[var(--text-tertiary)] shrink-0" />
                  ) : (
                    <BookOpen size={18} className="text-[var(--text-tertiary)] shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-[var(--text-primary)] text-sm">{course.title}</p>
                    <p className="text-xs text-[var(--text-tertiary)] truncate">{course.description}</p>
                  </div>
                  {!isLocked && !courseComplete && firstIncomplete && (
                    <button
                      onClick={() => navigate(`/learn/lesson/${firstIncomplete.id}`)}
                      className="shrink-0 flex items-center gap-1 text-xs font-semibold text-[var(--text-primary)] hover:text-[var(--accent-positive)] transition-colors"
                    >
                      {coursePct > 0 ? "Continue" : "Start"}
                      <ChevronRight size={14} />
                    </button>
                  )}
                  {courseComplete && (
                    <span className="shrink-0 text-xs text-[var(--accent-positive)] font-semibold">Complete ✓</span>
                  )}
                </div>
                {coursePct > 0 && (
                  <div className="mt-2 h-1 bg-[#334155] rounded-full overflow-hidden">
                    <div className={cn("h-full rounded-full", bar)} style={{ width: `${coursePct * 100}%` }} />
                  </div>
                )}
              </div>

              {/* Lessons list */}
              <div className="divide-y divide-zinc-900/50">
                {lessons.map((lesson, lessonIdx) => {
                  const done = completedIds.includes(lesson.id);
                  const lessonLocked = isLocked || (lessonIdx > 0 && !completedIds.includes(lessons[lessonIdx - 1]?.id ?? ""));
                  // First lesson is always accessible
                  const isAccessible = lessonIdx === 0 || done || !lessonLocked || !!firstIncomplete && lesson.id === firstIncomplete.id;

                  return (
                    <div
                      key={lesson.id}
                      onClick={() => !isLocked && navigate(`/learn/lesson/${lesson.id}`)}
                      className={cn(
                        "flex items-center gap-3 px-4 py-3 transition-colors",
                        !isLocked && "cursor-pointer hover:bg-[var(--bg-elevated-2)]/50",
                        isLocked && "opacity-50"
                      )}
                    >
                      <div className={cn(
                        "w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-sm",
                        done ? "bg-[#22C55E]/20 text-[var(--accent-positive)]" : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]"
                      )}>
                        {done ? <CheckCircle2 size={14} /> : <span className="text-[11px] font-bold">{lessonIdx + 1}</span>}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className={cn("text-sm font-medium truncate", done ? "text-[var(--text-secondary)]" : "text-[var(--text-primary)]")}>
                          {lesson.title}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[10px] text-[var(--text-tertiary)] capitalize">{lesson.type}</span>
                          <span className="text-[10px] text-[var(--text-tertiary)]">·</span>
                          <Clock size={10} className="text-[var(--text-tertiary)]" />
                          <span className="text-[10px] text-[var(--text-tertiary)]">{lesson.durationMin}m</span>
                          {lesson.type === "challenge" && <FlaskConical size={10} className="text-amber-500" />}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Zap size={11} className={done ? "text-[var(--text-tertiary)]" : "text-amber-400"} />
                        <span className={cn("text-xs font-semibold", done ? "text-[var(--text-tertiary)]" : "text-[var(--text-secondary)]")}>
                          {lesson.xp}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {p && <LevelBar xp={p.xp} compact className="max-w-xs" />}
      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask about this Course"
        context={track ? `Learning track: ${track.title} — ${track.description}` : "Trading course content"}
        suggestedQuestions={[
          "Can you give me an overview of what I'll learn?",
          "What prerequisites do I need for this course?",
          "How long will this course take to complete?",
          "What real-world skills will I gain?",
          "What should I study after finishing this course?",
        ]}
      />
    </div>
  );
}
