import { useState, useEffect, useRef, useCallback } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Mic, MicOff, X, Send, Loader2 } from "lucide-react";
import { voiceChat, getVoiceUsage, type VoiceChatResponse } from "@/api/voice";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function VoiceAIModal({ open, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [context, setContext] = useState<"portfolio" | "market" | "general">("portfolio");
  const [listening, setListening] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasAutoOpened = useRef(false);

  const { data: usage } = useQuery({
    queryKey: ["voice-usage"],
    queryFn: getVoiceUsage,
    enabled: open,
    staleTime: 10_000,
  });

  const mutation = useMutation({
    mutationFn: (msg: string) => voiceChat(msg, sessionId, context),
    onSuccess: (data: VoiceChatResponse) => {
      setSessionId(data.session_id);
      setMessages(prev => [
        ...prev,
        { role: "assistant", content: data.response, timestamp: new Date().toISOString() },
      ]);
      if (typeof window !== "undefined" && window.speechSynthesis) {
        const utterance = new SpeechSynthesisUtterance(data.response);
        utterance.rate = 1.1;
        window.speechSynthesis.speak(utterance);
      }
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const isLimit =
        typeof detail === "object" && detail !== null && "upgrade" in detail;
      setMessages(prev => [
        ...prev,
        {
          role: "assistant",
          content: isLimit
            ? "You've reached your daily 10-minute voice limit. Upgrade to Plus for unlimited voice AI."
            : "Sorry, I ran into an issue. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    },
  });

  const sendMessage = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      setMessages(prev => [
        ...prev,
        { role: "user", content: text, timestamp: new Date().toISOString() },
      ]);
      setInput("");
      mutation.mutate(text);
    },
    [mutation],
  );

  // Elapsed timer
  useEffect(() => {
    if (open) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [open]);

  // Reset hasAutoOpened when modal closes
  useEffect(() => {
    if (!open) {
      hasAutoOpened.current = false;
    }
  }, [open]);

  // Focus input on open
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 100);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Escape to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const startListening = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const SRClass = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!SRClass) {
      alert("Voice input not supported in this browser");
      return;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SRClass();
    rec.continuous = false;
    rec.interimResults = false;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (event: any) => {
      const text = event.results[0][0].transcript as string;
      setListening(false);
      sendMessage(text);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recognitionRef.current = rec;
    rec.start();
    setListening(true);
  };

  const fmtTime = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const limitSec = usage?.limit_seconds ?? 600;
  const usedSec = usage?.used_seconds ?? 0;
  const remaining = usage?.unlimited ? null : Math.max(0, limitSec - usedSec);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="w-full max-w-2xl h-[600px] rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] flex flex-col overflow-hidden shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--border-subtle)] shrink-0">
          <div className="flex items-center gap-3">
            <div
              className={`w-3 h-3 rounded-full ${
                listening
                  ? "bg-[#4ade80] animate-pulse"
                  : mutation.isPending
                  ? "bg-amber-400 animate-pulse"
                  : "bg-[#4ade80]"
              }`}
            />
            <span className="font-bold text-sm text-[var(--text-primary)]">BMG Voice AI</span>
            <div className="flex gap-1">
              {(["portfolio", "market", "general"] as const).map(c => (
                <button
                  key={c}
                  onClick={() => setContext(c)}
                  className={`px-2 py-0.5 rounded text-xs font-medium capitalize transition-colors ${
                    context === c
                      ? "bg-[#4ade80] text-black"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-[var(--text-secondary)]">{fmtTime(elapsed)}</span>
            {remaining !== null && (
              <span className={`text-xs font-mono ${remaining < 60 ? "text-amber-400" : "text-[#4ade80]"}`}>
                {fmtTime(remaining)} left
              </span>
            )}
            {usage?.unlimited && <span className="text-xs text-[#4ade80]">∞ unlimited</span>}
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-[var(--bg-base)] text-[var(--text-secondary)]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Waveform when listening */}
        {listening && (
          <div className="flex items-center justify-center gap-1 py-2 bg-[#4ade80]/5 shrink-0">
            {[1, 2, 3, 4, 5].map(i => (
              <div
                key={i}
                className="w-1 bg-[#4ade80] rounded-full"
                style={{
                  height: `${8 + Math.sin(Date.now() / 200 + i) * 8}px`,
                  animation: `pulse ${0.5 + i * 0.1}s ease-in-out infinite alternate`,
                }}
              />
            ))}
            <span className="ml-2 text-xs text-[#4ade80]">Listening…</span>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                  m.role === "user"
                    ? "bg-[var(--bg-base)] text-[var(--text-primary)] rounded-br-sm"
                    : "border-l-4 border-[#4ade80] bg-[#4ade80]/5 text-[var(--text-primary)] rounded-bl-sm"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {mutation.isPending && (
            <div className="flex justify-start">
              <div className="border-l-4 border-[#4ade80] bg-[#4ade80]/5 rounded-2xl rounded-bl-sm px-4 py-2.5">
                <Loader2 className="w-4 h-4 text-[#4ade80] animate-spin" />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-[var(--border-subtle)] shrink-0">
          <div className="flex items-center gap-2">
            <button
              onClick={
                listening
                  ? () => {
                      recognitionRef.current?.stop();
                      setListening(false);
                    }
                  : startListening
              }
              className={`p-2.5 rounded-lg transition-colors ${
                listening
                  ? "bg-red-500/20 text-red-400"
                  : "bg-[var(--bg-base)] text-[var(--text-secondary)] hover:text-[#4ade80]"
              }`}
            >
              {listening ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
            </button>
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage(input);
                }
              }}
              placeholder="Ask anything about your portfolio…"
              className="flex-1 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#4ade80]/50"
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || mutation.isPending}
              className="p-2.5 rounded-lg bg-[#4ade80] text-black hover:bg-[#a3e635] transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
