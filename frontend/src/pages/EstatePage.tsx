import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  ScrollText, Plus, Trash2, CheckCircle2, XCircle, AlertTriangle, ShieldAlert,
  KeyRound, X, ChevronDown, ChevronUp,
} from "lucide-react";
import {
  listBeneficiaries,
  createBeneficiary,
  updateBeneficiary,
  deleteBeneficiary,
  getEstateHealthCheck,
  listDigitalAssets,
  createDigitalAsset,
  deleteDigitalAsset,
} from "@/api/estate";
import type { BeneficiaryRecord, DigitalAssetRecord } from "@/api/estate";

// ── constants ─────────────────────────────────────────────────────────────────

const ACCOUNT_TYPES = [
  { value: "retirement", label: "Retirement" },
  { value: "brokerage", label: "Brokerage" },
  { value: "bank", label: "Bank" },
  { value: "life_insurance", label: "Life Insurance" },
];

const RELATIONSHIPS = [
  { value: "spouse", label: "Spouse" },
  { value: "child", label: "Child" },
  { value: "sibling", label: "Sibling" },
  { value: "parent", label: "Parent" },
  { value: "other", label: "Other" },
];

const DIGITAL_ASSET_TYPES = [
  { value: "crypto_wallet", label: "Crypto Wallet" },
  { value: "password_manager", label: "Password Manager" },
  { value: "email", label: "Email Account" },
  { value: "social", label: "Social Media" },
  { value: "other", label: "Other" },
];

// ── helpers ───────────────────────────────────────────────────────────────────

function accountTypeLabel(v: string | null) {
  return ACCOUNT_TYPES.find((t) => t.value === v)?.label ?? v ?? "—";
}

function digitalTypeLabel(v: string | null) {
  return DIGITAL_ASSET_TYPES.find((t) => t.value === v)?.label ?? v ?? "—";
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function isStale(lastReviewed: string | null): boolean {
  if (!lastReviewed) return true;
  try {
    const ms = Date.now() - new Date(lastReviewed).getTime();
    return ms > 730 * 24 * 60 * 60 * 1000;
  } catch {
    return true;
  }
}

// ── Estate Health Score ───────────────────────────────────────────────────────

function computeScore(
  beneficiaries: BeneficiaryRecord[],
  digitalAssets: DigitalAssetRecord[],
  issues: string[],
): number {
  let score = 0;

  // +20: at least 1 beneficiary record
  if (beneficiaries.length > 0) score += 20;

  // +30: all accounts have TOD/POD
  const allTodPod =
    beneficiaries.length > 0 &&
    beneficiaries.every((r) => r.has_tod || r.has_pod);
  if (allTodPod) score += 30;

  // +20: all reviewed within 2 years
  const allReviewed =
    beneficiaries.length > 0 && beneficiaries.every((r) => !isStale(r.last_reviewed));
  if (allReviewed) score += 20;

  // +15: digital assets documented
  if (digitalAssets.length > 0) score += 15;

  // +15: no pct issues
  const hasPctIssue = issues.some((i) => i.includes("percentages sum to"));
  if (beneficiaries.length > 0 && !hasPctIssue) score += 15;

  return Math.min(score, 100);
}

function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-400";
  if (score >= 50) return "text-amber-400";
  return "text-red-400";
}

function scoreBg(score: number) {
  if (score >= 80) return "bg-emerald-400";
  if (score >= 50) return "bg-amber-400";
  return "bg-red-400";
}

function scoreLabel(score: number) {
  if (score >= 80) return "Good";
  if (score >= 50) return "Needs Attention";
  return "At Risk";
}

// ── blank form shapes ─────────────────────────────────────────────────────────

type BeneficiaryForm = Omit<BeneficiaryRecord, "id" | "created_at">;
type DigitalAssetForm = Omit<DigitalAssetRecord, "id" | "created_at">;

const BLANK_BENEFICIARY: BeneficiaryForm = {
  account_name: "",
  account_type: "brokerage",
  beneficiary_name: "",
  beneficiary_relationship: "spouse",
  beneficiary_pct: 100,
  has_tod: false,
  has_pod: false,
  last_reviewed: "",
  notes: "",
};

const BLANK_DIGITAL: DigitalAssetForm = {
  asset_type: "crypto_wallet",
  description: "",
  location_hint: "",
  recovery_contact: "",
};

// ── BeneficiaryModal ─────────────────────────────────────────────────────────

interface BeneficiaryModalProps {
  initial?: BeneficiaryRecord | null;
  onClose: () => void;
  onSave: (form: BeneficiaryForm) => void;
  saving: boolean;
}

function BeneficiaryModal({ initial, onClose, onSave, saving }: BeneficiaryModalProps) {
  const [form, setForm] = useState<BeneficiaryForm>(
    initial
      ? {
          account_name: initial.account_name,
          account_type: initial.account_type,
          beneficiary_name: initial.beneficiary_name,
          beneficiary_relationship: initial.beneficiary_relationship,
          beneficiary_pct: initial.beneficiary_pct,
          has_tod: initial.has_tod,
          has_pod: initial.has_pod,
          last_reviewed: initial.last_reviewed,
          notes: initial.notes,
        }
      : { ...BLANK_BENEFICIARY }
  );

  function set<K extends keyof BeneficiaryForm>(key: K, val: BeneficiaryForm[K]) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
          <h2 className="text-[var(--text-primary)] font-semibold text-base">
            {initial ? "Edit Account" : "Add Beneficiary Account"}
          </h2>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Account Name *</label>
            <input
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={form.account_name}
              onChange={(e) => set("account_name", e.target.value)}
              placeholder="e.g. Fidelity 401k"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Account Type</label>
              <select
                className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)] cursor-pointer"
                value={form.account_type ?? ""}
                onChange={(e) => set("account_type", e.target.value)}
              >
                {ACCOUNT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Beneficiary %</label>
              <input
                type="number"
                min={1}
                max={100}
                className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
                value={form.beneficiary_pct}
                onChange={(e) => set("beneficiary_pct", Number(e.target.value))}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Beneficiary Name</label>
              <input
                className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
                value={form.beneficiary_name ?? ""}
                onChange={(e) => set("beneficiary_name", e.target.value)}
                placeholder="Full name"
              />
            </div>
            <div>
              <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Relationship</label>
              <select
                className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)] cursor-pointer"
                value={form.beneficiary_relationship ?? ""}
                onChange={(e) => set("beneficiary_relationship", e.target.value)}
              >
                {RELATIONSHIPS.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.has_tod}
                onChange={(e) => set("has_tod", e.target.checked)}
                className="accent-[var(--accent-positive)] w-4 h-4"
              />
              <span className="text-sm text-[var(--text-secondary)]">TOD Designation</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.has_pod}
                onChange={(e) => set("has_pod", e.target.checked)}
                className="accent-[var(--accent-positive)] w-4 h-4"
              />
              <span className="text-sm text-[var(--text-secondary)]">POD Designation</span>
            </label>
          </div>

          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Last Reviewed (date)</label>
            <input
              type="date"
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={form.last_reviewed ?? ""}
              onChange={(e) => set("last_reviewed", e.target.value || null)}
            />
          </div>

          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Notes</label>
            <textarea
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)] resize-none"
              rows={2}
              value={form.notes ?? ""}
              onChange={(e) => set("notes", e.target.value || null)}
              placeholder="Optional notes"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-[var(--border-subtle)] flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] rounded-lg transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={!form.account_name.trim() || saving}
            className="px-4 py-2 text-sm font-semibold bg-[var(--accent-positive)] text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity cursor-pointer"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── DigitalAssetModal ─────────────────────────────────────────────────────────

interface DigitalAssetModalProps {
  onClose: () => void;
  onSave: (form: DigitalAssetForm) => void;
  saving: boolean;
}

function DigitalAssetModal({ onClose, onSave, saving }: DigitalAssetModalProps) {
  const [form, setForm] = useState<DigitalAssetForm>({ ...BLANK_DIGITAL });

  function set<K extends keyof DigitalAssetForm>(key: K, val: DigitalAssetForm[K]) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
          <h2 className="text-[var(--text-primary)] font-semibold text-base">Add Digital Asset</h2>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-4 py-3">
            <p className="text-xs text-amber-400">
              Never store private keys, seed phrases, or passwords here. Only store location hints and recovery contacts.
            </p>
          </div>

          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Asset Type</label>
            <select
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)] cursor-pointer"
              value={form.asset_type ?? ""}
              onChange={(e) => set("asset_type", e.target.value)}
            >
              {DIGITAL_ASSET_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Description</label>
            <input
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={form.description ?? ""}
              onChange={(e) => set("description", e.target.value || null)}
              placeholder="e.g. Ledger hardware wallet — BTC and ETH"
            />
          </div>

          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Location Hint</label>
            <input
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={form.location_hint ?? ""}
              onChange={(e) => set("location_hint", e.target.value || null)}
              placeholder="e.g. Safe in home office — do not store actual keys here"
            />
          </div>

          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">Recovery Contact</label>
            <input
              className="w-full bg-[var(--bg-base)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={form.recovery_contact ?? ""}
              onChange={(e) => set("recovery_contact", e.target.value || null)}
              placeholder="Name or email of person who can assist"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-[var(--border-subtle)] flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] rounded-lg transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={saving}
            className="px-4 py-2 text-sm font-semibold bg-[var(--accent-positive)] text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity cursor-pointer"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function EstatePage() {
  const qc = useQueryClient();

  const { data: beneficiaryData } = useQuery({
    queryKey: ["estate-beneficiaries"],
    queryFn: listBeneficiaries,
  });

  const { data: digitalData } = useQuery({
    queryKey: ["estate-digital-assets"],
    queryFn: listDigitalAssets,
  });

  const { data: healthData } = useQuery({
    queryKey: ["estate-health"],
    queryFn: getEstateHealthCheck,
  });

  const beneficiaries = beneficiaryData?.beneficiaries ?? [];
  const digitalAssets = digitalData?.digital_assets ?? [];
  const issues = healthData?.issues ?? [];
  const score = computeScore(beneficiaries, digitalAssets, issues);

  // Modal state
  const [showBeneficiaryModal, setShowBeneficiaryModal] = useState(false);
  const [editingBeneficiary, setEditingBeneficiary] = useState<BeneficiaryRecord | null>(null);
  const [showDigitalModal, setShowDigitalModal] = useState(false);
  const [healthExpanded, setHealthExpanded] = useState(true);

  // Mutations
  const createBeneficiaryMutation = useMutation({
    mutationFn: createBeneficiary,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["estate-beneficiaries"] });
      qc.invalidateQueries({ queryKey: ["estate-health"] });
      setShowBeneficiaryModal(false);
      toast.success("Account added");
    },
    onError: () => toast.error("Failed to add account"),
  });

  const updateBeneficiaryMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<Omit<BeneficiaryRecord, "id" | "created_at">> }) =>
      updateBeneficiary(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["estate-beneficiaries"] });
      qc.invalidateQueries({ queryKey: ["estate-health"] });
      setEditingBeneficiary(null);
      toast.success("Account updated");
    },
    onError: () => toast.error("Failed to update account"),
  });

  const deleteBeneficiaryMutation = useMutation({
    mutationFn: deleteBeneficiary,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["estate-beneficiaries"] });
      qc.invalidateQueries({ queryKey: ["estate-health"] });
      toast.success("Account removed");
    },
    onError: () => toast.error("Failed to remove account"),
  });

  const createDigitalMutation = useMutation({
    mutationFn: createDigitalAsset,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["estate-digital-assets"] });
      qc.invalidateQueries({ queryKey: ["estate-health"] });
      setShowDigitalModal(false);
      toast.success("Digital asset added");
    },
    onError: () => toast.error("Failed to add digital asset"),
  });

  const deleteDigitalMutation = useMutation({
    mutationFn: deleteDigitalAsset,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["estate-digital-assets"] });
      qc.invalidateQueries({ queryKey: ["estate-health"] });
      toast.success("Digital asset removed");
    },
    onError: () => toast.error("Failed to remove digital asset"),
  });

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)] pb-16">
      {/* Legal disclaimer banner */}
      <div className="bg-amber-500/10 border-b border-amber-500/20 px-4 py-3">
        <div className="max-w-5xl mx-auto flex items-start gap-3">
          <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-300 leading-relaxed">
            <strong className="font-semibold">Legal disclaimer:</strong> This is for organizational purposes only — not legal advice. Consult an estate attorney for legally binding documents.
          </p>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-600 to-indigo-600 flex items-center justify-center">
            <ScrollText size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">Beneficiary Vault</h1>
            <p className="text-sm text-[var(--text-tertiary)]">Estate lite — organize your accounts and digital assets</p>
          </div>
        </div>

        {/* Health Score Card */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Estate Health Score</h2>
            <span className={cn("text-xs font-bold px-2 py-1 rounded-full", scoreColor(score),
              score >= 80 ? "bg-emerald-400/10" : score >= 50 ? "bg-amber-400/10" : "bg-red-400/10"
            )}>
              {scoreLabel(score)}
            </span>
          </div>
          <div className="flex items-end gap-4 mb-4">
            <span className={cn("text-5xl font-extrabold tabular-nums", scoreColor(score))}>{score}</span>
            <span className="text-[var(--text-tertiary)] text-lg mb-1">/100</span>
          </div>
          {/* Progress bar */}
          <div className="h-2 bg-[var(--bg-base)] rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all duration-500", scoreBg(score))}
              style={{ width: `${score}%` }}
            />
          </div>
          {/* Score breakdown */}
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
            {[
              { label: "Has beneficiary records", points: 20, met: beneficiaries.length > 0 },
              { label: "All accounts have TOD/POD", points: 30, met: beneficiaries.length > 0 && beneficiaries.every((r) => r.has_tod || r.has_pod) },
              { label: "All reviewed within 2 years", points: 20, met: beneficiaries.length > 0 && beneficiaries.every((r) => !isStale(r.last_reviewed)) },
              { label: "Digital assets documented", points: 15, met: digitalAssets.length > 0 },
              { label: "Beneficiary % totals 100%", points: 15, met: beneficiaries.length > 0 && !issues.some((i) => i.includes("percentages sum to")) },
            ].map((item) => (
              <div key={item.label} className={cn(
                "flex items-start gap-1.5 p-2 rounded-lg",
                item.met ? "bg-emerald-400/5" : "bg-[var(--bg-base)]"
              )}>
                {item.met
                  ? <CheckCircle2 size={13} className="text-emerald-400 shrink-0 mt-0.5" />
                  : <XCircle size={13} className="text-[var(--text-tertiary)] shrink-0 mt-0.5" />}
                <div>
                  <span className={item.met ? "text-emerald-400" : "text-[var(--text-tertiary)]"}>{item.label}</span>
                  <span className="block text-[10px] text-[var(--text-tertiary)]">+{item.points} pts</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Beneficiary Accounts */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
            <h2 className="font-semibold text-[var(--text-primary)]">Beneficiary Accounts</h2>
            <button
              onClick={() => setShowBeneficiaryModal(true)}
              className="flex items-center gap-1.5 text-xs font-semibold text-[var(--accent-positive)] hover:opacity-80 transition-opacity cursor-pointer"
            >
              <Plus size={14} />
              Add Account
            </button>
          </div>

          {beneficiaries.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <ScrollText size={32} className="text-[var(--text-tertiary)] mx-auto mb-3 opacity-40" />
              <p className="text-[var(--text-tertiary)] text-sm">No accounts yet. Add your first beneficiary account.</p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {beneficiaries.map((r) => {
                const missingDesignation = !r.has_tod && !r.has_pod;
                const stale = isStale(r.last_reviewed);
                return (
                  <div key={r.id} className="px-6 py-4 hover:bg-[var(--bg-elevated-2)] transition-colors group">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-[var(--text-primary)] text-sm">{r.account_name}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--bg-base)] text-[var(--text-tertiary)] border border-[var(--border-subtle)]">
                            {accountTypeLabel(r.account_type)}
                          </span>
                          {missingDesignation && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 flex items-center gap-1">
                              <ShieldAlert size={10} />
                              Missing TOD/POD
                            </span>
                          )}
                          {stale && !missingDesignation && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                              Review needed
                            </span>
                          )}
                        </div>
                        <div className="mt-1.5 flex items-center gap-4 text-xs text-[var(--text-tertiary)]">
                          {r.beneficiary_name && (
                            <span>{r.beneficiary_name} ({r.beneficiary_relationship ?? "—"}) · {r.beneficiary_pct}%</span>
                          )}
                          <span className="flex items-center gap-1">
                            TOD: {r.has_tod
                              ? <CheckCircle2 size={11} className="text-emerald-400" />
                              : <XCircle size={11} className="text-red-400" />}
                          </span>
                          <span className="flex items-center gap-1">
                            POD: {r.has_pod
                              ? <CheckCircle2 size={11} className="text-emerald-400" />
                              : <XCircle size={11} className="text-red-400" />}
                          </span>
                          <span>Reviewed: {formatDate(r.last_reviewed)}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                        <button
                          onClick={() => setEditingBeneficiary(r)}
                          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-base)] transition-colors cursor-pointer"
                          title="Edit"
                        >
                          <ScrollText size={13} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Remove "${r.account_name}"?`)) {
                              deleteBeneficiaryMutation.mutate(r.id);
                            }
                          }}
                          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-red-400 hover:bg-red-400/10 transition-colors cursor-pointer"
                          title="Delete"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Digital Asset Inventory */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
            <h2 className="font-semibold text-[var(--text-primary)]">Digital Asset Inventory</h2>
            <button
              onClick={() => setShowDigitalModal(true)}
              className="flex items-center gap-1.5 text-xs font-semibold text-[var(--accent-positive)] hover:opacity-80 transition-opacity cursor-pointer"
            >
              <Plus size={14} />
              Add Digital Asset
            </button>
          </div>

          <div className="px-6 py-3 bg-[var(--bg-base)] border-b border-[var(--border-subtle)]">
            <p className="text-xs text-[var(--text-tertiary)]">
              These records help your executor locate and transfer digital assets.{" "}
              <strong className="text-amber-400">Never store private keys here.</strong>
            </p>
          </div>

          {digitalAssets.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <KeyRound size={32} className="text-[var(--text-tertiary)] mx-auto mb-3 opacity-40" />
              <p className="text-[var(--text-tertiary)] text-sm">No digital assets documented yet.</p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {digitalAssets.map((r) => (
                <div key={r.id} className="px-6 py-4 hover:bg-[var(--bg-elevated-2)] transition-colors group">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--bg-base)] text-[var(--text-tertiary)] border border-[var(--border-subtle)]">
                          {digitalTypeLabel(r.asset_type)}
                        </span>
                        <span className="text-sm text-[var(--text-primary)] font-medium">{r.description || "—"}</span>
                      </div>
                      <div className="mt-1.5 flex items-center gap-4 text-xs text-[var(--text-tertiary)]">
                        {r.location_hint && <span>Location: {r.location_hint}</span>}
                        {r.recovery_contact && <span>Contact: {r.recovery_contact}</span>}
                      </div>
                    </div>
                    <button
                      onClick={() => {
                        if (confirm("Remove this digital asset record?")) {
                          deleteDigitalMutation.mutate(r.id);
                        }
                      }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-red-400 hover:bg-red-400/10 cursor-pointer"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Estate Health Check — action items */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <button
            onClick={() => setHealthExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-6 py-4 hover:bg-[var(--bg-elevated-2)] transition-colors cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <ShieldAlert size={16} className={issues.length > 0 ? "text-amber-400" : "text-emerald-400"} />
              <h2 className="font-semibold text-[var(--text-primary)]">Action Items</h2>
              {issues.length > 0 && (
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-amber-400/10 text-amber-400 font-semibold">
                  {issues.length}
                </span>
              )}
            </div>
            {healthExpanded ? <ChevronUp size={16} className="text-[var(--text-tertiary)]" /> : <ChevronDown size={16} className="text-[var(--text-tertiary)]" />}
          </button>

          {healthExpanded && (
            <div className="border-t border-[var(--border-subtle)]">
              {issues.length === 0 ? (
                <div className="px-6 py-8 text-center">
                  <CheckCircle2 size={28} className="text-emerald-400 mx-auto mb-2" />
                  <p className="text-sm text-emerald-400 font-medium">No issues detected</p>
                  <p className="text-xs text-[var(--text-tertiary)] mt-1">Your estate records look complete.</p>
                </div>
              ) : (
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {issues.map((issue, i) => (
                    <li key={i} className="flex items-start gap-3 px-6 py-3">
                      <AlertTriangle size={14} className="text-amber-400 shrink-0 mt-0.5" />
                      <span className="text-sm text-[var(--text-secondary)]">{issue}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      {showBeneficiaryModal && (
        <BeneficiaryModal
          initial={null}
          onClose={() => setShowBeneficiaryModal(false)}
          onSave={(form) => createBeneficiaryMutation.mutate(form)}
          saving={createBeneficiaryMutation.isPending}
        />
      )}

      {editingBeneficiary && (
        <BeneficiaryModal
          initial={editingBeneficiary}
          onClose={() => setEditingBeneficiary(null)}
          onSave={(form) => updateBeneficiaryMutation.mutate({ id: editingBeneficiary.id, body: form })}
          saving={updateBeneficiaryMutation.isPending}
        />
      )}

      {showDigitalModal && (
        <DigitalAssetModal
          onClose={() => setShowDigitalModal(false)}
          onSave={(form) => createDigitalMutation.mutate(form)}
          saving={createDigitalMutation.isPending}
        />
      )}
    </div>
  );
}
