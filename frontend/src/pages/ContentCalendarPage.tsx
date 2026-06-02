import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AtSign,
  Link2,
  Video,
  FileText,
  Check,
  AlertTriangle,
  XCircle,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  getContentPosts,
  createContentPost,
  updateContentPost,
  deleteContentPost,
  checkCompliance,
  getDraftVault,
  type ContentPost,
} from "@/api/founder";

// ── Helpers ────────────────────────────────────────────────────────────────────

const PLATFORMS = [
  { value: "twitter", label: "Twitter", icon: AtSign },
  { value: "linkedin", label: "LinkedIn", icon: Link2 },
  { value: "tiktok", label: "TikTok", icon: Video },
  { value: "reels", label: "Reels", icon: Video },
  { value: "substack", label: "Substack", icon: FileText },
] as const;

const CONTENT_TYPES = [
  { value: "tweet", label: "Tweet" },
  { value: "thread", label: "Thread" },
  { value: "video", label: "Video" },
  { value: "newsletter", label: "Newsletter" },
] as const;

type Platform = (typeof PLATFORMS)[number]["value"];

function PlatformBadge({ platform }: { platform: string }) {
  const abbr: Record<string, string> = {
    twitter: "T",
    linkedin: "L",
    tiktok: "TT",
    reels: "R",
    substack: "S",
  };
  const color: Record<string, string> = {
    twitter: "bg-sky-500/20 text-sky-400 border-sky-500/30",
    linkedin: "bg-blue-600/20 text-blue-400 border-blue-600/30",
    tiktok: "bg-pink-500/20 text-pink-400 border-pink-500/30",
    reels: "bg-purple-500/20 text-purple-400 border-purple-500/30",
    substack: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  };
  return (
    <span
      className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${color[platform] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"}`}
    >
      {abbr[platform] ?? platform.slice(0, 2).toUpperCase()}
    </span>
  );
}

function getWeekDays(): Date[] {
  const today = new Date();
  const day = today.getDay(); // 0=Sun, 1=Mon…
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((day + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return d;
  });
}

function isSameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function toDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ── Compliance badge ──────────────────────────────────────────────────────────

function ComplianceIssues({
  issues,
}: {
  issues: ContentPost["compliance_issues"];
}) {
  if (!issues || issues.length === 0) return null;
  return (
    <div className="space-y-1.5 mt-2">
      {issues.map((issue, i) => (
        <div key={i} className="flex items-center gap-2">
          {issue.severity === "blocked" ? (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30 uppercase">
              BLOCKED
            </span>
          ) : (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 uppercase">
              FLAG
            </span>
          )}
          <span className="text-xs text-[var(--text-secondary)]">
            "{issue.phrase}"
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Editor panel ──────────────────────────────────────────────────────────────

const TWITTER_LIMIT = 280;

interface EditorProps {
  post: Partial<ContentPost>;
  onChange: (p: Partial<ContentPost>) => void;
  onSaveDraft: () => void;
  onMarkPosted: () => void;
  onSchedule: () => void;
  onCheckCompliance: () => void;
  onDelete?: () => void;
  isSaving: boolean;
  isChecking: boolean;
}

function Editor({
  post,
  onChange,
  onSaveDraft,
  onMarkPosted,
  onSchedule,
  onCheckCompliance,
  onDelete,
  isSaving,
  isChecking,
}: EditorProps) {
  const body = post.body_md ?? "";
  const platform = (post.platform ?? "twitter") as Platform;
  const isTwitter = platform === "twitter";
  const charPct = isTwitter ? Math.min(1, body.length / TWITTER_LIMIT) : 0;
  const charOver = isTwitter && body.length > TWITTER_LIMIT;

  const hasIssues = (post.compliance_issues ?? []).length > 0;
  const isClean = post.compliance_checked && !hasIssues;

  return (
    <div className="flex-1 min-w-0 space-y-4">
      {/* Title */}
      <input
        value={post.title ?? ""}
        onChange={(e) => onChange({ ...post, title: e.target.value })}
        placeholder="Post title…"
        className="w-full text-base font-semibold bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#84cc16]/50"
      />

      {/* Platform + Type row */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={platform}
          onChange={(e) => onChange({ ...post, platform: e.target.value })}
          className="text-sm bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16]/50"
        >
          {PLATFORMS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <select
          value={post.content_type ?? "tweet"}
          onChange={(e) => onChange({ ...post, content_type: e.target.value })}
          className="text-sm bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16]/50"
        >
          {CONTENT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {/* Body */}
      <div className="relative">
        <textarea
          value={body}
          onChange={(e) => onChange({ ...post, body_md: e.target.value })}
          placeholder="Write your post…"
          rows={10}
          className="w-full text-sm font-mono bg-[#0a0a0a] border border-[var(--border-subtle)] rounded-lg px-4 py-3 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#84cc16]/50 resize-y"
        />
        {isTwitter && (
          <div className="flex items-center gap-2 mt-1">
            <div className="flex-1 h-1 bg-[var(--border-subtle)] rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${charOver ? "bg-red-500" : "bg-[#84cc16]"}`}
                style={{ width: `${charPct * 100}%` }}
              />
            </div>
            <span
              className={`text-xs font-mono ${charOver ? "text-red-400" : "text-[var(--text-secondary)]"}`}
            >
              {body.length}/{TWITTER_LIMIT}
            </span>
          </div>
        )}
      </div>

      {/* Compliance */}
      <div className="space-y-2">
        <button
          onClick={onCheckCompliance}
          disabled={isChecking || !post.id}
          className="px-4 py-2 rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[#84cc16]/40 transition-colors disabled:opacity-40 flex items-center gap-2"
        >
          {isChecking ? (
            <span className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <Check className="w-3.5 h-3.5" />
          )}
          Check compliance
        </button>

        {isClean && (
          <div className="flex items-center gap-2 text-[#84cc16] text-sm">
            <Check className="w-4 h-4" />
            Compliant
          </div>
        )}

        {hasIssues && (
          <ComplianceIssues issues={post.compliance_issues ?? []} />
        )}
      </div>

      {/* Schedule */}
      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="datetime-local"
          value={post.scheduled_for?.slice(0, 16) ?? ""}
          onChange={(e) =>
            onChange({ ...post, scheduled_for: e.target.value || null })
          }
          className="text-sm bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16]/50"
        />
        <button
          onClick={onSchedule}
          disabled={isSaving || !post.scheduled_for}
          className="px-4 py-2 rounded-lg bg-[#84cc16] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors disabled:opacity-50"
        >
          Schedule post
        </button>
      </div>

      {/* Bottom action row */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={onSaveDraft}
          disabled={isSaving}
          className="px-4 py-2 rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[#84cc16]/40 transition-colors disabled:opacity-50"
        >
          {isSaving ? "Saving…" : "Save Draft"}
        </button>
        <button
          onClick={onMarkPosted}
          disabled={isSaving}
          className="px-4 py-2 rounded-lg border border-[#84cc16]/40 text-sm text-[#84cc16] hover:bg-[#84cc16]/10 transition-colors disabled:opacity-50"
        >
          Mark Posted
        </button>
        {onDelete && (
          <button
            onClick={onDelete}
            disabled={isSaving}
            className="ml-auto px-4 py-2 rounded-lg border border-red-500/30 text-sm text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50 flex items-center gap-1"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

// ── Weekly calendar strip ─────────────────────────────────────────────────────

interface CalendarStripProps {
  posts: ContentPost[];
  onSlotClick: (date: string) => void;
}

function CalendarStrip({ posts, onSlotClick }: CalendarStripProps) {
  const days = getWeekDays();
  const today = new Date();

  const postsByDay = useMemo(() => {
    const map: Record<string, ContentPost[]> = {};
    days.forEach((d) => {
      const key = toDateString(d);
      map[key] = posts.filter((p) => {
        if (!p.scheduled_for) return false;
        return isSameDay(new Date(p.scheduled_for), d);
      });
    });
    return map;
  }, [posts, days]);

  const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  return (
    <div className="grid grid-cols-7 gap-1">
      {days.map((day, i) => {
        const key = toDateString(day);
        const isToday = isSameDay(day, today);
        const dayPosts = postsByDay[key] ?? [];

        return (
          <div
            key={key}
            className={`rounded-xl border p-2 min-h-[80px] cursor-pointer transition-all ${
              isToday
                ? "border-[#84cc16]/50 bg-[#84cc16]/5"
                : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] hover:border-[#84cc16]/30"
            }`}
            onClick={() => onSlotClick(key)}
          >
            <div
              className={`text-[10px] font-bold mb-1.5 ${isToday ? "text-[#84cc16]" : "text-[var(--text-secondary)]"}`}
            >
              {DAY_LABELS[i]}
              <span className="ml-1 font-mono">{day.getDate()}</span>
            </div>
            <div className="space-y-1">
              {dayPosts.slice(0, 3).map((p) => (
                <div
                  key={p.id}
                  className="rounded px-1.5 py-0.5 text-[9px] font-medium truncate"
                  style={{ background: "rgba(132,204,22,0.15)", color: "#84cc16" }}
                >
                  {p.title || p.platform}
                </div>
              ))}
              {dayPosts.length > 3 && (
                <div className="text-[9px] text-[var(--text-secondary)]">
                  +{dayPosts.length - 3} more
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

const EMPTY_POST: Partial<ContentPost> = {
  platform: "twitter",
  content_type: "tweet",
  title: "",
  body_md: "",
  scheduled_for: null,
  status: "draft",
  compliance_issues: [],
  compliance_checked: false,
};

export default function ContentCalendarPage() {
  const qc = useQueryClient();
  const [selectedPost, setSelectedPost] = useState<Partial<ContentPost>>(EMPTY_POST);
  const isExisting = typeof selectedPost.id === "number";

  const { data: posts = [] } = useQuery<ContentPost[]>({
    queryKey: ["content-posts"],
    queryFn: () => getContentPosts(),
    staleTime: 60_000,
  });

  const { data: drafts = [] } = useQuery<ContentPost[]>({
    queryKey: ["content-drafts"],
    queryFn: getDraftVault,
    staleTime: 300_000,
  });

  const createMutation = useMutation({
    mutationFn: (data: Partial<ContentPost>) => createContentPost(data),
    onSuccess: (created) => {
      toast.success("Draft saved!");
      setSelectedPost(created);
      qc.invalidateQueries({ queryKey: ["content-posts"] });
      qc.invalidateQueries({ queryKey: ["content-drafts"] });
    },
    onError: () => toast.error("Failed to save"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ContentPost> }) =>
      updateContentPost(id, data),
    onSuccess: (updated) => {
      toast.success("Saved!");
      setSelectedPost(updated);
      qc.invalidateQueries({ queryKey: ["content-posts"] });
    },
    onError: () => toast.error("Failed to save"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteContentPost(id),
    onSuccess: () => {
      toast.success("Deleted");
      setSelectedPost(EMPTY_POST);
      qc.invalidateQueries({ queryKey: ["content-posts"] });
      qc.invalidateQueries({ queryKey: ["content-drafts"] });
    },
    onError: () => toast.error("Failed to delete"),
  });

  const complianceMutation = useMutation({
    mutationFn: (id: number) => checkCompliance(id),
    onSuccess: (result) => {
      setSelectedPost((prev) => ({
        ...prev,
        compliance_issues: result.issues,
        compliance_checked: true,
      }));
      if (result.issues.length === 0) {
        toast.success("All clear — no compliance issues!");
      } else {
        toast.warning(`${result.issues.length} issue(s) found`);
      }
      qc.invalidateQueries({ queryKey: ["content-posts"] });
    },
    onError: () => toast.error("Compliance check failed"),
  });

  const isSaving = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;
  const isChecking = complianceMutation.isPending;

  function handleSaveDraft() {
    const data = { ...selectedPost, status: "draft" };
    if (isExisting) {
      updateMutation.mutate({ id: selectedPost.id!, data });
    } else {
      createMutation.mutate(data);
    }
  }

  function handleMarkPosted() {
    const data = { ...selectedPost, status: "posted", posted_at: new Date().toISOString() };
    if (isExisting) {
      updateMutation.mutate({ id: selectedPost.id!, data });
    } else {
      createMutation.mutate(data);
    }
  }

  function handleSchedule() {
    const data = { ...selectedPost, status: "scheduled" };
    if (isExisting) {
      updateMutation.mutate({ id: selectedPost.id!, data });
    } else {
      createMutation.mutate(data);
    }
  }

  function handleCheckCompliance() {
    if (selectedPost.id) {
      complianceMutation.mutate(selectedPost.id);
    }
  }

  function handleDelete() {
    if (selectedPost.id) {
      deleteMutation.mutate(selectedPost.id);
    }
  }

  function handleSlotClick(date: string) {
    setSelectedPost({ ...EMPTY_POST, scheduled_for: `${date}T09:00` });
  }

  // Sidebar items: vault + existing posts
  const sidebarItems = [...drafts, ...posts.filter(
    (p) => !drafts.some((d) => d.id === p.id)
  )];

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-6xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-black text-[var(--text-primary)]">
            Content Calendar
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Draft, schedule, and compliance-check your posts
          </p>
        </div>

        {/* Weekly calendar strip */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 space-y-3">
          <h2 className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-widest">
            This Week
          </h2>
          <CalendarStrip posts={posts} onSlotClick={handleSlotClick} />
        </div>

        {/* Editor + Sidebar */}
        <div className="flex gap-4 min-h-[600px]">
          {/* Draft Vault sidebar */}
          <div className="w-[280px] shrink-0 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
              <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-widest">
                Draft Vault
              </span>
              <button
                onClick={() => setSelectedPost(EMPTY_POST)}
                className="p-1 rounded hover:bg-[#84cc16]/10 text-[var(--text-secondary)] hover:text-[#84cc16] transition-colors"
                title="New post"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-[var(--border-subtle)]">
              {sidebarItems.length === 0 ? (
                <p className="text-xs text-[var(--text-secondary)] p-4 italic">
                  No drafts yet.
                </p>
              ) : (
                sidebarItems.map((post) => {
                  const isActive = selectedPost.id === post.id;
                  const hasBlocker = post.compliance_issues?.some(
                    (i) => i.severity === "blocked"
                  );
                  return (
                    <button
                      key={post.id}
                      onClick={() => setSelectedPost(post)}
                      className={`w-full text-left px-4 py-3 transition-colors ${
                        isActive
                          ? "bg-[#84cc16]/10 border-l-2 border-l-[#84cc16]"
                          : "hover:bg-[var(--bg-base)]"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <PlatformBadge platform={post.platform} />
                        {hasBlocker && (
                          <XCircle className="w-3 h-3 text-red-400" />
                        )}
                        {post.compliance_issues &&
                          post.compliance_issues.length > 0 &&
                          !hasBlocker && (
                            <AlertTriangle className="w-3 h-3 text-amber-400" />
                          )}
                      </div>
                      <div className="text-xs font-medium text-[var(--text-primary)] truncate">
                        {post.title || "(untitled)"}
                      </div>
                      <div className="text-[10px] text-[var(--text-secondary)] mt-0.5 capitalize">
                        {post.status}
                        {post.scheduled_for &&
                          ` · ${new Date(post.scheduled_for).toLocaleDateString()}`}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Editor */}
          <div className="flex-1 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 flex flex-col">
            <Editor
              post={selectedPost}
              onChange={setSelectedPost}
              onSaveDraft={handleSaveDraft}
              onMarkPosted={handleMarkPosted}
              onSchedule={handleSchedule}
              onCheckCompliance={handleCheckCompliance}
              onDelete={isExisting ? handleDelete : undefined}
              isSaving={isSaving}
              isChecking={isChecking}
            />
          </div>
        </div>

      </div>
    </div>
  );
}
