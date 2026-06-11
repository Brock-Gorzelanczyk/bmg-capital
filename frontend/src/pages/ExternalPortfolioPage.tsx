import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, RefreshCw, Trash2, Plus, TrendingDown, AlertTriangle, Layers } from "lucide-react";
import { toast } from "sonner";
import {
  getBrokerages, getAllHoldings, getInsights, deleteBrokerage, syncBrokerage,
  type ExternalHolding, type InsightsResponse,
} from "@/api/linkedAccounts";
import ConnectBrokerageModal from "@/components/portfolio/ConnectBrokerageModal";

export default function ExternalPortfolioPage() {
  const qc = useQueryClient();
  const [connectOpen, setConnectOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"holdings" | "insights">("holdings");

  const { data: brokerages = [], isLoading: brokLoading } = useQuery({
    queryKey: ["linked-brokerages"],
    queryFn: getBrokerages,
    staleTime: 30_000,
  });

  const { data: holdingsData } = useQuery({
    queryKey: ["external-holdings"],
    queryFn: getAllHoldings,
    staleTime: 60_000,
    enabled: brokerages.length > 0,
  });

  const { data: insights } = useQuery({
    queryKey: ["external-insights"],
    queryFn: getInsights,
    staleTime: 60_000,
    enabled: brokerages.length > 0,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBrokerage,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["linked-brokerages"] });
      qc.invalidateQueries({ queryKey: ["external-holdings"] });
      toast.success("Brokerage disconnected");
    },
  });

  const syncMutation = useMutation({
    mutationFn: syncBrokerage,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["linked-brokerages"] });
      qc.invalidateQueries({ queryKey: ["external-holdings"] });
      toast.success("Holdings synced");
    },
  });

  const totalAUM = holdingsData?.total_value ?? 0;

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">

        {/* Hero */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="text-2xl font-black text-[var(--text-primary)]">Your Money, Everywhere</h1>
              <p className="text-sm text-[var(--text-secondary)] mt-1">
                Read-only access to your existing brokerages — BMG never trades these accounts
              </p>
            </div>
            <div className="text-right">
              <div className="text-3xl font-black font-mono" style={{ color: "#4ade80" }}>
                ${totalAUM.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
              <div className="text-xs text-[var(--text-secondary)]">total external AUM</div>
            </div>
          </div>
        </div>

        {/* Connected brokerages */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-secondary)]">
              Connected Accounts
            </h2>
            <button
              onClick={() => setConnectOpen(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#4ade80] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors"
            >
              <Plus className="w-4 h-4" />
              Connect
            </button>
          </div>

          {brokLoading ? (
            <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
          ) : brokerages.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[var(--border-subtle)] p-8 text-center space-y-3">
              <Building2 className="w-8 h-8 text-[var(--text-secondary)] mx-auto" />
              <p className="text-sm text-[var(--text-secondary)]">No brokerages connected yet.</p>
              <button
                onClick={() => setConnectOpen(true)}
                className="px-5 py-2 rounded-lg bg-[#4ade80] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors"
              >
                Connect your first brokerage
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {brokerages.map(b => (
                <div key={b.id} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-[var(--bg-base)] flex items-center justify-center text-xs font-black text-[#4ade80]">
                    {b.institution_name.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm text-[var(--text-primary)]">{b.institution_name}</div>
                    <div className="text-xs text-[var(--text-secondary)]">
                      {b.holdings_count} holdings · {b.last_synced_at ? `synced ${new Date(b.last_synced_at).toLocaleTimeString()}` : "not synced"}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => syncMutation.mutate(b.id)}
                      disabled={syncMutation.isPending}
                      className="p-1.5 rounded hover:bg-[var(--bg-base)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                      title="Sync"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => { if (confirm("Disconnect this brokerage?")) deleteMutation.mutate(b.id); }}
                      className="p-1.5 rounded hover:bg-[var(--bg-base)] text-[var(--text-secondary)] hover:text-red-400 transition-colors"
                      title="Disconnect"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tabs */}
        {brokerages.length > 0 && (
          <>
            <div className="flex gap-2">
              {(["holdings", "insights"] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 rounded-lg text-sm font-semibold capitalize transition-colors ${activeTab === tab ? "bg-[#4ade80] text-black" : "bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {activeTab === "holdings" && holdingsData && (
              <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[var(--text-secondary)] text-xs uppercase tracking-wide border-b border-[var(--border-subtle)]">
                      <th className="text-left p-4">Symbol</th>
                      <th className="text-left p-4 hidden sm:table-cell">Institution</th>
                      <th className="text-right p-4">Qty</th>
                      <th className="text-right p-4">Value</th>
                      <th className="text-right p-4 hidden md:table-cell">Cost Basis</th>
                      <th className="text-right p-4">P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {holdingsData.holdings.map((h: ExternalHolding, i: number) => (
                      <tr key={i} className="hover:bg-[var(--bg-base)] transition-colors">
                        <td className="p-4">
                          <div className="font-mono font-bold text-[var(--text-primary)]">{h.symbol}</div>
                          <div className="text-xs text-[var(--text-secondary)] truncate max-w-[120px]">{h.name}</div>
                        </td>
                        <td className="p-4 hidden sm:table-cell text-[var(--text-secondary)] text-xs">{h.institution}</td>
                        <td className="p-4 text-right font-mono text-[var(--text-secondary)]">{h.quantity.toFixed(2)}</td>
                        <td className="p-4 text-right font-mono font-semibold text-[var(--text-primary)]">
                          ${(h.current_value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </td>
                        <td className="p-4 text-right font-mono text-[var(--text-secondary)] hidden md:table-cell">
                          ${(h.cost_basis ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </td>
                        <td className={`p-4 text-right font-mono font-semibold ${(h.unrealized_pnl_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {h.unrealized_pnl_pct != null ? `${h.unrealized_pnl_pct >= 0 ? "+" : ""}${h.unrealized_pnl_pct.toFixed(1)}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {activeTab === "insights" && insights && (
              <div className="space-y-4">
                {insights.what_to_sell.length > 0 && (
                  <InsightSection
                    title="What to Sell"
                    icon={<TrendingDown className="w-4 h-4" />}
                    color="red"
                    items={insights.what_to_sell.map(i => ({
                      label: i.symbol,
                      sub: i.name,
                      value: `${i.loss_pct.toFixed(1)}%`,
                      detail: `Unrealized loss: $${Math.abs(i.unrealized_loss).toFixed(0)}`,
                    }))}
                  />
                )}
                {insights.tax_loss_candidates.length > 0 && (
                  <InsightSection
                    title="Tax-Loss Candidates"
                    icon={<AlertTriangle className="w-4 h-4" />}
                    color="amber"
                    items={insights.tax_loss_candidates.map(i => ({
                      label: i.symbol,
                      sub: `${i.loss_pct.toFixed(1)}% loss`,
                      value: `$${i.potential_savings.toFixed(0)}`,
                      detail: "est. tax savings at 22%",
                    }))}
                  />
                )}
                {insights.concentration_risks.length > 0 && (
                  <InsightSection
                    title="Concentration Risk"
                    icon={<Layers className="w-4 h-4" />}
                    color="purple"
                    items={insights.concentration_risks.map(i => ({
                      label: i.symbol,
                      sub: `$${i.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                      value: `${i.pct_of_portfolio.toFixed(1)}%`,
                      detail: "of external portfolio",
                    }))}
                  />
                )}
                {insights.what_to_sell.length === 0 && insights.tax_loss_candidates.length === 0 && insights.concentration_risks.length === 0 && (
                  <p className="text-sm text-[var(--text-secondary)] text-center py-8">
                    Your external portfolio looks healthy — no immediate action items.
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
      {connectOpen && <ConnectBrokerageModal onClose={() => setConnectOpen(false)} />}
    </div>
  );
}

function InsightSection({ title, icon, color, items }: {
  title: string; icon: React.ReactNode; color: "red" | "amber" | "purple";
  items: Array<{ label: string; sub: string; value: string; detail: string }>;
}) {
  const borderColor = { red: "border-red-500", amber: "border-amber-400", purple: "border-purple-400" }[color];
  const textColor = { red: "text-red-400", amber: "text-amber-400", purple: "text-purple-400" }[color];
  return (
    <div className={`rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden`}>
      <div className={`border-l-4 ${borderColor} p-4 flex items-center gap-2`}>
        <span className={textColor}>{icon}</span>
        <span className="text-sm font-bold text-[var(--text-primary)] uppercase tracking-wide">{title}</span>
      </div>
      <div className="divide-y divide-[var(--border-subtle)]">
        {items.map((item, i) => (
          <div key={i} className="flex items-center justify-between p-4">
            <div>
              <div className="font-mono font-bold text-sm text-[var(--text-primary)]">{item.label}</div>
              <div className="text-xs text-[var(--text-secondary)]">{item.sub}</div>
            </div>
            <div className="text-right">
              <div className={`font-mono font-bold text-sm ${textColor}`}>{item.value}</div>
              <div className="text-xs text-[var(--text-secondary)]">{item.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
