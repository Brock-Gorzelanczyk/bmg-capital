import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Heart, MessageCircle, Trash2, Send, TrendingUp, BookMarked, Users } from "lucide-react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { getFeed, createPost, deletePost, toggleLike, getComments, addComment } from "@/api/social";
import type { SocialPost, SocialComment } from "@/api/social";
import { COMPANY_INFO } from "@/data/companyInfo";

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

const TICKER_REGEX = /\$([A-Z]{1,5})/g;
const MAX_CONTENT = 500;

// ── Render post content with $SYMBOL chips ────────────────────────────────────

function PostContent({ content }: { content: string }) {
  const navigate = useNavigate();
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  const regex = new RegExp(TICKER_REGEX.source, "g");

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={lastIndex}>{content.slice(lastIndex, match.index)}</span>);
    }
    const symbol = match[1];
    parts.push(
      <button
        key={match.index}
        onClick={() => navigate(`/research?symbol=${symbol}`)}
        className="inline-flex items-center px-1.5 py-0.5 rounded-md bg-teal-500/15 text-teal-400 border border-teal-500/30 font-mono text-xs font-semibold hover:bg-teal-500/25 hover:border-teal-500/50 transition-colors mx-0.5"
      >
        ${symbol}
      </button>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) {
    parts.push(<span key={lastIndex}>{content.slice(lastIndex)}</span>);
  }
  return <p className="text-[var(--text-secondary)] text-sm leading-relaxed whitespace-pre-wrap">{parts}</p>;
}

// ── Trending tickers from feed ────────────────────────────────────────────────

function TrendingTickers({ posts }: { posts: SocialPost[] }) {
  const navigate = useNavigate();
  const counts = new Map<string, number>();

  for (const post of posts) {
    const regex = new RegExp(TICKER_REGEX.source, "g");
    let m: RegExpExecArray | null;
    while ((m = regex.exec(post.content)) !== null) {
      const sym = m[1];
      counts.set(sym, (counts.get(sym) ?? 0) + 1);
    }
    if (post.symbol) {
      counts.set(post.symbol, (counts.get(post.symbol) ?? 0) + 1);
    }
  }

  const top = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  if (top.length === 0) return null;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
      <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide mb-3">
        Trending in Community
      </p>
      <div className="flex flex-wrap gap-2">
        {top.map(([sym, count]) => (
          <button
            key={sym}
            onClick={() => navigate(`/research?symbol=${sym}`)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-400 hover:bg-teal-500/20 hover:border-teal-500/40 transition-colors"
          >
            <span className="font-mono text-xs font-semibold">${sym}</span>
            <span className="text-[10px] text-teal-500/70">{count}</span>
          </button>
        ))}
      </div>
    </div>
  );
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
      <PostContent content={post.content} />

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

const ALL_SYMBOLS = Object.keys(COMPANY_INFO);

function ComposeBox({ onPost }: { onPost: (body: { content: string; symbol?: string; is_memo?: boolean }) => void }) {
  const [content, setContent] = useState("");
  const [symbol, setSymbol] = useState("");
  const [isMemo, setIsMemo] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [tickerQuery, setTickerQuery] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const atRef = useRef<number>(-1);

  const submit = () => {
    if (!content.trim() || content.length > MAX_CONTENT) return;
    onPost({ content: content.trim(), symbol: symbol.trim().toUpperCase() || undefined, is_memo: isMemo });
    setContent("");
    setSymbol("");
    setIsMemo(false);
    setSuggestions([]);
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    if (val.length > MAX_CONTENT) return;
    setContent(val);

    // Detect $TICKER autocomplete trigger
    const cursor = e.target.selectionStart ?? val.length;
    const textBeforeCursor = val.slice(0, cursor);
    const dollarMatch = textBeforeCursor.match(/\$([A-Za-z]*)$/);
    if (dollarMatch) {
      const query = dollarMatch[1].toUpperCase();
      atRef.current = cursor - dollarMatch[0].length;
      setTickerQuery(query);
      const matched = ALL_SYMBOLS.filter((s) => s.startsWith(query)).slice(0, 5);
      setSuggestions(matched);
    } else {
      setSuggestions([]);
      atRef.current = -1;
    }
  };

  const insertSuggestion = (sym: string) => {
    if (atRef.current === -1) return;
    const before = content.slice(0, atRef.current);
    const after = content.slice(atRef.current + 1 + tickerQuery.length);
    const newVal = before + `$${sym}` + after;
    if (newVal.length <= MAX_CONTENT) setContent(newVal);
    setSuggestions([]);
    atRef.current = -1;
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const remaining = MAX_CONTENT - content.length;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={handleContentChange}
          onKeyDown={(e) => {
            if (e.key === "Escape") setSuggestions([]);
            if (e.key === "Enter" && e.metaKey) submit();
          }}
          placeholder="Share a trade idea or market thought… (⌘+Enter to post)"
          rows={3}
          className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2.5 rounded-xl focus:outline-none focus:border-[#3B82F6] resize-none placeholder-[#475569]"
        />
        {/* Character counter */}
        <span className={cn(
          "absolute bottom-3 right-3 text-[10px] font-mono pointer-events-none",
          remaining <= 50 ? (remaining <= 20 ? "text-[var(--accent-negative)]" : "text-[#F59E0B]") : "text-[var(--text-tertiary)]"
        )}>
          {remaining}
        </span>
        {/* Autocomplete dropdown */}
        {suggestions.length > 0 && (
          <div className="absolute left-2 top-full mt-1 z-20 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl shadow-xl overflow-hidden min-w-[180px]">
            {suggestions.map((sym) => (
              <button
                key={sym}
                onMouseDown={(e) => { e.preventDefault(); insertSuggestion(sym); }}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-[var(--bg-elevated-2)] transition-colors"
              >
                <span className="font-mono text-xs font-semibold text-teal-400">${sym}</span>
                <span className="text-[11px] text-[var(--text-tertiary)] truncate">{COMPANY_INFO[sym]?.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>
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
          disabled={!content.trim() || content.length > MAX_CONTENT}
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

      {/* Trending tickers */}
      {posts.length > 0 && <TrendingTickers posts={posts} />}

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
