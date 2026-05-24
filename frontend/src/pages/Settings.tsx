import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LogOut, User, Crown, Zap, Star, ExternalLink, AlertCircle, TrendingUp, MessageCircle, Send, X, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { getMyTier, createPortal } from "@/api/tiers";
import { useTierStore } from "@/store/tierStore";
import client from "@/api/client";
import type { TierName } from "@/api/tiers";

interface ChatMessage { role: "user" | "assistant"; content: string; }

function SupportChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "Hi! I'm your 24/7 support agent. I know everything about this app — ask me anything!" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open]);

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
    <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[#1E293B]/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Bot size={14} className="text-[#3B82F6]" />
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Support Agent</span>
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-[#22C55E]/15 text-[#22C55E] font-semibold">24/7</span>
        </div>
        <span className="text-[#475569] text-xs">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-[#1E293B]">
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
                    ? "bg-[#3B82F6] text-white rounded-tr-sm"
                    : "bg-[#1E293B] text-[#94A3B8] rounded-tl-sm"
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
                <div className="bg-[#1E293B] text-[#475569] text-xs rounded-2xl rounded-tl-sm px-3 py-2">
                  <span className="animate-pulse">Thinking…</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
          <div className="flex items-center gap-2 px-3 pb-3 pt-2 border-t border-[#1E293B]">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
              placeholder="Ask anything about the app…"
              disabled={loading}
              className="flex-1 bg-[#1E293B] border border-[#334155] text-white text-xs px-3 py-2 rounded-lg placeholder-[#475569] focus:outline-none focus:border-[#3B82F6] disabled:opacity-50"
            />
            <button
              onClick={send}
              disabled={!input.trim() || loading}
              className="w-8 h-8 flex items-center justify-center rounded-lg bg-[#3B82F6] hover:bg-[#2563EB] text-white disabled:opacity-40 transition-colors shrink-0"
            >
              <Send size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const TIER_META: Record<TierName, { label: string; Icon: typeof Star; color: string; bg: string }> = {
  free:    { label: "Free",    Icon: Star,  color: "text-[#94A3B8]", bg: "bg-[#1E293B]" },
  plus:    { label: "Plus",    Icon: Zap,   color: "text-[#3B82F6]", bg: "bg-[#3B82F6]/10" },
  premium: { label: "Premium", Icon: Crown, color: "text-[#F59E0B]", bg: "bg-[#F59E0B]/10" },
};

export default function Settings() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [portalLoading, setPortalLoading] = useState(false);

  const { data: tierData } = useQuery({
    queryKey: ["tier-me"],
    queryFn: getMyTier,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (tierData) useTierStore.getState().setTierData(tierData);
  }, [tierData]);

  const handleSignOut = () => {
    logout();
    navigate("/login");
  };

  const handleManageBilling = async () => {
    setPortalLoading(true);
    try {
      const { url } = await createPortal();
      window.location.href = url;
    } catch (e: any) {
      setPortalLoading(false);
      const msg = e?.response?.data?.detail ?? "Could not open billing portal";
      alert(msg);
    }
  };

  const tier = tierData?.tier ?? "free";
  const status = tierData?.status ?? "active";
  const meta = TIER_META[tier];
  const TierIcon = meta.Icon;

  const statusLabel = status === "trialing"
    ? `Trial ends ${tierData?.trial_ends_at ? new Date(tierData.trial_ends_at).toLocaleDateString() : ""}`
    : status === "past_due"
    ? "Payment past due"
    : status === "cancelled"
    ? "Cancels at period end"
    : tier === "free"
    ? "No active subscription"
    : `Renews ${tierData?.current_period_end ? new Date(tierData.current_period_end).toLocaleDateString() : ""}`;

  return (
    <div className="max-w-2xl mx-auto pb-20 md:pb-6 space-y-4">
      <h1 className="text-xl font-bold text-[#F8FAFC] mb-2">Settings</h1>

      {/* Account info */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B]">
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Account</span>
        </div>
        <div className="divide-y divide-[#1E293B]">
          <div className="flex items-center justify-between px-4 py-3">
            <div className="flex items-center gap-2 text-[#94A3B8]">
              <User size={14} />
              <span className="text-sm">Username</span>
            </div>
            <span className="text-sm text-[#F8FAFC] font-medium">{user?.username ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between px-4 py-3">
            <span className="text-sm text-[#94A3B8]">Email</span>
            <span className="text-sm text-[#F8FAFC] font-medium">{user?.email ?? "—"}</span>
          </div>
        </div>
      </div>

      {/* Subscription */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B]">
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Subscription</span>
        </div>
        <div className="p-4 space-y-3">
          {/* Current tier badge */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", meta.bg)}>
                <TierIcon size={16} className={meta.color} />
              </div>
              <div>
                <div className="text-white text-sm font-semibold">{meta.label}</div>
                <div className={cn("text-xs", status === "past_due" ? "text-[#EF4444]" : "text-[#475569]")}>
                  {statusLabel}
                </div>
              </div>
            </div>
            {tier !== "premium" && (
              <button
                onClick={() => navigate("/upgrade")}
                className="text-xs font-semibold text-[#3B82F6] hover:text-[#60A5FA] transition-colors"
              >
                Upgrade →
              </button>
            )}
          </div>

          {/* Past due warning */}
          {status === "past_due" && (
            <div className="flex items-start gap-2 bg-[#EF4444]/10 border border-[#EF4444]/20 rounded-lg px-3 py-2.5">
              <AlertCircle size={14} className="text-[#EF4444] shrink-0 mt-0.5" />
              <p className="text-xs text-[#EF4444]">
                Your payment failed. Update your payment method to keep access.
              </p>
            </div>
          )}

          {/* Cancel notice */}
          {tierData?.cancel_at_period_end && (
            <div className="flex items-start gap-2 bg-[#F59E0B]/10 border border-[#F59E0B]/20 rounded-lg px-3 py-2.5">
              <AlertCircle size={14} className="text-[#F59E0B] shrink-0 mt-0.5" />
              <p className="text-xs text-[#F59E0B]">
                Subscription cancels {tierData.current_period_end ? `on ${new Date(tierData.current_period_end).toLocaleDateString()}` : "at end of period"}.
              </p>
            </div>
          )}

          {/* AUM override notice */}
          {tierData?.aum_override && (
            <div className="flex items-start gap-2 bg-[#22C55E]/10 border border-[#22C55E]/20 rounded-lg px-3 py-2.5">
              <TrendingUp size={14} className="text-[#22C55E] shrink-0 mt-0.5" />
              <p className="text-xs text-[#22C55E]">
                {meta.label} included free based on your portfolio balance.
              </p>
            </div>
          )}

          {/* Manage billing */}
          {tierData?.has_stripe && (
            <button
              onClick={handleManageBilling}
              disabled={portalLoading}
              className="flex items-center gap-2 w-full bg-[#1E293B] hover:bg-[#334155] border border-[#334155] text-[#94A3B8] hover:text-white text-sm font-medium rounded-lg px-4 py-2.5 transition-colors disabled:opacity-50"
            >
              <ExternalLink size={14} />
              {portalLoading ? "Opening portal…" : "Manage billing & invoices"}
            </button>
          )}
        </div>
      </div>

      {/* Sign out */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B]">
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Session</span>
        </div>
        <div className="p-4">
          <button
            onClick={handleSignOut}
            className="flex items-center gap-2.5 w-full bg-[#EF4444]/10 hover:bg-[#EF4444]/20 border border-[#EF4444]/20 hover:border-[#EF4444]/40 text-[#EF4444] text-sm font-semibold rounded-lg px-4 py-3 transition-colors cursor-pointer"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </div>

      {/* Support Agent */}
      <SupportChat />
    </div>
  );
}
