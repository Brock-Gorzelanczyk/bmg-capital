import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LogOut, User, Crown, Zap, Star, ExternalLink, AlertCircle, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { getMyTier, createPortal } from "@/api/tiers";
import { useTierStore } from "@/store/tierStore";
import type { TierName } from "@/api/tiers";

const TIER_META: Record<TierName, { label: string; Icon: typeof Star; color: string; bg: string }> = {
  free:    { label: "Free",    Icon: Star,  color: "text-[var(--text-secondary)]", bg: "bg-[var(--bg-elevated-2)]" },
  plus:    { label: "Plus",    Icon: Zap,   color: "text-[var(--accent-positive)]", bg: "bg-[var(--accent-positive)]/10" },
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
      <h1 className="text-xl font-bold text-[var(--text-primary)] mb-2">Settings</h1>

      {/* Account info */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
          <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.1em]">Account</span>
        </div>
        <div className="divide-y divide-[#1E293B]">
          <div className="flex items-center justify-between px-4 py-3">
            <div className="flex items-center gap-2 text-[var(--text-secondary)]">
              <User size={14} />
              <span className="text-sm">Username</span>
            </div>
            <span className="text-sm text-[var(--text-primary)] font-medium">{user?.username ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between px-4 py-3">
            <span className="text-sm text-[var(--text-secondary)]">Email</span>
            <span className="text-sm text-[var(--text-primary)] font-medium">{user?.email ?? "—"}</span>
          </div>
        </div>
      </div>

      {/* Subscription */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
          <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.1em]">Subscription</span>
        </div>
        <div className="p-4 space-y-3">
          {/* Current tier badge */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", meta.bg)}>
                <TierIcon size={16} className={meta.color} />
              </div>
              <div>
                <div className="text-[var(--text-primary)] text-sm font-semibold">{meta.label}</div>
                <div className={cn("text-xs", status === "past_due" ? "text-[var(--accent-negative)]" : "text-[var(--text-tertiary)]")}>
                  {statusLabel}
                </div>
              </div>
            </div>
            {tier !== "premium" && (
              <button
                onClick={() => navigate("/upgrade")}
                className="text-xs font-semibold text-[var(--accent-positive)] hover:text-[#60A5FA] transition-colors"
              >
                Upgrade →
              </button>
            )}
          </div>

          {/* Past due warning */}
          {status === "past_due" && (
            <div className="flex items-start gap-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative)]/20 rounded-lg px-3 py-2.5">
              <AlertCircle size={14} className="text-[var(--accent-negative)] shrink-0 mt-0.5" />
              <p className="text-xs text-[var(--accent-negative)]">
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
            <div className="flex items-start gap-2 bg-[var(--accent-positive-bg)] border border-[var(--accent-positive)]/20 rounded-lg px-3 py-2.5">
              <TrendingUp size={14} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />
              <p className="text-xs text-[var(--accent-positive)]">
                {meta.label} included free based on your portfolio balance.
              </p>
            </div>
          )}

          {/* Manage billing */}
          {tierData?.has_stripe && (
            <button
              onClick={handleManageBilling}
              disabled={portalLoading}
              className="flex items-center gap-2 w-full bg-[var(--bg-elevated-2)] hover:bg-[#334155] border border-[var(--border-emphasis)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-sm font-medium rounded-lg px-4 py-2.5 transition-colors disabled:opacity-50"
            >
              <ExternalLink size={14} />
              {portalLoading ? "Opening portal…" : "Manage billing & invoices"}
            </button>
          )}
        </div>
      </div>

      {/* Sign out */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
          <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.1em]">Session</span>
        </div>
        <div className="p-4">
          <button
            onClick={handleSignOut}
            className="flex items-center gap-2.5 w-full bg-[var(--accent-negative-bg)] hover:bg-[#EF4444]/20 border border-[var(--accent-negative)]/20 hover:border-[#EF4444]/40 text-[var(--accent-negative)] text-sm font-semibold rounded-lg px-4 py-3 transition-colors cursor-pointer"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </div>

    </div>
  );
}
