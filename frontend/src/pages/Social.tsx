import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Heart, MessageCircle, Trash2, Send, TrendingUp, BookMarked, Users } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { getFeed, createPost, deletePost, toggleLike, getComments, addComment } from "@/api/social";
import type { SocialPost, SocialComment } from "@/api/social";

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  const h = Math.floor(diff / 3_600_000);
  const d = Math.floor(diff / 86_400_000);
  if (d >= 1) return `${d}d ago`;
  if (h >= 1) return `${h}h ago`;
  if (m >= 1) return `${m}m ago`;
  return "just now";
}

function avatar(username: string) {
  return username?.[0]?.toUpperCase() ?? "?";
}

// ── Comment thread ────────────────────────────────────────────────────────────

function CommentThread({ postId }: { postId: number }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");

  const { data: comments = [], isLoading } = useQuery({
    queryKey: ["comments", postId],
    queryFn: () => getComments(postId),
    staleTime: 30_000,
  });

  const addMut = useMutation({
    mutationFn: (content: string) => addComment(postId, content),
    onSuccess: (c) => {
      setText("");
      qc.setQueryData<SocialComment[]>(["comments", postId], (old = []) => [...old, c]);
      qc.invalidateQueries({ queryKey: ["social-feed"] });
    },
  });

  return (
    <div className="mt-3 pl-4 border-l border-[var(--border-subtle)] space-y-2">
      {isLoading ? (
        <div className="text-[var(--text-tertiary)] text-xs animate-pulse">Loading…</div>
      ) : (
        comments.map((c) => (
          <div key={c.id} className="flex gap-2 items-start">
            <div className="w-5 h-5 rounded-full bg-gradient-to-br from-[#475569] to-[#334155] flex items-center justify-center text-[9px] text-[var(--text-primary)] shrink-0">
              {avatar(c.username)}
            </div>
            <div>
              <span className="text-[var(--text-secondary)] text-xs font-semibold">{c.username} </span>
              <span className="text-[var(--text-tertiary)] text-[10px]">{timeAgo(c.created_at)}</span>
              <p className="text-[var(--text-secondary)] text-xs mt-0.5">{c.content}</p>
            </div>
          </div>
        ))
      )}
      <div className="flex gap-2 pt-1">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) addMut.mutate(text.trim()); }}
          placeholder="Add a comment…"
          className="flex-1 bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs px-3 py-1.5 rounded-lg focus:outline-none focus:border-[#3B82F6]"
        />
        <button
          onClick={() => text.trim() && addMut.mutate(text.trim())}
          disabled={!text.trim()}
          className="text-[var(--accent-positive)] disabled:text-[var(--border-emphasis)] transition-colors"
        >
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}

// ── Post card ────────────────────────────────────────────────────────────────

function PostCard({ post, currentUserId }: { post: SocialPost; currentUserId: number }) {
  const qc = useQueryClient();
  const [showComments, setShowComments] = useState(false);

  const likeMut = useMutation({
    mutationFn: () => toggleLike(post.id),
    onSuccess: ({ liked, likes_count }) => {
      qc.setQueryData<SocialPost[]>(["social-feed"], (old = []) =>
        old.map((p) => p.id === post.id ? { ...p, liked_by_me: liked, likes_count } : p)
      );
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => deletePost(post.id),
    onSuccess: () => {
      toast.success("Post deleted");
      qc.setQueryData<SocialPost[]>(["social-feed"], (old = []) => old.filter((p) => p.id !== post.id));
    },
  });

  return (
    <div className={cn(
      "bg-[var(--bg-elevated)] border rounded-xl p-4 space-y-3",
      post.is_memo ? "border-[#F59E0B]/30" : "border-[var(--border-subtle)]"
    )}>
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#3B82F6] to-[#8B5CF6] flex items-center justify-center text-xs text-[var(--text-primary)] font-bold shrink-0">
          {avatar(post.username)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[var(--text-primary)] text-sm font-semibold">{post.username}</span>
            {post.symbol && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-elevated-2)] text-[var(--accent-positive)] font-mono font-semibold">
                ${post.symbol}
              </span>
            )}
            {post.is_memo && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-900/40 text-[#F59E0B]">
                Trade Memo
              </span>
            )}
            <span className="text-[var(--text-tertiary)] text-[10px] ml-auto">{timeAgo(post.created_at)}</span>
          </div>
        </div>
        {post.user_id === currentUserId && (
          <button
            onClick={() => deleteMut.mutate()}
            className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors shrink-0"
          >
            <Trash2 size={13} />
          </button>
        )}
      </div>

      {/* Content */}
      <p className="text-[var(--text-secondary)] text-sm leading-relaxed whitespace-pre-wrap">{post.content}</p>

      {/* Actions */}
      <div className="flex items-center gap-4 pt-1 border-t border-[var(--border-subtle)]">
        <button
          onClick={() => likeMut.mutate()}
          className={cn(
            "flex items-center gap-1.5 text-xs transition-colors",
            post.liked_by_me ? "text-[var(--accent-negative)]" : "text-[var(--text-tertiary)] hover:text-[var(--accent-negative)]"
          )}
        >
          <Heart size={13} fill={post.liked_by_me ? "currentColor" : "none"} />
          <span>{post.likes_count}</span>
        </button>
        <button
          onClick={() => setShowComments((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
        >
          <MessageCircle size={13} />
          <span>{post.comments_count}</span>
        </button>
      </div>

      {/* Comments */}
      {showComments && <CommentThread postId={post.id} />}
    </div>
  );
}

// ── Compose box ───────────────────────────────────────────────────────────────

function ComposeBox({ onPost }: { onPost: (body: { content: string; symbol?: string; is_memo?: boolean }) => void }) {
  const [content, setContent] = useState("");
  const [symbol, setSymbol] = useState("");
  const [isMemo, setIsMemo] = useState(false);

  const submit = () => {
    if (!content.trim()) return;
    onPost({ content: content.trim(), symbol: symbol.trim().toUpperCase() || undefined, is_memo: isMemo });
    setContent("");
    setSymbol("");
    setIsMemo(false);
  };

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && e.metaKey) submit(); }}
        placeholder="Share a trade idea or market thought… (⌘+Enter to post)"
        rows={3}
        className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2.5 rounded-xl focus:outline-none focus:border-[#3B82F6] resize-none placeholder-[#475569]"
      />
      <div className="flex items-center gap-3">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="$AAPL (optional)"
          className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs px-3 py-1.5 rounded-lg w-28 font-mono placeholder-[#475569] focus:outline-none focus:border-[#3B82F6]"
        />
        <button
          onClick={() => setIsMemo((v) => !v)}
          className={cn(
            "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors",
            isMemo
              ? "border-[#F59E0B]/50 bg-amber-900/20 text-[#F59E0B]"
              : "border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
          )}
        >
          <BookMarked size={12} />
          Trade Memo
        </button>
        <button
          onClick={submit}
          disabled={!content.trim()}
          className="ml-auto flex items-center gap-2 bg-[var(--accent-positive)] hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed text-[var(--text-primary)] text-sm font-semibold px-4 py-1.5 rounded-xl transition-colors"
        >
          <Send size={13} />
          Post
        </button>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

type FeedFilter = "all" | "memos" | "symbol";

export default function Social() {
  const { user } = useAuthStore();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [symbolFilter, setSymbolFilter] = useState("");

  const feedParams = {
    symbol: filter === "symbol" && symbolFilter ? symbolFilter : undefined,
    memos_only: filter === "memos",
  };

  const { data: posts = [], isLoading } = useQuery({
    queryKey: ["social-feed", feedParams],
    queryFn: () => getFeed(feedParams),
    staleTime: 30_000,
  });

  const postMut = useMutation({
    mutationFn: createPost,
    onSuccess: (post) => {
      toast.success("Posted!");
      qc.setQueryData<SocialPost[]>(["social-feed", feedParams], (old = []) => [post, ...old]);
    },
    onError: () => toast.error("Failed to post"),
  });

  return (
    <div className="space-y-4 pb-8 max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Community Feed</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Share trade ideas and market insights</p>
        </div>
        <div className="flex items-center gap-1.5 text-[var(--text-tertiary)]">
          <Users size={14} />
          <span className="text-xs">{posts.length} posts</span>
        </div>
      </div>

      {/* Compose */}
      <ComposeBox onPost={postMut.mutate} />

      {/* Filters */}
      <div className="flex items-center gap-2">
        {([
          { id: "all", label: "All" },
          { id: "memos", label: "📋 Memos" },
          { id: "symbol", label: "🔍 Symbol" },
        ] as const).map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setFilter(id)}
            className={cn(
              "text-xs px-3 py-1.5 rounded-full transition-colors",
              filter === id
                ? "bg-[var(--accent-positive)] text-[var(--text-primary)]"
                : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {label}
          </button>
        ))}
        {filter === "symbol" && (
          <input
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs px-3 py-1.5 rounded-lg w-20 font-mono placeholder-[#475569] focus:outline-none focus:border-[#3B82F6]"
          />
        )}
      </div>

      {/* Feed */}
      {isLoading ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-28 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl animate-pulse" />
          ))}
        </div>
      ) : posts.length === 0 ? (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-12 text-center">
          <TrendingUp size={32} className="text-[var(--border-emphasis)] mx-auto mb-3" />
          <p className="text-[var(--text-tertiary)] text-sm">No posts yet</p>
          <p className="text-[var(--border-emphasis)] text-xs mt-1">Be the first to share a trade idea</p>
        </div>
      ) : (
        <div className="space-y-3">
          {posts.map((p) => (
            <PostCard key={p.id} post={p} currentUserId={user?.id ?? -1} />
          ))}
        </div>
      )}
    </div>
  );
}
