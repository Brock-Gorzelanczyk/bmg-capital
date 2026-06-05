import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  Plus, Trash2, Edit2, TrendingUp, TrendingDown, X, Landmark,
} from "lucide-react";
import {
  getNWAccounts,
  createNWAccount,
  updateNWAccount,
  deleteNWAccount,
  getNWSummary,
  getNWHistory,
} from "@/api/networth";
import type { NWAccount, NWSnapshot } from "@/api/networth";
import { getStrategyLabPortfolio } from "@/api/bots";

// ── formatting helpers ───────────────────────────────────────────────────────

function fmtUSD(n: number, compact = false): string {
  if (compact && Math.abs(n) >= 1_000_000) {
    return "$" + (n / 1_000_000).toFixed(2) + "M";
  }
  if (compact && Math.abs(n) >= 1_000) {
    return "$" + (n / 1_000).toFixed(1) + "k";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtChange(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return sign + fmtUSD(n);
}

// ── account type config ───────────────────────────────────────────────────────

const ACCOUNT_TYPES = [
  { value: "checking", label: "Checking", icon: "🏦" },
  { value: "savings", label: "Savings", icon: "🏦" },
  { value: "brokerage", label: "Brokerage", icon: "📈" },
  { value: "retirement", label: "Retirement", icon: "🏖️" },
  { value: "crypto", label: "Crypto", icon: "₿" },
  { value: "real_estate", label: "Real Estate", icon: "🏠" },
  { value: "vehicle", label: "Vehicle", icon: "🚗" },
  { value: "credit_card", label: "Credit Card", icon: "💳" },
  { value: "student_loan", label: "Student Loan", icon: "🎓" },
  { value: "mortgage", label: "Mortgage", icon: "🏠" },
  { value: "auto_loan", label: "Auto Loan", icon: "🚗" },
  { value: "loan", label: "Loan", icon: "🎓" },
  { value: "other", label: "Other", icon: "💰" },
];

const LIABILITY_TYPES = new Set(["credit_card", "student_loan", "mortgage", "auto_loan", "loan"]);

function getTypeConfig(type: string) {
  return ACCOUNT_TYPES.find((t) => t.value === type) ?? { value: type, label: type, icon: "💰" };
}

// ── sparkline SVG ────────────────────────────────────────────────────────────

function Sparkline({ data }: { data: number[] }) {
  if (data.length < 2) {
    return (
      <div className="w-full h-20 flex items-center justify-center text-xs text-[var(--text-tertiary)]">
        Not enough data yet
      </div>
    );
  }

  const W = 1000;
  const H = 80;
  const PAD = 4;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const pts = data.map((v, i) => {
    const x = PAD + (i / (data.length - 1)) * (W - PAD * 2);
    const y = PAD + ((max - v) / range) * (H - PAD * 2);
    return `${x},${y}`;
  });

  const pathD = `M ${pts.join(" L ")}`;
  const firstY = parseFloat(pts[0].split(",")[1]);
  const lastY = parseFloat(pts[pts.length - 1].split(",")[1]);
  const fillD = `M ${pts[0]} L ${pts.join(" L ")} L ${W - PAD},${H} L ${PAD},${H} Z`;

  const positive = data[data.length - 1] >= data[0];
  const lineColor = positive ? "#14b8a6" : "#f87171";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20" preserveAspectRatio="none">
      <defs>
        <linearGradient id="nw-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={fillD} fill="url(#nw-fill)" />
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      {/* start dot */}
      <circle cx={parseFloat(pts[0].split(",")[0])} cy={firstY} r="4" fill={lineColor} />
      {/* end dot */}
      <circle cx={parseFloat(pts[pts.length - 1].split(",")[0])} cy={lastY} r="5" fill={lineColor} />
    </svg>
  );
}

// ── asset/liability bar ───────────────────────────────────────────────────────

function AssetBar({ assets, liabilities }: { assets: number; liabilities: number }) {
  const total = assets + liabilities || 1;
  const assetPct = Math.round((assets / total) * 100);
  const liabPct = 100 - assetPct;

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs text-[var(--text-tertiary)]">
        <span>Assets <span className="text-emerald-400 font-semibold">{fmtUSD(assets, true)}</span></span>
        <span>Liabilities <span className="text-red-400 font-semibold">{fmtUSD(liabilities, true)}</span></span>
      </div>
      <div className="flex h-3 w-full rounded-full overflow-hidden gap-0.5 bg-[var(--bg-elevated-2)]">
        {assetPct > 0 && (
          <div
            className="bg-emerald-500 h-full rounded-l-full transition-all duration-500"
            style={{ width: `${assetPct}%` }}
          />
        )}
        {liabPct > 0 && (
          <div
            className="bg-red-500 h-full rounded-r-full transition-all duration-500"
            style={{ width: `${liabPct}%` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
        <span>{assetPct}% assets</span>
        <span>{liabPct}% liabilities</span>
      </div>
    </div>
  );
}

// ── history line chart ────────────────────────────────────────────────────────

type TimeRange = "1M" | "3M" | "6M" | "1Y" | "All";

const TIME_RANGE_DAYS: Record<TimeRange, number | null> = {
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "1Y": 365,
  "All": null,
};

// Stable "now" for use in pure render calculations (captured once on mount)
const NOW_MS = Date.now();

function NWHistoryChart({ history }: { history: NWSnapshot[] }) {
  const [range, setRange] = useState<TimeRange>("1Y");

  const filtered = useMemo(() => {
    const days = TIME_RANGE_DAYS[range];
    if (!days) return history;
    const cutoff = new Date(NOW_MS - days * 86_400_000);
    return history.filter((s) => new Date(s.snapshot_date) >= cutoff);
  }, [history, range]);

  const hasData = filtered.length >= 2;

  const W = 1000;
  const H = 140;
  const PAD_X = 8;
  const PAD_Y = 12;

  const chartPts = useMemo(() => {
    if (!hasData) return [];
    const values = filtered.map((s) => s.net_worth);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const rangeV = max - min || 1;
    return filtered.map((s, i) => {
      const x = PAD_X + (i / (filtered.length - 1)) * (W - PAD_X * 2);
      const y = PAD_Y + ((max - s.net_worth) / rangeV) * (H - PAD_Y * 2);
      return { x, y, v: s.net_worth, date: s.snapshot_date };
    });
  }, [filtered, hasData]);

  const positive = hasData && filtered[filtered.length - 1].net_worth >= filtered[0].net_worth;
  const lineColor = positive ? "#34d399" : "#f87171";
  const pathD = hasData ? `M ${chartPts.map((p) => `${p.x},${p.y}`).join(" L ")}` : "";
  const fillD = hasData
    ? `M ${chartPts[0].x},${chartPts[0].y} L ${chartPts.map((p) => `${p.x},${p.y}`).join(" L ")} L ${chartPts[chartPts.length - 1].x},${H} L ${chartPts[0].x},${H} Z`
    : "";

  // X-axis labels: show first and last dates
  const labelFirst = filtered.length > 0 ? new Date(filtered[0].snapshot_date).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";
  const labelLast = filtered.length > 0 ? new Date(filtered[filtered.length - 1].snapshot_date).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide">Net Worth History</h3>
        <div className="flex gap-1">
          {(["1M", "3M", "6M", "1Y", "All"] as TimeRange[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={cn(
                "px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors cursor-pointer",
                range === r
                  ? "bg-[var(--accent-positive)]/20 text-emerald-400 border border-emerald-500/30"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)]"
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {!hasData ? (
        <div className="h-36 flex flex-col items-center justify-center text-center gap-2">
          <TrendingUp size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">Tracking net worth over time — check back soon</p>
          <p className="text-xs text-[var(--text-tertiary)]">A data point is saved each time you update your accounts</p>
        </div>
      ) : (
        <div>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-36" preserveAspectRatio="none">
            <defs>
              <linearGradient id="nwh-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity="0.2" />
                <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={fillD} fill="url(#nwh-fill)" />
            <path d={pathD} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {/* start/end dots */}
            <circle cx={chartPts[0].x} cy={chartPts[0].y} r="4" fill={lineColor} opacity="0.6" />
            <circle cx={chartPts[chartPts.length - 1].x} cy={chartPts[chartPts.length - 1].y} r="5" fill={lineColor} />
          </svg>
          <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-1 px-1">
            <span>{labelFirst}</span>
            <span className={cn("font-semibold text-xs", positive ? "text-emerald-400" : "text-red-400")}>
              {fmtUSD(filtered[filtered.length - 1].net_worth, true)}
            </span>
            <span>{labelLast}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── financial health metrics ──────────────────────────────────────────────────

interface HealthMetricsProps {
  totalAssets: number;
  totalLiabilities: number;
  bmgValueCents: number;
  onAddAccount: () => void;
  hasAccounts: boolean;
}

function HealthMetrics({ totalAssets, totalLiabilities, bmgValueCents, onAddAccount, hasAccounts }: HealthMetricsProps) {
  if (!hasAccounts) {
    return (
      <div className="bg-[var(--bg-elevated)] border border-dashed border-[var(--border-subtle)] rounded-2xl p-8 text-center space-y-3">
        <div className="text-3xl">💰</div>
        <p className="text-sm font-medium text-[var(--text-secondary)]">No accounts linked</p>
        <p className="text-xs text-[var(--text-tertiary)]">Connect your first account to track your net worth</p>
        <button
          onClick={onAddAccount}
          className="mt-1 inline-flex items-center gap-1.5 bg-[var(--accent-positive)] text-white text-sm font-semibold px-4 py-2 rounded-xl hover:opacity-90 transition-opacity cursor-pointer"
        >
          <Plus size={14} /> Add Account
        </button>
      </div>
    );
  }

  const investmentPct = totalAssets > 0
    ? Math.round(((totalAssets - totalLiabilities) / totalAssets) * 100)
    : 0;
  const debtToAsset = totalAssets > 0
    ? (totalLiabilities / totalAssets * 100).toFixed(1)
    : "0.0";
  const bmgValue = bmgValueCents / 100;
  const bmgPct = totalAssets > 0
    ? Math.round((bmgValue / totalAssets) * 100)
    : 0;

  const metrics = [
    {
      icon: "💰",
      label: "Investment %",
      value: `${investmentPct}%`,
      sub: "Net equity vs total assets",
      color: investmentPct >= 60 ? "text-emerald-400" : investmentPct >= 30 ? "text-amber-400" : "text-red-400",
    },
    {
      icon: "💳",
      label: "Debt-to-Asset",
      value: `${debtToAsset}%`,
      sub: "Total liabilities ÷ total assets",
      color: parseFloat(debtToAsset) <= 30 ? "text-emerald-400" : parseFloat(debtToAsset) <= 60 ? "text-amber-400" : "text-red-400",
    },
    {
      icon: "🎯",
      label: "BMG Portfolio %",
      value: `${bmgPct}%`,
      sub: "Strategy Lab value vs total assets",
      color: "text-[var(--text-primary)]",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {metrics.map((m) => (
        <div key={m.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xl">{m.icon}</span>
            <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide">{m.label}</span>
          </div>
          <p className={cn("text-2xl font-bold", m.color)}>{m.value}</p>
          <p className="text-[11px] text-[var(--text-tertiary)]">{m.sub}</p>
        </div>
      ))}
    </div>
  );
}

// ── add/edit modal ────────────────────────────────────────────────────────────

interface ModalProps {
  initial?: NWAccount | null;
  onClose: () => void;
  onSave: (data: Omit<NWAccount, "id" | "last_updated">) => void;
  saving: boolean;
}

function AccountModal({ initial, onClose, onSave, saving }: ModalProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [accountType, setAccountType] = useState(initial?.account_type ?? "checking");
  const [institution, setInstitution] = useState(initial?.institution ?? "");
  const [balance, setBalance] = useState(initial?.balance?.toString() ?? "");
  const [isLiability, setIsLiability] = useState(initial?.is_liability ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");

  function handleTypeChange(type: string) {
    setAccountType(type);
    if (LIABILITY_TYPES.has(type)) setIsLiability(true);
    else if (!initial?.is_liability) setIsLiability(false);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) { toast.error("Account name is required"); return; }
    const bal = parseFloat(balance);
    if (isNaN(bal) || bal < 0) { toast.error("Balance must be a positive number"); return; }
    onSave({
      name: name.trim(),
      account_type: accountType,
      institution: institution.trim(),
      balance: bal,
      is_liability: isLiability,
      currency: initial?.currency ?? "USD",
      notes: notes.trim(),
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl p-6 space-y-4">
        {/* header */}
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-[var(--text-primary)]">
            {initial ? "Edit Account" : "Add Account"}
          </h2>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Account name */}
          <div>
            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Account Name *</label>
            <input
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder-zinc-600 focus:outline-none focus:border-[var(--accent-positive)]"
              placeholder="e.g. Chase Checking"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {/* Account type */}
          <div>
            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Account Type *</label>
            <select
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={accountType}
              onChange={(e) => handleTypeChange(e.target.value)}
            >
              {ACCOUNT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.icon} {t.label}</option>
              ))}
            </select>
          </div>

          {/* Institution */}
          <div>
            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Institution (optional)</label>
            <input
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder-zinc-600 focus:outline-none focus:border-[var(--accent-positive)]"
              placeholder="e.g. Fidelity"
              value={institution}
              onChange={(e) => setInstitution(e.target.value)}
            />
          </div>

          {/* Balance */}
          <div>
            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Balance ($) *</label>
            <input
              type="number"
              min="0"
              step="0.01"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder-zinc-600 focus:outline-none focus:border-[var(--accent-positive)]"
              placeholder="0.00"
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
            />
          </div>

          {/* Is Liability toggle */}
          <div className="flex items-center justify-between py-1">
            <div>
              <p className="text-sm text-[var(--text-secondary)]">Is this a liability?</p>
              <p className="text-[11px] text-[var(--text-tertiary)]">Debt, loan, or credit balance you owe</p>
            </div>
            <button
              type="button"
              onClick={() => setIsLiability((v) => !v)}
              className={cn(
                "relative w-10 h-5.5 rounded-full transition-colors duration-200 flex-shrink-0 cursor-pointer",
                isLiability ? "bg-red-500" : "bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)]"
              )}
              style={{ height: "22px", width: "40px" }}
            >
              <span
                className={cn(
                  "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200",
                  isLiability ? "translate-x-5" : "translate-x-0.5"
                )}
              />
            </button>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Notes (optional)</label>
            <textarea
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder-zinc-600 focus:outline-none focus:border-[var(--accent-positive)] resize-none"
              placeholder="Any additional notes…"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          <button
            type="submit"
            disabled={saving}
            className="w-full bg-[var(--accent-positive)] hover:opacity-90 disabled:opacity-50 text-white font-semibold text-sm py-2.5 rounded-xl transition-opacity cursor-pointer"
          >
            {saving ? "Saving…" : initial ? "Save Changes" : "Add Account"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function NetWorthPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editTarget, setEditTarget] = useState<NWAccount | null>(null);

  const { data: accountsData, isLoading: loadingAccounts } = useQuery({
    queryKey: ["nw-accounts"],
    queryFn: getNWAccounts,
    staleTime: 30_000,
  });

  const { data: summary, isLoading: loadingSummary } = useQuery({
    queryKey: ["nw-summary"],
    queryFn: getNWSummary,
    staleTime: 30_000,
  });

  const { data: historyData } = useQuery({
    queryKey: ["nw-history"],
    queryFn: getNWHistory,
    staleTime: 60_000,
    retry: 0,
  });

  const { data: strategyPortfolio } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 60_000,
    retry: 0,
  });

  const accounts = accountsData?.accounts ?? [];
  const history = useMemo(() => historyData?.history ?? [], [historyData]);

  // Last 90 days of data for sparkline
  const sparkData = useMemo(() => {
    const cutoff = new Date(NOW_MS - 90 * 86_400_000);
    return history
      .filter((s) => new Date(s.snapshot_date) >= cutoff)
      .map((s) => s.net_worth);
  }, [history]);

  // Invalidate after any mutation
  function invalidate() {
    qc.invalidateQueries({ queryKey: ["nw-accounts"] });
    qc.invalidateQueries({ queryKey: ["nw-summary"] });
    qc.invalidateQueries({ queryKey: ["nw-history"] });
  }

  const createMut = useMutation({
    mutationFn: createNWAccount,
    onSuccess: () => { toast.success("Account added"); setShowModal(false); invalidate(); },
    onError: () => toast.error("Failed to add account"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<NWAccount> }) =>
      updateNWAccount(id, body),
    onSuccess: () => { toast.success("Account updated"); setEditTarget(null); invalidate(); },
    onError: () => toast.error("Failed to update account"),
  });

  const deleteMut = useMutation({
    mutationFn: deleteNWAccount,
    onSuccess: () => { toast.success("Account removed"); invalidate(); },
    onError: () => toast.error("Failed to delete account"),
  });

  function handleSave(data: Omit<NWAccount, "id" | "last_updated">) {
    if (editTarget) {
      updateMut.mutate({ id: editTarget.id, body: data });
    } else {
      createNWAccount(data).then(() => {
        toast.success("Account added");
        setShowModal(false);
        invalidate();
      }).catch(() => toast.error("Failed to add account"));
    }
  }

  function openEdit(a: NWAccount) {
    setEditTarget(a);
    setShowModal(true);
  }

  function handleClose() {
    setShowModal(false);
    setEditTarget(null);
  }

  const nw = summary?.net_worth ?? 0;
  const isPositive = nw >= 0;
  const change30d = summary?.change_30d ?? null;

  const loading = loadingAccounts || loadingSummary;

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-5">

      {/* ── Hero row ─────────────────────────────────────────────────────────── */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Landmark size={16} className="text-[var(--text-tertiary)]" />
              <span className="text-xs text-[var(--text-tertiary)] font-medium uppercase tracking-wide">Net Worth</span>
            </div>
            <div className={cn(
              "text-4xl md:text-5xl font-bold tracking-tight",
              isPositive ? "text-emerald-400" : "text-red-400"
            )}>
              {loading ? "—" : fmtUSD(nw)}
            </div>
            <p className="text-xs text-[var(--text-tertiary)] mt-1">As of today</p>
          </div>

          <div className="flex flex-col items-end gap-2">
            {change30d !== null && (
              <div className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold",
                change30d >= 0
                  ? "bg-emerald-500/15 text-emerald-400"
                  : "bg-red-500/15 text-red-400"
              )}>
                {change30d >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                {fmtChange(change30d)} (30d)
              </div>
            )}
            <button
              onClick={() => { setEditTarget(null); setShowModal(true); }}
              className="flex items-center gap-1.5 bg-[var(--accent-positive)] hover:opacity-90 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-opacity cursor-pointer"
            >
              <Plus size={15} />
              Add Account
            </button>
          </div>
        </div>

        {/* Sparkline */}
        <div className="mt-4">
          <Sparkline data={sparkData} />
        </div>
      </div>

      {/* ── Asset / Liability split bar ───────────────────────────────────────── */}
      {summary && (summary.total_assets > 0 || summary.total_liabilities > 0) && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
          <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide mb-3">Asset / Liability Split</h3>
          <AssetBar assets={summary.total_assets} liabilities={summary.total_liabilities} />
        </div>
      )}

      {/* ── By-category grid ──────────────────────────────────────────────────── */}
      {summary && Object.keys(summary.by_category).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide mb-3 px-1">By Category</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {Object.entries(summary.by_category).map(([type, vals]) => {
              const cfg = getTypeConfig(type);
              const net = vals.assets - vals.liabilities;
              const isLiab = vals.liabilities > vals.assets;
              return (
                <div
                  key={type}
                  className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{cfg.icon}</span>
                    <span className="text-xs font-medium text-[var(--text-secondary)] truncate">{cfg.label}</span>
                  </div>
                  <div className={cn(
                    "text-base font-bold",
                    isLiab ? "text-red-400" : "text-[var(--text-primary)]"
                  )}>
                    {fmtUSD(Math.abs(net), true)}
                  </div>
                  {vals.liabilities > 0 && (
                    <p className="text-[10px] text-red-400">−{fmtUSD(vals.liabilities, true)} owed</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Accounts list ─────────────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3 px-1">
          <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide">Accounts ({accounts.length})</h3>
        </div>

        {loading && accounts.length === 0 ? (
          <div className="text-sm text-[var(--text-tertiary)] py-8 text-center">Loading…</div>
        ) : accounts.length === 0 ? (
          <div className="bg-[var(--bg-elevated)] border border-dashed border-[var(--border-subtle)] rounded-2xl p-10 text-center space-y-3">
            <div className="text-4xl">🏦</div>
            <p className="text-sm font-medium text-[var(--text-secondary)]">No accounts yet</p>
            <p className="text-xs text-[var(--text-tertiary)]">Add your first account to start tracking your net worth.</p>
            <button
              onClick={() => { setEditTarget(null); setShowModal(true); }}
              className="mt-2 flex items-center gap-1.5 bg-[var(--accent-positive)] text-white text-sm font-semibold px-4 py-2 rounded-xl mx-auto cursor-pointer hover:opacity-90 transition-opacity"
            >
              <Plus size={14} /> Add Account
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {accounts.map((a) => {
              const cfg = getTypeConfig(a.account_type);
              return (
                <div
                  key={a.id}
                  className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex items-center gap-3"
                >
                  <span className="text-xl shrink-0">{cfg.icon}</span>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-[var(--text-primary)] truncate">{a.name}</span>
                      <span className="text-[10px] bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-tertiary)] px-1.5 py-0.5 rounded-md font-mono uppercase">
                        {cfg.label}
                      </span>
                      {a.is_liability && (
                        <span className="text-[10px] bg-red-500/10 border border-red-500/20 text-red-400 px-1.5 py-0.5 rounded-md">
                          liability
                        </span>
                      )}
                    </div>
                    {a.institution && (
                      <p className="text-xs text-[var(--text-tertiary)] truncate mt-0.5">{a.institution}</p>
                    )}
                  </div>

                  <div className="text-right shrink-0">
                    <p className={cn(
                      "text-sm font-semibold",
                      a.is_liability ? "text-red-400" : "text-[var(--text-primary)]"
                    )}>
                      {a.is_liability ? "−" : ""}{fmtUSD(a.balance)}
                    </p>
                    {a.last_updated && (
                      <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5">
                        {new Date(a.last_updated).toLocaleDateString()}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => openEdit(a)}
                      className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] transition-colors cursor-pointer"
                    >
                      <Edit2 size={14} />
                    </button>
                    <button
                      onClick={() => {
                        if (window.confirm(`Delete "${a.name}"?`)) deleteMut.mutate(a.id);
                      }}
                      className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── History chart ─────────────────────────────────────────────────────── */}
      <NWHistoryChart history={history} />

      {/* ── Financial health metrics ──────────────────────────────────────────── */}
      <div>
        <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wide mb-3 px-1">Financial Health</h3>
        <HealthMetrics
          totalAssets={summary?.total_assets ?? 0}
          totalLiabilities={summary?.total_liabilities ?? 0}
          bmgValueCents={strategyPortfolio?.total_value_cents ?? 0}
          onAddAccount={() => { setEditTarget(null); setShowModal(true); }}
          hasAccounts={accounts.length > 0}
        />
      </div>

      {/* ── Add/Edit modal ────────────────────────────────────────────────────── */}
      {showModal && (
        <AccountModal
          initial={editTarget}
          onClose={handleClose}
          onSave={handleSave}
          saving={createMut.isPending || updateMut.isPending}
        />
      )}
    </div>
  );
}
