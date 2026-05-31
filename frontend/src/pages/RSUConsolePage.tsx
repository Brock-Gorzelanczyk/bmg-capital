import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  Layers,
  Plus,
  Trash2,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Calendar,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Info,
} from "lucide-react";
import { toast } from "sonner";

// ─── Types ────────────────────────────────────────────────────────────────────

interface RSUGrant {
  id: string;
  company: string;
  symbol: string;
  total_shares: number;
  vested_shares: number;
  grant_price: number;
  current_price: number | null;
  grant_date: string;
  vest_end_date: string;
  withholding_pct: number;
  sell_strategy: "sell_all" | "hold_all" | "cover_taxes";
}

type SellStrategy = RSUGrant["sell_strategy"];

const STRATEGY_LABELS: Record<SellStrategy, { label: string; desc: string }> = {
  sell_all: { label: "Sell All at Vest", desc: "Diversify immediately — no concentration risk." },
  hold_all: { label: "Hold All", desc: "Keep shares; concentrated position, higher upside." },
  cover_taxes: { label: "Sell to Cover Taxes", desc: "Sell only enough to pay withholding; hold the rest." },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(v: number | null, decimals = 2) {
  if (v == null) return "—";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

function fmtShares(n: number) {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function vestProgress(g: RSUGrant) {
  return g.total_shares > 0 ? (g.vested_shares / g.total_shares) * 100 : 0;
}

function unvestedValue(g: RSUGrant) {
  const unvested = g.total_shares - g.vested_shares;
  return g.current_price != null ? unvested * g.current_price : null;
}

function withholdingGap(g: RSUGrant) {
  // Supplemental wage withholding is 22% federal for RSUs < $1M, 37% above.
  // If current price >> grant price, actual tax rate is higher than withholding.
  if (!g.current_price) return null;
  const vestedValue = g.vested_shares * g.current_price;
  const effectiveTaxRate = vestedValue > 1_000_000 ? 0.37 : 0.22;
  const gap = (effectiveTaxRate - g.withholding_pct / 100) * vestedValue;
  return gap;
}

function strategyNetProceeds(g: RSUGrant, strategy: SellStrategy): number | null {
  if (!g.current_price) return null;
  const vestedValue = g.vested_shares * g.current_price;
  const taxOwed = vestedValue * (g.withholding_pct / 100);
  if (strategy === "sell_all") return vestedValue - taxOwed;
  if (strategy === "hold_all") return -taxOwed; // you owe taxes, no proceeds
  if (strategy === "cover_taxes") return 0; // proceeds exactly cover taxes
  return null;
}

// ─── Grant Card ───────────────────────────────────────────────────────────────

function GrantCard({ grant, onDelete }: { grant: RSUGrant; onDelete: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const progress = vestProgress(grant);
  const gap = withholdingGap(grant);
  const hasGap = gap != null && gap > 500;
  const unvested = unvestedValue(grant);
  const gain = grant.current_price != null ? grant.current_price - grant.grant_price : null;
  const gainPct = grant.grant_price > 0 && gain != null ? (gain / grant.grant_price) * 100 : null;

  return (
    <div className={cn(
      "bg-[var(--bg-elevated)] border rounded-xl overflow-hidden transition-all",
      hasGap ? "border-amber-400/30" : "border-[var(--border-subtle)]"
    )}>
      {/* Header row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-elevated-2)]/30 transition-colors cursor-pointer text-left"
      >
        <div className="w-9 h-9 rounded-lg bg-[var(--bg-elevated-2)] flex items-center justify-center shrink-0">
          <span className="text-[10px] font-bold font-mono text-[var(--text-secondary)]">{grant.symbol}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[var(--text-primary)] text-sm">{grant.company}</span>
            {hasGap && (
              <span className="text-[9px] bg-amber-400/10 border border-amber-400/20 text-amber-400 rounded-full px-1.5 py-0.5 flex items-center gap-1 shrink-0">
                <AlertTriangle size={8} /> Tax gap
              </span>
            )}
          </div>
          <div className="text-[10px] text-[var(--text-tertiary)]">
            {fmtShares(grant.vested_shares)} / {fmtShares(grant.total_shares)} shares vested · {STRATEGY_LABELS[grant.sell_strategy].label}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-sm font-mono font-bold text-[var(--text-primary)]">
            {unvested != null ? fmt(unvested, 0) : "—"}
          </div>
          <div className="text-[10px] text-[var(--text-tertiary)]">unvested value</div>
        </div>
        {expanded ? <ChevronUp size={14} className="text-[var(--text-tertiary)] shrink-0" /> : <ChevronDown size={14} className="text-[var(--text-tertiary)] shrink-0" />}
      </button>

      {/* Progress bar */}
      <div className="px-4 pb-3">
        <div className="w-full h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-[#3B82F6] to-emerald-400 rounded-full"
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-[9px] text-[var(--text-tertiary)]">{progress.toFixed(0)}% vested</span>
          <span className="text-[9px] text-[var(--text-tertiary)]">Ends {grant.vest_end_date}</span>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-[var(--border-subtle)] px-4 py-3 space-y-4">
          {/* Stats row */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Grant Price", value: fmt(grant.grant_price) },
              { label: "Current Price", value: grant.current_price != null ? fmt(grant.current_price) : "—" },
              {
                label: "Price Gain",
                value: gainPct != null ? `${gainPct >= 0 ? "+" : ""}${gainPct.toFixed(1)}%` : "—",
                color: gainPct != null ? (gainPct >= 0 ? "text-emerald-400" : "text-red-400") : "text-[var(--text-primary)]",
              },
            ].map((s) => (
              <div key={s.label} className="bg-[var(--bg-elevated-2)] rounded-lg p-2.5 text-center">
                <div className="text-[9px] text-[var(--text-tertiary)] mb-1">{s.label}</div>
                <div className={cn("font-mono font-bold text-sm", s.color ?? "text-[var(--text-primary)]")}>{s.value}</div>
              </div>
            ))}
          </div>

          {/* Withholding gap alert */}
          {hasGap && (
            <div className="flex gap-2 bg-amber-400/5 border border-amber-400/20 rounded-lg px-3 py-2.5 text-xs text-[var(--text-secondary)]">
              <AlertTriangle size={13} className="text-amber-400 shrink-0 mt-0.5" />
              <span>
                <strong className="text-amber-400">Withholding gap: ≈{fmt(gap, 0)}</strong> — your {grant.withholding_pct}% flat withholding
                may be less than your marginal rate. Set aside additional funds for tax season.
              </span>
            </div>
          )}

          {/* Sell strategy comparison */}
          <div>
            <p className="text-[10px] text-[var(--text-tertiary)] mb-2">Sell strategy comparison (vested shares)</p>
            <div className="space-y-1.5">
              {(["sell_all", "hold_all", "cover_taxes"] as SellStrategy[]).map((s) => {
                const net = strategyNetProceeds(grant, s);
                const isActive = grant.sell_strategy === s;
                return (
                  <div
                    key={s}
                    className={cn(
                      "flex items-center justify-between px-3 py-2 rounded-lg border text-xs",
                      isActive
                        ? "bg-[#3B82F6]/8 border-[#3B82F6]/25 text-[var(--text-primary)]"
                        : "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] text-[var(--text-tertiary)]"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      {isActive && <CheckCircle2 size={11} className="text-[#3B82F6]" />}
                      <div>
                        <div className="font-medium">{STRATEGY_LABELS[s].label}</div>
                        <div className="text-[9px] opacity-70">{STRATEGY_LABELS[s].desc}</div>
                      </div>
                    </div>
                    <div className="font-mono font-semibold text-right shrink-0">
                      {net != null ? (net >= 0 ? fmt(net, 0) : `-${fmt(Math.abs(net), 0)}`) : "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <button
            onClick={onDelete}
            className="flex items-center gap-1.5 text-[10px] text-red-400/70 hover:text-red-400 transition-colors cursor-pointer"
          >
            <Trash2 size={11} /> Remove grant
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Add Grant Form ───────────────────────────────────────────────────────────

interface AddGrantFormProps { onAdd: (g: RSUGrant) => void; onCancel: () => void }

function AddGrantForm({ onAdd, onCancel }: AddGrantFormProps) {
  const [form, setForm] = useState({
    company: "",
    symbol: "",
    total_shares: "",
    vested_shares: "",
    grant_price: "",
    current_price: "",
    grant_date: "",
    vest_end_date: "",
    withholding_pct: "22",
    sell_strategy: "sell_all" as SellStrategy,
  });

  function submit() {
    if (!form.company || !form.symbol || !form.total_shares || !form.grant_price) {
      toast.error("Fill in company, symbol, shares, and grant price");
      return;
    }
    onAdd({
      id: Date.now().toString(),
      company: form.company,
      symbol: form.symbol.toUpperCase(),
      total_shares: Number(form.total_shares),
      vested_shares: Number(form.vested_shares || 0),
      grant_price: Number(form.grant_price),
      current_price: form.current_price ? Number(form.current_price) : null,
      grant_date: form.grant_date,
      vest_end_date: form.vest_end_date,
      withholding_pct: Number(form.withholding_pct),
      sell_strategy: form.sell_strategy,
    });
  }

  const field = (label: string, key: keyof typeof form, type = "text", placeholder = "") => (
    <div>
      <label className="text-[10px] text-[var(--text-tertiary)] mb-1 block">{label}</label>
      <input
        type={type}
        placeholder={placeholder}
        value={form[key] as string}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#3B82F6]"
      />
    </div>
  );

  return (
    <div className="bg-[var(--bg-elevated)] border border-[#3B82F6]/30 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-[var(--text-primary)]">Add RSU Grant</span>
        <button onClick={onCancel} className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] cursor-pointer text-[10px]">Cancel</button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {field("Company Name", "company", "text", "Acme Corp")}
        {field("Ticker Symbol", "symbol", "text", "ACME")}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {field("Total Shares Granted", "total_shares", "number", "1000")}
        {field("Shares Vested So Far", "vested_shares", "number", "250")}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {field("Grant Price ($)", "grant_price", "number", "150.00")}
        {field("Current Price ($)", "current_price", "number", "195.00")}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {field("Grant Date", "grant_date", "date")}
        {field("Vest End Date", "vest_end_date", "date")}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {field("Withholding %", "withholding_pct", "number", "22")}
        <div>
          <label className="text-[10px] text-[var(--text-tertiary)] mb-1 block">Sell Strategy</label>
          <select
            value={form.sell_strategy}
            onChange={(e) => setForm((f) => ({ ...f, sell_strategy: e.target.value as SellStrategy }))}
            className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#3B82F6]"
          >
            {(Object.keys(STRATEGY_LABELS) as SellStrategy[]).map((k) => (
              <option key={k} value={k}>{STRATEGY_LABELS[k].label}</option>
            ))}
          </select>
        </div>
      </div>

      <button
        onClick={submit}
        className="w-full py-2 rounded-lg bg-[#3B82F6] text-white text-sm font-medium hover:bg-[#2563EB] transition-colors cursor-pointer"
      >
        Add Grant
      </button>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function RSUConsolePage() {
  const [grants, setGrants] = useState<RSUGrant[]>([
    {
      id: "demo1",
      company: "Example Corp",
      symbol: "EXPL",
      total_shares: 1000,
      vested_shares: 250,
      grant_price: 150,
      current_price: 210,
      grant_date: "2024-01-15",
      vest_end_date: "2028-01-15",
      withholding_pct: 22,
      sell_strategy: "sell_all",
    },
  ]);
  const [showForm, setShowForm] = useState(false);

  const totalUnvested = grants.reduce((a, g) => {
    const u = unvestedValue(g);
    return u != null ? a + u : a;
  }, 0);

  const grantsWithGap = grants.filter((g) => {
    const gap = withholdingGap(g);
    return gap != null && gap > 500;
  });

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <Layers size={20} className="text-[#3B82F6]" />
            RSU Console
          </h1>
          <p className="text-sm text-[var(--text-tertiary)] mt-0.5">
            Track RSU grants, vesting schedules, and tax withholding gaps
          </p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#3B82F6]/10 border border-[#3B82F6]/20 text-[#3B82F6] text-xs font-medium hover:bg-[#3B82F6]/15 transition-colors cursor-pointer shrink-0"
        >
          <Plus size={13} /> Add Grant
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Total Grants", value: String(grants.length), sub: "active" },
          { label: "Unvested Value", value: totalUnvested > 0 ? fmt(totalUnvested, 0) : "—", sub: "at current price" },
          { label: "Tax Gap Alerts", value: String(grantsWithGap.length), sub: grantsWithGap.length > 0 ? "review withholding" : "all clear", color: grantsWithGap.length > 0 ? "text-amber-400" : "text-emerald-400" },
        ].map((c) => (
          <div key={c.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-3 text-center">
            <div className="text-[10px] text-[var(--text-tertiary)] mb-1">{c.label}</div>
            <div className={cn("font-mono font-bold text-lg", c.color ?? "text-[var(--text-primary)]")}>{c.value}</div>
            <div className="text-[10px] text-[var(--text-tertiary)]">{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Info callout */}
      <div className="flex gap-2 bg-blue-500/5 border border-blue-500/20 rounded-lg px-3 py-2.5 text-xs text-[var(--text-secondary)]">
        <Info size={13} className="text-blue-400 shrink-0 mt-0.5" />
        <span>
          RSUs are taxed as ordinary income at vesting, not at grant. The flat 22% withholding often falls short of your marginal rate — especially if shares appreciated significantly. Build a reserve.
        </span>
      </div>

      {/* Add form */}
      {showForm && (
        <AddGrantForm
          onAdd={(g) => { setGrants((prev) => [...prev, g]); setShowForm(false); toast.success("Grant added"); }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Grant cards */}
      <div className="space-y-3">
        {grants.length === 0 ? (
          <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">
            No RSU grants yet. Add a grant to track vesting and tax exposure.
          </div>
        ) : (
          grants.map((g) => (
            <GrantCard
              key={g.id}
              grant={g}
              onDelete={() => {
                setGrants((prev) => prev.filter((x) => x.id !== g.id));
                toast("Grant removed");
              }}
            />
          ))
        )}
      </div>
    </div>
  );
}
