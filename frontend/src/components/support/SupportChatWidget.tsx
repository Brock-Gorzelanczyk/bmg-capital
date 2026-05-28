import { useState, useEffect, useRef } from "react";
import { Bot, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

interface ChatMessage { role: "user" | "assistant"; content: string; }

export default function SupportChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "Hi! I'm your 24/7 support agent. I know everything about this app — ask me anything!" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const { data } = await client.post<{ reply: string }>("/support/chat", { messages: next });
      setMessages((m) => [...m, { role: "assistant", content: data.reply }]);
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: "Sorry, I ran into an issue. Try again in a moment." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-3 md:bottom-4 md:right-4 z-50 flex flex-col items-end gap-2">
      {/* Chat panel */}
      {open && (
        <div className="w-[calc(100vw-1.5rem)] md:w-80 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full bg-[#3B82F6]/20 flex items-center justify-center">
                <Bot size={13} className="text-[#3B82F6]" />
              </div>
              <span className="text-xs font-semibold text-[var(--text-primary)]">Support Agent</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-[#22C55E]/15 text-[var(--accent-positive)] font-semibold">24/7</span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
            >
              <X size={14} />
            </button>
          </div>

          {/* Messages */}
          <div className="h-72 overflow-y-auto px-4 py-3 space-y-3">
            {messages.map((m, i) => (
              <div key={i} className={cn("flex gap-2", m.role === "user" ? "justify-end" : "justify-start")}>
                {m.role === "assistant" && (
                  <div className="w-6 h-6 rounded-full bg-[#3B82F6]/20 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot size={12} className="text-[#3B82F6]" />
                  </div>
                )}
                <div className={cn(
                  "max-w-[80%] text-xs rounded-2xl px-3 py-2 leading-relaxed",
                  m.role === "user"
                    ? "bg-[#3B82F6] text-[var(--text-primary)] rounded-tr-sm"
                    : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] rounded-tl-sm"
                )}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex gap-2 justify-start">
                <div className="w-6 h-6 rounded-full bg-[#3B82F6]/20 flex items-center justify-center shrink-0">
                  <Bot size={12} className="text-[#3B82F6]" />
                </div>
                <div className="bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] text-xs rounded-2xl rounded-tl-sm px-3 py-2">
                  <span className="animate-pulse">Thinking…</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="flex items-center gap-2 px-3 pb-3 pt-2 border-t border-[var(--border-subtle)]">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
              placeholder="Ask anything about the app…"
              disabled={loading}
              className="flex-1 bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-xs px-3 py-2 rounded-lg placeholder-[#475569] focus:outline-none focus:border-[#3B82F6] disabled:opacity-50"
            />
            <button
              onClick={send}
              disabled={!input.trim() || loading}
              className="w-8 h-8 flex items-center justify-center rounded-lg bg-[#3B82F6] hover:bg-[#2563EB] text-[var(--text-primary)] disabled:opacity-40 transition-colors shrink-0"
            >
              <Send size={13} />
            </button>
          </div>
        </div>
      )}

      {/* Trigger pill */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2.5 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] hover:bg-[var(--bg-elevated-2)]/60 rounded-xl px-4 py-2.5 transition-colors shadow-xl shadow-black/40"
      >
        <Bot size={15} className="text-[#3B82F6]" />
        <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">Support Agent</span>
        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-[#22C55E]/15 text-[var(--accent-positive)] font-semibold border border-[var(--accent-positive)]/20">24/7</span>
      </button>
    </div>
  );
}
