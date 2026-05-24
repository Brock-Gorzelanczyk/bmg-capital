import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Zap, Crown, Star, Shield, TrendingUp, BookOpen, BarChart2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { getMyTier, createCheckout, startTrial } from "@/api/tiers";
import { useTierStore } from "@/store/tierStore";
import type { TierName } from "@/api/tiers";

const FEATURE_ROWS = [
  { label: "Chart history",        free: "1 year",    plus: "5 years",           premium: "20 years",         icon: BarChart2  },
  { label: "Indicators per chart", free: "5",         plus: "20",                premium: "50",               icon: TrendingUp },
  { label: "Watchlists",           free: "1",         plus: "10",                premium: "Unlimited",        icon: Shield     },
  { label: "Price alerts",         free: "10",        plus: "100",               premium: "Unlimited",        icon: Shield     },
  { label: "Strategy backtesting", free: "—",         plus: "5 years",           premium: "20 years",         icon: TrendingUp },
  { label: "Cash APY",             free: "1.5%",      plus: "3.5%",              premium: "4.5%",             icon: TrendingUp },
  { label: "IRA match",            free: "—",         plus: "1% (up to $70)",    premium: "3% (up to $210)",  icon: Shield     },
  { label: "Pro Mode charts",      free: "—",         plus: "✓",                 premium: "✓",                icon: BarChart2  },
  { label: "Extended hours",       free: "—",         plus: "✓",                 premium: "✓",                icon: Shield     },
  { label: "Options Lab",          free: "—",         plus: "Basic",             premium: "Full + Flow",      icon: TrendingUp },
  { label: "AI tutor",             free: "—",         plus: "✓",                 premium: "✓",                icon: BookOpen   },
  { label: "Level 2 quotes",       free: "—",         plus: "—",                 premium: "✓",                icon: BarChart2  },
  { label: "Options flow",         free: "—",         plus: "—",                 premium: "✓",                icon: TrendingUp },
  { label: "Support",              free: "Community", plus: "Email",             premium: "Live chat",        icon: Shield     },
];

const PRICING = {
  plus:    { monthly: 5.99,  annual: 59,  equiv: 4.92  },
  premium: { monthly: 19.99, annual: 199, equiv: 16.58 },
};

export default function UpgradePage() {
  const [billing, setBilling] = useState<"monthly" | "annual">("monthly");
  const [loadingPlan, setLoadingPlan] = useState<TierName | null>(null);

  const { data: tierData } = useQuery({
    queryKey: ["tier-me"],
    queryFn: getMyTier,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (tierData) useTierStore.getState().setTierData(tierData);
  }, [tierData]);

  const currentTier = tierData?.tier ?? "free";
  const alreadyTrialed = Boolean(tierData?.trial_ends_at);

  const price = (plan: "plus" | "premium") =>
    billing === "annual"
      ? `$${PRICING[plan].equiv.toFixed(2)}`
      : `$${PRICING[plan].monthly}`;

  const handleSubscribe = async (plan: "plus" | "premium") => {
    setLoadingPlan(plan);
    try {
      const { url } = await createCheckout(plan, billing);
      window.location.href = url;
    } catch {
      setLoadingPlan(null);
      alert("Stripe not configured yet — check back soon!");
    }
  };

  const handleTrial = async () => {
    setLoadingPlan("plus");
    try {
      await startTrial();
      window.location.reload();
    } catch (e: any) {
      setLoadingPlan(null);
      alert(e?.response?.data?.detail ?? "Could not start trial");
    }
  };

  return (
    <div className="pb-16 max-w-5xl mx-auto space-y-10">

      {/* Header */}
      <div className="text-center pt-2 space-y-2">
        <div className="inline-flex items-center gap-2 bg-[#3B82F6]/10 border border-[#3B82F6]/20 text-[#3B82F6] text-xs px-3 py-1 rounded-full">
          <Crown size={12} />
          Upgrade your plan
        </div>
        <h1 className="text-3xl font-bold text-white">Unlock your full potential</h1>
        <p className="text-[#475569] text-sm max-w-md mx-auto">
          Professional-grade tools for every level of trader.
        </p>
      </div>

      {/* Monthly / Annual toggle */}
      <div className="flex items-center justify-center gap-1 bg-[#0F172A] border border-[#1E293B] rounded-xl p-1 w-fit mx-auto">
        <button
          onClick={() => setBilling("monthly")}
          className={cn(
            "px-5 py-2 rounded-lg text-sm font-semibold transition-colors",
            billing === "monthly" ? "bg-[#1E293B] text-white" : "text-[#475569] hover:text-[#94A3B8]"
          )}
        >
          Monthly
        </button>
        <button
          onClick={() => setBilling("annual")}
          className={cn(
            "px-5 py-2 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2",
            billing === "annual" ? "bg-[#1E293B] text-white" : "text-[#475569] hover:text-[#94A3B8]"
          )}
        >
          Annual
          <span className="text-[10px] font-bold text-[#22C55E] bg-[#22C55E]/10 px-1.5 py-0.5 rounded">
            SAVE 18%
          </span>
        </button>
      </div>

      {/* Plan cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Free */}
        <div className={cn(
          "bg-[#0F172A] border border-[#1E293B] rounded-2xl p-6 flex flex-col",
          currentTier === "free" && "ring-1 ring-[#94A3B8]/30"
        )}>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[#1E293B] flex items-center justify-center">
              <Star size={18} className="text-[#94A3B8]" />
            </div>
            <div>
              <div className="text-white font-bold">Free</div>
              <div className="text-[#94A3B8] text-xs">Forever free</div>
            </div>
          </div>
          <div className="mb-6">
            <span className="text-3xl font-bold text-white">$0</span>
            <span className="text-[#475569] text-xs ml-1">/month</span>
          </div>
          <div className="mt-auto py-2.5 text-center text-sm rounded-xl bg-[#1E293B] text-[#475569]">
            {currentTier === "free" ? "Current plan" : "Downgrade"}
          </div>
        </div>

        {/* Plus */}
        <div className={cn(
          "bg-gradient-to-b from-[#0f1e3a] to-[#0F172A] border rounded-2xl p-6 flex flex-col relative",
          currentTier === "plus"
            ? "border-[#3B82F6]/60 ring-1 ring-[#3B82F6]/30"
            : "border-[#3B82F6]/30"
        )}>
          <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 bg-[#3B82F6] text-white text-[10px] font-bold px-3 py-0.5 rounded-full uppercase tracking-wider">
            Most Popular
          </div>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[#3B82F6]/15 flex items-center justify-center">
              <Zap size={18} className="text-[#3B82F6]" />
            </div>
            <div>
              <div className="text-white font-bold">Plus</div>
              <div className="text-[#3B82F6] text-xs">For active traders</div>
            </div>
          </div>
          <div className="mb-1">
            <span className="text-3xl font-bold text-white">{price("plus")}</span>
            <span className="text-[#475569] text-xs ml-1">/month</span>
          </div>
          {billing === "annual" && (
            <div className="text-[#22C55E] text-xs mb-2">billed $59/year — save $12.88</div>
          )}
          <div className="flex-1" />

          {currentTier === "plus" ? (
            <div className="py-2.5 text-center text-sm text-[#475569] bg-[#1E293B] rounded-xl">
              Current plan
            </div>
          ) : (
            <div className="space-y-2">
              <button
                onClick={() => handleSubscribe("plus")}
                disabled={!!loadingPlan}
                className="w-full py-2.5 rounded-xl text-sm font-bold bg-[#3B82F6] hover:bg-[#2563EB] text-white transition-colors disabled:opacity-50"
              >
                {loadingPlan === "plus" ? "Loading…" : currentTier === "premium" ? "Downgrade to Plus" : "Subscribe"}
              </button>
              {currentTier === "free" && !alreadyTrialed && (
                <button
                  onClick={handleTrial}
                  disabled={!!loadingPlan}
                  className="w-full py-2 text-xs text-[#3B82F6]/70 hover:text-[#3B82F6] transition-colors"
                >
                  Try free for 7 days →
                </button>
              )}
            </div>
          )}
        </div>

        {/* Premium */}
        <div className={cn(
          "bg-gradient-to-b from-[#2a1d00] to-[#0F172A] border rounded-2xl p-6 flex flex-col",
          currentTier === "premium"
            ? "border-[#F59E0B]/60 ring-1 ring-[#F59E0B]/30"
            : "border-[#F59E0B]/30"
        )}>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[#F59E0B]/15 flex items-center justify-center">
              <Crown size={18} className="text-[#F59E0B]" />
            </div>
            <div>
              <div className="text-white font-bold">Premium</div>
              <div className="text-[#F59E0B] text-xs">For professionals</div>
            </div>
          </div>
          <div className="mb-1">
            <span className="text-3xl font-bold text-white">{price("premium")}</span>
            <span className="text-[#475569] text-xs ml-1">/month</span>
          </div>
          {billing === "annual" && (
            <div className="text-[#22C55E] text-xs mb-2">billed $199/year — save $40.88</div>
          )}
          <div className="flex-1" />

          {currentTier === "premium" ? (
            <div className="py-2.5 text-center text-sm text-[#475569] bg-[#1E293B] rounded-xl">
              Current plan
            </div>
          ) : (
            <button
              onClick={() => handleSubscribe("premium")}
              disabled={!!loadingPlan}
              className="w-full py-2.5 rounded-xl text-sm font-bold bg-gradient-to-r from-[#F59E0B] to-[#D97706] hover:from-[#D97706] hover:to-[#B45309] text-white transition-colors disabled:opacity-50"
            >
              {loadingPlan === "premium" ? "Loading…" : "Upgrade to Premium"}
            </button>
          )}
        </div>
      </div>

      {/* Feature comparison table */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-[#1E293B]">
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">
            Feature comparison
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#1E293B]">
                <th className="text-left px-5 py-3 text-[#475569] font-medium w-1/3">Feature</th>
                <th className="text-center px-3 py-3 text-[#94A3B8] font-semibold">Free</th>
                <th className="text-center px-3 py-3 text-[#3B82F6] font-semibold">Plus</th>
                <th className="text-center px-3 py-3 text-[#F59E0B] font-semibold">Premium</th>
              </tr>
            </thead>
            <tbody>
              {FEATURE_ROWS.map((row, i) => (
                <tr
                  key={row.label}
                  className={cn(
                    "border-b border-[#1E293B]/50",
                    i % 2 === 0 ? "" : "bg-[#020617]/40"
                  )}
                >
                  <td className="px-5 py-3 text-[#94A3B8]">{row.label}</td>
                  <td className="text-center px-3 py-3 text-[#475569]">{row.free}</td>
                  <td className="text-center px-3 py-3 text-[#94A3B8]">
                    {row.plus === "✓"
                      ? <Check size={14} className="text-[#22C55E] mx-auto" />
                      : row.plus}
                  </td>
                  <td className="text-center px-3 py-3 text-[#94A3B8]">
                    {row.premium === "✓"
                      ? <Check size={14} className="text-[#22C55E] mx-auto" />
                      : row.premium}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AUM complimentary note */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl px-5 py-4 flex items-start gap-3">
        <TrendingUp size={16} className="text-[#22C55E] shrink-0 mt-0.5" />
        <div>
          <p className="text-[#94A3B8] text-sm font-medium">
            Complimentary upgrades based on portfolio balance
          </p>
          <p className="text-[#475569] text-xs mt-0.5">
            $10,000+ balance → Plus free.&nbsp; $50,000+ balance → Premium free. Checked daily.
          </p>
        </div>
      </div>

      <p className="text-center text-[#475569] text-xs">
        All plans include paper trading. Upgrade or downgrade anytime. Cancel anytime.
      </p>
    </div>
  );
}
