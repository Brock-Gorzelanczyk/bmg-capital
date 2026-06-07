import { useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Clock, BookOpen, GraduationCap, Lock, Award } from "lucide-react";
import { getTracks } from "@/api/learning";
import type { LearningTrack } from "@/api/learning";
import { cn } from "@/lib/utils";

// Colors per cert tier
const TIER_STYLES: Record<string, { badge: string; bar: string; accent: string }> = {
  "1": {
    badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    bar: "bg-emerald-500",
    accent: "border-emerald-500/30",
  },
  "2": {
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    bar: "bg-blue-500",
    accent: "border-blue-500/30",
  },
  "3": {
    badge: "bg-violet-500/10 text-violet-400 border-violet-500/20",
    bar: "bg-violet-500",
    accent: "border-violet-500/30",
  },
  "exam_prep": {
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    bar: "bg-amber-500",
    accent: "border-amber-500/30",
  },
};

const CERT_TIERS = [
  {
    tier: "1",
    name: "Tier 1 Certificate",
    subtitle: "Foundation",
    tracks: ["Track 1", "Track 2", "Track 3", "Track 4"],
    description: "Platform mastery, business analysis, financial statements, and valuation.",
  },
  {
    tier: "2",
    name: "Tier 2 Certificate",
    subtitle: "Applied",
    tracks: ["Track 5", "Track 6", "Track 7"],
    description: "Portfolio construction, macro & factors, and professional risk management.",
  },
  {
    tier: "3",
    name: "Tier 3 Certificate",
    subtitle: "Advanced",
    tracks: ["Track 8", "Track 9"],
    description: "Behavioral finance, forensic accounting, and live stock pitch.",
  },
];

function ProgressBar({ pct, barClass }: { pct: number; barClass: string }) {
  return (
    <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all duration-500", barClass)}
        style={{ width: `${Math.min(pct * 100, 100)}%` }}
      />
    </div>
  );
}

function TrackCard({ track }: { track: LearningTrack }) {
  const navigate = useNavigate();
  const styles = TIER_STYLES[track.cert_tier ?? "1"] ?? TIER_STYLES["1"];
  const publishedModules = track.modules.filter((m) => m.is_published).length;
  const totalModules = track.modules.length;
  const pct = track.total_lessons > 0 ? track.completed_lessons / track.total_lessons : 0;
  const certLabel =
    track.cert_tier === "exam_prep"
      ? "Exam Prep"
      : track.cert_tier
      ? `Tier ${track.cert_tier}`
      : "";

  return (
    <div
      onClick={() => navigate(`/learn/tracks/${track.slug}`)}
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 cursor-pointer",
        "hover:bg-[var(--bg-elevated-2)] hover:border-[var(--border-emphasis)] transition-all duration-150 group"
      )}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h3 className="font-semibold text-[var(--text-primary)] text-sm leading-tight">
              {track.name}
            </h3>
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
          <p className="text-[11px] text-[var(--text-tertiary)] leading-relaxed line-clamp-2">
            {track.description}
          </p>
        </div>
        <ChevronRight
          size={15}
          className="text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] shrink-0 mt-0.5 transition-colors"
        />
      </div>

      <div className="flex items-center gap-3 text-[10px] text-[var(--text-tertiary)] mb-3">
        <span className="flex items-center gap-1">
          <Clock size={10} /> {track.estimated_hours}h
        </span>
        <span className="flex items-center gap-1">
          <BookOpen size={10} /> {totalModules} modules
        </span>
        {publishedModules < totalModules && (
          <span className="flex items-center gap-1 text-zinc-500">
            <Lock size={10} /> {totalModules - publishedModules} coming soon
          </span>
        )}
      </div>

      {pct > 0 ? (
        <div className="space-y-1">
          <ProgressBar pct={pct} barClass={styles.bar} />
          <p className="text-[10px] text-[var(--text-tertiary)]">
            {track.completed_lessons} / {track.total_lessons} lessons complete
          </p>
        </div>
      ) : (
        <ProgressBar pct={0} barClass={styles.bar} />
      )}
    </div>
  );
}

export default function LearnPage() {
  const navigate = useNavigate();
  const { data: tracks, isLoading } = useQuery({
    queryKey: ["learning-tracks"],
    queryFn: getTracks,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto space-y-4">
        <div className="h-8 w-48 bg-[var(--bg-elevated-2)] rounded animate-pulse" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-36 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!tracks || tracks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-[var(--text-tertiary)]">
        <GraduationCap size={32} />
        <p>Curriculum loading… check back shortly.</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-20 md:pb-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <GraduationCap size={22} className="text-[var(--accent-positive)]" />
            IMCP Learning Center
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Investment Management Competency Program — {tracks.length} tracks, structured from first principles to CFA/ACG exam readiness.
          </p>
        </div>
      </div>

      {/* Track grid */}
      <div>
        <h2 className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">
          All Tracks
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {tracks.map((track) => (
            <TrackCard key={track.slug} track={track} />
          ))}
        </div>
      </div>

      {/* Certification tiers */}
      <div>
        <h2 className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">
          Certification Tiers
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {CERT_TIERS.map((tier) => {
            const styles = TIER_STYLES[tier.tier];
            return (
              <div
                key={tier.tier}
                className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className={cn(
                      "text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full border",
                      styles.badge
                    )}
                  >
                    {tier.subtitle}
                  </span>
                  <span className="text-sm font-semibold text-[var(--text-primary)]">
                    {tier.name}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-tertiary)] mb-2">
                  {tier.description}
                </p>
                <div className="flex flex-wrap gap-1">
                  {tier.tracks.map((t) => (
                    <span
                      key={t}
                      className="text-[9px] bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] px-1.5 py-0.5 rounded"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Exam prep note */}
      <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4 flex items-start gap-3">
        <GraduationCap size={18} className="text-amber-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">Track 10 — CFA / ACG / CQA Exam Prep</p>
          <p className="text-[11px] text-[var(--text-tertiary)] mt-0.5">
            40+ hours of targeted exam prep, available independently of certification tiers.
          </p>
        </div>
      </div>

      {/* Take Final Exam CTA */}
      <div className="bg-lime-500/5 border border-lime-500/20 rounded-2xl p-5 flex items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <Award size={20} className="text-lime-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              Ready to get certified?
            </p>
            <p className="text-[11px] text-[var(--text-tertiary)] mt-0.5">
              Complete all modules, then sit the Learning Center Exam — 150 questions, 4 hours, 90% to pass.
            </p>
          </div>
        </div>
        <Link
          to="/learn/exam"
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-lime-500 hover:bg-lime-400 text-black text-xs font-semibold transition-all shrink-0"
        >
          Take Final Exam
          <ChevronRight size={13} />
        </Link>
      </div>
    </div>
  );
}
