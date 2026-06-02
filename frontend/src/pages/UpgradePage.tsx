import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, Zap, Crown, Star, Shield, TrendingUp, BookOpen, BarChart2, Bot, ArrowRight } from "lucide-react";
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
        <div className="inline-flex items-center gap-2 bg-[var(--accent-positive)]/10 border border-[#3B82F6]/20 text-[var(--accent-positive)] text-xs px-3 py-1 rounded-full">
          <Crown size={12} />
          Upgrade your plan
        </div>
        <h1 className="text-3xl font-bold text-[var(--text-primary)]">Unlock your full potential</h1>
        <p className="text-[var(--text-tertiary)] text-sm max-w-md mx-auto">
          Professional-grade tools for every level of trader.
        </p>
      </div>

      {/* Monthly / Annual toggle */}
      <div className="flex items-center justify-center gap-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-1 w-fit mx-auto">
        <button
          onClick={() => setBilling("monthly")}
          className={cn(
            "px-5 py-2 rounded-lg text-sm font-semibold transition-colors",
            billing === "monthly" ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
          )}
        >
          Monthly
        </button>
        <button
          onClick={() => setBilling("annual")}
          className={cn(
            "px-5 py-2 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2",
            billing === "annual" ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
          )}
        >
          Annual
          <span className="text-[10px] font-bold text-[var(--accent-positive)] bg-[var(--accent-positive-bg)] px-1.5 py-0.5 rounded">
            SAVE 18%
          </span>
        </button>
      </div>

      {/* Plan cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Free */}
        <div className={cn(
          "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-6 flex flex-col",
          currentTier === "free" && "ring-1 ring-[#94A3B8]/30"
        )}>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[var(--bg-elevated-2)] flex items-center justify-center">
              <Star size={18} className="text-[var(--text-secondary)]" />
            </div>
            <div>
              <div className="text-[var(--text-primary)] font-bold">Free</div>
              <div className="text-[var(--text-secondary)] text-xs">Forever free</div>
            </div>
          </div>
          <div className="mb-4">
            <span className="text-3xl font-bold text-[var(--text-primary)]">$0</span>
            <span className="text-[var(--text-tertiary)] text-xs ml-1">/month</span>
          </div>
          <ul className="space-y-2 mb-6 flex-1">
            {[
              "Manual everything",
              "Basic strategy execution (paper only)",
              "Watchlist + alerts (manually configured)",
              "Basic tax document generation",
              "No automation",
            ].map((f) => (
              <li key={f} className="flex items-start gap-2 text-xs text-[var(--text-tertiary)]">
                <Check size={12} className="text-[var(--text-tertiary)] shrink-0 mt-0.5" />
                {f}
              </li>
            ))}
          </ul>
          <div className="py-2.5 text-center text-sm rounded-xl bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]">
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
          <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 bg-[var(--accent-positive)] text-[var(--text-primary)] text-[10px] font-bold px-3 py-0.5 rounded-full uppercase tracking-wider">
            Most Popular
          </div>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[var(--accent-positive)]/15 flex items-center justify-center">
              <Zap size={18} className="text-[var(--accent-positive)]" />
            </div>
            <div>
              <div className="text-[var(--text-primary)] font-bold">Plus</div>
              <div className="text-[var(--accent-positive)] text-xs">For active traders</div>
            </div>
          </div>
          <div className="mb-1">
            <span className="text-3xl font-bold text-[var(--text-primary)]">{price("plus")}</span>
            <span className="text-[var(--text-tertiary)] text-xs ml-1">/month</span>
          </div>
          {billing === "annual" && (
            <div className="text-[var(--accent-positive)] text-xs mb-2">billed $59/year — save $12.88</div>
          )}
          <ul className="space-y-2 mb-6 flex-1">
            {[
              "Full Labs autonomy (Trading & Strategies)",
              "Smart Transfers + Round-ups",
              "Auto-rebalance + auto-curated watchlist",
              "AI bill negotiation (1 bill/month)",
              "Morning Brief + Daily Digest",
            ].map((f) => (
              <li key={f} className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                <Check size={12} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />
                {f}
              </li>
            ))}
          </ul>

          {currentTier === "plus" ? (
            <div className="py-2.5 text-center text-sm text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] rounded-xl">
              Current plan
            </div>
          ) : (
            <div className="space-y-2">
              <button
                onClick={() => handleSubscribe("plus")}
                disabled={!!loadingPlan}
                className="w-full py-2.5 rounded-xl text-sm font-bold bg-[var(--accent-positive)] hover:brightness-110 text-[var(--text-primary)] transition-colors disabled:opacity-50"
              >
                {loadingPlan === "plus" ? "Loading…" : currentTier === "premium" ? "Downgrade to Plus" : "Subscribe"}
              </button>
              {currentTier === "free" && !alreadyTrialed && (
                <button
                  onClick={handleTrial}
                  disabled={!!loadingPlan}
                  className="w-full py-2 text-xs text-[var(--accent-positive)]/70 hover:text-[var(--accent-positive)] transition-colors"
                >
                  Try free for 7 days →
                </button>
              )}
            </div>
          )}
        </div>

        {/* Premium */}
        <div className={cn(
          "bg-gradient-to-b from-[#0d1f0a] to-[#0F172A] border rounded-2xl p-6 flex flex-col relative",
          currentTier === "premium"
            ? "border-[#84cc16]/60 ring-1 ring-[#84cc16]/30"
            : "border-[#84cc16]/40"
        )}>
          <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 bg-[#84cc16] text-black text-[10px] font-bold px-3 py-0.5 rounded-full uppercase tracking-wider">
            Recommended
          </div>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[#84cc16]/15 flex items-center justify-center">
              <Crown size={18} className="text-[#84cc16]" />
            </div>
            <div>
              <div className="text-[var(--text-primary)] font-bold">Premium</div>
              <div className="text-[#84cc16] text-xs">Full Autopilot</div>
            </div>
          </div>
          <div className="mb-1">
            <span className="text-3xl font-bold text-[var(--text-primary)]">{price("premium")}</span>
            <span className="text-[var(--text-tertiary)] text-xs ml-1">/month</span>
          </div>
          {billing === "annual" && (
            <div className="text-[#84cc16] text-xs mb-2">billed $199/year — save $40.88</div>
          )}
          <ul className="space-y-2 mb-6 flex-1">
            {[
              "Everything in Plus",
              "Full Autopilot — 9-category automation",
              "Tax-loss harvesting (cross-account)",
              "Direct indexing",
              "AI thesis updates + quarterly review",
              "Subscription analyzer (unlimited negotiation)",
              "Custom guardrail tuning",
              "Auto-tax planning (Roth conversion, estimated taxes)",
              "Priority support",
            ].map((f) => (
              <li key={f} className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                <Check size={12} className="text-[#84cc16] shrink-0 mt-0.5" />
                {f}
              </li>
            ))}
          </ul>

          {currentTier === "premium" ? (
            <div className="py-2.5 text-center text-sm text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] rounded-xl">
              Current plan
            </div>
          ) : (
            <button
              onClick={() => handleSubscribe("premium")}
              disabled={!!loadingPlan}
              className="w-full py-2.5 rounded-xl text-sm font-bold bg-[#84cc16] hover:brightness-110 text-black transition-colors disabled:opacity-50"
            >
              {loadingPlan === "premium" ? "Loading…" : "Upgrade to Premium"}
            </button>
          )}
        </div>
      </div>

      {/* What Full Autopilot means */}
      <div className="bg-[var(--bg-elevated)] border border-[#84cc16]/30 rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Bot size={18} className="text-[#84cc16]" />
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
            What "Full Autopilot" means
          </span>
        </div>
        <p className="text-[var(--text-secondary)] text-sm leading-relaxed max-w-2xl">
          While you sleep, BMG is running 247 strategies, harvesting tax losses, curating your watchlist,
          tracking your bills, and generating your morning brief. Today alone, it did{" "}
          <span className="text-[#84cc16] font-semibold">47 things</span> for you.
        </p>
        <Link
          to="/autopilot/activity"
          className="inline-flex items-center gap-2 text-sm text-[#84cc16] hover:underline font-semibold"
        >
          See your Autopilot activity
          <ArrowRight size={14} />
        </Link>
      </div>

      {/* Feature comparison table */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
            Feature comparison
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-subtle)]">
                <th className="text-left px-5 py-3 text-[var(--text-tertiary)] font-medium w-1/3">Feature</th>
                <th className="text-center px-3 py-3 text-[var(--text-secondary)] font-semibold">Free</th>
                <th className="text-center px-3 py-3 text-[var(--accent-positive)] font-semibold">Plus</th>
                <th className="text-center px-3 py-3 text-[#F59E0B] font-semibold">Premium</th>
              </tr>
            </thead>
            <tbody>
              {FEATURE_ROWS.map((row, i) => (
                <tr
                  key={row.label}
                  className={cn(
                    "border-b border-[var(--border-subtle)]/50",
                    i % 2 === 0 ? "" : "bg-[#020617]/40"
                  )}
                >
                  <td className="px-5 py-3 text-[var(--text-secondary)]">{row.label}</td>
                  <td className="text-center px-3 py-3 text-[var(--text-tertiary)]">{row.free}</td>
                  <td className="text-center px-3 py-3 text-[var(--text-secondary)]">
                    {row.plus === "✓"
                      ? <Check size={14} className="text-[var(--accent-positive)] mx-auto" />
                      : row.plus}
                  </td>
                  <td className="text-center px-3 py-3 text-[var(--text-secondary)]">
                    {row.premium === "✓"
                      ? <Check size={14} className="text-[var(--accent-positive)] mx-auto" />
                      : row.premium}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AUM complimentary note */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-5 py-4 flex items-start gap-3">
        <TrendingUp size={16} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />
        <div>
          <p className="text-[var(--text-secondary)] text-sm font-medium">
            Complimentary upgrades based on portfolio balance
          </p>
          <p className="text-[var(--text-tertiary)] text-xs mt-0.5">
            $10,000+ balance → Plus free.&nbsp; $50,000+ balance → Premium free. Checked daily.
          </p>
        </div>
      </div>

      <p className="text-center text-[var(--text-tertiary)] text-xs">
        All plans include paper trading. Upgrade or downgrade anytime. Cancel anytime.
      </p>
    </div>
  );
}
