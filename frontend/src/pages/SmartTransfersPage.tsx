import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  ArrowRightLeft,
  Plus,
  Trash2,
  CheckCircle2,
  TrendingDown,
  DollarSign,
  RefreshCw,
  X,
  ChevronRight,
  Leaf,
  AlertTriangle,
  Info,
} from "lucide-react";
import api from "@/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TLHOpportunity {
  symbol: string;
  current_price: number | null;
  cost_basis: number | null;
  market_value: number | null;
  unrealized_loss: number | null;
  loss_pct: number | null;
  harvest_tax_savings: number | null;
  wash_sale_risk: boolean;
  suggested_replacement: string | null;
}

interface TLHSummary {
  ytd_harvested: number;
  estimated_tax_saved: number;
  num_harvests: number;
}

// ─── API ──────────────────────────────────────────────────────────────────────

async function fetchTLHOpportunities(): Promise<{ opportunities: TLHOpportunity[] }> {
  const res = await api.get("/tlh/opportunities");
  return res.data;
}

async function fetchTLHSummary(): Promise<TLHSummary> {
  const res = await api.get("/tlh/summary");
  return res.data;
}

// ─── Transfer Rule type (stored client-side for now) ─────────────────────────

interface TransferRule {
  id: string;
  from_account: string;
  to_account: string;
  trigger: "monthly" | "quarterly" | "tax_loss" | "threshold";
  amount: string;
  enabled: boolean;
}

const ACCOUNT_OPTIONS = ["Brokerage (Taxable)", "Roth IRA", "Traditional IRA", "401k", "HSA", "529 Plan"];
const TRIGGER_LABELS: Record<TransferRule["trigger"], string> = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  tax_loss: "After tax-loss harvest",
  threshold: "When balance exceeds",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(v: number | null, prefix = "$") {
  if (v == null) return "—";
  return `${prefix}${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(v: number | null) {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

// ─── TLH Opportunities Panel ─────────────────────────────────────────────────

function TLHPanel() {
  const { data: opps, isLoading } = useQuery({
    queryKey: ["tlh-opportunities"],
    queryFn: fetchTLHOpportunities,
    staleTime: 60_000,
  });
  const { data: summary } = useQuery({
    queryKey: ["tlh-summary"],
    queryFn: fetchTLHSummary,
    staleTime: 60_000,
  });

  const opportunities = opps?.opportunities ?? [];

  return (
    <div className="space-y-4">
      {/* YTD Summary row */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "YTD Harvested", value: fmt(summary?.ytd_harvested ?? 0), sub: "realized losses" },
          { label: "Est. Tax Saved", value: fmt(summary?.estimated_tax_saved ?? 0), sub: "at 37% rate" },
          { label: "Harvests Done", value: String(summary?.num_harvests ?? 0), sub: "this year" },
        ].map((c) => (
          <div key={c.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-3 text-center">
            <div className="text-xs text-[var(--text-tertiary)] mb-1">{c.label}</div>
            <div className="font-mono font-bold text-[var(--text-primary)] text-lg">{c.value}</div>
            <div className="text-[10px] text-[var(--text-tertiary)]">{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Opportunities table */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
          <span className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
            <Leaf size={14} className="text-emerald-400" /> Harvest Opportunities
          </span>
          <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] rounded-full px-2 py-0.5">
            {opportunities.length} eligible
          </span>
        </div>

        {isLoading ? (
          <div className="py-10 text-center text-sm text-[var(--text-tertiary)] animate-pulse">Scanning positions…</div>
        ) : opportunities.length === 0 ? (
          <div className="py-10 text-center text-sm text-[var(--text-tertiary)]">
            No harvest opportunities right now. Good news — your portfolio is up!
          </div>
        ) : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {opportunities.map((opp) => (
              <div key={opp.symbol} className="px-4 py-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-[var(--text-primary)]">{opp.symbol}</span>
                    {opp.wash_sale_risk && (
                      <span className="text-[9px] bg-amber-400/10 border border-amber-400/20 text-amber-400 rounded-full px-1.5 py-0.5 flex items-center gap-1">
                        <AlertTriangle size={8} /> Wash-sale risk
                      </span>
                    )}
                  </div>
                  {opp.suggested_replacement && (
                    <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">
                      Replacement: <span className="font-mono text-[var(--text-secondary)]">{opp.suggested_replacement}</span>
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-mono text-red-400 font-medium">
                    −{fmt(opp.unrealized_loss)}
                  </div>
                  <div className="text-[10px] text-[var(--text-tertiary)]">
                    {pct(opp.loss_pct)} · saves ≈{fmt(opp.harvest_tax_savings)}
                  </div>
                </div>
                <ChevronRight size={14} className="text-[var(--text-tertiary)] shrink-0" />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Wash sale explanation */}
      <div className="flex gap-2 bg-blue-500/5 border border-blue-500/20 rounded-lg px-3 py-2.5 text-xs text-[var(--text-secondary)]">
        <Info size={13} className="text-blue-400 shrink-0 mt-0.5" />
        <span>
          <strong className="text-[var(--text-primary)]">Wash-sale rule:</strong> You must wait 30 days before re-buying the same security after harvesting a loss. Use a similar (not identical) ETF as a replacement to maintain market exposure.
        </span>
      </div>
    </div>
  );
}

// ─── Transfer Rules Panel ─────────────────────────────────────────────────────

function TransferRulesPanel() {
  const [rules, setRules] = useState<TransferRule[]>([
    { id: "1", from_account: "Brokerage (Taxable)", to_account: "Roth IRA", trigger: "monthly", amount: "$500", enabled: true },
    { id: "2", from_account: "Brokerage (Taxable)", to_account: "HSA", trigger: "quarterly", amount: "$1,000", enabled: false },
  ]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    from_account: ACCOUNT_OPTIONS[0],
    to_account: ACCOUNT_OPTIONS[1],
    trigger: "monthly" as TransferRule["trigger"],
    amount: "",
  });

  function addRule() {
    if (!form.amount) { toast.error("Enter a transfer amount"); return; }
    const newRule: TransferRule = {
      id: Date.now().toString(),
      from_account: form.from_account,
      to_account: form.to_account,
      trigger: form.trigger,
      amount: form.amount.startsWith("$") ? form.amount : `$${form.amount}`,
      enabled: true,
    };
    setRules((prev) => [...prev, newRule]);
    setShowForm(false);
    setForm({ from_account: ACCOUNT_OPTIONS[0], to_account: ACCOUNT_OPTIONS[1], trigger: "monthly", amount: "" });
    toast.success("Transfer rule added");
  }

  function toggleRule(id: string) {
    setRules((prev) => prev.map((r) => r.id === id ? { ...r, enabled: !r.enabled } : r));
  }

  function deleteRule(id: string) {
    setRules((prev) => prev.filter((r) => r.id !== id));
    toast("Rule removed");
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--text-tertiary)]">
          Automate recurring transfers between accounts to maximize tax efficiency.
        </p>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#3B82F6]/10 border border-[#3B82F6]/20 text-[#3B82F6] text-xs font-medium hover:bg-[#3B82F6]/15 transition-colors cursor-pointer"
        >
          <Plus size={13} /> Add Rule
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="bg-[var(--bg-elevated)] border border-[#3B82F6]/30 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-[var(--text-primary)]">New Transfer Rule</span>
            <button onClick={() => setShowForm(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] cursor-pointer"><X size={14} /></button>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] mb-1 block">From Account</label>
              <select
                value={form.from_account}
                onChange={(e) => setForm((f) => ({ ...f, from_account: e.target.value }))}
                className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#3B82F6]"
              >
                {ACCOUNT_OPTIONS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] mb-1 block">To Account</label>
              <select
                value={form.to_account}
                onChange={(e) => setForm((f) => ({ ...f, to_account: e.target.value }))}
                className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#3B82F6]"
              >
                {ACCOUNT_OPTIONS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] mb-1 block">Trigger</label>
              <select
                value={form.trigger}
                onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value as TransferRule["trigger"] }))}
                className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#3B82F6]"
              >
                {(Object.keys(TRIGGER_LABELS) as TransferRule["trigger"][]).map((k) => (
                  <option key={k} value={k}>{TRIGGER_LABELS[k]}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-tertiary)] mb-1 block">Amount</label>
              <input
                type="text"
                placeholder="$500"
                value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
          </div>

          <button
            onClick={addRule}
            className="w-full py-2 rounded-lg bg-[#3B82F6] text-white text-sm font-medium hover:bg-[#2563EB] transition-colors cursor-pointer"
          >
            Create Rule
          </button>
        </div>
      )}

      {/* Rules list */}
      {rules.length === 0 ? (
        <div className="py-8 text-center text-sm text-[var(--text-tertiary)]">No transfer rules yet. Add one to automate account funding.</div>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className={cn(
                "bg-[var(--bg-elevated)] border rounded-xl px-4 py-3 flex items-center gap-3 transition-opacity",
                rule.enabled ? "border-[var(--border-subtle)]" : "border-[var(--border-subtle)] opacity-50"
              )}
            >
              <ArrowRightLeft size={14} className="text-[var(--text-tertiary)] shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[var(--text-primary)] truncate">
                  {rule.amount} · {rule.from_account} <span className="text-[var(--text-tertiary)]">→</span> {rule.to_account}
                </div>
                <div className="text-[10px] text-[var(--text-tertiary)]">{TRIGGER_LABELS[rule.trigger]}</div>
              </div>
              <button
                onClick={() => toggleRule(rule.id)}
                className={cn(
                  "text-xs px-2 py-0.5 rounded-full border font-medium cursor-pointer transition-colors",
                  rule.enabled
                    ? "bg-emerald-400/10 border-emerald-400/20 text-emerald-400 hover:bg-emerald-400/15"
                    : "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                )}
              >
                {rule.enabled ? "On" : "Off"}
              </button>
              <button
                onClick={() => deleteRule(rule.id)}
                className="text-[var(--text-tertiary)] hover:text-red-400 transition-colors cursor-pointer"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

type Tab = "tlh" | "transfers";

export default function SmartTransfersPage() {
  const [activeTab, setActiveTab] = useState<Tab>("tlh");

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "tlh", label: "Tax-Loss Harvesting", icon: <TrendingDown size={13} /> },
    { key: "transfers", label: "Smart Transfers", icon: <ArrowRightLeft size={13} /> },
  ];

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <ArrowRightLeft size={20} className="text-[#3B82F6]" />
            Smart Transfers & TLH
          </h1>
          <p className="text-sm text-[var(--text-tertiary)] mt-0.5">
            Cross-account tax-loss harvesting and automated transfer rules
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-sm font-medium transition-colors cursor-pointer",
              activeTab === t.key
                ? "bg-[var(--bg-base)] text-[var(--text-primary)] shadow-sm"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {t.icon}
            <span className="hidden sm:inline">{t.label}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      {activeTab === "tlh" && <TLHPanel />}
      {activeTab === "transfers" && <TransferRulesPanel />}
    </div>
  );
}
