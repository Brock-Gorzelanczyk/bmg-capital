import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { X, Zap, Crown, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTierStore } from "@/store/tierStore";
import { startTrial, createCheckout } from "@/api/tiers";
import type { TierName } from "@/api/tiers";

interface PaywallSheetProps {
  open: boolean;
  onClose: () => void;
  /** Which tier is required to unlock this feature */
  requiredTier?: TierName;
  /** Short description of what's being gated */
  featureLabel?: string;
  /** Longer description shown in the sheet */
  featureDescription?: string;
}

const TIER_META: Record<"plus" | "premium", { label: string; color: string; bg: string; border: string; Icon: typeof Zap; price: string }> = {
  plus: {
    label: "Plus",
    color: "text-[#3B82F6]",
    bg: "bg-[#3B82F6]",
    border: "border-[#3B82F6]/40",
    Icon: Zap,
    price: "$5.99/mo",
  },
  premium: {
    label: "Premium",
    color: "text-[#F59E0B]",
    bg: "bg-gradient-to-r from-[#F59E0B] to-[#D97706]",
    border: "border-[#F59E0B]/40",
    Icon: Crown,
    price: "$19.99/mo",
  },
};

export default function PaywallSheet({
  open,
  onClose,
  requiredTier = "plus",
  featureLabel = "this feature",
  featureDescription,
}: PaywallSheetProps) {
  const navigate = useNavigate();
  const { tier: currentTier, trialEndsAt } = useTierStore();
  const [loading, setLoading] = useState(false);
  const [interval, setInterval] = useState<"monthly" | "annual">("monthly");

  if (!open) return null;

  const meta = TIER_META[requiredTier === "premium" ? "premium" : "plus"];
  const alreadyTrialed = Boolean(trialEndsAt);

  const handleTrial = async () => {
    setLoading(true);
    try {
      await startTrial();
      onClose();
      window.location.reload();
    } catch (e: any) {
      setLoading(false);
    }
  };

  const handleCheckout = async () => {
    setLoading(true);
    try {
      const { url } = await createCheckout(requiredTier === "premium" ? "premium" : "plus", interval);
      window.location.href = url;
    } catch (e: any) {
      setLoading(false);
      navigate("/upgrade");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Sheet */}
      <div className="relative z-10 w-full sm:max-w-md mx-auto bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-t-2xl sm:rounded-2xl p-6 shadow-2xl">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
        >
          <X size={18} />
        </button>

        {/* Icon + badge */}
        <div className="flex flex-col items-center text-center mb-5">
          <div className={cn(
            "w-14 h-14 rounded-2xl flex items-center justify-center mb-3",
            requiredTier === "premium" ? "bg-[#F59E0B]/10" : "bg-[#3B82F6]/10"
          )}>
            <Lock size={26} className={meta.color} />
          </div>
          <div className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1 rounded-full mb-2", meta.color, "bg-current/10")}>
            <meta.Icon size={12} />
            {meta.label} Feature
          </div>
          <h2 className="text-[var(--text-primary)] font-bold text-lg leading-snug">
            Unlock {featureLabel}
          </h2>
          {featureDescription && (
            <p className="text-[var(--text-tertiary)] text-sm mt-1.5 max-w-xs">{featureDescription}</p>
          )}
        </div>

        {/* Billing interval toggle */}
        <div className="flex items-center justify-center gap-2 mb-5">
          <button
            onClick={() => setInterval("monthly")}
            className={cn(
              "px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors",
              interval === "monthly"
                ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            Monthly
          </button>
          <button
            onClick={() => setInterval("annual")}
            className={cn(
              "px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5",
              interval === "annual"
                ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            Annual
            <span className="text-[var(--accent-positive)] text-[10px] font-bold">SAVE 18%</span>
          </button>
        </div>

        {/* Price display */}
        <div className={cn("rounded-xl border p-4 mb-4 text-center", meta.border, "bg-[#020617]")}>
          <div className={cn("text-2xl font-bold", meta.color)}>
            {requiredTier === "premium"
              ? interval === "annual" ? "$16.58/mo" : "$19.99/mo"
              : interval === "annual" ? "$4.92/mo" : "$5.99/mo"}
          </div>
          {interval === "annual" && (
            <div className="text-[var(--text-tertiary)] text-xs mt-0.5">
              billed {requiredTier === "premium" ? "$199" : "$59"}/year
            </div>
          )}
        </div>

        {/* CTAs */}
        <div className="space-y-2">
          <button
            onClick={handleCheckout}
            disabled={loading}
            className={cn(
              "w-full py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-50",
              requiredTier === "premium"
                ? "bg-gradient-to-r from-[#F59E0B] to-[#D97706] hover:from-[#D97706] hover:to-[#B45309] text-[var(--text-primary)]"
                : "bg-[#3B82F6] hover:bg-[#2563EB] text-[var(--text-primary)]"
            )}
          >
            {loading ? "Loading…" : `Subscribe to ${meta.label}`}
          </button>

          {!alreadyTrialed && currentTier === "free" && (
            <button
              onClick={handleTrial}
              disabled={loading}
              className="w-full py-2.5 rounded-xl text-sm font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] transition-colors disabled:opacity-50"
            >
              Start free 7-day trial
            </button>
          )}

          <button
            onClick={() => { onClose(); navigate("/upgrade"); }}
            className="w-full py-2 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
          >
            View all plans
          </button>
        </div>
      </div>
    </div>
  );
}
