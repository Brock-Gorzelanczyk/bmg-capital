import { useState, useRef } from "react";
import { useParams, Navigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/store/authStore";
import { cn } from "@/lib/utils";
import { BracketFrame, SectionLabel, GlowInput, BMGButton, BMGCard } from "@/components/design";
import {
  getBotConfig, getBotWatchlist, getBotAudit,
  patchBotConfig, deleteBotConfig,
  enableBot, disableBot, pauseBot, resumeBot,
  addWatchlistSymbol, removeWatchlistSymbol,
} from "@/api/adminBots";

const ADMIN_EMAIL = "32bgorzelanczyk@gmail.com";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUsd(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function getDeepValue(obj: Record<string, unknown>, key: string): unknown {
  const parts = key.split(".");
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}

// ── Confirm dialog ────────────────────────────────────────────────────────────

function ConfirmDialog({
  message, onConfirm, onCancel,
}: { message: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <BracketFrame className="bg-[var(--bmg-bg-card)] border border-[var(--bmg-green-border)] rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl" glow>
        <SectionLabel as="p" className="mb-3">Confirm Action</SectionLabel>
        <p className="text-sm text-[var(--bmg-text)] mb-5">{message}</p>
        <div className="flex gap-3 justify-end">
          <BMGButton variant="secondary" size="sm" onClick={onCancel}>Cancel</BMGButton>
          <BMGButton variant="destructive" size="sm" onClick={onConfirm}>Confirm</BMGButton>
        </div>
      </BracketFrame>
    </div>
  );
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <BMGCard padding="md">
      <SectionLabel as="h2" className="mb-4">{title}</SectionLabel>
      {children}
    </BMGCard>
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = (text: string) => {
    setMsg(text);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setMsg(null), 3000);
  };

  const Toast = msg ? (
    <div className="fixed bottom-6 right-6 z-50 bg-[var(--bmg-bg-card)] border border-[var(--bmg-green-border)] text-sm text-[var(--bmg-text)] px-4 py-2.5 rounded-lg shadow-xl">
      {msg}
    </div>
  ) : null;

  return { show, Toast };
}

// ── Section 1: Position Sizing ────────────────────────────────────────────────

function SizingSection({
  botId, config, botCapital, onSaved,
}: { botId: string; config: Record<string, unknown>; botCapital: number; onSaved: () => void }) {
  const risk = (config.risk as Record<string, unknown>) ?? {};
  const [vals, setVals] = useState({
    deployment_target_pct:  Number(risk.deployment_target_pct ?? 0.5),
    target_position_count:  Number(risk.target_position_count ?? 20),
    max_position_pct:       Number(risk.max_position_pct ?? 0.05),
    max_total_deployed_pct: Number(risk.max_total_deployed_pct ?? 0.8),
  });
  const [dirty, setDirty] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const { show, Toast } = useToast();

  const orig = {
    deployment_target_pct:  Number(risk.deployment_target_pct ?? 0.5),
    target_position_count:  Number(risk.target_position_count ?? 20),
    max_position_pct:       Number(risk.max_position_pct ?? 0.05),
    max_total_deployed_pct: Number(risk.max_total_deployed_pct ?? 0.8),
  };

  const update = (k: keyof typeof vals, raw: string) => {
    const v = k === "target_position_count" ? parseInt(raw) : parseFloat(raw);
    const next = { ...vals, [k]: isNaN(v) ? vals[k] : v };
    setVals(next);
    setDirty(JSON.stringify(next) !== JSON.stringify(orig));
  };

  const qc = useQueryClient();
  const { mutateAsync: patch, isPending } = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      patchBotConfig(botId, key, value),
  });
  const { mutateAsync: del } = useMutation({
    mutationFn: (key: string) => deleteBotConfig(botId, key),
  });

  const handleSave = async () => {
    if (vals.deployment_target_pct > 0.80 || vals.max_position_pct > 0.20) {
      setConfirm(true);
      return;
    }
    await doSave();
  };

  const doSave = async () => {
    setConfirm(false);
    try {
      await patch({ key: "risk.deployment_target_pct",  value: vals.deployment_target_pct });
      await patch({ key: "risk.target_position_count",  value: vals.target_position_count });
      await patch({ key: "risk.max_position_pct",       value: vals.max_position_pct });
      await patch({ key: "risk.max_total_deployed_pct", value: vals.max_total_deployed_pct });
      qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] });
      setDirty(false);
      show("Position sizing saved");
      onSaved();
    } catch (e: any) {
      show(`Error: ${e?.response?.data?.detail ?? e.message}`);
    }
  };

  const handleReset = async () => {
    try {
      await del("risk.deployment_target_pct");
      await del("risk.target_position_count");
      await del("risk.max_position_pct");
      await del("risk.max_total_deployed_pct");
      qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] });
      show("Reset to YAML defaults");
      onSaved();
    } catch {
      show("Reset failed — some keys may not have overrides");
    }
  };

  const perTrade = botCapital > 0
    ? Math.min(
        (botCapital * vals.deployment_target_pct) / Math.max(1, vals.target_position_count),
        botCapital * vals.max_position_pct,
      )
    : 0;
  const totalTarget   = botCapital * vals.deployment_target_pct;
  const hardCapSingle = botCapital * vals.max_position_pct;
  const hardCapTotal  = botCapital * vals.max_total_deployed_pct;

  const fields: { key: keyof typeof vals; label: string; tip: string; step: string; min: string; max: string; pct?: boolean }[] = [
    { key: "deployment_target_pct",  label: "Deployment target %",     tip: "What % of bot capital to target deploying",      step: "0.01", min: "0", max: "1",    pct: true },
    { key: "target_position_count",  label: "Target position count",   tip: "Spread deployment across N positions",            step: "1",    min: "1", max: "100" },
    { key: "max_position_pct",       label: "Max position % (cap)",    tip: "Hard cap — no single position larger than this",  step: "0.01", min: "0", max: "1",    pct: true },
    { key: "max_total_deployed_pct", label: "Max total deployed % (cap)", tip: "Hard cap — total deployment never exceeds this", step: "0.01", min: "0", max: "1", pct: true },
  ];

  return (
    <Section title="Position Sizing">
      {confirm && (
        <ConfirmDialog
          message={`Deployment target ${(vals.deployment_target_pct * 100).toFixed(0)}% or max position ${(vals.max_position_pct * 100).toFixed(0)}% is high. Confirm?`}
          onConfirm={doSave}
          onCancel={() => setConfirm(false)}
        />
      )}
      {Toast}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
        {fields.map(f => (
          <div key={f.key}>
            <label className="block text-xs text-[var(--bmg-text-muted)] mb-1 group">
              {f.label}
              <span className="ml-1 text-[var(--bmg-text-label)] cursor-help" title={f.tip}>(?)</span>
            </label>
            <div className="flex items-center gap-2">
              <GlowInput
                type="number"
                step={f.step} min={f.min} max={f.max}
                value={f.pct ? (vals[f.key] as number * 100).toFixed(1) : vals[f.key]}
                onChange={e => {
                  const raw = f.pct ? String(parseFloat(e.target.value) / 100) : e.target.value;
                  update(f.key, raw);
                }}
                className="tabular-nums"
              />
              {f.pct && <span className="text-xs text-[var(--bmg-text-muted)]">%</span>}
            </div>
          </div>
        ))}
      </div>

      {/* Live preview */}
      {botCapital > 0 && (
        <div className="bg-[var(--bmg-bg-input)] border border-[var(--bmg-green-border)]/50 rounded-lg p-3 mb-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
          {[
            ["Per-trade target", fmtUsd(perTrade)],
            ["Total deployment target", fmtUsd(totalTarget)],
            ["Hard cap / trade", fmtUsd(hardCapSingle)],
            ["Hard cap / total", fmtUsd(hardCapTotal)],
          ].map(([label, val]) => (
            <div key={label as string}>
              <p className="text-[10px] text-[var(--bmg-text-label)] uppercase tracking-wide font-mono">{label}</p>
              <p className="text-sm font-semibold text-[var(--bmg-text)] tabular-nums font-mono">{val}</p>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <BMGButton variant="secondary" size="sm" onClick={handleReset}>
          Reset to YAML
        </BMGButton>
        <BMGButton
          variant="primary" size="sm"
          onClick={handleSave}
          disabled={!dirty || isPending}
          loading={isPending}
        >
          {isPending ? "Saving…" : "Save changes"}
        </BMGButton>
      </div>
    </Section>
  );
}

// ── Section 2: Confidence Threshold ──────────────────────────────────────────

function ConfidenceSection({ botId, config, onSaved }: { botId: string; config: Record<string, unknown>; onSaved: () => void }) {
  const yaml = Number(config.confidence_threshold ?? 0.5);
  const [val, setVal] = useState(yaml);
  const [dirty, setDirty] = useState(false);
  const { show, Toast } = useToast();

  const qc = useQueryClient();
  const { mutateAsync: patch, isPending } = useMutation({
    mutationFn: (v: number) => patchBotConfig(botId, "confidence_threshold", v),
  });
  const { mutateAsync: del } = useMutation({
    mutationFn: () => deleteBotConfig(botId, "confidence_threshold"),
  });

  return (
    <Section title="Confidence Threshold">
      {Toast}
      <div className="flex items-end gap-4 mb-4">
        <div>
          <label className="block text-xs text-[var(--bmg-text-muted)] mb-1">
            Global threshold
            <span className="ml-1 text-[var(--bmg-text-label)] cursor-help" title="Minimum model confidence to emit a signal. Higher = fewer but more reliable signals.">(?)</span>
          </label>
          <div className="flex items-center gap-2">
            <GlowInput
              type="number" step="0.01" min="0" max="1"
              value={(val * 100).toFixed(1)}
              onChange={e => {
                const v = parseFloat(e.target.value) / 100;
                setVal(isNaN(v) ? val : v);
                setDirty(Math.abs((isNaN(v) ? val : v) - yaml) > 0.001);
              }}
              className="w-28 tabular-nums"
            />
            <span className="text-xs text-[var(--bmg-text-muted)]">%</span>
          </div>
          <p className="text-xs text-[var(--bmg-text-label)] font-mono mt-1">YAML default: {(yaml * 100).toFixed(1)}%</p>
        </div>
      </div>
      <div className="flex gap-2">
        <BMGButton
          variant="secondary" size="sm"
          onClick={async () => {
            try { await del(); qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] }); show("Reset to YAML"); onSaved(); }
            catch { show("No override to reset"); }
          }}
        >
          Reset to YAML
        </BMGButton>
        <BMGButton
          variant="primary" size="sm"
          onClick={async () => {
            try { await patch(val); qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] }); setDirty(false); show("Threshold saved"); onSaved(); }
            catch (e: any) { show(`Error: ${e?.response?.data?.detail ?? e.message}`); }
          }}
          disabled={!dirty || isPending}
          loading={isPending}
        >
          {isPending ? "Saving…" : "Save"}
        </BMGButton>
      </div>
    </Section>
  );
}

// ── Section 3: Watchlist ──────────────────────────────────────────────────────

function WatchlistSection({ botId }: { botId: string }) {
  const [input, setInput] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const { show, Toast } = useToast();

  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["admin-bot-watchlist", botId],
    queryFn: () => getBotWatchlist(botId),
  });
  const { mutateAsync: add, isPending: adding } = useMutation({
    mutationFn: (sym: string) => addWatchlistSymbol(botId, sym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-bot-watchlist", botId] }),
  });
  const { mutateAsync: remove } = useMutation({
    mutationFn: (sym: string) => removeWatchlistSymbol(botId, sym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-bot-watchlist", botId] }),
  });

  const handleAdd = async () => {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    try {
      await add(sym);
      setInput("");
      show(`${sym} added`);
    } catch (e: any) {
      show(`Error: ${e?.response?.data?.detail ?? e.message}`);
    }
  };

  return (
    <Section title="Watchlist">
      {Toast}
      {confirm && (
        <ConfirmDialog
          message={`Remove ${confirm} from watchlist?`}
          onConfirm={async () => { await remove(confirm); setConfirm(null); show(`${confirm} removed`); }}
          onCancel={() => setConfirm(null)}
        />
      )}

      <div className="flex flex-wrap gap-2 mb-4 min-h-8">
        {(data?.symbols ?? []).map(sym => (
          <span
            key={sym}
            className="inline-flex items-center gap-1 px-2.5 py-1 bg-[var(--bmg-bg-input)] border border-[var(--bmg-green-border)] rounded-full text-xs text-[var(--bmg-text)]"
          >
            {sym}
            <button
              onClick={() => setConfirm(sym)}
              className="text-zinc-500 hover:text-red-400 transition-colors ml-0.5 leading-none"
              title={`Remove ${sym}`}
            >
              ×
            </button>
          </span>
        ))}
        {!data && <span className="text-xs text-[var(--bmg-text-label)]">Loading…</span>}
        {data?.symbols.length === 0 && <span className="text-xs text-[var(--bmg-text-label)]">No symbols in watchlist</span>}
      </div>

      <div className="flex gap-3 items-end">
        <div className="w-44">
          <GlowInput
            type="text"
            value={input}
            onChange={e => setInput(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === "Enter" && handleAdd()}
            placeholder="BTC/USD or AAPL"
          />
        </div>
        <BMGButton
          variant="primary"
          size="sm"
          onClick={handleAdd}
          disabled={adding || !input.trim()}
        >
          Add
        </BMGButton>
      </div>
    </Section>
  );
}

// ── Section 4: Cooldown ───────────────────────────────────────────────────────

function CooldownSection({ botId, config, onSaved }: { botId: string; config: Record<string, unknown>; onSaved: () => void }) {
  const yaml = Number(config.cooldown_minutes ?? 0);
  const [val, setVal] = useState(yaml);
  const [dirty, setDirty] = useState(false);
  const { show, Toast } = useToast();

  const qc = useQueryClient();
  const { mutateAsync: patch, isPending } = useMutation({
    mutationFn: (v: number) => patchBotConfig(botId, "cooldown_minutes", v),
  });
  const { mutateAsync: del } = useMutation({
    mutationFn: () => deleteBotConfig(botId, "cooldown_minutes"),
  });

  return (
    <Section title="Cooldown">
      {Toast}
      <div className="flex items-end gap-4 mb-4">
        <div>
          <label className="block text-xs text-[var(--bmg-text-muted)] mb-1">
            Cooldown minutes
            <span className="ml-1 text-[var(--bmg-text-label)] cursor-help" title="Minimum time between signals on the same (symbol, side). 0 = no cooldown.">(?)</span>
          </label>
          <div className="flex items-center gap-2">
            <GlowInput
              type="number" step="1" min="0" max="1440"
              value={val}
              onChange={e => {
                const v = parseInt(e.target.value);
                setVal(isNaN(v) ? val : v);
                setDirty((isNaN(v) ? val : v) !== yaml);
              }}
              className="w-28 tabular-nums"
            />
            <span className="text-xs text-[var(--bmg-text-muted)]">min</span>
          </div>
          <p className="text-xs text-[var(--bmg-text-label)] font-mono mt-1">YAML default: {yaml} min</p>
        </div>
      </div>
      <div className="flex gap-2">
        <BMGButton
          variant="secondary" size="sm"
          onClick={async () => {
            try { await del(); qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] }); show("Reset to YAML"); onSaved(); }
            catch { show("No override to reset"); }
          }}
        >
          Reset to YAML
        </BMGButton>
        <BMGButton
          variant="primary" size="sm"
          onClick={async () => {
            try { await patch(val); qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] }); setDirty(false); show("Cooldown saved"); onSaved(); }
            catch (e: any) { show(`Error: ${e?.response?.data?.detail ?? e.message}`); }
          }}
          disabled={!dirty || isPending}
          loading={isPending}
        >
          {isPending ? "Saving…" : "Save"}
        </BMGButton>
      </div>
    </Section>
  );
}

// ── Audit log ─────────────────────────────────────────────────────────────────

function AuditLog({ botId }: { botId: string }) {
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ["admin-bot-audit", botId],
    queryFn: () => getBotAudit(botId),
    enabled: open,
  });

  return (
    <div className="bg-[var(--bmg-bg-card)] border border-[var(--bmg-green-border)] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-xs font-mono font-semibold text-[var(--bmg-text-muted)] hover:text-[var(--bmg-text)] transition-colors"
      >
        <SectionLabel>Audit Log</SectionLabel>
        <span className="text-[var(--bmg-text-label)]">{open ? "▲ collapse" : "▼ expand"}</span>
      </button>

      {open && (
        <div className="border-t border-[var(--bmg-green-border)]/40 divide-y divide-[var(--bmg-green-border)]/20">
          {!data && <p className="px-5 py-3 text-xs text-[var(--bmg-text-label)]">Loading…</p>}
          {data?.entries.length === 0 && <p className="px-5 py-3 text-xs text-[var(--bmg-text-label)]">No changes recorded yet.</p>}
          {data?.entries.map(e => (
            <div key={e.id} className="px-5 py-2.5 flex items-start gap-3 text-xs font-mono">
              <span className="text-[var(--bmg-text-label)] whitespace-nowrap">{timeAgo(e.changed_at)}</span>
              <span className="text-[var(--bmg-green)]">{e.key}</span>
              <span className="text-[var(--bmg-text-muted)]">
                {e.old_value !== null && e.old_value !== undefined
                  ? `${JSON.stringify(e.old_value)} → `
                  : ""}
                {e.new_value !== null ? (
                  <span className="text-[var(--bmg-text)]">{JSON.stringify(e.new_value)}</span>
                ) : (
                  <span className="text-[var(--bmg-red)]">deleted</span>
                )}
              </span>
              <span className="ml-auto text-[var(--bmg-text-label)] flex-shrink-0">{e.changed_by}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminBotDetailPage() {
  const { user } = useAuthStore();
  const { botId } = useParams<{ botId: string }>();
  const qc = useQueryClient();

  if ((user as any)?.email !== ADMIN_EMAIL) return <Navigate to="/strategy" replace />;
  if (!botId) return <Navigate to="/admin" replace />;

  const { data: configData, isLoading, isError } = useQuery({
    queryKey: ["admin-bot-config", botId],
    queryFn: () => getBotConfig(botId),
    staleTime: 10_000,
  });

  const { show: showToast, Toast } = useToast();
  const [confirm, setConfirm] = useState<null | "disable">(null);

  const { mutateAsync: doEnable }  = useMutation({ mutationFn: () => enableBot(botId),  onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-bots"] }) });
  const { mutateAsync: doDisable } = useMutation({ mutationFn: () => disableBot(botId), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-bots"] }) });
  const { mutateAsync: doPause }   = useMutation({ mutationFn: () => pauseBot(botId),   onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-bots"] }) });
  const { mutateAsync: doResume }  = useMutation({ mutationFn: () => resumeBot(botId),  onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-bots"] }) });

  const cfg = configData?.config ?? {};
  const overrides = configData?.overrides ?? [];

  const enabledOverride = overrides.find(o => o.key === "enabled");
  const pausedOverride  = overrides.find(o => o.key === "paused");
  const isEnabled = enabledOverride ? Boolean(enabledOverride.value) : true;
  const isPaused  = pausedOverride  ? Boolean(pausedOverride.value)  : false;

  const lastChange = overrides.length > 0
    ? overrides.reduce((a, b) => a.updated_at > b.updated_at ? a : b)
    : null;

  const label = botId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

  const cap = ((): number => {
    const risk = cfg.risk as Record<string, unknown> | undefined;
    return Number(cfg.starting_capital_cents ?? (risk ? undefined : 5_000_000)) / 100;
  })();

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-4">
      {Toast}
      {confirm === "disable" && (
        <ConfirmDialog
          message={`Disable ${label}? It will stop scanning and signalling.`}
          onConfirm={async () => { setConfirm(null); await doDisable(); showToast("Bot disabled"); }}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* Breadcrumb */}
      <Link to="/admin" className="text-xs font-mono text-[var(--bmg-text-label)] hover:text-[var(--bmg-text-muted)] transition-colors">
        ← All bots
      </Link>

      {/* Header */}
      <BracketFrame className="bg-[var(--bmg-bg-card)] border border-[var(--bmg-green-border)] rounded-xl p-5" glow>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <SectionLabel as="h1" className="text-base mb-1">{label}</SectionLabel>
            {lastChange && (
              <p className="text-xs text-[var(--bmg-text-muted)] mt-0.5">
                Last change {timeAgo(lastChange.updated_at)} by {lastChange.updated_by}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {!isEnabled
              ? <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">DISABLED</span>
              : isPaused
              ? <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">PAUSED</span>
              : <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-[var(--bmg-green-dim)] text-[var(--bmg-green)] border border-[var(--bmg-green-border)]">ACTIVE</span>
            }
          </div>
        </div>

        <div className="flex gap-2 mt-4 flex-wrap">
          {isPaused ? (
            <BMGButton variant="primary" size="sm" onClick={async () => { await doResume(); showToast("Bot resumed"); }}>
              Resume
            </BMGButton>
          ) : (
            <BMGButton variant="secondary" size="sm" onClick={async () => { await doPause(); showToast("Bot paused"); }}>
              Pause
            </BMGButton>
          )}

          {isEnabled ? (
            <BMGButton variant="destructive" size="sm" onClick={() => setConfirm("disable")}>
              Disable
            </BMGButton>
          ) : (
            <BMGButton variant="primary" size="sm" onClick={async () => { await doEnable(); showToast("Bot enabled"); }}>
              Enable
            </BMGButton>
          )}

          {overrides.length > 0 && (
            <span className="text-xs text-[var(--bmg-text-muted)] self-center font-mono">{overrides.length} override{overrides.length !== 1 ? "s" : ""} active</span>
          )}
        </div>
      </BracketFrame>

      {isLoading && (
        <div className="space-y-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-[var(--bmg-bg-card)] border border-[var(--bmg-green-border)] rounded-xl h-32 animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
          Failed to load config. Backend may be restarting.
        </p>
      )}

      {configData && (
        <>
          <SizingSection
            botId={botId} config={cfg} botCapital={cap}
            onSaved={() => qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] })}
          />
          <ConfidenceSection
            botId={botId} config={cfg}
            onSaved={() => qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] })}
          />
          <WatchlistSection botId={botId} />
          <CooldownSection
            botId={botId} config={cfg}
            onSaved={() => qc.invalidateQueries({ queryKey: ["admin-bot-config", botId] })}
          />
          <AuditLog botId={botId} />
        </>
      )}
    </div>
  );
}
