import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BracketFrame, SectionLabel, BMGCard, BMGButton, GlowInput } from "@/components/design";
import SignalExplainButton from "@/components/explain/SignalExplainButton";
import {
  getCatalog,
  evaluate,
  scanTicker,
  getSetups,
  createSetup,
  deleteSetup,
  getSignals,
  type EvaluateResult,
  type ScoutSetup,
} from "@/api/scout";

// ── Helpers ───────────────────────────────────────────────────────────────────

function qualityColor(q: number) {
  if (q >= 70) return "var(--bmg-green)";
  if (q >= 45) return "#f59e0b";
  return "var(--bmg-red)";
}

function sideColor(side: string) {
  if (side === "buy" || side === "cover") return "var(--bmg-green)";
  if (side === "sell" || side === "short") return "var(--bmg-red)";
  return "var(--bmg-text-muted)";
}

function setupStatusColor(status: string) {
  if (status === "fired") return "var(--bmg-green)";
  if (status === "active") {
    return "#f59e0b";
  }
  return "var(--bmg-text-muted)";
}

function setupStatusLabel(setup: ScoutSetup) {
  if (setup.status === "fired") return "FIRED";
  if (setup.last_confidence !== null && setup.last_confidence !== undefined) {
    const pct = setup.last_confidence * 100;
    if (pct >= 70) return "ARMED";
    if (pct >= 45) return "CLOSE";
    return "COLD";
  }
  return "PENDING";
}

function fmtPrice(v: number | null | undefined) {
  if (v == null) return "—";
  if (v >= 1000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (v >= 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(6)}`;
}

function fmtTs(ts: string | null) {
  if (!ts) return "—";
  const d = new Date(ts);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return d.toLocaleDateString();
}

// ── QualityBar ─────────────────────────────────────────────────────────────────

function QualityBar({ value }: { value: number }) {
  const color = qualityColor(value);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${value}%`, backgroundColor: color }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

// ── EvalResultCard ─────────────────────────────────────────────────────────────

function EvalResultCard({
  result,
  ticker,
  onApply,
  applying,
}: {
  result: EvaluateResult;
  ticker: string;
  onApply: () => void;
  applying: boolean;
}) {
  const canApply = result.setup_quality >= 50;
  const sideLabel =
    result.side === "buy" ? "LONG" : result.side === "sell" ? "SHORT" : "NEUTRAL";

  return (
    <BracketFrame className="p-5 space-y-4 bg-zinc-900/60 rounded-xl border border-zinc-800">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <SectionLabel as="p">{result.display_name}</SectionLabel>
          <p className="text-xs text-zinc-500 mt-0.5">{result.category}</p>
        </div>
        <span
          className="font-mono text-xs px-2 py-0.5 rounded border"
          style={{
            color: sideColor(result.side),
            borderColor: sideColor(result.side) + "40",
            backgroundColor: sideColor(result.side) + "10",
          }}
        >
          {sideLabel}
        </span>
      </div>

      {/* Quality bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">Setup Quality</span>
          <span className="font-mono text-[10px] text-zinc-500">
            conf {(result.confidence * 100).toFixed(1)}% / threshold {(result.threshold * 100).toFixed(0)}%
          </span>
        </div>
        <QualityBar value={result.setup_quality} />
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-3 text-center">
        {(["entry", "stop", "target"] as const).map((k) => (
          <div key={k} className="bg-zinc-900 rounded-lg p-2">
            <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-widest mb-1">{k}</p>
            <p className="font-mono text-sm text-white">
              {fmtPrice(k === "entry" ? result.entry : k === "stop" ? result.stop : result.target)}
            </p>
          </div>
        ))}
      </div>

      {/* Reason */}
      {result.reason && (
        <p className="text-xs text-zinc-400 leading-relaxed">{result.reason}</p>
      )}

      {/* Apply button */}
      <BMGButton
        onClick={onApply}
        disabled={!canApply || applying}
        loading={applying}
        className="w-full"
        size="sm"
      >
        {canApply ? `Apply ${ticker} / ${result.display_name} to My Setups` : "Quality too low (< 50)"}
      </BMGButton>
    </BracketFrame>
  );
}

// ── Tab: EVALUATE ──────────────────────────────────────────────────────────────

function EvaluateTab() {
  const [ticker, setTicker] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [result, setResult] = useState<EvaluateResult | null>(null);
  const qc = useQueryClient();

  const { data: catalogData } = useQuery({
    queryKey: ["scout-catalog"],
    queryFn: getCatalog,
    staleTime: 10 * 60_000, // 10 min — prevents stale-forever from persisted cache
  });

  const grouped = useMemo(() => {
    const entries = catalogData?.strategies ?? [];

    // When a ticker is typed, surface matching strategies as a "Suggested" group
    if (ticker.trim()) {
      const t = ticker.trim().toUpperCase();
      const CRYPTO_SYMBOLS = new Set(["BTC", "ETH", "SOL", "AVAX", "LINK", "MATIC", "BNB", "ADA", "DOT", "DOGE", "XRP", "LTC", "UNI", "AAVE", "ATOM", "NEAR", "ARB", "OP"]);
      const isCrypto = t.includes("/") || CRYPTO_SYMBOLS.has(t) || t.endsWith("USD") || t.endsWith("USDT");

      const suggested = entries.filter((e) =>
        isCrypto
          ? e.category.toLowerCase().startsWith("crypto")
          : !e.category.toLowerCase().startsWith("crypto")
      );
      const rest = entries.filter((e) =>
        isCrypto
          ? !e.category.toLowerCase().startsWith("crypto")
          : e.category.toLowerCase().startsWith("crypto")
      );

      const restMap: Record<string, typeof entries> = {};
      for (const e of rest) (restMap[e.category] ??= []).push(e);

      return [
        [`✦ Suggested for ${isCrypto ? "Crypto" : "Stocks"}`, suggested] as [string, typeof entries],
        ...Object.entries(restMap).sort(([a], [b]) => a.localeCompare(b)),
      ];
    }

    const map: Record<string, typeof entries> = {};
    for (const e of entries) {
      (map[e.category] ??= []).push(e);
    }
    return Object.entries(map).sort(([a], [b]) => a.localeCompare(b));
  }, [catalogData, ticker]);

  const evalMut = useMutation({
    mutationFn: () => evaluate(strategyId, ticker),
    onSuccess: (data) => setResult(data),
    onError: () => toast.error("Evaluation failed — check ticker / strategy"),
  });

  const applyMut = useMutation({
    mutationFn: () => createSetup(ticker.toUpperCase(), strategyId),
    onSuccess: (data) => {
      toast.success(data.already_exists ? "Setup already active" : "Setup added to My Setups");
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
    },
    onError: () => toast.error("Failed to add setup"),
  });

  return (
    <div className="space-y-5">
      <BMGCard>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--bmg-text-label)] block mb-2">
              Strategy
            </label>
            <select
              value={strategyId}
              onChange={(e) => { setStrategyId(e.target.value); setResult(null); }}
              className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-[var(--bmg-green)] transition-colors"
            >
              <option value="">— select strategy —</option>
              {grouped.map(([cat, items]) => (
                <optgroup key={cat} label={cat}>
                  {items.map((s) => (
                    <option key={s.strategy_id} value={s.strategy_id}>
                      {s.display_name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <GlowInput
            label="Ticker"
            placeholder="NVDA, BTC/USD…"
            value={ticker}
            onChange={(e) => { setTicker(e.target.value.toUpperCase()); setResult(null); }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && ticker && strategyId) evalMut.mutate();
            }}
          />
        </div>
        <div className="mt-4 flex justify-end">
          <BMGButton
            onClick={() => evalMut.mutate()}
            disabled={!ticker || !strategyId || evalMut.isPending}
            loading={evalMut.isPending}
          >
            Evaluate
          </BMGButton>
        </div>
      </BMGCard>

      {result && (
        <EvalResultCard
          result={result}
          ticker={ticker.toUpperCase()}
          onApply={() => applyMut.mutate()}
          applying={applyMut.isPending}
        />
      )}
    </div>
  );
}

// ── Tab: SCAN TICKER ──────────────────────────────────────────────────────────

function ScanTickerTab() {
  const [ticker, setTicker] = useState("");
  const [scanTicker_, setScanTicker] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data, isFetching, isError } = useQuery({
    queryKey: ["scout-scan", scanTicker_],
    queryFn: () => (scanTicker_ ? scanTicker(scanTicker_) : null),
    enabled: !!scanTicker_,
    staleTime: 60_000,
    retry: 0,
  });

  const applyMut = useMutation({
    mutationFn: ({ t, sid }: { t: string; sid: string }) => createSetup(t, sid),
    onSuccess: (d) => {
      toast.success(d.already_exists ? "Already in setups" : "Added to My Setups");
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
    },
    onError: () => toast.error("Failed to add"),
  });

  return (
    <div className="space-y-5">
      <BMGCard>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <GlowInput
              label="Ticker"
              placeholder="AAPL, ETH/USD…"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => { if (e.key === "Enter" && ticker) setScanTicker(ticker); }}
            />
          </div>
          <BMGButton
            onClick={() => setScanTicker(ticker)}
            disabled={!ticker || isFetching}
            loading={isFetching}
          >
            Scan
          </BMGButton>
        </div>
      </BMGCard>

      {isFetching && (
        <div className="text-center py-8 font-mono text-xs text-zinc-500 animate-pulse">
          Running 30+ strategies on {scanTicker_}…
        </div>
      )}

      {isError && scanTicker_ && !isFetching && (
        <div className="text-center py-8 bg-zinc-900/60 border border-zinc-800 rounded-2xl">
          <p className="text-red-400 text-sm font-semibold mb-1">Could not fetch bar data for {scanTicker_}</p>
          <p className="text-zinc-500 text-xs">Check the symbol and try again. Crypto pairs should use BTC/USD format.</p>
        </div>
      )}

      {data && (
        <BMGCard padding="none">
          <div className="px-4 py-3 border-b border-t-dim flex items-center justify-between">
            <SectionLabel>Top strategies for {data.ticker}</SectionLabel>
            <span className="font-mono-t text-[10px] text-t-gdim">{data.bar_count} bars</span>
          </div>

          {data.conflict_warning && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-t-amber/10 border border-t-amber/30 rounded-lg flex items-start gap-2">
              <span className="text-t-amber text-xs mt-0.5 shrink-0">⚠</span>
              <p className="text-t-amber text-xs font-ui-t leading-relaxed">{data.conflict_warning}</p>
            </div>
          )}

          <div className="divide-y divide-t-dim/60">
            {data.results.length === 0 && (
              <div className="px-4 py-8 text-center">
                <p className="text-t-mid2 text-sm font-mono-t mb-1">No setups detected</p>
                <p className="text-t-muted text-xs font-ui-t">
                  {data.message || `No high-confidence setups currently for ${data.ticker}.`}
                </p>
              </div>
            )}
            {data.results.map((r) => {
              const sideLabel =
                r.side === "buy" ? "LONG" : r.side === "sell" ? "SHORT" : "NEUTRAL";
              return (
                <div
                  key={r.strategy_id}
                  className="px-4 py-3 flex items-center gap-3 hover:bg-zinc-800/30 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-xs text-white truncate">{r.display_name}</span>
                      <span
                        className="font-mono text-[9px] px-1.5 py-0.5 rounded border shrink-0"
                        style={{
                          color: sideColor(r.side),
                          borderColor: sideColor(r.side) + "40",
                        }}
                      >
                        {sideLabel}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-[10px] text-zinc-500">
                      <span className="font-mono">{r.category}</span>
                      <span className="font-mono">conf {(r.confidence * 100).toFixed(1)}%</span>
                    </div>
                    <QualityBar value={r.setup_quality} />
                  </div>
                  <BMGButton
                    size="sm"
                    variant="secondary"
                    onClick={() => applyMut.mutate({ t: data.ticker, sid: r.strategy_id })}
                    disabled={r.setup_quality < 50 || applyMut.isPending}
                  >
                    Apply
                  </BMGButton>
                </div>
              );
            })}
          </div>
        </BMGCard>
      )}
    </div>
  );
}

// ── Tab: MY SETUPS ────────────────────────────────────────────────────────────

function MySetupsTab() {
  const qc = useQueryClient();

  const { data: setupData, isLoading } = useQuery({
    queryKey: ["scout-setups"],
    queryFn: getSetups,
    refetchInterval: 60_000,
  });

  const { data: signalData } = useQuery({
    queryKey: ["scout-signals"],
    queryFn: getSignals,
    refetchInterval: 60_000,
  });

  const removeMut = useMutation({
    mutationFn: deleteSetup,
    onSuccess: () => {
      toast.success("Setup removed");
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
    },
  });

  const setups = setupData?.setups ?? [];
  const signals = signalData?.signals ?? [];

  return (
    <div className="space-y-5">
      {/* Active setups */}
      <BMGCard padding="none">
        <div className="px-4 py-3 border-b border-zinc-800">
          <SectionLabel>Active Setups</SectionLabel>
        </div>
        {isLoading && (
          <div className="p-8 text-center font-mono text-xs text-zinc-500 animate-pulse">
            Loading setups…
          </div>
        )}
        {!isLoading && setups.length === 0 && (
          <div className="p-8 text-center">
            <p className="text-sm text-zinc-500">No active setups yet.</p>
            <p className="text-xs text-zinc-600 mt-1">Use Evaluate or Scan Ticker to add one.</p>
          </div>
        )}
        {setups.length > 0 && (
          <div className="divide-y divide-zinc-800/60">
            {setups.map((s) => {
              const statusLabel = setupStatusLabel(s);
              const statusColor = setupStatusColor(s.status);
              const confPct =
                s.last_confidence !== null && s.last_confidence !== undefined
                  ? `${(s.last_confidence * 100).toFixed(1)}%`
                  : "—";
              return (
                <div
                  key={s.id}
                  className="px-4 py-3 flex items-center gap-3 hover:bg-zinc-800/20 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-mono text-xs text-white">{s.ticker}</span>
                      <span className="text-zinc-600 text-xs">·</span>
                      <span className="font-mono text-xs text-zinc-400 truncate">{s.display_name}</span>
                    </div>
                    <div className="flex items-center gap-3 text-[10px] text-zinc-500 font-mono">
                      <span
                        className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
                        style={{ color: statusColor, borderColor: statusColor + "40" }}
                      >
                        {statusLabel}
                      </span>
                      <span>conf {confPct}</span>
                      <span>scanned {fmtTs(s.last_scanned_at)}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => removeMut.mutate(s.id)}
                    disabled={removeMut.isPending}
                    className="text-[10px] font-mono text-zinc-600 hover:text-[var(--bmg-red)] transition-colors uppercase tracking-widest"
                  >
                    Remove
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </BMGCard>

      {/* Fired signals history */}
      {signals.length > 0 && (
        <BMGCard padding="none">
          <div className="px-4 py-3 border-b border-zinc-800">
            <SectionLabel>Fired Signals</SectionLabel>
          </div>
          <div className="divide-y divide-zinc-800/60">
            {signals.slice(0, 20).map((sig) => {
              const sideLabel =
                sig.side === "buy" ? "LONG" : sig.side === "sell" ? "SHORT" : sig.side.toUpperCase();
              return (
                <div key={sig.id} className="px-4 py-3 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-mono text-xs text-white">{sig.ticker}</span>
                      <span
                        className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
                        style={{
                          color: sideColor(sig.side),
                          borderColor: sideColor(sig.side) + "40",
                        }}
                      >
                        {sideLabel}
                      </span>
                      <span className="font-mono text-xs text-zinc-400 truncate">{sig.display_name}</span>
                    </div>
                    <div className="flex items-center gap-3 text-[10px] text-zinc-500 font-mono">
                      <span>conf {(sig.confidence * 100).toFixed(1)}%</span>
                      {sig.entry_price && <span>entry {fmtPrice(sig.entry_price)}</span>}
                      <span>{fmtTs(sig.created_at)}</span>
                    </div>
                  </div>
                  <SignalExplainButton signalId={sig.id} source="scout" />
                </div>
              );
            })}
          </div>
        </BMGCard>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

type Tab = "evaluate" | "scan" | "setups";

export default function StrategyScoutPage() {
  const [tab, setTab] = useState<Tab>("evaluate");

  // Feature-flag guard — if the catalog 404s, the feature is off server-side
  const { isError: catalogError, isLoading: catalogLoading } = useQuery({
    queryKey: ["scout-catalog"],
    queryFn: getCatalog,
    retry: 0,
    staleTime: 300_000,
  });

  const { data: setupData } = useQuery({
    queryKey: ["scout-setups"],
    queryFn: getSetups,
    staleTime: 60_000,
    enabled: !catalogError,
  });
  const activeCount = (setupData?.setups ?? []).filter(
    (s) => s.status === "active" || s.status === "fired"
  ).length;

  const tabs: { key: Tab; label: string }[] = [
    { key: "evaluate", label: "// EVALUATE" },
    { key: "scan",     label: "// SCAN TICKER" },
    { key: "setups",   label: `// MY SETUPS${activeCount > 0 ? ` (${activeCount})` : ""}` },
  ];

  if (catalogLoading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-6">
        <div className="h-48 rounded-2xl bg-zinc-900 border border-zinc-800 animate-pulse" />
      </div>
    );
  }

  if (catalogError) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-6">
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-10 text-center">
          <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest mb-3">
            // STRATEGY SCOUT
          </p>
          <p className="text-white font-semibold mb-2">Strategy Scout is not enabled</p>
          <p className="text-zinc-500 text-sm">
            Set{" "}
            <code className="bg-zinc-800 px-1.5 py-0.5 rounded text-xs text-zinc-300">
              ENABLE_STRATEGY_SCOUT=true
            </code>{" "}
            in Railway environment variables to activate.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 pb-20 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Strategy Scout</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Match strategies to tickers. Apply setups to get personal Discord alerts when confidence arms.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-zinc-800 pb-0">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={[
              "px-4 py-2.5 font-mono text-[10px] tracking-[0.16em] uppercase transition-all duration-200",
              tab === t.key
                ? "text-[var(--bmg-green)] border-b-2 border-[var(--bmg-green)]"
                : "text-zinc-500 hover:text-zinc-300",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "evaluate" && <EvaluateTab />}
      {tab === "scan"     && <ScanTickerTab />}
      {tab === "setups"   && <MySetupsTab />}

      {/* Footer */}
      <p className="text-xs text-zinc-700 text-center">
        Paper trading. Not investment advice. Not a registered investment adviser.
      </p>
    </div>
  );
}
