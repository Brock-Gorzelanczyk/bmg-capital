import { useQuery } from "@tanstack/react-query";
import { Check, X, Zap, Crown, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { getPlans, getMyTier } from "@/api/tiers";
import type { TierName } from "@/api/tiers";

const TIER_ICONS = { free: Star, pro: Zap, premium: Crown };
const TIER_COLORS: Record<TierName, string> = {
  free: "text-[#94A3B8]",
  pro: "text-[#3B82F6]",
  premium: "text-[#F59E0B]",
};
const TIER_BORDER: Record<TierName, string> = {
  free: "border-[#1E293B]",
  pro: "border-[#3B82F6]/50",
  premium: "border-[#F59E0B]/50",
};
const TIER_GRADIENT: Record<TierName, string> = {
  free: "from-[#1E293B] to-[#0F172A]",
  pro: "from-[#1e3a5f] to-[#0F172A]",
  premium: "from-[#3d2a00] to-[#0F172A]",
};

const FEATURE_LABELS: Record<string, string> = {
  paper_trading: "Paper Trading",
  basic_screener: "Stock Screener",
  learn: "Learning Center",
  strategy_backtest: "Strategy Backtesting",
  options_lab: "Options Lab",
  social: "Community Feed",
  ai_explain: "AI Explainer",
  advanced_charts: "Advanced Charts",
};

export default function UpgradePage() {
  const { data: tierData } = useQuery({ queryKey: ["tier-me"], queryFn: getMyTier, staleTime: 60_000 });
  const { data: plansData, isLoading } = useQuery({ queryKey: ["tier-plans"], queryFn: getPlans, staleTime: 60_000 });

  const currentTier = tierData?.tier ?? "free";
  const plans = plansData?.plans ?? [];

  return (
    <div className="space-y-8 pb-12 max-w-5xl mx-auto">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center gap-2 bg-gradient-to-r from-[#3B82F6]/10 to-[#8B5CF6]/10 border border-[#3B82F6]/20 text-[#3B82F6] text-xs px-3 py-1 rounded-full mb-2">
          <Crown size={12} />
          Upgrade your plan
        </div>
        <h1 className="text-3xl font-bold text-white">Unlock your full potential</h1>
        <p className="text-[#475569] text-base max-w-xl mx-auto">
          From paper trading to professional tools — get the features you need to trade with confidence.
        </p>
      </div>

      {/* Current tier banner */}
      <div className={cn(
        "flex items-center justify-between bg-[#0F172A] border rounded-xl px-5 py-3",
        TIER_BORDER[currentTier]
      )}>
        <div className="flex items-center gap-3">
          {(() => { const Icon = TIER_ICONS[currentTier]; return <Icon size={18} className={TIER_COLORS[currentTier]} />; })()}
          <div>
            <span className="text-white text-sm font-semibold capitalize">{currentTier} Plan</span>
            <span className="text-[#475569] text-xs ml-2">— your current plan</span>
          </div>
        </div>
        {currentTier !== "premium" && (
          <span className="text-[#3B82F6] text-xs">Upgrade below ↓</span>
        )}
      </div>

      {/* Plans grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-96 bg-[#0F172A] border border-[#1E293B] rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {plans.map((plan) => {
            const Icon = TIER_ICONS[plan.id];
            const isCurrent = plan.id === currentTier;
            const isPro = plan.id === "pro";

            return (
              <div
                key={plan.id}
                className={cn(
                  "relative bg-gradient-to-b border rounded-2xl p-6 flex flex-col",
                  TIER_GRADIENT[plan.id],
                  TIER_BORDER[plan.id],
                  isPro && "ring-1 ring-[#3B82F6]/30"
                )}
              >
                {isPro && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#3B82F6] text-white text-[10px] font-bold px-3 py-0.5 rounded-full uppercase tracking-wider">
                    Most Popular
                  </div>
                )}

                {/* Plan header */}
                <div className="flex items-center gap-2.5 mb-4">
                  <div className={cn(
                    "w-9 h-9 rounded-xl flex items-center justify-center",
                    plan.id === "free" ? "bg-[#1E293B]" : plan.id === "pro" ? "bg-[#1e3a5f]" : "bg-[#3d2a00]"
                  )}>
                    <Icon size={18} className={TIER_COLORS[plan.id]} />
                  </div>
                  <div>
                    <div className="text-white font-bold text-base">{plan.name}</div>
                    <div className={cn("text-xs font-semibold", TIER_COLORS[plan.id])}>
                      {plan.pricing.monthly === 0 ? "Free forever" : `$${plan.pricing.monthly}/mo`}
                    </div>
                  </div>
                </div>

                {/* Pricing */}
                {plan.pricing.monthly > 0 && (
                  <div className="mb-4 p-3 bg-black/20 rounded-xl">
                    <div className="flex items-baseline gap-1">
                      <span className="text-2xl font-bold text-white">${plan.pricing.monthly}</span>
                      <span className="text-[#475569] text-xs">/month</span>
                    </div>
                    <div className="text-[#475569] text-[11px] mt-0.5">
                      or ${plan.pricing.annual}/year <span className="text-[#22C55E]">(save {Math.round((1 - plan.pricing.annual / (plan.pricing.monthly * 12)) * 100)}%)</span>
                    </div>
                  </div>
                )}

                {/* Features */}
                <div className="flex-1 space-y-2 mb-6">
                  {Object.entries(FEATURE_LABELS).map(([key, label]) => {
                    const val = plan.features[key as keyof typeof plan.features];
                    const enabled = typeof val === "boolean" ? val : (val as number) > 0;
                    return (
                      <div key={key} className="flex items-center gap-2">
                        {enabled ? (
                          <Check size={13} className="text-[#22C55E] shrink-0" />
                        ) : (
                          <X size={13} className="text-[#334155] shrink-0" />
                        )}
                        <span className={cn("text-xs", enabled ? "text-[#94A3B8]" : "text-[#334155]")}>
                          {label}
                          {key === "watchlist_limit" && (
                            <span className="ml-1 text-[#475569]">
                              ({(plan.features.watchlist_limit as number) === -1 ? "unlimited" : `${plan.features.watchlist_limit} stocks`})
                            </span>
                          )}
                          {key === "alerts_limit" && (
                            <span className="ml-1 text-[#475569]">
                              ({(plan.features.alerts_limit as number) === -1 ? "unlimited" : `${plan.features.alerts_limit} alerts`})
                            </span>
                          )}
                        </span>
                      </div>
                    );
                  })}
                </div>

                {/* CTA */}
                {isCurrent ? (
                  <div className="text-center py-2.5 rounded-xl bg-[#1E293B] text-[#475569] text-sm font-medium">
                    Current Plan
                  </div>
                ) : (
                  <button
                    onClick={() => {
                      // Stripe/payment integration goes here
                      alert(`Upgrade to ${plan.name} coming soon! Stripe integration pending.`);
                    }}
                    className={cn(
                      "py-2.5 rounded-xl text-sm font-semibold transition-all",
                      plan.id === "pro"
                        ? "bg-[#3B82F6] hover:bg-[#2563EB] text-white"
                        : plan.id === "premium"
                        ? "bg-gradient-to-r from-[#F59E0B] to-[#D97706] hover:from-[#D97706] hover:to-[#B45309] text-white"
                        : "bg-[#1E293B] hover:bg-[#334155] text-[#94A3B8]"
                    )}
                  >
                    {plan.id === "free" ? "Downgrade to Free" : `Upgrade to ${plan.name}`}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Feature comparison note */}
      <div className="text-center text-[#475569] text-xs space-y-1">
        <p>All plans include paper trading so you can practice risk-free.</p>
        <p>Upgrade or downgrade anytime. Cancel anytime.</p>
      </div>
    </div>
  );
}
