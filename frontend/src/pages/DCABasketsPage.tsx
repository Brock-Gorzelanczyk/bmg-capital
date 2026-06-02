import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  getBaskets,
  getTemplates,
  createBasket,
  deleteBasket,
  pauseBasket,
  resumeBasket,
  type DCABasket,
  type DCABasketAsset,
  type DCATemplate,
} from "@/api/dcaBaskets";

// ── Helpers ───────────────────────────────────────────────────────────────────

const ASSET_TYPE_COLORS: Record<string, string> = {
  crypto: "bg-purple-500/15 text-purple-400 border-purple-500/25",
  etf:    "bg-blue-500/15 text-blue-400 border-blue-500/25",
  stock:  "bg-amber-500/15 text-amber-400 border-amber-500/25",
};

function AssetPill({ asset }: { asset: DCABasketAsset }) {
  const color = ASSET_TYPE_COLORS[asset.asset_type] ?? ASSET_TYPE_COLORS.etf;
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${color}`}>
      {asset.symbol} {asset.allocation_pct}%
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
    paused: "bg-amber-500/15 text-amber-400 border-amber-500/25",
    cancelled: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
  };
  return (
    <span className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border ${colors[status] ?? colors.cancelled}`}>
      {status}
    </span>
  );
}

// ── CreateBasketModal ─────────────────────────────────────────────────────────

interface CreateBasketModalProps {
  onClose: () => void;
  onSuccess: () => void;
  prefill?: DCATemplate | null;
}

interface AssetRow {
  symbol: string;
  allocation_pct: string;
  asset_type: string;
}

function CreateBasketModal({ onClose, onSuccess, prefill }: CreateBasketModalProps) {
  const qc = useQueryClient();
  const [name, setName] = useState(prefill?.name ?? "");
  const [amount, setAmount] = useState(prefill ? String(prefill.total_amount) : "");
  const [frequency, setFrequency] = useState(prefill?.frequency ?? "weekly");
  const [assets, setAssets] = useState<AssetRow[]>(
    prefill
      ? prefill.assets.map(a => ({ symbol: a.symbol, allocation_pct: String(a.allocation_pct), asset_type: a.asset_type }))
      : [{ symbol: "", allocation_pct: "", asset_type: "etf" }]
  );

  const totalPct = assets.reduce((s, a) => s + (parseFloat(a.allocation_pct) || 0), 0);
  const pctValid = Math.abs(totalPct - 100) < 0.1;

  const mutation = useMutation({
    mutationFn: () =>
      createBasket({
        name,
        total_amount: parseFloat(amount),
        frequency,
        assets: assets.map(a => ({
          symbol: a.symbol.toUpperCase(),
          allocation_pct: parseFloat(a.allocation_pct),
          asset_type: a.asset_type,
        })),
      }),
    onSuccess: () => {
      toast.success("Basket created");
      qc.invalidateQueries({ queryKey: ["dca-baskets"] });
      onSuccess();
      onClose();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err?.response?.data?.detail ?? "Failed to create basket");
    },
  });

  const addAsset = () => setAssets(prev => [...prev, { symbol: "", allocation_pct: "", asset_type: "etf" }]);
  const removeAsset = (i: number) => setAssets(prev => prev.filter((_, idx) => idx !== i));
  const updateAsset = (i: number, key: keyof AssetRow, val: string) =>
    setAssets(prev => prev.map((a, idx) => idx === i ? { ...a, [key]: val } : a));

  const canSubmit = name && parseFloat(amount) > 0 && pctValid && assets.every(a => a.symbol);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 overflow-y-auto" onClick={onClose}>
      <div
        className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-6 w-full max-w-lg space-y-4 my-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-[var(--text-primary)]">Create DCA Basket</h2>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer text-xl leading-none">&times;</button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)] block mb-1">Basket Name</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Crypto Core"
              className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-xl px-3 py-2.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16] transition-colors"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)] block mb-1">Amount ($)</label>
              <input
                type="number"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder="100"
                className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-xl px-3 py-2.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16] transition-colors"
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)] block mb-1">Frequency</label>
              <select
                value={frequency}
                onChange={e => setFrequency(e.target.value)}
                className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-xl px-3 py-2.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16] transition-colors"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="biweekly">Biweekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">Assets</label>
              <span className={`text-xs font-bold ${pctValid ? "text-[#84cc16]" : "text-amber-400"}`}>
                {totalPct.toFixed(1)}% / 100%
              </span>
            </div>
            <div className="space-y-2">
              {assets.map((a, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <input
                    value={a.symbol}
                    onChange={e => updateAsset(i, "symbol", e.target.value)}
                    placeholder="BTC"
                    className="w-20 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-2 py-2 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16] uppercase"
                  />
                  <input
                    type="number"
                    value={a.allocation_pct}
                    onChange={e => updateAsset(i, "allocation_pct", e.target.value)}
                    placeholder="%"
                    className="w-16 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-2 py-2 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16]"
                  />
                  <select
                    value={a.asset_type}
                    onChange={e => updateAsset(i, "asset_type", e.target.value)}
                    className="flex-1 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-2 py-2 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16]"
                  >
                    <option value="etf">ETF</option>
                    <option value="stock">Stock</option>
                    <option value="crypto">Crypto</option>
                  </select>
                  {assets.length > 1 && (
                    <button
                      onClick={() => removeAsset(i)}
                      className="text-[var(--text-tertiary)] hover:text-red-400 cursor-pointer text-lg leading-none"
                    >
                      &times;
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              onClick={addAsset}
              className="mt-2 text-xs text-[#84cc16] hover:underline cursor-pointer"
            >
              + Add asset
            </button>
          </div>
        </div>

        <button
          disabled={!canSubmit || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="w-full py-3 rounded-xl font-bold text-sm bg-[#84cc16] text-black hover:bg-[#a3e635] disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
        >
          {mutation.isPending ? "Creating…" : "Create Basket"}
        </button>
      </div>
    </div>
  );
}

// ── TemplateCard ──────────────────────────────────────────────────────────────

function TemplateCard({ template, onUse }: { template: DCATemplate; onUse: (t: DCATemplate) => void }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 space-y-3 flex flex-col">
      <div className="flex items-start justify-between">
        <h3 className="font-bold text-[var(--text-primary)]">{template.name}</h3>
        <span className="text-xs text-[var(--text-tertiary)] capitalize">{template.frequency}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {template.assets.map(a => (
          <AssetPill key={a.symbol} asset={a} />
        ))}
      </div>
      <p className="text-sm text-[var(--text-secondary)]">
        ${template.total_amount} / {template.frequency}
      </p>
      <button
        onClick={() => onUse(template)}
        className="mt-auto w-full py-2 rounded-xl border border-[#84cc16] text-[#84cc16] text-sm font-semibold hover:bg-[#84cc16]/10 transition-colors cursor-pointer"
      >
        Use Template
      </button>
    </div>
  );
}

// ── BasketCard ────────────────────────────────────────────────────────────────

function BasketCard({
  basket,
  onPause,
  onResume,
  onDelete,
}: {
  basket: DCABasket;
  onPause: (id: number) => void;
  onResume: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 space-y-3">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-bold text-[var(--text-primary)]">{basket.name}</h3>
          <p className="text-xs text-[var(--text-tertiary)]">
            ${basket.total_amount} / {basket.frequency} &middot; {basket.executions_count} executions
          </p>
        </div>
        <StatusPill status={basket.status} />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {basket.assets.map(a => (
          <AssetPill key={a.symbol} asset={a} />
        ))}
      </div>
      <p className="text-sm text-[var(--text-secondary)]">
        Total invested: <span className="font-semibold text-[var(--text-primary)]">${basket.total_invested.toFixed(2)}</span>
      </p>
      <div className="flex gap-2 pt-1">
        {basket.status === "active" && (
          <button
            onClick={() => onPause(basket.id)}
            className="flex-1 py-2 rounded-lg border border-amber-500/30 text-amber-400 text-xs font-semibold hover:bg-amber-500/10 transition-colors cursor-pointer"
          >
            Pause
          </button>
        )}
        {basket.status === "paused" && (
          <button
            onClick={() => onResume(basket.id)}
            className="flex-1 py-2 rounded-lg border border-emerald-500/30 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/10 transition-colors cursor-pointer"
          >
            Resume
          </button>
        )}
        <button
          onClick={() => onDelete(basket.id)}
          className="flex-1 py-2 rounded-lg border border-red-500/30 text-red-400 text-xs font-semibold hover:bg-red-500/10 transition-colors cursor-pointer"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DCABasketsPage() {
  const [showCreate, setShowCreate] = useState(false);
  const [prefillTemplate, setPrefillTemplate] = useState<DCATemplate | null>(null);
  const qc = useQueryClient();

  const { data: baskets = [], isLoading: basketsLoading } = useQuery({
    queryKey: ["dca-baskets"],
    queryFn: getBaskets,
    staleTime: 30_000,
  });

  const { data: templates = [], isLoading: templatesLoading } = useQuery({
    queryKey: ["dca-templates"],
    queryFn: getTemplates,
    staleTime: 60_000,
  });

  const pauseMutation = useMutation({
    mutationFn: (id: number) => pauseBasket(id),
    onSuccess: () => { toast.success("Basket paused"); qc.invalidateQueries({ queryKey: ["dca-baskets"] }); },
    onError: () => toast.error("Failed to pause basket"),
  });

  const resumeMutation = useMutation({
    mutationFn: (id: number) => resumeBasket(id),
    onSuccess: () => { toast.success("Basket resumed"); qc.invalidateQueries({ queryKey: ["dca-baskets"] }); },
    onError: () => toast.error("Failed to resume basket"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteBasket(id),
    onSuccess: () => { toast.success("Basket deleted"); qc.invalidateQueries({ queryKey: ["dca-baskets"] }); },
    onError: () => toast.error("Failed to delete basket"),
  });

  const handleUseTemplate = (t: DCATemplate) => {
    setPrefillTemplate(t);
    setShowCreate(true);
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Automated Multi-Asset Investing</h1>
          <p className="text-sm text-[var(--text-tertiary)] mt-1">Set up recurring DCA baskets across crypto, ETFs, and stocks.</p>
        </div>
        <button
          onClick={() => { setPrefillTemplate(null); setShowCreate(true); }}
          className="px-4 py-2.5 rounded-xl bg-[#84cc16] text-black text-sm font-bold hover:bg-[#a3e635] transition-colors cursor-pointer shrink-0"
        >
          + Create Custom
        </button>
      </div>

      {/* Templates */}
      <div>
        <h2 className="text-base font-semibold text-[var(--text-primary)] mb-3">Templates</h2>
        {templatesLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => <div key={i} className="h-44 bg-[var(--bg-elevated)] rounded-2xl animate-pulse" />)}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {templates.map(t => (
              <TemplateCard key={t.name} template={t} onUse={handleUseTemplate} />
            ))}
          </div>
        )}
      </div>

      {/* My Baskets */}
      <div>
        <h2 className="text-base font-semibold text-[var(--text-primary)] mb-3">My Baskets</h2>
        {basketsLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[...Array(2)].map((_, i) => <div key={i} className="h-44 bg-[var(--bg-elevated)] rounded-2xl animate-pulse" />)}
          </div>
        ) : baskets.length === 0 ? (
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-8 text-center">
            <p className="text-[var(--text-tertiary)] text-sm">No baskets yet. Use a template or create a custom basket to get started.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {baskets.map((b: DCABasket) => (
              <BasketCard
                key={b.id}
                basket={b}
                onPause={id => pauseMutation.mutate(id)}
                onResume={id => resumeMutation.mutate(id)}
                onDelete={id => deleteMutation.mutate(id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <CreateBasketModal
          onClose={() => { setShowCreate(false); setPrefillTemplate(null); }}
          onSuccess={() => { setShowCreate(false); setPrefillTemplate(null); }}
          prefill={prefillTemplate}
        />
      )}
    </div>
  );
}
