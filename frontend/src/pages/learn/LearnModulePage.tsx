import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Clock, CheckCircle2 } from "lucide-react";
import { getModule } from "@/api/learning";
import type { LessonSummary } from "@/api/learning";
import { cn } from "@/lib/utils";

function LessonRow({
  lesson,
  trackSlug,
  moduleSlug,
}: {
  lesson: LessonSummary;
  trackSlug: string;
  moduleSlug: string;
}) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/learn/tracks/${trackSlug}/${moduleSlug}/${lesson.slug}`)}
      className="flex items-center gap-3 p-3.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:bg-[var(--bg-elevated-2)] hover:border-[var(--border-emphasis)] cursor-pointer transition-all duration-150 group"
    >
      {/* Completion indicator */}
      <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center border border-[var(--border-emphasis)] bg-[var(--bg-elevated-2)] group-hover:border-[var(--accent-positive)]/40">
        {lesson.completed ? (
          <CheckCircle2 size={16} className="text-[var(--accent-positive)]" />
        ) : (
          <span className="text-[10px] font-bold text-[var(--text-tertiary)]">
            {lesson.order}
          </span>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <p
          className={cn(
            "text-sm font-medium leading-tight",
            lesson.completed ? "text-[var(--text-secondary)]" : "text-[var(--text-primary)]"
          )}
        >
          {lesson.title}
        </p>
        {lesson.estimated_minutes && (
          <p className="text-[10px] text-[var(--text-tertiary)] flex items-center gap-1 mt-0.5">
            <Clock size={9} /> {lesson.estimated_minutes} min
          </p>
        )}
      </div>

      <div className="shrink-0">
        <span
          className={cn(
            "text-xs font-medium px-2.5 py-1 rounded-lg border transition-colors",
            lesson.completed
              ? "text-[var(--accent-positive)] bg-[var(--accent-positive)]/8 border-[var(--accent-positive)]/20"
              : "text-[var(--text-secondary)] bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)] group-hover:text-[var(--text-primary)]"
          )}
        >
          {lesson.completed ? (
            <span className="flex items-center gap-1">
              Review <ChevronRight size={11} />
            </span>
          ) : (
            <span className="flex items-center gap-1">
              Start <ChevronRight size={11} />
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

export default function LearnModulePage() {
  const { trackSlug, moduleSlug } = useParams<{
    trackSlug: string;
    moduleSlug: string;
  }>();
  const navigate = useNavigate();

  const { data: module, isLoading } = useQuery({
    queryKey: ["learning-module", trackSlug, moduleSlug],
    queryFn: () => getModule(trackSlug!, moduleSlug!),
    enabled: !!(trackSlug && moduleSlug),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto space-y-4">
        <div className="h-6 w-32 bg-[var(--bg-elevated-2)] rounded animate-pulse" />
        <div className="h-28 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-16 bg-[var(--bg-elevated-2)] rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!module) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-tertiary)]">
        Module not found.{" "}
        <button
          className="ml-2 text-[var(--text-primary)] underline"
          onClick={() => navigate(`/learn/tracks/${trackSlug}`)}
        >
          Back to track
        </button>
      </div>
    );
  }

  const completedCount = module.lessons.filter((l) => l.completed).length;
  const pct = module.lesson_count > 0 ? completedCount / module.lesson_count : 0;

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-20 md:pb-8">
      {/* Back nav */}
      <button
        onClick={() => navigate(`/learn/tracks/${trackSlug}`)}
        className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm transition-colors"
      >
        <ChevronLeft size={16} /> Back to Track
      </button>

      {/* Module header */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6">
        <h1 className="text-xl font-bold text-[var(--text-primary)] mb-2">{module.name}</h1>
        {module.description && (
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-3">
            {module.description}
          </p>
        )}

        <div className="flex items-center gap-4 text-[11px] text-[var(--text-tertiary)] mb-3">
          {module.estimated_hours && (
            <span className="flex items-center gap-1">
              <Clock size={11} /> {module.estimated_hours}h estimated
            </span>
          )}
          <span>{module.lesson_count} lessons</span>
          <span>{completedCount} completed</span>
        </div>

        {module.lesson_count > 0 && (
          <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--accent-positive)] transition-all duration-500"
              style={{ width: `${pct * 100}%` }}
            />
          </div>
        )}
      </div>

      {/* Lesson list */}
      <div className="space-y-2">
        <h2 className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          Lessons
        </h2>
        {module.lessons.map((lesson) => (
          <LessonRow
            key={lesson.slug}
            lesson={lesson}
            trackSlug={trackSlug!}
            moduleSlug={moduleSlug!}
          />
        ))}
      </div>
    </div>
  );
}
