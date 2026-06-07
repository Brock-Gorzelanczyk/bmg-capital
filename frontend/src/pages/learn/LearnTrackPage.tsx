import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Clock, BookOpen, CheckCircle2, Lock } from "lucide-react";
import { getTrack } from "@/api/learning";
import type { ModuleSummary } from "@/api/learning";
import { cn } from "@/lib/utils";

const TIER_STYLES: Record<string, { badge: string; bar: string }> = {
  "1": { badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", bar: "bg-emerald-500" },
  "2": { badge: "bg-blue-500/10 text-blue-400 border-blue-500/20", bar: "bg-blue-500" },
  "3": { badge: "bg-violet-500/10 text-violet-400 border-violet-500/20", bar: "bg-violet-500" },
  "exam_prep": { badge: "bg-amber-500/10 text-amber-400 border-amber-500/20", bar: "bg-amber-500" },
};

function ModuleCard({
  module,
  trackSlug,
}: {
  module: ModuleSummary;
  trackSlug: string;
}) {
  const navigate = useNavigate();
  const pct = module.lesson_count > 0 ? module.completed_count / module.lesson_count : 0;
  const isComplete = module.lesson_count > 0 && module.completed_count >= module.lesson_count;
  const hasProgress = module.completed_count > 0 && !isComplete;

  function handleClick() {
    if (!module.is_published) return;
    navigate(`/learn/tracks/${trackSlug}/${module.slug}`);
  }

  return (
    <div
      onClick={handleClick}
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4",
        module.is_published
          ? "cursor-pointer hover:bg-[var(--bg-elevated-2)] hover:border-[var(--border-emphasis)] transition-all duration-150 group"
          : "opacity-60"
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-semibold text-[var(--text-primary)] text-sm leading-tight">
              {module.name}
            </span>
            {!module.is_published && (
              <span className="flex items-center gap-1 text-[9px] font-semibold text-zinc-500 bg-zinc-800 border border-zinc-700 px-1.5 py-0.5 rounded-full shrink-0">
                <Lock size={8} /> Coming soon
              </span>
            )}
            {isComplete && (
              <CheckCircle2 size={14} className="text-[var(--accent-positive)] shrink-0" />
            )}
          </div>
          {module.description && (
            <p className="text-[11px] text-[var(--text-tertiary)] leading-relaxed mb-2">
              {module.description}
            </p>
          )}
          <div className="flex items-center gap-3 text-[10px] text-[var(--text-tertiary)]">
            <span className="flex items-center gap-1">
              <BookOpen size={10} /> {module.lesson_count} lessons
            </span>
            {module.estimated_hours && (
              <span className="flex items-center gap-1">
                <Clock size={10} /> {module.estimated_hours}h
              </span>
            )}
          </div>
        </div>

        {module.is_published && (
          <div className="shrink-0 flex flex-col items-end gap-2">
            <button
              className={cn(
                "flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors",
                isComplete
                  ? "bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] border border-[var(--accent-positive)]/20"
                  : hasProgress
                  ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                  : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] border border-[var(--border-emphasis)] group-hover:bg-[var(--bg-elevated-3,#2a2a2e)]"
              )}
            >
              {isComplete ? (
                <>Review <CheckCircle2 size={12} /></>
              ) : hasProgress ? (
                <>Continue <ChevronRight size={12} /></>
              ) : (
                <>Start <ChevronRight size={12} /></>
              )}
            </button>
          </div>
        )}
      </div>

      {module.is_published && module.lesson_count > 0 && (
        <div className="mt-3 space-y-1">
          <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                isComplete ? "bg-[var(--accent-positive)]" : "bg-blue-500"
              )}
              style={{ width: `${pct * 100}%` }}
            />
          </div>
          {(pct > 0) && (
            <p className="text-[10px] text-[var(--text-tertiary)]">
              {module.completed_count} / {module.lesson_count} lessons
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function LearnTrackPage() {
  const { trackSlug } = useParams<{ trackSlug: string }>();
  const navigate = useNavigate();

  const { data: track, isLoading } = useQuery({
    queryKey: ["learning-track", trackSlug],
    queryFn: () => getTrack(trackSlug!),
    enabled: !!trackSlug,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto space-y-4">
        <div className="h-6 w-32 bg-[var(--bg-elevated-2)] rounded animate-pulse" />
        <div className="h-28 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (!track) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-tertiary)]">
        Track not found.{" "}
        <button
          className="ml-2 text-[var(--text-primary)] underline"
          onClick={() => navigate("/learn/tracks")}
        >
          Back to Learning Center
        </button>
      </div>
    );
  }

  const styles = TIER_STYLES[track.cert_tier ?? "1"] ?? TIER_STYLES["1"];
  const certLabel =
    track.cert_tier === "exam_prep" ? "Exam Prep" : track.cert_tier ? `Tier ${track.cert_tier}` : "";
  const pct = track.total_lessons > 0 ? track.completed_lessons / track.total_lessons : 0;

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-20 md:pb-8">
      {/* Back nav */}
      <button
        onClick={() => navigate("/learn/tracks")}
        className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm transition-colors"
      >
        <ChevronLeft size={16} /> Learning Center
      </button>

      {/* Track header */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <h1 className="text-xl font-bold text-[var(--text-primary)]">{track.name}</h1>
              {certLabel && (
                <span
                  className={cn(
                    "text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full border shrink-0",
                    styles.badge
                  )}
                >
                  {certLabel}
                </span>
              )}
            </div>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              {track.description}
            </p>
            <div className="flex items-center gap-4 mt-3 text-[11px] text-[var(--text-tertiary)]">
              <span className="flex items-center gap-1">
                <Clock size={11} /> {track.estimated_hours}h estimated
              </span>
              <span className="flex items-center gap-1">
                <BookOpen size={11} /> {track.modules.length} modules
              </span>
            </div>
          </div>
        </div>

        {pct > 0 && (
          <div className="mt-4 space-y-1">
            <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-500", styles.bar)}
                style={{ width: `${pct * 100}%` }}
              />
            </div>
            <p className="text-[10px] text-[var(--text-tertiary)]">
              {track.completed_lessons} / {track.total_lessons} lessons complete
            </p>
          </div>
        )}

        {track.prereq_track_slugs && track.prereq_track_slugs.length > 0 && (
          <div className="mt-3 text-[11px] text-[var(--text-tertiary)]">
            Prerequisites:{" "}
            {track.prereq_track_slugs.map((s, i) => (
              <span key={s}>
                {i > 0 && ", "}
                <button
                  className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] underline"
                  onClick={() => navigate(`/learn/tracks/${s}`)}
                >
                  {s.replace(/-/g, " ")}
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Modules */}
      <div className="space-y-3">
        <h2 className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          Modules
        </h2>
        {track.modules.map((module) => (
          <ModuleCard key={module.slug} module={module} trackSlug={track.slug} />
        ))}
      </div>
    </div>
  );
}
