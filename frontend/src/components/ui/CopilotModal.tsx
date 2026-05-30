import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation } from "react-router-dom";
import { Bot, X, Send, Loader2, ChevronDown, Zap, Database, TrendingUp, Shield, BarChart2, Coins } from "lucide-react";
import { cn } from "@/lib/utils";
import { parseCitations, parseSegments, type Citation, type Segment } from "@/lib/citationParser";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[];
}

interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  result?: unknown;
  done: boolean;
}

// ── Tool display metadata ─────────────────────────────────────────────────────

const TOOL_META: Record<string, { label: string; icon: React.FC<{ size?: number; className?: string }> }> = {
  get_quote:              { label: "Looking up quote",         icon: TrendingUp },
  run_screener:           { label: "Running screener",         icon: BarChart2 },
  get_news:               { label: "Fetching news",            icon: Database },
  get_strategy_summary:   { label: "Loading Strategy Lab",     icon: Zap },
  get_candidates:         { label: "Getting candidates",       icon: Zap },
  get_portfolio:          { label: "Loading portfolio",        icon: Database },
  get_crypto_market:      { label: "Fetching crypto market",   icon: Coins },
  check_token_security:   { label: "Scanning token security",  icon: Shield },
  get_defi_yields:        { label: "Fetching DeFi yields",     icon: Coins },
  get_governance_proposals:{ label: "Loading governance",      icon: Database },
  get_themes:             { label: "Loading themes",           icon: TrendingUp },
  get_earnings:           { label: "Fetching earnings",        icon: Database },
  get_insider_trades:     { label: "Fetching insider trades",  icon: Database },
  explain_term:           { label: "Explaining term",          icon: Bot },
};

// ── Page label detection ──────────────────────────────────────────────────────

function usePageLabel() {
  const { pathname } = useLocation();
  const MAP: Record<string, string> = {
    "/": "Dashboard", "/chart": "Chart", "/screener": "Screener",
    "/strategy": "Strategy Lab", "/options": "Options Lab", "/crypto": "Crypto Lab",
    "/defi": "DeFi Dashboard", "/security": "Security", "/discovery": "Discovery",
    "/paper": "Paper Trading", "/portfolio": "Portfolio", "/watchlist": "Watchlist",
    "/alerts": "Alerts", "/news": "News", "/earnings": "Earnings",
    "/research": "Research", "/journal": "Trade Journal", "/learn": "Learning Center",
  };
  return MAP[pathname] ?? pathname.replace("/", "").replace(/-/g, " ");
}

// ── SSE streaming helper ──────────────────────────────────────────────────────

function streamCopilot(
  messages: { role: string; content: string }[],
  page: string,
  onToolStart: (tool: string, input: Record<string, unknown>) => void,
  onToolResult: (tool: string, result: unknown) => void,
  onDelta: (delta: string) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): () => void {
  const token = localStorage.getItem("bmg_token") ?? "";
  let cancelled = false;

  fetch("/api/copilot/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body: JSON.stringify({ messages, page }),
  }).then(async (resp) => {
    if (!resp.ok) {
      onError(`HTTP ${resp.status}`);
      return;
    }
    const reader = resp.body?.getReader();
    if (!reader) { onError("No body"); return; }
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      if (cancelled) { reader.cancel(); return; }
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split("\n");
      buf = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const raw = trimmed.slice(5).trim();
        if (!raw) continue;
        try {
          const ev = JSON.parse(raw);
          if (ev.type === "tool_start") onToolStart(ev.tool, ev.input);
          else if (ev.type === "tool_result") onToolResult(ev.tool, ev.result);
          else if (ev.type === "text_delta") onDelta(ev.delta);
          else if (ev.type === "done") onDone();
          else if (ev.type === "error") onError(ev.message ?? "Error");
        } catch {
          // skip malformed
        }
      }
    }
    if (!cancelled) onDone();
  }).catch((e) => {
    if (!cancelled) onError(String(e));
  });

  return () => { cancelled = true; };
}

// ── Tool Call Card ────────────────────────────────────────────────────────────

function ToolCard({ call }: { call: ToolCall }) {
  const meta = TOOL_META[call.tool] ?? { label: call.tool, icon: Database };
  const Icon = meta.icon;
  const inputStr = Object.entries(call.input)
    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
    .join(", ");

  return (
    <div className="flex items-center gap-2 text-xs py-1 px-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] w-fit max-w-full">
      {call.done ? (
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-positive)] flex-shrink-0" />
      ) : (
        <Loader2 size={10} className="animate-spin text-blue-400 flex-shrink-0" />
      )}
      <Icon size={12} className="text-blue-400 flex-shrink-0" />
      <span className="text-[var(--text-secondary)] font-medium">{meta.label}</span>
      {inputStr && (
        <span className="text-[var(--text-tertiary)] truncate max-w-[200px]">{inputStr}</span>
      )}
    </div>
  );
}

// ── Message Bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg, isStreaming }: { msg: ChatMessage; isStreaming?: boolean }) {
  const isUser = msg.role === "user";

  return (
    <div className={cn("flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Bot size={14} className="text-white" />
        </div>
      )}
      <div className={cn("flex flex-col gap-1.5 max-w-[85%]", isUser ? "items-end" : "items-start")}>
        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <div className="flex flex-col gap-1">
            {msg.toolCalls.map((tc, i) => (
              <ToolCard key={i} call={tc} />
            ))}
          </div>
        )}
        {msg.content && (
          <div
            className={cn(
              "px-3 py-2.5 rounded-2xl text-sm leading-relaxed",
              isUser
                ? "bg-blue-600 text-white rounded-tr-sm"
                : "bg-[var(--bg-elevated)] text-[var(--text-primary)] rounded-tl-sm border border-[var(--border-subtle)]"
            )}
          >
            <MarkdownText text={msg.content} />
            {isStreaming && (
              <span className="inline-block w-0.5 h-3.5 bg-current animate-pulse ml-0.5 align-middle" />
            )}
          </div>
        )}
        {!msg.content && isStreaming && (
          <div className="px-3 py-2.5 rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-tl-sm">
            <Loader2 size={14} className="animate-spin text-[var(--text-tertiary)]" />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Citation chip ─────────────────────────────────────────────────────────────

function CitationChip({ num }: { num: number }) {
  return (
    <sup>
      <span className="inline-flex items-center justify-center w-4 h-4 rounded text-[9px] font-bold bg-teal-500/20 text-teal-400 border border-teal-500/30 cursor-default">
        {num}
      </span>
    </sup>
  );
}

// ── Sources section ───────────────────────────────────────────────────────────

function SourcesSection({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 pt-2 border-t border-[var(--border-subtle)]">
      <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wide mb-1.5">Sources</p>
      <div className="flex flex-wrap gap-1.5">
        {citations.map((c) => (
          <span
            key={c.num}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-teal-500/10 text-teal-400 border border-teal-500/20"
          >
            <span className="font-bold">[{c.num}]</span>
            <span className="text-[var(--text-tertiary)]">{c.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Simple markdown renderer ──────────────────────────────────────────────────

function MarkdownSegment({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\n)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <code key={i} className="font-mono text-xs bg-black/20 px-1 rounded">{part.slice(1, -1)}</code>;
        }
        if (part === "\n") {
          return <br key={i} />;
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

function MarkdownText({ text }: { text: string }) {
  const { body, citations } = parseCitations(text);
  const segments: Segment[] = parseSegments(body);
  return (
    <>
      <span>
        {segments.map((seg, i) => {
          if (seg.type === "cite") {
            return <CitationChip key={i} num={seg.num} />;
          }
          return <MarkdownSegment key={i} text={seg.content} />;
        })}
      </span>
      <SourcesSection citations={citations} />
    </>
  );
}

// ── Suggestion chips ──────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "What's AAPL trading at?",
  "Show me momentum breakout stocks",
  "How is my Strategy Lab performing?",
  "What are the top DeFi yields right now?",
  "Any active governance votes?",
  "Summarize latest market news",
];

// ── Main CopilotModal ─────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function CopilotModal({ open, onClose }: Props) {
  const page = usePageLabel();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const cancelRef = useRef<(() => void) | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const assistantIdRef = useRef<string>("");

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 60);
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback((text: string) => {
    const q = text.trim();
    if (!q || streaming) return;

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: q };
    const assistantId = crypto.randomUUID();
    assistantIdRef.current = assistantId;
    const assistantMsg: ChatMessage = { id: assistantId, role: "assistant", content: "", toolCalls: [] };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    const historyForApi = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const cancel = streamCopilot(
      historyForApi,
      page,
      (tool, inp) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, toolCalls: [...(m.toolCalls ?? []), { tool, input: inp, done: false }] }
              : m
          )
        );
      },
      (tool) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  toolCalls: (m.toolCalls ?? []).map((tc) =>
                    tc.tool === tool && !tc.done ? { ...tc, done: true } : tc
                  ),
                }
              : m
          )
        );
      },
      (delta) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + delta } : m
          )
        );
      },
      () => setStreaming(false),
      (err) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `Error: ${err}` }
              : m
          )
        );
        setStreaming(false);
      }
    );
    cancelRef.current = cancel;
  }, [messages, page, streaming]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    send(input);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { onClose(); return; }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-end md:items-center justify-center p-0 md:p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full md:max-w-2xl h-[90vh] md:h-[680px] flex flex-col rounded-t-2xl md:rounded-2xl bg-[var(--bg-base)] border border-[var(--border-subtle)] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-subtle)] flex-shrink-0">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Bot size={15} className="text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-[var(--text-primary)]">BMG Intelligence</p>
            <p className="text-xs text-[var(--text-tertiary)]">
              {streaming ? "Thinking…" : `On ${page}`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[var(--text-tertiary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={15} />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-6 pb-4">
              <div className="w-16 h-16 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-600/20 border border-blue-500/30 flex items-center justify-center">
                <Bot size={28} className="text-blue-400" />
              </div>
              <div className="text-center">
                <p className="text-[var(--text-primary)] font-semibold mb-1">Ask me anything</p>
                <p className="text-xs text-[var(--text-tertiary)]">Live market data · Strategy signals · DeFi yields · Token security</p>
              </div>
              <div className="flex flex-wrap gap-2 justify-center">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="text-xs px-3 py-1.5 rounded-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-blue-500/50 transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              isStreaming={streaming && i === messages.length - 1 && msg.role === "assistant"}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-4 py-3 border-t border-[var(--border-subtle)] flex-shrink-0">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about markets, your portfolio, crypto, DeFi…"
              disabled={streaming}
              className="flex-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-3.5 py-2.5 text-sm text-[var(--text-primary)] placeholder-[var(--text-tertiary)] outline-none focus:border-blue-500/50 disabled:opacity-60 transition-colors"
            />
            <button
              type="submit"
              disabled={!input.trim() || streaming}
              className="w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors flex-shrink-0"
            >
              {streaming ? (
                <Loader2 size={15} className="animate-spin text-white" />
              ) : (
                <Send size={15} className="text-white" />
              )}
            </button>
          </form>
          <p className="text-center text-[10px] text-[var(--text-tertiary)] mt-1.5">
            <kbd className="font-mono">⌘K</kbd> to close · Not investment advice
          </p>
        </div>
      </div>
    </div>
  );
}
