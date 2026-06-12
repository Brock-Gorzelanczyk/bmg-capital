import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Minus, AlertTriangle, TrendingUp, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { startTrial, createCheckout } from "@/api/tiers";

// ── helpers ─────────────────────────────────────────────────────────────────
function isLoggedIn(): boolean {
  try {
    return !!window.localStorage.getItem("bmg_token");
  } catch {
    return false;
  }
}

// ── static tier data ─────────────────────────────────────────────────────────
const TIERS = [
  {
    id: "free" as const,
    label: "FREE",
    monthlyPrice: 0,
    annualPrice: 0,
    annualMonthly: 0,
    badge: null,
    ctaLabel: "Start free",
    ctaVariant: "ghost" as const,
    features: [
      "1 paper bot",
      "5 strategies",
      "100 screener queries / week",
      "Basic alerts",
    ],
    notIncluded: [
      "AI Analyst",
      "Voice AI",
      "Custom Bot Builder save",
      "AI Co-Pilot",
      "Unlimited screener",
    ],
  },
  {
    id: "plus" as const,
    label: "PRO",
    monthlyPrice: 29,
    annualPrice: 290,
    annualMonthly: 24.17,
    badge: "MOST POPULAR",
    ctaLabel: "Start 14-day trial",
    ctaVariant: "primary" as const,
    features: [
      "All 8 paper bots",
      "All 99 strategies",
      "Unlimited screener queries",
      "Custom Bot Builder",
      "AI Co-Pilot",
      "Basic alerts",
    ],
    notIncluded: [
      "AI Analyst",
      "Voice AI",
      "Screener backtest",
      "Natural language screener",
    ],
  },
  {
    id: "premium" as const,
    label: "PRO+",
    monthlyPrice: 59,
    annualPrice: 590,
    annualMonthly: 49.17,
    badge: null,
    ctaLabel: "Start 14-day trial",
    ctaVariant: "secondary" as const,
    features: [
      "Everything in Pro",
      "AI Analyst",
      "Voice AI",
      "Screener backtest",
      "Natural language screener",
      "Priority Cmd+K",
      "All 8 paper bots",
      "All 99 strategies",
      "Unlimited screener queries",
      "Custom Bot Builder",
      "AI Co-Pilot",
    ],
    notIncluded: [],
  },
] as const;

// ── feature comparison table rows ────────────────────────────────────────────
const COMPARISON_ROWS: { feature: string; free: boolean; plus: boolean; premium: boolean }[] = [
  { feature: "Paper bots",               free: false, plus: true,  premium: true },
  { feature: "Strategies",               free: false, plus: true,  premium: true },
  { feature: "Unlimited screener",       free: false, plus: true,  premium: true },
  { feature: "Custom Bot Builder",       free: false, plus: true,  premium: true },
  { feature: "AI Co-Pilot",             free: false, plus: true,  premium: true },
  { feature: "Basic alerts",             free: true,  plus: true,  premium: true },
  { feature: "AI Analyst",              free: false, plus: false, premium: true },
  { feature: "Voice AI",                 free: false, plus: false, premium: true },
  { feature: "Screener backtest",        free: false, plus: false, premium: true },
  { feature: "Natural language screener",free: false, plus: false, premium: true },
  { feature: "Priority Cmd+K",           free: false, plus: false, premium: true },
];

// ── ROI calculator data ───────────────────────────────────────────────────────
const PORTFOLIO_SIZES = [
  { label: "$1K",    value: 1_000 },
  { label: "$10K",   value: 10_000 },
  { label: "$50K",   value: 50_000 },
  { label: "$100K",  value: 100_000 },
];

const STRATEGIES = [
  { label: "Stock Swing",    returnPct: 5.15, period: "30d" },
  { label: "Crypto Swing",   returnPct: 8.20, period: "30d" },
  { label: "Equity Income",  returnPct: 3.10, period: "30d" },
];

// ── FAQ data ──────────────────────────────────────────────────────────────────
const FAQ_ITEMS = [
  {
    q: "Why does BMG require no credit card for the trial?",
    a: "We want you to see real paper-trading results before you pay anything. The trial gives you full Pro+ access for 14 days — bots running, AI Analyst on, Voice AI included — with no friction.",
  },
  {
    q: "What happens after my 14-day Pro+ trial ends?",
    a: "If you haven't added a card, you auto-downgrade to the Free plan (1 bot, 5 strategies). Your data stays intact. You'll receive a win-back offer — 20% off Pro for 3 months — if you come back within the week.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes. Cancel from Settings → Subscription in 2 clicks. No cancellation fees, no lock-in.",
  },
  {
    q: "Is this real money or paper?",
    a: "Paper only. BMG is a simulation platform — no real capital is deployed. Live trading is coming soon, pending RIA registration.",
  },
  {
    q: "When does live trading unlock?",
    a: "Live trading is coming soon when BMG completes RIA registration. Pro+ subscribers get first access.",
  },
  {
    q: "What if my bot loses money?",
    a: "It's paper — no real money is at stake. Every bot decision is logged with a plain-English reason so you can understand and learn from each signal.",
  },
  {
    q: "How do I cancel?",
    a: "Settings → Subscription → Cancel. You keep access until the end of your billing period.",
  },
  {
    q: "What data powers the bots?",
    a: "EOD price data from major exchanges, earnings calendars, macroeconomic regime signals, and technical indicators — all from licensed data providers. Strategy decisions are logged and auditable.",
  },
];

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-zinc-800 last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full py-4 text-left text-sm font-medium text-zinc-200 hover:text-white transition-colors"
      >
        {q}
        <ChevronDown className={cn("w-4 h-4 text-zinc-500 shrink-0 ml-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && <p className="text-sm text-zinc-400 pb-4 leading-relaxed">{a}</p>}
    </div>
  );
}

// ── main component ───────────────────────────────────────────────────────────
export default function PricingPage() {
  const navigate = useNavigate();
  const [billing, setBilling] = useState<"monthly" | "annual">("annual");
  const [loading, setLoading] = useState<string | null>(null);

  // ROI calculator state
  const [portfolioIdx, setPortfolioIdx] = useState(1); // default $10K
  const [strategyIdx, setStrategyIdx]   = useState(0);

  const portfolio = PORTFOLIO_SIZES[portfolioIdx];
  const strategy  = STRATEGIES[strategyIdx];
  const estimatedGain = portfolio.value * (strategy.returnPct / 100);

  const handleCTA = useCallback(
    async (tierId: "free" | "plus" | "premium") => {
      if (tierId === "free") {
        navigate("/login?signup=true");
        return;
      }

      if (!isLoggedIn()) {
        navigate("/login?signup=true");
        return;
      }

      setLoading(tierId);
      try {
        // Attempt free trial first; fall back to checkout
        const res = await startTrial();
        if (res.ok) {
          toast.success("14-day trial started!");
          navigate("/");
        }
      } catch (err: unknown) {
        // Trial already used or not available — go to checkout
        try {
          const checkout = await createCheckout(tierId, billing);
          window.location.href = checkout.url;
        } catch {
          toast.error("Could not start checkout. Please try again.");
        }
      } finally {
        setLoading(null);
      }
    },
    [billing, navigate]
  );

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-16 space-y-16">

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="text-center space-y-4">
          <h1 className="text-4xl md:text-5xl font-black tracking-tight">
            Build, backtest, and deploy<br />
            <span className="text-blue-500">AI trading bots</span>
          </h1>
          <p className="text-zinc-400 max-w-xl mx-auto text-lg">
            Eight bots, ninety-nine strategies, paper now and live in Q3.
          </p>
          <p className="text-sm text-zinc-500">
            Start free — 14-day Pro+ trial included, no card required.
          </p>

          {/* Billing toggle */}
          <div className="flex items-center justify-center gap-1 mt-6 bg-zinc-900 border border-zinc-800 rounded-full p-1 w-fit mx-auto">
            {(["annual", "monthly"] as const).map((b) => (
              <button
                key={b}
                onClick={() => setBilling(b)}
                className={cn(
                  "flex items-center gap-2 px-5 py-2 rounded-full text-sm font-semibold transition-all capitalize",
                  billing === b
                    ? "bg-zinc-700 text-white shadow"
                    : "text-zinc-400 hover:text-zinc-200"
                )}
              >
                {b === "annual" ? "Annual" : "Monthly"}
                {b === "annual" && (
                  <span className="bg-emerald-500/20 text-emerald-400 text-[10px] font-bold px-2 py-0.5 rounded-full border border-emerald-500/30">
                    Save 17%
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* ── Tier cards ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
          {TIERS.map((tier) => {
            const isPro    = tier.id === "plus";
            const isProPlus = tier.id === "premium";
            const isFree   = tier.id === "free";

            const displayPrice =
              billing === "annual" && !isFree
                ? tier.annualMonthly
                : tier.monthlyPrice;

            return (
              <div key={tier.id} className="relative flex flex-col">
                {/* "MOST POPULAR" badge floating above card */}
                {tier.badge && (
                  <div className="flex justify-center mb-[-1px] z-10">
                    <span className="bg-blue-500 text-white text-xs font-bold px-3 py-1 rounded-full">
                      {tier.badge}
                    </span>
                  </div>
                )}

                <div
                  className={cn(
                    "bg-zinc-900 border rounded-2xl p-6 flex flex-col gap-6",
                    isPro
                      ? "border-blue-500 ring-2 ring-blue-500 shadow-xl shadow-blue-500/10"
                      : "border-zinc-800"
                  )}
                >
                  {/* Tier name + price */}
                  <div>
                    <div className="text-xs font-bold uppercase tracking-widest text-zinc-500 mb-1">
                      {tier.label}
                    </div>
                    {isFree ? (
                      <div className="text-4xl font-black">Free</div>
                    ) : (
                      <div>
                        <div className="flex items-end gap-1">
                          <span className="text-4xl font-black">
                            ${displayPrice % 1 === 0 ? displayPrice : displayPrice.toFixed(2)}
                          </span>
                          <span className="text-zinc-500 text-sm mb-1.5">/mo</span>
                        </div>
                        {billing === "annual" && (
                          <div className="text-xs text-zinc-500 mt-0.5">
                            billed ${tier.annualPrice}/year
                          </div>
                        )}
                        {/* Pro+ reference price anchors Pro as a deal */}
                        {isPro && (
                          <div className="text-xs text-zinc-600 mt-1">
                            Pro+ is ${billing === "annual" ? "49" : "59"}/mo — Pro is the smart pick
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Features included */}
                  <ul className="space-y-2 flex-1">
                    {tier.features.map((f) => (
                      <li key={f} className="flex items-start gap-2 text-sm text-zinc-300">
                        <Check
                          className={cn(
                            "w-4 h-4 shrink-0 mt-0.5",
                            isPro || isProPlus ? "text-emerald-400" : "text-zinc-500"
                          )}
                        />
                        <span>{f}</span>
                      </li>
                    ))}
                    {tier.notIncluded.map((f) => (
                      <li key={f} className="flex items-start gap-2 text-sm text-zinc-600">
                        <Minus className="w-4 h-4 shrink-0 mt-0.5" />
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>

                  {/* CTA */}
                  <button
                    disabled={loading === tier.id}
                    onClick={() => handleCTA(tier.id)}
                    className={cn(
                      "w-full py-3 rounded-xl font-bold text-sm transition-all",
                      tier.ctaVariant === "primary" &&
                        "bg-blue-500 text-white hover:bg-blue-400 disabled:opacity-50",
                      tier.ctaVariant === "secondary" &&
                        "bg-zinc-700 text-white hover:bg-zinc-600 disabled:opacity-50",
                      tier.ctaVariant === "ghost" &&
                        "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                    )}
                  >
                    {loading === tier.id ? "Loading…" : tier.ctaLabel}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Feature comparison table ────────────────────────────────────── */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
          <div className="p-6 border-b border-zinc-800">
            <h2 className="text-base font-bold text-white">Full feature comparison</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800">
                  <th className="text-left px-6 py-3 text-zinc-500 font-semibold">Feature</th>
                  <th className="text-center px-4 py-3 text-zinc-500 font-semibold">Free</th>
                  <th className="text-center px-4 py-3 text-blue-400 font-semibold">Pro</th>
                  <th className="text-center px-4 py-3 text-zinc-300 font-semibold">Pro+</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {COMPARISON_ROWS.map((row) => (
                  <tr key={row.feature} className="hover:bg-zinc-800/30 transition-colors">
                    <td className="px-6 py-3 text-zinc-400">{row.feature}</td>
                    <td className="px-4 py-3 text-center">
                      {row.free ? (
                        <Check className="w-4 h-4 text-emerald-400 mx-auto" />
                      ) : (
                        <Minus className="w-4 h-4 text-zinc-700 mx-auto" />
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {row.plus ? (
                        <Check className="w-4 h-4 text-emerald-400 mx-auto" />
                      ) : (
                        <Minus className="w-4 h-4 text-zinc-700 mx-auto" />
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {row.premium ? (
                        <Check className="w-4 h-4 text-emerald-400 mx-auto" />
                      ) : (
                        <Minus className="w-4 h-4 text-zinc-700 mx-auto" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── ROI Calculator ──────────────────────────────────────────────── */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-6">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-emerald-400" />
            <h2 className="text-base font-bold text-white">What would your strategy have returned?</h2>
          </div>

          <div className="space-y-4">
            {/* Portfolio size buttons */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-2">Portfolio size</p>
              <div className="flex flex-wrap gap-2">
                {PORTFOLIO_SIZES.map((p, idx) => (
                  <button
                    key={p.label}
                    onClick={() => setPortfolioIdx(idx)}
                    className={cn(
                      "px-4 py-2 rounded-lg text-sm font-semibold border transition-all",
                      portfolioIdx === idx
                        ? "bg-blue-500 border-blue-500 text-white"
                        : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-zinc-500"
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Strategy selector */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-2">Strategy</p>
              <div className="flex flex-wrap gap-2">
                {STRATEGIES.map((s, idx) => (
                  <button
                    key={s.label}
                    onClick={() => setStrategyIdx(idx)}
                    className={cn(
                      "px-4 py-2 rounded-lg text-sm font-semibold border transition-all",
                      strategyIdx === idx
                        ? "bg-blue-500 border-blue-500 text-white"
                        : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-zinc-500"
                    )}
                  >
                    {s.label}{" "}
                    <span className="opacity-70">
                      (+{s.returnPct}% paper, {s.period})
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Output */}
          <div className="bg-zinc-950 border border-zinc-800 rounded-xl p-6 text-center space-y-1">
            <div className="text-5xl font-black text-emerald-400">
              +${estimatedGain.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </div>
            <div className="text-zinc-400 text-sm">
              paper gain in {strategy.period} on a {portfolio.label} portfolio using {strategy.label}
              {" "}(+{strategy.returnPct}% paper)
            </div>
          </div>

          <p className="text-xs text-zinc-600 text-center">
            Paper trading simulation. Past performance does not guarantee future results.
          </p>
        </div>

        {/* ── Social proof ────────────────────────────────────────────────── */}
        <div className="text-center text-zinc-500 text-sm">
          12,847 Pro members ran{" "}
          <span className="text-zinc-300 font-semibold">248,000 paper backtests</span>{" "}
          last month
        </div>

        {/* ── FAQ ─────────────────────────────────────────────────────────── */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
          <h2 className="text-base font-bold text-white mb-2">Frequently asked questions</h2>
          {FAQ_ITEMS.map((item) => (
            <FAQItem key={item.q} q={item.q} a={item.a} />
          ))}
        </div>

        {/* ── Legal disclaimer ────────────────────────────────────────────── */}
        <div className="bg-amber-950/30 border border-amber-500/30 rounded-2xl p-6 flex gap-4">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="text-amber-300 text-sm font-bold uppercase tracking-wide">
              Important Disclosure
            </p>
            <p className="text-amber-200/70 text-sm leading-relaxed">
              Past performance does not guarantee future results. BMG Capital is not a registered
              investment adviser. All content is for informational purposes only. All performance
              figures are hypothetical backtested or paper-trading results. No real money is traded.
              Live trading coming soon, subject to Wisconsin RIA registration.
            </p>
          </div>
        </div>

      </div>
    </div>
  );
}
