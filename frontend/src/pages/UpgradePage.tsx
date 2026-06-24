import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, Gift } from "lucide-react";
import { simulateDepositMatch } from "@/api/depositMatch";

const TIERS = [
  {
    id: "free",
    name: "Free",
    monthly: 0,
    annual: 0,
    color: "border-[var(--border-subtle)]",
    badge: null,
    features: [
      "Stocks, ETFs, crypto",
      "Paper trading",
      "10 min Voice AI / day",
      "1 external brokerage link",
      "Basic education",
      "Daily AI brief",
    ],
  },
  {
    id: "plus",
    name: "Plus",
    monthly: 7.99,
    annual: 6.67,
    annualTotal: 79.99,
    color: "border-[#4ade80]",
    badge: "Most Popular",
    features: [
      "4.0% APY on cash (vs RH Gold 3.35%)",
      "1% IRA contribution match",
      "1% match on recurring deposits",
      "Unlimited Voice AI",
      "Unlimited external brokerages",
      "Pro Mode + Options Flow",
      "Tax-loss harvesting",
      "1 free CFP session / year",
    ],
    highlight: "4.0% APY on cash",
  },
  {
    id: "premium",
    name: "Premium",
    monthly: 19.99,
    annual: 16.67,
    annualTotal: 199.99,
    color: "border-purple-500",
    badge: "Full Power",
    features: [
      "5.0% APY on cash",
      "3% IRA match (matches RH Gold)",
      "2% match on recurring deposits",
      "Direct indexing at $25K*",
      "Unlimited CFP sessions",
      "IPO access",
      "L2 quotes + all Autonomous Labs",
      "Cross-account TLH with wash-sale guard",
    ],
    highlight: "5.0% APY + 3% IRA match",
  },
] as const;

type BillingCycle = "monthly" | "annual";

export default function UpgradePage() {
  const navigate = useNavigate();
  const [billing, setBilling] = useState<BillingCycle>("monthly");
  const [depositAmt, setDepositAmt] = useState(500);

  const plusSim = useQuery({
    queryKey: ["sim-plus", depositAmt],
    queryFn: () => simulateDepositMatch(depositAmt),
    staleTime: 30_000,
  });
  void plusSim; // used for data prefetch

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-5xl mx-auto px-4 py-12 space-y-10">

        {/* Header */}
        <div className="text-center space-y-3">
          <h1 className="text-4xl font-black tracking-tight">
            BMG Plus — <span style={{ color: "#4ade80" }}>Gold for the next 5 years</span>
          </h1>
          <p className="text-[var(--text-secondary)] max-w-xl mx-auto">
            More APY. More match. Voice AI. External accounts. Everything Robinhood Gold should be.
          </p>
          <div className="flex items-center justify-center gap-2 mt-4">
            {(["monthly", "annual"] as const).map(b => (
              <button
                key={b}
                onClick={() => setBilling(b)}
                className={`px-5 py-2 rounded-full text-sm font-semibold transition-colors capitalize ${billing === b ? "bg-[#4ade80] text-black" : "bg-[var(--bg-elevated)] text-[var(--text-secondary)]"}`}
              >
                {b} {b === "annual" && <span className="ml-1 text-xs opacity-70">Save 17%</span>}
              </button>
            ))}
          </div>
        </div>

        {/* Tier cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TIERS.map(tier => (
            <div key={tier.id} className={`relative rounded-2xl border-2 ${tier.color} bg-[var(--bg-elevated)] p-6 space-y-5 flex flex-col`}>
              {tier.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-xs font-bold bg-[#4ade80] text-black whitespace-nowrap">
                  {tier.badge}
                </div>
              )}

              <div>
                <div className="text-sm font-bold uppercase tracking-widest text-[var(--text-secondary)]">{tier.name}</div>
                <div className="text-4xl font-black font-mono mt-1" style={{ color: tier.id !== "free" ? "#4ade80" : undefined }}>
                  {tier.monthly === 0 ? "Free" : `$${billing === "annual" ? tier.annual?.toFixed(2) : tier.monthly}`}
                  {tier.monthly > 0 && <span className="text-lg font-normal text-[var(--text-secondary)]">/mo</span>}
                </div>
                {billing === "annual" && "annualTotal" in tier && tier.annualTotal && (
                  <div className="text-xs text-[var(--text-secondary)]">billed ${tier.annualTotal}/year</div>
                )}
                {"highlight" in tier && tier.highlight && (
                  <div className="mt-2 text-xs font-semibold text-[#4ade80]">★ {tier.highlight}</div>
                )}
              </div>

              <ul className="space-y-2 flex-1">
                {tier.features.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                    <Check className="w-4 h-4 text-[#4ade80] shrink-0 mt-0.5" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>

              {tier.id !== "free" ? (
                <button
                  onClick={() => navigate("/pricing")}
                  className="w-full py-3 rounded-xl font-bold text-sm bg-[#4ade80] text-black hover:bg-[#a3e635] transition-colors"
                >
                  Start 7-Day Free Trial
                </button>
              ) : (
                <div className="text-xs text-center text-[var(--text-secondary)] py-3">Current plan</div>
              )}
            </div>
          ))}
        </div>

        {/* Deposit match simulator */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
          <div className="flex items-center gap-2">
            <Gift className="w-5 h-5 text-[#4ade80]" />
            <h2 className="text-base font-bold text-[var(--text-primary)]">Deposit Match Simulator</h2>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">See how much BMG matches on your monthly recurring deposit.</p>
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-sm text-[var(--text-secondary)]">Monthly deposit:</label>
            <input
              type="range" min={100} max={5000} step={100}
              value={depositAmt} onChange={e => setDepositAmt(Number(e.target.value))}
              className="w-48 accent-[#4ade80]"
            />
            <span className="font-mono font-bold text-[var(--text-primary)]">${depositAmt}/mo</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { tier: "Free", pct: 0, color: "text-[var(--text-secondary)]" },
              { tier: "Plus", pct: 1, color: "text-[#4ade80]" },
              { tier: "Premium", pct: 2, color: "text-purple-400" },
            ].map(({ tier, pct, color }) => (
              <div key={tier} className="rounded-xl bg-[var(--bg-base)] p-4 space-y-1">
                <div className="text-xs font-bold text-[var(--text-secondary)] uppercase">{tier}</div>
                <div className={`text-2xl font-black font-mono ${color}`}>
                  +${((depositAmt * pct) / 100).toFixed(2)}/mo
                </div>
                <div className="text-xs text-[var(--text-secondary)]">
                  ${(depositAmt * pct / 100 * 12).toFixed(0)}/year match ({pct}%)
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-[var(--text-secondary)]">90-day hold required. Match credited monthly.</p>
        </div>

        {/* vs Robinhood Gold */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6">
          <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-secondary)] mb-4">BMG Plus vs Robinhood Gold</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-[var(--text-secondary)] border-b border-[var(--border-subtle)]">
                <th className="text-left pb-2">Feature</th>
                <th className="text-center pb-2">Robinhood Gold $5/mo</th>
                <th className="text-center pb-2 text-[#4ade80]">BMG Plus $7.99/mo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {[
                ["APY on cash", "3.35%", "4.0%"],
                ["IRA match", "3% (Gold)", "1% (Plus)"],
                ["Deposit match", "None", "1% recurring"],
                ["Voice AI", "None", "Unlimited"],
                ["External brokerages", "None", "Unlimited"],
                ["Tax-loss harvesting", "None", "Included"],
                ["CFP session", "None", "1/year free"],
              ].map(([feature, rh, bmg]) => (
                <tr key={feature}>
                  <td className="py-2 text-[var(--text-secondary)]">{feature}</td>
                  <td className="py-2 text-center text-[var(--text-secondary)]">{rh}</td>
                  <td className="py-2 text-center font-semibold text-[#4ade80]">{bmg}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-[var(--text-secondary)] mt-3">*IRA match requires active subscription + 5-year hold. Direct indexing at $25K (vs Wealthfront $100K).</p>
        </div>

      </div>
    </div>
  );
}
