import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { TrendingUp, Lock, ChevronRight, X, DollarSign, Calendar, Building2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { getIPODeals, registerIPO, getMyIPORegistrations, type IPODeal, type IPORegistration } from "@/api/ipo";
import { getMyTier } from "@/api/tiers";
import { useNavigate } from "react-router-dom";

const TIER_RANK: Record<string, number> = { free: 0, plus: 1, premium: 2 };

const SECTOR_COLORS: Record<string, string> = {
  Technology: "bg-blue-500/20 text-blue-400",
  "Clean Energy": "bg-green-500/20 text-green-400",
  SaaS: "bg-purple-500/20 text-purple-400",
  Healthcare: "bg-red-500/20 text-red-400",
  Finance: "bg-yellow-500/20 text-yellow-400",
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  upcoming: { label: "Upcoming", color: "bg-[#84cc16]/20 text-[#84cc16]" },
  pricing: { label: "Pricing", color: "bg-yellow-500/20 text-yellow-400" },
  open: { label: "Open", color: "bg-green-500/20 text-green-400" },
  closed: { label: "Closed", color: "bg-zinc-500/20 text-zinc-400" },
  trading: { label: "Trading", color: "bg-blue-500/20 text-blue-400" },
};

function formatDate(iso: string | null) {
  if (!iso) return "TBD";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function IPOAccessPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selectedDeal, setSelectedDeal] = useState<IPODeal | null>(null);
  const [amount, setAmount] = useState(500);

  const { data: deals = [] } = useQuery({ queryKey: ["ipo-deals"], queryFn: getIPODeals });
  const { data: myRegs = [] } = useQuery({ queryKey: ["ipo-my-registrations"], queryFn: getMyIPORegistrations });
  const { data: tierData } = useQuery({ queryKey: ["my-tier"], queryFn: getMyTier });

  const userTier = tierData?.tier ?? "free";
  const userTierRank = TIER_RANK[userTier] ?? 0;

  const registeredDealIds = new Set(myRegs.map((r: IPORegistration) => r.deal?.id));

  const registerMutation = useMutation({
    mutationFn: () => registerIPO(selectedDeal!.id, amount),
    onSuccess: () => {
      toast.success(`Waitlisted for ${selectedDeal!.company_name} IPO`);
      qc.invalidateQueries({ queryKey: ["ipo-my-registrations"] });
      setSelectedDeal(null);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Registration failed";
      toast.error(msg);
    },
  });

  const canAccess = (deal: IPODeal) => userTierRank >= (TIER_RANK[deal.min_tier] ?? 2);

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="rounded-2xl border border-blue-500/30 bg-blue-500/5 p-6">
          <div className="flex items-center gap-3 mb-2">
            <TrendingUp className="w-6 h-6 text-blue-400" />
            <h1 className="text-2xl font-black text-[var(--text-primary)]">IPO Access</h1>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">Get early access to upcoming IPOs before they hit the market.</p>
          {userTier === "free" && (
            <div className="mt-4 flex items-start gap-3 rounded-xl bg-yellow-500/10 border border-yellow-500/30 p-4">
              <AlertCircle className="w-4 h-4 text-yellow-400 mt-0.5 shrink-0" />
              <div className="text-sm text-yellow-300">
                IPO access requires <strong>Plus or Premium</strong> tier.{" "}
                <button onClick={() => navigate("/upgrade")} className="underline font-semibold hover:text-yellow-200">Upgrade now</button>
              </div>
            </div>
          )}
        </div>

        {/* Deal Cards */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Available IPOs</h2>
          {deals.length === 0 && (
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-8 text-center text-sm text-[var(--text-secondary)]">
              No upcoming IPOs at this time. Check back soon.
            </div>
          )}
          <div className="grid grid-cols-1 gap-4">
            {deals.map((deal: IPODeal) => {
              const accessible = canAccess(deal);
              const alreadyRegistered = registeredDealIds.has(deal.id);
              const statusInfo = STATUS_LABELS[deal.status] ?? { label: deal.status, color: "bg-zinc-500/20 text-zinc-400" };
              const sectorColor = SECTOR_COLORS[deal.sector] ?? "bg-zinc-500/20 text-zinc-400";

              return (
                <div
                  key={deal.id}
                  className={`rounded-2xl border ${accessible ? "border-[var(--border-subtle)] hover:border-blue-500/40" : "border-[var(--border-subtle)] opacity-70"} bg-[var(--bg-elevated)] p-5 transition-all`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${sectorColor}`}>{deal.sector}</span>
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${statusInfo.color}`}>{statusInfo.label}</span>
                        {deal.min_tier !== "free" && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-[#84cc16]/20 text-[#84cc16] capitalize">{deal.min_tier}+</span>
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-bold text-[var(--text-primary)] text-lg">{deal.company_name}</h3>
                          {deal.ticker && <span className="text-xs text-[var(--text-secondary)] font-mono bg-[var(--bg-base)] px-2 py-0.5 rounded">{deal.ticker}</span>}
                        </div>
                        <p className="text-sm text-[var(--text-secondary)] mt-1">{deal.description}</p>
                      </div>
                      <div className="flex flex-wrap gap-4 text-sm">
                        {(deal.price_range_low || deal.price_range_high) && (
                          <div className="flex items-center gap-1.5 text-[var(--text-secondary)]">
                            <DollarSign className="w-3.5 h-3.5" />
                            <span className="font-mono">
                              ${deal.price_range_low ?? "?"} – ${deal.price_range_high ?? "?"}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center gap-1.5 text-[var(--text-secondary)]">
                          <Calendar className="w-3.5 h-3.5" />
                          <span>{formatDate(deal.expected_date)}</span>
                        </div>
                        {deal.lead_underwriter && (
                          <div className="flex items-center gap-1.5 text-[var(--text-secondary)]">
                            <Building2 className="w-3.5 h-3.5" />
                            <span>{deal.lead_underwriter}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="shrink-0">
                      {!accessible ? (
                        <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] bg-[var(--bg-base)] px-3 py-2 rounded-lg">
                          <Lock className="w-3.5 h-3.5" />
                          <span className="capitalize">{deal.min_tier}</span>
                        </div>
                      ) : alreadyRegistered ? (
                        <div className="text-xs font-semibold text-[#84cc16] bg-[#84cc16]/10 border border-[#84cc16]/30 px-3 py-2 rounded-lg">
                          Waitlisted
                        </div>
                      ) : (
                        <button
                          onClick={() => { setSelectedDeal(deal); setAmount(500); }}
                          className="flex items-center gap-1.5 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded-lg transition-colors"
                        >
                          Register <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* My Registrations */}
        {myRegs.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">My Registrations</h2>
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-[var(--text-secondary)] border-b border-[var(--border-subtle)]">
                    <th className="text-left p-4">Company</th>
                    <th className="text-center p-4">Status</th>
                    <th className="text-right p-4">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {myRegs.map((reg: IPORegistration) => (
                    <tr key={reg.id}>
                      <td className="p-4">
                        <div className="font-medium text-[var(--text-primary)]">{reg.deal?.company_name ?? "—"}</div>
                        {reg.deal?.ticker && <div className="text-xs text-[var(--text-secondary)] font-mono">{reg.deal.ticker}</div>}
                      </td>
                      <td className="p-4 text-center">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                          reg.status === "allocated" ? "bg-green-500/20 text-green-400" :
                          reg.status === "cancelled" ? "bg-zinc-500/20 text-zinc-400" :
                          reg.status === "missed" ? "bg-red-500/20 text-red-400" :
                          "bg-[#84cc16]/20 text-[#84cc16]"
                        }`}>{reg.status}</span>
                      </td>
                      <td className="p-4 text-right font-mono font-bold text-[var(--text-primary)]">
                        ${reg.requested_amount.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Registration Panel */}
      {selectedDeal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
            <div className="flex items-center justify-between p-5 border-b border-[var(--border-subtle)]">
              <div>
                <div className="font-bold text-[var(--text-primary)]">{selectedDeal.company_name}</div>
                <div className="text-xs text-[var(--text-secondary)] mt-0.5">
                  {selectedDeal.ticker && `${selectedDeal.ticker} · `}
                  {selectedDeal.price_range_low && selectedDeal.price_range_high
                    ? `$${selectedDeal.price_range_low}–$${selectedDeal.price_range_high}`
                    : "Price TBD"}
                </div>
              </div>
              <button onClick={() => setSelectedDeal(null)} className="p-1 rounded hover:bg-[var(--bg-base)] text-[var(--text-secondary)]">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-5">
              <div className="rounded-xl bg-[var(--bg-base)] p-4 text-sm text-[var(--text-secondary)]">
                {selectedDeal.description}
              </div>
              <div className="space-y-2">
                <label className="text-sm font-semibold text-[var(--text-primary)]">Requested Amount</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] text-sm">$</span>
                  <input
                    type="number"
                    min={100}
                    step={100}
                    value={amount}
                    onChange={e => setAmount(Number(e.target.value))}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-7 py-2.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-blue-500"
                  />
                </div>
                <p className="text-xs text-[var(--text-secondary)]">Actual allocation may be less depending on demand. You will only be charged if allocated.</p>
              </div>
              <div className="flex gap-3">
                <button onClick={() => setSelectedDeal(null)} className="flex-1 py-2.5 rounded-xl bg-[var(--bg-base)] text-[var(--text-primary)] text-sm font-semibold hover:bg-[var(--border-subtle)] transition-colors">
                  Cancel
                </button>
                <button
                  onClick={() => registerMutation.mutate()}
                  disabled={registerMutation.isPending || amount < 100}
                  className="flex-1 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-bold hover:bg-blue-500 transition-colors disabled:opacity-50"
                >
                  {registerMutation.isPending ? "Registering…" : "Join Waitlist"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
