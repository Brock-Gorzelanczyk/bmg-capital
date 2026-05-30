import { useRef, useState, useCallback, useEffect } from "react";
import { Bot, X, Send, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

// ── SSE streaming helper (mirrors CopilotModal exactly) ───────────────────────

function streamCopilot(
  messages: { role: string; content: string }[],
  page: string,
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
    if (!resp.ok) { onError(`HTTP ${resp.status}`); return; }
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
          if (ev.type === "text_delta") onDelta(ev.delta);
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

// ── Simple markdown renderer (mirrors CopilotModal) ───────────────────────────

function MarkdownText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\n)/g);
  return (
    <span>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <code key={i} className="font-mono text-xs bg-black/20 px-1 rounded">{part.slice(1, -1)}</code>;
        }
        if (part === "\n") return <br key={i} />;
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  suggestedQuestions?: string[];
  /** Passed to the backend as the page context string */
  context?: string;
}

// ── AskAIDrawer ───────────────────────────────────────────────────────────────

export default function AskAIDrawer({ open, onClose, title, suggestedQuestions = [], context }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const cancelRef = useRef<(() => void) | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const assistantIdRef = useRef<string>("");

  // Reset conversation when drawer opens fresh
  useEffect(() => {
    if (open) {
      setMessages([]);
      setInput("");
      setStreaming(false);
      setTimeout(() => inputRef.current?.focus(), 80);
    } else {
      cancelRef.current?.();
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
    const assistantMsg: ChatMessage = { id: assistantId, role: "assistant", content: "" };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    const historyForApi = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const cancel = streamCopilot(
      historyForApi,
      context ?? title,
      (delta) => {
        setMessages((prev) =>
          prev.map((m) => m.id === assistantId ? { ...m, content: m.content + delta } : m)
        );
      },
      () => setStreaming(false),
      (err) => {
        setMessages((prev) =>
          prev.map((m) => m.id === assistantId ? { ...m, content: `Error: ${err}` } : m)
        );
        setStreaming(false);
      },
    );
    cancelRef.current = cancel;
  }, [messages, streaming, context, title]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
    if (e.key === "Escape") onClose();
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          "fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm transition-opacity duration-200",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        className={cn(
          "fixed top-0 right-0 h-full w-80 z-[61] flex flex-col bg-[var(--bg-base)] border-l border-[var(--border-subtle)] shadow-2xl transition-transform duration-300 ease-in-out",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-subtle)] flex-shrink-0">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Bot size={15} className="text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-[var(--text-primary)] truncate">{title}</p>
            <p className="text-xs text-[var(--text-tertiary)]">
              {streaming ? "Thinking…" : "BMG Intelligence"}
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
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
          {messages.length === 0 && (
            <div className="flex flex-col gap-3 pt-2">
              <p className="text-xs text-[var(--text-tertiary)] text-center">Try a suggested question or type your own</p>
              {suggestedQuestions.map((q) => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="text-xs text-left px-3 py-2 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-blue-500/50 transition-all leading-snug"
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {messages.map((msg, i) => {
            const isUser = msg.role === "user";
            const isStreaming = streaming && i === messages.length - 1 && !isUser;
            return (
              <div key={msg.id} className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}>
                {!isUser && (
                  <div className="w-6 h-6 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Bot size={12} className="text-white" />
                  </div>
                )}
                <div className={cn("max-w-[85%]", isUser ? "items-end" : "items-start")}>
                  {msg.content ? (
                    <div
                      className={cn(
                        "px-3 py-2 rounded-2xl text-xs leading-relaxed",
                        isUser
                          ? "bg-blue-600 text-white rounded-tr-sm"
                          : "bg-[var(--bg-elevated)] text-[var(--text-primary)] rounded-tl-sm border border-[var(--border-subtle)]"
                      )}
                    >
                      <MarkdownText text={msg.content} />
                      {isStreaming && (
                        <span className="inline-block w-0.5 h-3 bg-current animate-pulse ml-0.5 align-middle" />
                      )}
                    </div>
                  ) : isStreaming ? (
                    <div className="px-3 py-2 rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-tl-sm">
                      <Loader2 size={12} className="animate-spin text-[var(--text-tertiary)]" />
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-3 py-3 border-t border-[var(--border-subtle)] flex-shrink-0">
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything…"
              disabled={streaming}
              rows={2}
              className="flex-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-3 py-2 text-xs text-[var(--text-primary)] placeholder-[var(--text-tertiary)] outline-none focus:border-blue-500/50 disabled:opacity-60 transition-colors resize-none"
            />
            <button
              onClick={() => send(input)}
              disabled={!input.trim() || streaming}
              className="w-9 h-9 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors flex-shrink-0"
            >
              {streaming ? (
                <Loader2 size={14} className="animate-spin text-white" />
              ) : (
                <Send size={14} className="text-white" />
              )}
            </button>
          </div>
          <p className="text-center text-[10px] text-[var(--text-tertiary)] mt-1.5">
            Enter to send · Shift+Enter for newline · Not investment advice
          </p>
        </div>
      </div>
    </>
  );
}
