import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import SignalExplainButton from "@/components/explain/SignalExplainButton";
import { useNavigate } from "react-router-dom";
import {
  getCatalog,
  evaluate,
  getSetups,
  createSetup,
  deleteSetup,
  getSignals,
  screenStrategy,
  scanTicker,
  quickLookup,
  type EvaluateResult,
  type ScoutSetup,
  type ScreenResult,
  type ScanResult,
  type QuickLookupResult,
} from "@/api/scout";

// ── Design tokens (terminal · phosphor · violet scout) ───────────────────────
const C = {
  bg0:          "#040804",
  bg1:          "#060c06",
  bg2:          "#0a120a",
  surface:      "#080d08",
  surfaceDeep:  "#0a0a10",
  violet:       "#a78bfa",
  violetDim:    "rgba(167,139,250,0.08)",
  violetBorder: "rgba(167,139,250,0.22)",
  violetBorderHot: "rgba(167,139,250,0.32)",
  green:        "#4ade80",
  greenDim:     "rgba(74,222,128,0.08)",
  greenBorder:  "rgba(74,222,128,0.12)",
  greenBorderHot: "rgba(74,222,128,0.32)",
  amber:        "#fbbf24",
  amberBorder:  "rgba(251,191,36,0.26)",
  red:          "#f87171",
  cyan:         "#38bdf8",
  hi:           "#eafbe9",
  body:         "#dce8dc",
  mid:          "#9fb0a0",
  dim:          "#7e8e7e",
  faint:        "#50604f",
  borderDim:    "rgba(74,222,128,0.12)",
  borderMid:    "rgba(74,222,128,0.25)",
};

const MONO = "'JetBrains Mono', 'Geist Mono', ui-monospace, monospace";
const SANS = "'Space Grotesk', 'Inter', system-ui, sans-serif";

// ── Helpers ───────────────────────────────────────────────────────────────────

function armPct(conf: number | null | undefined): number {
  if (conf == null) return 0;
  return Math.min(100, Math.round(conf * 100));
}

function gaugeColor(pct: number, fired?: boolean): string {
  if (fired || pct >= 95) return C.green;
  if (pct >= 70) return C.violet;
  return C.dim;
}

function gaugeGlow(pct: number, fired?: boolean): string {
  if (fired || pct >= 95) return "rgba(74,222,128,0.6)";
  return "rgba(167,139,250,0.5)";
}

function armStatusLabel(setup: ScoutSetup): string {
  if (setup.status === "fired") return "◉ FIRED";
  const pct = armPct(setup.last_confidence);
  if (pct >= 95) return "◉ ARMED — FIRING";
  if (pct >= 70) return "arming";
  if (pct >= 45) return "close";
  return "watching";
}

function armStatusColor(setup: ScoutSetup): string {
  if (setup.status === "fired") return C.green;
  const pct = armPct(setup.last_confidence);
  if (pct >= 95) return C.green;
  if (pct >= 70) return C.violet;
  return C.faint;
}

function sideColor(side: string): string {
  if (side === "buy" || side === "cover") return C.green;
  if (side === "sell" || side === "short") return C.red;
  return C.dim;
}

function confColor(c: number): string {
  if (c >= 0.7) return C.green;
  if (c >= 0.5) return C.amber;
  return C.red;
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (v >= 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(6)}`;
}

function fmtTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return d.toLocaleDateString();
}

// ── RadialGauge ───────────────────────────────────────────────────────────────

function RadialGauge({
  pct,
  size = 72,
  fired = false,
}: {
  pct: number;
  size?: number;
  fired?: boolean;
}) {
  const r = size * 0.417;
  const circ = 2 * Math.PI * r;
  const offset = (circ * (1 - pct / 100)).toFixed(1);
  const color = gaugeColor(pct, fired);
  const glow = pct >= 70 || fired ? `drop-shadow(0 0 4px ${gaugeGlow(pct, fired)})` : undefined;
  const sw = (size * 0.083).toFixed(1);

  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        style={{ width: size, height: size, transform: "rotate(-90deg)" }}
      >
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#121a12" strokeWidth={sw} />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={sw}
          strokeLinecap="round"
          strokeDasharray={circ.toFixed(1)}
          strokeDashoffset={offset}
          style={{
            filter: glow,
            transition: "stroke-dashoffset 0.6s ease, stroke 0.4s ease",
          }}
        />
      </svg>
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        pointerEvents: "none",
      }}>
        <span style={{
          fontFamily: MONO,
          fontSize: size === 72 ? 17 : size === 52 ? 12 : 14,
          fontWeight: 600, color, lineHeight: 1,
        }}>
          {pct}%
        </span>
        <span style={{ fontFamily: MONO, fontSize: 7, color: C.faint, letterSpacing: "0.1em", marginTop: 1 }}>
          ARM
        </span>
      </div>
    </div>
  );
}

// ── SectionLabel ──────────────────────────────────────────────────────────────

function SectionDivider({ label, color = C.faint }: { label: string; color?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.16em", color, opacity: 0.85 }}>
        // {label}
      </span>
      <span style={{ flex: 1, height: 1, background: `linear-gradient(90deg,${color === C.violet ? "rgba(167,139,250,0.22)" : C.borderDim},transparent)` }} />
    </div>
  );
}

// ── PairingCard ───────────────────────────────────────────────────────────────

function PairingCard({
  setup,
  onRemove,
  removing,
}: {
  setup: ScoutSetup;
  onRemove: () => void;
  removing: boolean;
}) {
  const pct = armPct(setup.last_confidence);
  const fired = setup.status === "fired";
  const armed = fired || pct >= 95;
  const color = gaugeColor(pct, fired);

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 18,
        border: `1px solid ${armed ? C.greenBorderHot : C.violetBorderHot}`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 6,
        background: armed ? "linear-gradient(180deg,#0a140c,#080d08)" : C.surfaceDeep,
        padding: "16px 18px",
        animation: armed ? "bmg-violetglow 3.2s ease-in-out infinite" : undefined,
        transition: "background 0.3s ease",
      }}
    >
      <RadialGauge pct={pct} size={72} fired={fired} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
          <span style={{ fontFamily: MONO, fontSize: 15, color: C.hi, fontWeight: 500 }}>
            {setup.ticker}
          </span>
          <span style={{
            fontFamily: MONO, fontSize: 9, color: C.violet,
            border: `1px solid rgba(167,139,250,0.3)`, borderRadius: 3, padding: "2px 7px",
          }}>
            {setup.display_name}
          </span>
          <span style={{
            fontFamily: MONO, fontSize: 9, letterSpacing: "0.08em",
            color: armStatusColor(setup),
          }}>
            {armStatusLabel(setup)}
          </span>
        </div>
        <div style={{ fontFamily: MONO, fontSize: 11, color: C.dim, marginTop: 8 }}>
          scanned {fmtTs(setup.last_scanned_at)}
        </div>
        {setup.last_confidence != null && (
          <div style={{ fontFamily: MONO, fontSize: 10, color: C.faint, marginTop: 4 }}>
            confidence: {(setup.last_confidence * 100).toFixed(1)}%
          </div>
        )}
      </div>

      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontFamily: MONO, fontSize: 10, color: C.faint }}>DISTANCE</div>
        <div style={{ fontFamily: MONO, fontSize: 15, color, marginTop: 4 }}>
          {pct}%
        </div>
        <button
          onClick={onRemove}
          disabled={removing}
          style={{
            marginTop: 8, fontFamily: MONO, fontSize: 9, letterSpacing: "0.14em",
            color: C.faint, background: "none", border: "none", cursor: "pointer",
            textTransform: "uppercase", padding: 0,
          }}
          onMouseEnter={(e) => ((e.target as HTMLElement).style.color = C.red)}
          onMouseLeave={(e) => ((e.target as HTMLElement).style.color = C.faint)}
        >
          REMOVE
        </button>
      </div>
    </div>
  );
}

// ── EvalResultCard ────────────────────────────────────────────────────────────

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
  const sideLabel = result.side === "buy" ? "LONG" : result.side === "sell" ? "SHORT" : "NEUTRAL";
  const sc = sideColor(result.side);
  const qPct = result.setup_quality;
  const qColor = qPct >= 70 ? C.green : qPct >= 45 ? C.amber : C.red;

  return (
    <div style={{
      border: `1px solid ${C.violetBorder}`,
      borderLeft: `3px solid ${C.violet}`,
      borderRadius: 6,
      background: C.surfaceDeep,
      padding: "18px",
      animation: "bmg-slideIn 0.2s ease both",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontFamily: SANS, fontSize: 15, fontWeight: 600, color: C.hi }}>
            {result.display_name}
          </div>
          <div style={{ fontFamily: MONO, fontSize: 10, color: C.faint, marginTop: 3 }}>
            {result.category}
          </div>
        </div>
        <span style={{
          fontFamily: MONO, fontSize: 9, padding: "3px 8px",
          border: `1px solid ${sc}40`, borderRadius: 3,
          color: sc, background: `${sc}10`,
        }}>
          {sideLabel}
        </span>
      </div>

      <div style={{ marginTop: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.14em" }}>SETUP QUALITY</span>
          <span style={{ fontFamily: MONO, fontSize: 10, color: C.dim }}>
            conf {(result.confidence * 100).toFixed(1)}% / threshold {(result.threshold * 100).toFixed(0)}%
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ flex: 1, height: 5, borderRadius: 3, background: "#121a12", overflow: "hidden" }}>
            <div style={{
              height: "100%", borderRadius: 3, width: `${qPct}%`,
              background: qColor,
              boxShadow: qPct >= 70 ? `0 0 6px ${qColor}` : undefined,
              transition: "width 0.5s ease",
            }} />
          </div>
          <span style={{ fontFamily: MONO, fontSize: 11, color: qColor, minWidth: 28, textAlign: "right" }}>
            {qPct}
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 14 }}>
        {(["entry", "stop", "target"] as const).map((k) => (
          <div key={k} style={{
            background: C.bg1, border: `1px solid ${C.borderDim}`,
            borderRadius: 4, padding: "10px 12px", textAlign: "center",
          }}>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.1em", marginBottom: 5 }}>
              {k.toUpperCase()}
            </div>
            <div style={{ fontFamily: MONO, fontSize: 13, color: C.hi, fontWeight: 500 }}>
              {fmtPrice(k === "entry" ? result.entry : k === "stop" ? result.stop : result.target)}
            </div>
          </div>
        ))}
      </div>

      {result.reason && (
        <p style={{ fontFamily: SANS, fontSize: 12, color: C.dim, lineHeight: 1.6, marginTop: 12 }}>
          {result.reason}
        </p>
      )}

      <button
        onClick={onApply}
        disabled={!canApply || applying}
        style={{
          width: "100%", marginTop: 14,
          fontFamily: SANS, fontSize: 13, fontWeight: 600, letterSpacing: "0.04em",
          color: canApply ? C.bg0 : C.faint,
          background: canApply ? C.violet : "transparent",
          border: `1px solid ${canApply ? C.violet : C.faint}`,
          borderRadius: 5, padding: "12px",
          cursor: canApply ? "pointer" : "not-allowed",
          boxShadow: canApply && !applying ? "0 0 18px rgba(167,139,250,0.4)" : undefined,
          transition: "all 0.15s ease",
          opacity: applying ? 0.7 : 1,
        }}
      >
        {applying ? "Adding…" : canApply ? `⊹ Apply ${ticker} / ${result.display_name}` : "Quality too low (< 50)"}
      </button>
    </div>
  );
}

// ── EvaluateTab ───────────────────────────────────────────────────────────────

function EvaluateTab() {
  const [ticker, setTicker] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [result, setResult] = useState<EvaluateResult | null>(null);
  const qc = useQueryClient();

  const { data: catalogData, isLoading: catalogLoading, isError: catalogError } = useQuery({
    queryKey: ["scout-catalog"],
    queryFn: getCatalog,
    staleTime: 10 * 60_000,
  });

  const grouped = useMemo(() => {
    const entries = catalogData?.strategies ?? [];
    if (ticker.trim()) {
      const t = ticker.trim().toUpperCase();
      const CRYPTO = new Set(["BTC","ETH","SOL","AVAX","LINK","MATIC","BNB","ADA","DOT","DOGE","XRP","LTC","UNI","AAVE","ATOM","NEAR","ARB","OP"]);
      const isCrypto = t.includes("/") || CRYPTO.has(t) || t.endsWith("USD") || t.endsWith("USDT");
      const suggested = entries.filter((e) => isCrypto ? e.category.toLowerCase().startsWith("crypto") : !e.category.toLowerCase().startsWith("crypto"));
      const rest = entries.filter((e) => isCrypto ? !e.category.toLowerCase().startsWith("crypto") : e.category.toLowerCase().startsWith("crypto"));
      const restMap: Record<string, typeof entries> = {};
      for (const e of rest) (restMap[e.category] ??= []).push(e);
      return [[`✦ Suggested for ${isCrypto ? "Crypto" : "Stocks"}`, suggested] as [string, typeof entries], ...Object.entries(restMap).sort(([a], [b]) => a.localeCompare(b))];
    }
    const map: Record<string, typeof entries> = {};
    for (const e of entries) (map[e.category] ??= []).push(e);
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

  const inputStyle = {
    width: "100%",
    background: C.bg1,
    border: `1px solid ${C.borderDim}`,
    borderRadius: 4,
    padding: "9px 12px",
    fontFamily: MONO,
    fontSize: 13,
    color: C.hi,
    outline: "none",
  };

  if (catalogLoading) {
    return (
      <div style={{ border: `1px solid ${C.borderDim}`, borderRadius: 6, background: C.surface, padding: "32px 18px", textAlign: "center" }}>
        <div style={{ fontFamily: MONO, fontSize: 11, color: C.faint, animation: "bmg-pulse 1.4s ease infinite" }}>
          {"// loading catalog ▮"}
        </div>
      </div>
    );
  }

  if (catalogError) {
    return (
      <div style={{ border: `1px solid rgba(248,113,113,0.22)`, borderRadius: 6, background: "rgba(248,113,113,0.04)", padding: "24px 18px", textAlign: "center" }}>
        <div style={{ fontFamily: MONO, fontSize: 11, color: C.red, letterSpacing: "0.1em" }}>// CATALOG_LOAD_ERROR</div>
        <div style={{ fontFamily: SANS, fontSize: 13, color: C.mid, marginTop: 8 }}>Unable to load strategy catalog. Check backend connection.</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{
        border: `1px solid ${C.borderDim}`,
        borderRadius: 6, background: C.surface, padding: 18,
      }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.18em", marginBottom: 8 }}>STRATEGY</div>
            <select
              value={strategyId}
              onChange={(e) => { setStrategyId(e.target.value); setResult(null); }}
              style={{ ...inputStyle, cursor: "pointer" }}
            >
              <option value="">— select strategy —</option>
              {grouped.map(([cat, items]) => (
                <optgroup key={cat} label={cat}>
                  {items.map((s) => (
                    <option key={s.strategy_id} value={s.strategy_id}>{s.display_name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.18em", marginBottom: 8 }}>TICKER</div>
            <input
              placeholder="NVDA, BTC/USD…"
              value={ticker}
              onChange={(e) => { setTicker(e.target.value.toUpperCase()); setResult(null); }}
              onKeyDown={(e) => { if (e.key === "Enter" && ticker && strategyId) evalMut.mutate(); }}
              style={inputStyle}
            />
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={() => evalMut.mutate()}
            disabled={!ticker || !strategyId || evalMut.isPending}
            style={{
              fontFamily: SANS, fontSize: 13, fontWeight: 600, letterSpacing: "0.04em",
              color: C.bg0, background: C.violet,
              border: "none", borderRadius: 5, padding: "10px 24px",
              cursor: (!ticker || !strategyId || evalMut.isPending) ? "not-allowed" : "pointer",
              boxShadow: "0 0 18px rgba(167,139,250,0.4)",
              opacity: (!ticker || !strategyId || evalMut.isPending) ? 0.5 : 1,
              transition: "all 0.15s ease",
            }}
          >
            {evalMut.isPending ? "Evaluating…" : "⊹ Evaluate"}
          </button>
        </div>
      </div>

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

// ── FindSetupsTab ─────────────────────────────────────────────────────────────

const UNIVERSE_OPTIONS = [
  { value: "sp500_plus_top_crypto", label: "S&P 500 + Top Crypto" },
  { value: "sp500",                 label: "S&P 500" },
  { value: "russell1000",           label: "Russell 1000" },
  { value: "crypto_top50",          label: "Top 50 Crypto" },
  { value: "watchlist",             label: "My Watchlist" },
];

function FindSetupsTab() {
  const qc = useQueryClient();

  const { data: catalogData } = useQuery({
    queryKey: ["scout-catalog"],
    queryFn: getCatalog,
    staleTime: 10 * 60_000,
  });

  const strategies = catalogData?.strategies ?? [];
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const [selectedUniverse, setSelectedUniverse] = useState("sp500_plus_top_crypto");
  const [runScreen, setRunScreen] = useState(false);

  const { data: screenData, isFetching, isError } = useQuery({
    queryKey: ["scout-screen", selectedStrategy, selectedUniverse],
    queryFn: () => screenStrategy(selectedStrategy, selectedUniverse),
    enabled: runScreen && !!selectedStrategy,
    staleTime: 300_000,
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

  const currentStrategyName = strategies.find((s) => s.strategy_id === selectedStrategy)?.display_name ?? selectedStrategy;
  const universeLabel = Object.fromEntries(UNIVERSE_OPTIONS.map((o) => [o.value, o.label]));

  const selectStyle = {
    width: "100%",
    background: "#060c06",
    border: `1px solid ${C.borderDim}`,
    borderRadius: 4,
    padding: "9px 12px",
    fontFamily: MONO,
    fontSize: 13,
    color: C.hi,
    outline: "none",
    cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ border: `1px solid ${C.borderDim}`, borderRadius: 6, background: C.surface, padding: 18 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.18em", marginBottom: 8 }}>STRATEGY</div>
            <select value={selectedStrategy} onChange={(e) => { setSelectedStrategy(e.target.value); setRunScreen(false); }} style={selectStyle}>
              <option value="">— select strategy —</option>
              {strategies.map((s) => <option key={s.strategy_id} value={s.strategy_id}>{s.display_name}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.18em", marginBottom: 8 }}>UNIVERSE</div>
            <select value={selectedUniverse} onChange={(e) => { setSelectedUniverse(e.target.value); setRunScreen(false); }} style={selectStyle}>
              {UNIVERSE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={() => setRunScreen(true)}
            disabled={!selectedStrategy || isFetching}
            style={{
              fontFamily: SANS, fontSize: 13, fontWeight: 600, letterSpacing: "0.04em",
              color: C.bg0, background: C.green,
              border: "none", borderRadius: 5, padding: "10px 24px",
              cursor: (!selectedStrategy || isFetching) ? "not-allowed" : "pointer",
              boxShadow: "0 0 18px rgba(74,222,128,0.35)",
              opacity: (!selectedStrategy || isFetching) ? 0.5 : 1,
              transition: "all 0.15s ease",
            }}
          >
            {isFetching ? "Scanning…" : "⊹ Screen"}
          </button>
        </div>
      </div>

      {isFetching && (
        <div style={{ border: `1px solid ${C.borderDim}`, borderRadius: 6, background: C.surface, padding: "32px 18px", textAlign: "center" }}>
          <div style={{ fontFamily: MONO, fontSize: 12, color: C.green }}>
            {"// scanning " + (universeLabel[selectedUniverse] ?? selectedUniverse) + " ▮"}
          </div>
          <div style={{ width: 200, height: 3, background: "#121a12", borderRadius: 2, margin: "14px auto 0", overflow: "hidden" }}>
            <div style={{ height: "100%", background: C.green, borderRadius: 2, animation: "bmg-pulse 1s ease infinite", opacity: 0.7 }} />
          </div>
        </div>
      )}

      {isError && !isFetching && (
        <div style={{ border: `1px solid rgba(248,113,113,0.22)`, borderRadius: 6, background: "rgba(248,113,113,0.04)", padding: "24px 18px", textAlign: "center" }}>
          <div style={{ fontFamily: MONO, fontSize: 11, color: C.red, letterSpacing: "0.1em" }}>// SCREENER_ERROR</div>
          <div style={{ fontFamily: SANS, fontSize: 13, color: C.mid, marginTop: 8 }}>Check strategy selection and try again.</div>
        </div>
      )}

      {screenData && !isFetching && (
        <div style={{ border: `1px solid ${C.borderDim}`, borderRadius: 6, background: C.surface, overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "12px 16px", borderBottom: `1px solid ${C.borderDim}`,
          }}>
            <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.14em", color: C.violet }}>
              {screenData.match_count} MATCH{screenData.match_count !== 1 ? "ES" : ""} · {screenData.scanned_count} SCANNED
            </span>
            {screenData.cached && (
              <span style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.12em" }}>CACHED</span>
            )}
          </div>

          {screenData.results.length === 0 && (
            <div style={{ padding: "40px 18px", textAlign: "center" }}>
              <div style={{ fontFamily: MONO, fontSize: 11, color: C.faint }}>
                {"// NO_SETUPS_FOUND — " + currentStrategyName + " · 0 matches"}
              </div>
            </div>
          )}

          {screenData.results.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${C.borderDim}` }}>
                    {["#", "SYMBOL", "ASSET", "DIRECTION", "CONF", "QUALITY", "PRICE", "ACTION"].map((col) => (
                      <th key={col} style={{
                        padding: "8px 12px", fontFamily: MONO, fontSize: 9,
                        color: C.faint, letterSpacing: "0.16em", textAlign: "left", fontWeight: 400,
                      }}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {screenData.results.map((r: ScreenResult) => {
                    const dirColor = r.direction === "LONG" ? C.green : C.red;
                    const metricEntries = Object.entries(r.key_metrics ?? {});
                    return (
                      <>
                        <tr
                          key={`${r.symbol}-${r.rank}`}
                          style={{ borderBottom: `1px solid rgba(74,222,128,0.04)`, transition: "background 0.1s" }}
                          onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "rgba(167,139,250,0.04)")}
                          onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
                        >
                          <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 10, color: C.faint }}>{r.rank}</td>
                          <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 14, color: C.hi, fontWeight: 500 }}>{r.symbol}</td>
                          <td style={{ padding: "11px 12px" }}>
                            <span style={{
                              fontFamily: MONO, fontSize: 9, padding: "2px 7px",
                              borderRadius: 3, border: `1px solid ${r.asset_class === "crypto" ? C.cyan + "40" : C.borderDim}`,
                              color: r.asset_class === "crypto" ? C.cyan : C.dim,
                              background: r.asset_class === "crypto" ? "rgba(56,189,248,0.08)" : "transparent",
                            }}>{r.asset_class === "crypto" ? "CRYPTO" : "EQUITY"}</span>
                          </td>
                          <td style={{ padding: "11px 12px" }}>
                            <span style={{
                              fontFamily: MONO, fontSize: 9, padding: "2px 7px", borderRadius: 3,
                              border: `1px solid ${dirColor}40`, color: dirColor, background: `${dirColor}10`,
                            }}>{r.direction}</span>
                          </td>
                          <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 12, color: confColor(r.confidence) }}>
                            {(r.confidence * 100).toFixed(1)}%
                          </td>
                          <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 12, color: confColor(r.setup_quality / 100) }}>
                            {r.setup_quality}
                          </td>
                          <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 12, color: C.dim }}>
                            {r.current_price != null ? fmtPrice(r.current_price) : "—"}
                          </td>
                          <td style={{ padding: "11px 12px" }}>
                            <button
                              onClick={() => applyMut.mutate({ t: r.symbol, sid: screenData.strategy_id })}
                              disabled={applyMut.isPending}
                              style={{
                                fontFamily: MONO, fontSize: 9, letterSpacing: "0.12em",
                                color: C.violet, background: C.violetDim,
                                border: `1px solid ${C.violetBorder}`, borderRadius: 4,
                                padding: "5px 10px", cursor: "pointer", transition: "all 0.15s",
                              }}
                            >ARM</button>
                          </td>
                        </tr>
                        {(r.summary || metricEntries.length > 0) && (
                          <tr key={`${r.symbol}-detail`} style={{ background: "rgba(167,139,250,0.02)" }}>
                            <td colSpan={8} style={{ padding: "4px 12px 10px" }}>
                              {r.summary && (
                                <p style={{ fontFamily: SANS, fontSize: 10, color: C.faint, lineHeight: 1.5, margin: "0 0 4px" }}>{r.summary}</p>
                              )}
                              {metricEntries.length > 0 && (
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                  {metricEntries.map(([k, v]) => (
                                    <span key={k} style={{
                                      fontFamily: MONO, fontSize: 9, padding: "2px 7px",
                                      background: C.bg1, border: `1px solid ${C.borderDim}`,
                                      borderRadius: 3, color: C.faint,
                                    }}>{k}: {String(v)}</span>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── MySetupsView (arm gauge two-column layout) ────────────────────────────────

function MySetupsView() {
  const qc = useQueryClient();

  const { data: setupData, isLoading: setupsLoading } = useQuery({
    queryKey: ["scout-setups"],
    queryFn: getSetups,
    refetchInterval: 60_000,
  });

  const { data: signalData } = useQuery({
    queryKey: ["scout-signals"],
    queryFn: getSignals,
    refetchInterval: 60_000,
  });

  const { data: catalogData } = useQuery({
    queryKey: ["scout-catalog"],
    queryFn: getCatalog,
    staleTime: 10 * 60_000,
  });

  const strategies = catalogData?.strategies ?? [];
  const [selStrat, setSelStrat] = useState("");
  const [selTicker, setSelTicker] = useState("");

  const removeMut = useMutation({
    mutationFn: deleteSetup,
    onSuccess: () => {
      toast.success("Setup removed");
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
    },
  });

  const addMut = useMutation({
    mutationFn: () => createSetup(selTicker.toUpperCase(), selStrat),
    onSuccess: (data) => {
      toast.success(data.already_exists ? "Setup already active" : "⊹ Setup armed");
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
      setSelStrat("");
      setSelTicker("");
    },
    onError: () => toast.error("Failed to add setup"),
  });

  const setups = (setupData?.setups ?? []).slice().sort((a, b) => armPct(b.last_confidence) - armPct(a.last_confidence));
  const signals = signalData?.signals ?? [];
  const armedCount = setups.filter((s) => armPct(s.last_confidence) >= 95 || s.status === "fired").length;

  // Preview arm gauge
  const previewPct = useMemo(() => {
    if (!selStrat || !selTicker) return 0;
    const seed = (selStrat + "|" + selTicker).split("").reduce((a, ch) => a + ch.charCodeAt(0), 0);
    return 42 + (seed % 56);
  }, [selStrat, selTicker]);

  const QUICK_TICKERS = ["NVDA", "TSLA", "BTC/USD", "ETH/USD", "SOL/USD", "SPY", "QQQ"];

  const selectStyle: React.CSSProperties = {
    width: "100%",
    background: C.bg1,
    border: `1px solid ${C.borderDim}`,
    borderRadius: 4,
    padding: "9px 12px",
    fontFamily: MONO,
    fontSize: 12,
    color: C.hi,
    outline: "none",
    cursor: "pointer",
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18 }}>

      {/* LEFT: Pairings board */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <SectionDivider label="ACTIVE PAIRINGS · CLOSEST TO FIRING" color={C.violet} />

        {setupsLoading && (
          <div style={{ border: `1px solid ${C.borderDim}`, borderRadius: 6, padding: "28px 18px", textAlign: "center" }}>
            <div style={{ fontFamily: MONO, fontSize: 11, color: C.faint, animation: "bmg-pulse 1.4s ease infinite" }}>
              {"// loading · scanning setups ▮"}
            </div>
          </div>
        )}

        {!setupsLoading && setups.length === 0 && (
          <div style={{
            border: `1px solid ${C.violetBorder}`, borderRadius: 6, borderStyle: "dashed",
            background: C.violetDim, padding: "40px 18px", textAlign: "center",
          }}>
            <div style={{ fontFamily: MONO, fontSize: 11, color: C.violet, letterSpacing: "0.12em", marginBottom: 8 }}>
              // NO PAIRINGS ARMED
            </div>
            <div style={{ fontFamily: SANS, fontSize: 13, color: C.dim }}>
              Use the composer to arm your first strategy × ticker pairing.
            </div>
          </div>
        )}

        {setups.map((setup) => (
          <PairingCard
            key={setup.id}
            setup={setup}
            onRemove={() => removeMut.mutate(setup.id)}
            removing={removeMut.isPending}
          />
        ))}
      </div>

      {/* RIGHT: Composer + Fired log */}
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>

        {/* Composer */}
        <div style={{
          border: `1px solid ${C.violetBorder}`,
          borderRadius: 6,
          background: "linear-gradient(180deg,#0c0a14,#08070d)",
          padding: 18,
          position: "relative",
          overflow: "hidden",
        }}>
          {/* Radar sweep decoration */}
          <div style={{
            position: "absolute", top: -40, right: -40, width: 160, height: 160,
            borderRadius: "50%", opacity: 0.16,
            background: "conic-gradient(from 0deg, transparent, rgba(167,139,250,0.5), transparent 40%)",
            animation: "bmg-sweep 4s linear infinite",
            pointerEvents: "none",
          }} />

          <div style={{ position: "relative" }}>
            <SectionDivider label="NEW SCOUT PAIRING" color={C.violet} />

            <div style={{ marginTop: 14 }}>
              <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.16em", marginBottom: 8 }}>
                STRATEGY
              </div>
              <select value={selStrat} onChange={(e) => setSelStrat(e.target.value)} style={selectStyle}>
                <option value="">— pick strategy —</option>
                {strategies.map((s) => (
                  <option key={s.strategy_id} value={s.strategy_id}>{s.display_name}</option>
                ))}
              </select>
            </div>

            <div style={{ marginTop: 12 }}>
              <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.16em", marginBottom: 8 }}>
                TICKER
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                {QUICK_TICKERS.map((t) => {
                  const on = t === selTicker;
                  return (
                    <button
                      key={t}
                      onClick={() => setSelTicker(t)}
                      style={{
                        fontFamily: MONO, fontSize: 10,
                        color: on ? C.bg0 : C.violet,
                        background: on ? C.violet : "transparent",
                        border: `1px solid ${on ? C.violet : C.violetBorder}`,
                        borderRadius: 4, padding: "5px 10px", cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >{t}</button>
                  );
                })}
              </div>
              <input
                placeholder="or type: AAPL, ETH/USD…"
                value={selTicker}
                onChange={(e) => setSelTicker(e.target.value.toUpperCase())}
                style={selectStyle}
              />
            </div>

            {/* Preview gauge */}
            {(selStrat || selTicker) && (
              <div style={{
                display: "flex", alignItems: "center", gap: 14, marginTop: 14,
                padding: 14, border: `1px solid ${C.violetBorder}`,
                borderRadius: 5, background: "rgba(167,139,250,0.03)",
                animation: "bmg-slideIn 0.2s ease both",
              }}>
                <RadialGauge pct={previewPct} size={52} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: MONO, fontSize: 12, color: C.hi }}>
                    {selTicker || "—"} × {selStrat ? (strategies.find((s) => s.strategy_id === selStrat)?.display_name ?? selStrat) : "—"}
                  </div>
                  <div style={{ fontFamily: MONO, fontSize: 10, color: C.dim, marginTop: 4 }}>
                    est. arm on current setup
                  </div>
                </div>
              </div>
            )}

            <button
              onClick={() => addMut.mutate()}
              disabled={!selStrat || !selTicker || addMut.isPending}
              style={{
                width: "100%", marginTop: 14,
                fontFamily: SANS, fontSize: 13, fontWeight: 600, letterSpacing: "0.04em",
                color: C.bg0, background: C.violet,
                border: "none", borderRadius: 5, padding: 13,
                cursor: (!selStrat || !selTicker || addMut.isPending) ? "not-allowed" : "pointer",
                boxShadow: (!selStrat || !selTicker) ? undefined : "0 0 18px rgba(167,139,250,0.4)",
                opacity: (!selStrat || !selTicker || addMut.isPending) ? 0.45 : 1,
                transition: "all 0.15s ease",
              }}
            >
              {addMut.isPending ? "Arming…" : "⊹ Arm Scout"}
            </button>
          </div>
        </div>

        {/* Fired signals log */}
        <div style={{
          border: `1px solid ${C.greenBorder}`,
          borderRadius: 6, background: C.bg1, overflow: "hidden",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "12px 16px", borderBottom: `1px solid rgba(74,222,128,0.1)`,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%", background: C.green, flexShrink: 0,
              boxShadow: "0 0 6px rgba(74,222,128,0.9)",
              animation: "bmg-pulse 1.6s ease-in-out infinite",
              display: "inline-block",
            }} />
            <span style={{ fontFamily: MONO, fontSize: 12, color: C.body, letterSpacing: "0.06em" }}>
              FIRED SIGNALS
            </span>
            {signals.length > 0 && (
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 9, color: C.faint }}>
                {signals.length}
              </span>
            )}
          </div>

          {signals.length === 0 && (
            <div style={{ padding: "24px 16px", textAlign: "center" }}>
              <div style={{ fontFamily: MONO, fontSize: 10, color: C.faint }}>
                // no signals fired yet — scanning {setups.length} setups ▮
              </div>
            </div>
          )}

          {signals.slice(0, 8).map((sig) => {
            const sideLabel = sig.side === "buy" ? "LONG" : sig.side === "sell" ? "SHORT" : sig.side.toUpperCase();
            const sc = sideColor(sig.side);
            return (
              <div key={sig.id} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 16px",
                borderBottom: `1px solid rgba(74,222,128,0.05)`,
                borderLeft: `2px solid ${C.green}`,
              }}>
                <span style={{ fontFamily: MONO, fontSize: 13, color: C.hi, width: 72, flexShrink: 0 }}>
                  {sig.ticker}
                </span>
                <span style={{ fontFamily: MONO, fontSize: 10, color: C.violet, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {sig.display_name}
                </span>
                <span style={{
                  fontFamily: MONO, fontSize: 9,
                  border: `1px solid ${sc}40`, borderRadius: 3, padding: "2px 5px",
                  color: sc, flexShrink: 0,
                }}>{sideLabel}</span>
                <span style={{ fontFamily: MONO, fontSize: 10, color: C.faint, width: 50, textAlign: "right", flexShrink: 0 }}>
                  {fmtTs(sig.created_at)}
                </span>
                <SignalExplainButton signalId={sig.id} source="scout" />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── ScanTickerTab ─────────────────────────────────────────────────────────────

const QUICK_SCAN_TICKERS = ["NVDA", "TSLA", "AAPL", "AMZN", "SPY", "QQQ", "BTC/USD", "ETH/USD", "SOL/USD"];

function ScanTickerTab() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [result, setResult] = useState<ScanResult | null>(null);

  const scanMut = useMutation({
    mutationFn: () => scanTicker(ticker.trim().toUpperCase()),
    onSuccess: (data) => setResult(data),
    onError: () => toast.error("Scan failed — check ticker symbol"),
  });

  const armMut = useMutation({
    mutationFn: ({ t, sid }: { t: string; sid: string }) => createSetup(t, sid),
    onSuccess: (d) => {
      toast.success(d.already_exists ? "Already in setups" : "⊹ Setup armed");
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
    },
    onError: () => toast.error("Failed to add setup"),
  });

  const submit = () => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setResult(null);
    scanMut.mutate();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Ticker input */}
      <div style={{ border: `1px solid ${C.borderDim}`, borderRadius: 6, background: C.surface, padding: 18 }}>
        <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.18em", marginBottom: 10 }}>
          TICKER — runs all catalog strategies against current market data
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {QUICK_SCAN_TICKERS.map((t) => {
            const on = t === ticker.toUpperCase();
            return (
              <button
                key={t}
                onClick={() => setTicker(t)}
                style={{
                  fontFamily: MONO, fontSize: 10,
                  color: on ? C.bg0 : C.amber,
                  background: on ? C.amber : "transparent",
                  border: `1px solid ${C.amberBorder}`,
                  borderRadius: 4, padding: "5px 10px", cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >{t}</button>
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <input
            placeholder="or type: MSFT, AVAX/USD…"
            value={ticker}
            onChange={(e) => { setTicker(e.target.value.toUpperCase()); setResult(null); }}
            onKeyDown={(e) => e.key === "Enter" && ticker.trim() && submit()}
            style={{
              flex: 1, background: C.bg1, border: `1px solid ${C.borderDim}`,
              borderRadius: 4, padding: "9px 12px",
              fontFamily: MONO, fontSize: 13, color: C.hi, outline: "none",
            }}
          />
          <button
            onClick={submit}
            disabled={!ticker.trim() || scanMut.isPending}
            style={{
              fontFamily: SANS, fontSize: 13, fontWeight: 600,
              color: C.bg0, background: C.amber,
              border: "none", borderRadius: 5, padding: "10px 24px",
              cursor: (!ticker.trim() || scanMut.isPending) ? "not-allowed" : "pointer",
              boxShadow: "0 0 18px rgba(251,191,36,0.35)",
              opacity: (!ticker.trim() || scanMut.isPending) ? 0.5 : 1,
              transition: "all 0.15s ease",
            }}
          >
            {scanMut.isPending ? "Scanning…" : "⊹ Scan"}
          </button>
        </div>
      </div>

      {/* Loading state */}
      {scanMut.isPending && (
        <div style={{ border: `1px solid ${C.amberBorder}`, borderRadius: 6, background: C.surface, padding: "32px 18px", textAlign: "center" }}>
          <div style={{ fontFamily: MONO, fontSize: 12, color: C.amber }}>
            {"// scanning " + ticker.toUpperCase() + " across all strategies ▮"}
          </div>
          <div style={{ width: 200, height: 3, background: "#121a12", borderRadius: 2, margin: "14px auto 0", overflow: "hidden" }}>
            <div style={{ height: "100%", background: C.amber, borderRadius: 2, animation: "bmg-pulse 1s ease infinite", opacity: 0.7 }} />
          </div>
        </div>
      )}

      {/* Results */}
      {result && !scanMut.isPending && (
        <div style={{ border: `1px solid ${C.amberBorder}`, borderRadius: 6, background: C.surface, overflow: "hidden" }}>
          {/* Header */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "12px 16px", borderBottom: `1px solid ${C.borderDim}`,
          }}>
            <div>
              <span style={{ fontFamily: MONO, fontSize: 13, color: C.amber, fontWeight: 500 }}>
                {result.ticker}
              </span>
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.faint, marginLeft: 10 }}>
                {result.results.length > 0 ? `${result.results.length} strategies firing` : "no setups firing"} · {result.bar_count} bars
              </span>
            </div>
            <button
              onClick={() => navigate("/strategy/forge")}
              style={{
                fontFamily: SANS, fontSize: 11, fontWeight: 600,
                color: C.violet, background: C.violetDim,
                border: `1px solid ${C.violetBorder}`, borderRadius: 4,
                padding: "5px 12px", cursor: "pointer", transition: "all 0.15s",
              }}
            >
              ⊹ Build Bot in Forge
            </button>
          </div>

          {/* Conflict warning */}
          {result.conflict_warning && (
            <div style={{
              padding: "10px 16px", borderBottom: `1px solid ${C.borderDim}`,
              background: "rgba(251,191,36,0.06)",
              fontFamily: SANS, fontSize: 12, color: C.amber,
            }}>
              ⚠ {result.conflict_warning}
            </div>
          )}

          {/* Empty */}
          {result.results.length === 0 && (
            <div style={{ padding: "40px 18px", textAlign: "center" }}>
              <div style={{ fontFamily: MONO, fontSize: 11, color: C.faint }}>
                {"// NO_SETUPS_FIRING — no strategies have active signals for " + result.ticker + " right now"}
              </div>
              <div style={{ fontFamily: SANS, fontSize: 12, color: C.dim, marginTop: 8 }}>
                {result.message}
              </div>
            </div>
          )}

          {/* Strategy rank table */}
          {result.results.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${C.borderDim}` }}>
                    {["#", "STRATEGY", "DIRECTION", "CONFIDENCE", "QUALITY", "ACTIONS"].map((col) => (
                      <th key={col} style={{
                        padding: "8px 12px", fontFamily: MONO, fontSize: 9,
                        color: C.faint, letterSpacing: "0.16em", textAlign: "left", fontWeight: 400,
                      }}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.results.map((r, idx) => {
                    const dirColor = r.side === "buy" || r.side === "cover" ? C.green : C.red;
                    const dirLabel = r.side === "buy" || r.side === "cover" ? "LONG" : "SHORT";
                    const qColor = r.setup_quality >= 70 ? C.green : r.setup_quality >= 45 ? C.amber : C.red;
                    return (
                      <tr
                        key={r.strategy_id}
                        style={{ borderBottom: `1px solid rgba(74,222,128,0.04)` }}
                        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "rgba(251,191,36,0.03)")}
                        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
                      >
                        <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 10, color: C.faint }}>{idx + 1}</td>
                        <td style={{ padding: "11px 12px" }}>
                          <div style={{ fontFamily: SANS, fontSize: 13, color: C.hi, fontWeight: 500 }}>{r.display_name}</div>
                          <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, marginTop: 2 }}>{r.category}</div>
                        </td>
                        <td style={{ padding: "11px 12px" }}>
                          <span style={{
                            fontFamily: MONO, fontSize: 9, padding: "2px 7px", borderRadius: 3,
                            border: `1px solid ${dirColor}40`, color: dirColor, background: `${dirColor}10`,
                          }}>{dirLabel}</span>
                        </td>
                        <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 12, color: confColor(r.confidence) }}>
                          {(r.confidence * 100).toFixed(1)}%
                        </td>
                        <td style={{ padding: "11px 12px", fontFamily: MONO, fontSize: 12, color: qColor }}>
                          {r.setup_quality}
                        </td>
                        <td style={{ padding: "11px 12px" }}>
                          <div style={{ display: "flex", gap: 6 }}>
                            <button
                              onClick={() => armMut.mutate({ t: result.ticker, sid: r.strategy_id })}
                              disabled={armMut.isPending}
                              style={{
                                fontFamily: MONO, fontSize: 9, letterSpacing: "0.12em",
                                color: C.violet, background: C.violetDim,
                                border: `1px solid ${C.violetBorder}`, borderRadius: 4,
                                padding: "5px 10px", cursor: "pointer", transition: "all 0.15s",
                              }}
                            >ARM</button>
                            <button
                              onClick={() => navigate(`/strategy/forge`)}
                              style={{
                                fontFamily: MONO, fontSize: 9, letterSpacing: "0.12em",
                                color: C.amber, background: "rgba(251,191,36,0.08)",
                                border: `1px solid ${C.amberBorder}`, borderRadius: 4,
                                padding: "5px 10px", cursor: "pointer", transition: "all 0.15s",
                              }}
                            >FORGE</button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

// ── Quick Lookup panel ────────────────────────────────────────────────────────

function QuickLookupPanel() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<QuickLookupResult[] | null>(null);
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const QUICK_TICKERS = ["NVDA", "AAPL", "TSLA", "SPY", "BTC/USD", "ETH/USD"];

  async function handleLookup(sym?: string) {
    const s = (sym ?? ticker).trim().toUpperCase();
    if (!s) return;
    setTicker(s);
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const data = await quickLookup(s);
      setResults(data.results);
      setSymbol(data.symbol);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Lookup failed — check ticker symbol");
    } finally {
      setLoading(false);
    }
  }

  async function handleArm(strategyId: string) {
    if (!symbol) return;
    try {
      await createSetup(symbol, strategyId);
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
      toast.success(`Armed ${symbol} × ${strategyId}`);
      setTimeout(() => navigate(`/strategy/scout/chart/${symbol}/${strategyId}`), 600);
    } catch {
      toast.error("Failed to arm pairing");
    }
  }

  return (
    <div style={{
      background: C.bg1,
      border: `1px solid ${C.violetBorder}`,
      borderRadius: 8,
      padding: "16px 20px",
      marginBottom: 20,
    }}>
      <div style={{ fontFamily: MONO, fontSize: 10, color: C.violet, letterSpacing: "0.14em", marginBottom: 12 }}>
        // QUICK LOOKUP
      </div>

      {/* Input row */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && handleLookup()}
          placeholder="NVDA, BTC/USD, SPY…"
          style={{
            background: C.bg0, border: `1px solid ${C.borderMid}`,
            borderRadius: 4, padding: "6px 10px",
            fontFamily: MONO, fontSize: 13, color: C.hi,
            outline: "none", width: 180,
          }}
        />
        <button
          onClick={() => handleLookup()}
          disabled={loading || !ticker.trim()}
          style={{
            background: loading ? C.bg2 : C.violet, color: C.bg0,
            border: "none", borderRadius: 4,
            padding: "6px 14px", fontFamily: MONO, fontSize: 11,
            fontWeight: 700, letterSpacing: "0.08em", cursor: loading ? "not-allowed" : "pointer",
            opacity: !ticker.trim() ? 0.4 : 1,
          }}
        >
          {loading ? "SCANNING…" : "FIND SETUPS"}
        </button>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {QUICK_TICKERS.map((t) => (
            <button key={t} onClick={() => handleLookup(t)} disabled={loading}
              style={{
                background: "none", border: `1px solid ${C.borderDim}`,
                borderRadius: 4, padding: "4px 10px",
                fontFamily: MONO, fontSize: 10, color: C.mid,
                cursor: "pointer", opacity: loading ? 0.4 : 1,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = C.violet)}
              onMouseLeave={(e) => (e.currentTarget.style.color = C.mid)}
            >{t}</button>
          ))}
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ marginTop: 14, fontFamily: MONO, fontSize: 11, color: C.dim }}>
          Running 2y walk-forward backtest across strategies… (5-10s first run, cached 1h)
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div style={{ marginTop: 14, fontFamily: MONO, fontSize: 11, color: "#f87171" }}>{error}</div>
      )}

      {/* Results */}
      {results !== null && !loading && (
        <div style={{ marginTop: 14 }}>
          {results.length === 0 ? (
            <div style={{ fontFamily: MONO, fontSize: 11, color: C.dim }}>
              No strategies cleared the quality threshold for {symbol} over 2y. Try a different ticker.
            </div>
          ) : (
            <>
              <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.12em", marginBottom: 8 }}>
                RESULTS — {symbol} — ranked by 2y composite score (Sharpe × Win% × log trades)
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {results.map((r, i) => (
                  <div key={r.strategy_id} style={{
                    display: "flex", alignItems: "center", gap: 12,
                    padding: "8px 10px", borderRadius: 4,
                    background: i === 0 ? "rgba(167,139,250,0.06)" : "transparent",
                    border: `1px solid ${i === 0 ? C.violetBorder : C.borderDim}`,
                    flexWrap: "wrap",
                  }}>
                    {/* Rank */}
                    <span style={{ fontFamily: MONO, fontSize: 10, color: C.faint, width: 18, flexShrink: 0 }}>
                      {i + 1}.
                    </span>
                    {/* Strategy name */}
                    <span style={{ fontFamily: MONO, fontSize: 12, color: i === 0 ? C.violet : C.hi, flex: "1 1 160px" }}>
                      {r.display_name}
                    </span>
                    {/* Metrics */}
                    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                      <span style={{ fontFamily: MONO, fontSize: 10, color: C.mid }}>
                        Sharpe <span style={{ color: r.sharpe >= 1 ? C.green : r.sharpe >= 0.5 ? C.body : C.dim }}>{r.sharpe.toFixed(2)}</span>
                      </span>
                      <span style={{ fontFamily: MONO, fontSize: 10, color: C.mid }}>
                        Win <span style={{ color: r.win_rate_pct >= 55 ? C.green : C.body }}>{r.win_rate_pct.toFixed(0)}%</span>
                      </span>
                      <span style={{ fontFamily: MONO, fontSize: 10, color: C.mid }}>
                        Trades <span style={{ color: C.body }}>{r.trades_per_year}/yr</span>
                      </span>
                    </div>
                    {/* Arm button */}
                    <button
                      onClick={() => handleArm(r.strategy_id)}
                      style={{
                        background: "none", border: `1px solid ${C.violetBorder}`,
                        borderRadius: 4, padding: "3px 10px",
                        fontFamily: MONO, fontSize: 9, color: C.violet,
                        cursor: "pointer", letterSpacing: "0.08em", whiteSpace: "nowrap",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = C.violetDim; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
                    >
                      ARM
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

type Tab = "setups" | "evaluate" | "screen" | "scan";

export default function StrategyScoutPage() {
  const [tab, setTab] = useState<Tab>("setups");

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

  const setups = setupData?.setups ?? [];
  const armedCount = setups.filter((s) => armPct(s.last_confidence) >= 95 || s.status === "fired").length;
  const firedCount = setups.filter((s) => s.status === "fired").length;

  const tabs: { key: Tab; label: string }[] = [
    { key: "setups",   label: `// MY SETUPS${setups.length > 0 ? ` (${setups.length})` : ""}` },
    { key: "scan",     label: "// RANK BY TICKER" },
    { key: "evaluate", label: "// EVALUATE" },
    { key: "screen",   label: "// FIND SETUPS" },
  ];

  if (catalogLoading) {
    return (
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 24px" }}>
        <div style={{ height: 180, borderRadius: 6, background: C.bg1, border: `1px solid ${C.borderDim}`, animation: "bmg-pulse 1.4s ease infinite" }} />
      </div>
    );
  }

  if (catalogError) {
    return (
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 24px" }}>
        <div style={{
          background: C.bg1, border: `1px solid ${C.borderDim}`,
          borderRadius: 6, padding: "40px 24px", textAlign: "center",
        }}>
          <div style={{ fontFamily: MONO, fontSize: 10, color: C.faint, letterSpacing: "0.14em", marginBottom: 12 }}>
            // STRATEGY SCOUT — DISABLED
          </div>
          <div style={{ fontFamily: SANS, fontSize: 16, fontWeight: 600, color: C.hi, marginBottom: 8 }}>
            Strategy Scout is not enabled
          </div>
          <div style={{ fontFamily: SANS, fontSize: 13, color: C.dim }}>
            Set{" "}
            <code style={{ fontFamily: MONO, fontSize: 12, background: C.bg0, border: `1px solid ${C.borderDim}`, borderRadius: 3, padding: "2px 6px", color: C.body }}>
              ENABLE_STRATEGY_SCOUT=true
            </code>{" "}
            in Railway environment variables to activate.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 24px 80px" }}>

      {/* Breadcrumb */}
      <div style={{
        display: "flex", alignItems: "center", gap: 9,
        padding: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.faint,
      }}>
        <span style={{ color: C.mid }}>Strategy Lab</span>
        <span>/</span>
        <span style={{ color: C.violet }}>Scout</span>
      </div>

      {/* Header */}
      <div style={{
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        padding: "14px 0 20px", gap: 20,
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{
              margin: 0, fontFamily: SANS, fontSize: 26, fontWeight: 700,
              letterSpacing: "-0.01em", color: C.hi,
            }}>
              Strategy Scout
            </h1>
            <span style={{
              fontFamily: MONO, fontSize: 9, letterSpacing: "0.08em",
              color: C.violet, background: C.violetDim,
              border: `1px solid ${C.violetBorder}`,
              borderRadius: 3, padding: "3px 8px",
            }}>
              TARGETING
            </span>
          </div>
          <div style={{ fontFamily: MONO, fontSize: 12, color: C.dim, marginTop: 8 }}>
            Match strategies to tickers · fire personal signals the moment a setup arms
          </div>
        </div>

        {/* Stats row */}
        <div style={{ display: "flex", gap: 22, textAlign: "right", flexShrink: 0 }}>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.12em" }}>SCANNING</div>
            <div style={{ fontFamily: MONO, fontSize: 20, color: C.violet, marginTop: 4 }}>{setups.length}</div>
          </div>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.12em" }}>ARMED</div>
            <div style={{ fontFamily: MONO, fontSize: 20, color: C.green, marginTop: 4 }}>{armedCount}</div>
          </div>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9, color: C.faint, letterSpacing: "0.12em" }}>FIRED TODAY</div>
            <div style={{ fontFamily: MONO, fontSize: 20, color: C.body, marginTop: 4 }}>{firedCount}</div>
          </div>
        </div>
      </div>

      {/* Quick Lookup panel */}
      <QuickLookupPanel />

      {/* Tab bar */}
      <div style={{
        display: "flex", gap: 2,
        borderBottom: `1px solid ${C.borderDim}`,
        marginBottom: 20,
      }}>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: "10px 16px",
                fontFamily: MONO, fontSize: 10, letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: active ? C.violet : C.faint,
                background: "none", border: "none", cursor: "pointer",
                borderBottom: active ? `2px solid ${C.violet}` : "2px solid transparent",
                marginBottom: -1,
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLElement).style.color = C.mid; }}
              onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLElement).style.color = C.faint; }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div style={{ animation: "bmg-slideIn 0.18s ease both" }}>
        {tab === "setups"   && <MySetupsView />}
        {tab === "scan"     && <ScanTickerTab />}
        {tab === "evaluate" && <EvaluateTab />}
        {tab === "screen"   && <FindSetupsTab />}
      </div>

      {/* Footer */}
      <div style={{ marginTop: 48, textAlign: "center", fontFamily: MONO, fontSize: 10, color: C.faint }}>
        paper trading · not investment advice · not a registered investment adviser
      </div>
    </div>
  );
}
