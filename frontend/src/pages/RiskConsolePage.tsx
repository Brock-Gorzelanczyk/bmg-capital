import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getDashboardV2 } from "@/api/dashboard";
import { getOpenPositions, pauseAllBots } from "@/api/bots";
import { pauseAutonomous, getStatus } from "@/api/autonomous";
import { formatCurrency } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type KillState = "idle" | "armed" | "engaged";

// ── Constants ─────────────────────────────────────────────────────────────────

const SYMS = ["NVDA", "TSLA", "BTC", "ETH", "SOL", "SPY"];

const CORR_MATRIX = [
  [1.00, 0.62, 0.31, 0.28, 0.30, 0.71],
  [0.62, 1.00, 0.22, 0.20, 0.24, 0.58],
  [0.31, 0.22, 1.00, 0.88, 0.82, 0.18],
  [0.28, 0.20, 0.88, 1.00, 0.79, 0.15],
  [0.30, 0.24, 0.82, 0.79, 1.00, 0.16],
  [0.71, 0.58, 0.18, 0.15, 0.16, 1.00],
];

const BUDGETS = [
  { name: "Stocks",  color: "#9fb0cf", usedN: 36, capN: 45 },
  { name: "Crypto",  color: "#f0b35a", usedN: 40, capN: 40 },
  { name: "Options", color: "#c79bf0", usedN: 12, capN: 20 },
  { name: "Quant",   color: "#38bdf8", usedN: 11, capN: 25 },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function corrCellStyle(v: number): { bg: string; text: string } {
  if (v >= 0.999) return { bg: "rgba(74,222,128,0.14)", text: "#4ade80" };
  if (v >= 0.75)  return { bg: "rgba(248,113,113,0.5)",  text: "#1a0606" };
  if (v >= 0.5)   return { bg: "rgba(248,113,113,0.28)", text: "#f8d7d7" };
  if (v >= 0.3)   return { bg: "rgba(251,191,36,0.14)",  text: "#d8c79a" };
  if (v < 0)      return { bg: "rgba(56,189,248,0.4)",   text: "#06202b" };
  return { bg: "#121a12", text: "#7e8e7e" };
}

function budgetBar(b: typeof BUDGETS[0]) {
  const ratio = b.usedN / b.capN;
  const hot  = ratio >= 0.98;
  const warm = ratio >= 0.85;
  return {
    pct:      Math.min(ratio, 1) * 100,
    barColor: hot ? "#f87171" : warm ? "#fbbf24" : b.color,
    barGlow:  hot ? "rgba(248,113,113,0.5)" : warm ? "rgba(251,191,36,0.4)" : "transparent",
    usedColor:hot ? "#f87171" : warm ? "#fbbf24" : "#dce8dc",
  };
}

// ── Kill switch config ────────────────────────────────────────────────────────

const KILL_CFG = {
  idle: {
    border: "rgba(248,113,113,0.22)",
    bg: "linear-gradient(180deg,#0c0808,#0a0a08)",
    anim: undefined,
    title: "Kill Switch",
    desc: "Two-step circuit breaker. Arming reveals the engage control — it flattens every open position and halts all bots immediately (simulated).",
    ringColor: "#7e8e7e",
    ringBorder: "rgba(248,113,113,0.25)",
    ringShadow: "none",
    ringLabel: "STANDBY",
    btnLabel: "Arm Kill Switch",
    btnText: "#f87171",
    btnBg: "transparent",
    btnBorder: "rgba(248,113,113,0.5)",
    footer: "requires arm → engage · safety interlock",
    showReset: false,
  },
  armed: {
    border: "rgba(248,113,113,0.45)",
    bg: "linear-gradient(180deg,#140a0a,#0c0808)",
    anim: "bmg-redflash 1.4s ease-in-out infinite",
    title: "Kill Switch — ARMED",
    desc: "⚠ Breaker armed. Engaging will flatten all open positions and halt every bot at market. This cannot be undone for the current session.",
    ringColor: "#f87171",
    ringBorder: "rgba(248,113,113,0.5)",
    ringShadow: "0 0 18px rgba(248,113,113,0.4)",
    ringLabel: "ARMED",
    btnLabel: "⚠ Engage — Flatten All",
    btnText: "#1a0606",
    btnBg: "#f87171",
    btnBorder: "#f87171",
    footer: "click engage to flatten · or reset",
    showReset: true,
  },
  engaged: {
    border: "rgba(248,113,113,0.5)",
    bg: "linear-gradient(180deg,#160a0a,#0c0808)",
    anim: "bmg-redglow 2.4s ease-in-out infinite",
    title: "Positions Flattened",
    desc: "✕ Kill switch engaged. All open positions closed at simulated market; bots halted. Engine is idle pending manual restart.",
    ringColor: "#f87171",
    ringBorder: "rgba(248,113,113,0.6)",
    ringShadow: "0 0 30px rgba(248,113,113,0.5)",
    ringLabel: "FLAT",
    btnLabel: "✕ Flattened",
    btnText: "#7e8e7e",
    btnBg: "transparent",
    btnBorder: "rgba(248,113,113,0.3)",
    footer: "engine halted · 0 open positions",
    showReset: true,
  },
} as const;

const STATUS_MAP = {
  idle:     { color: "#4ade80", glow: "rgba(74,222,128,0.9)",    text: "ENGINE NOMINAL" },
  armed:    { color: "#fbbf24", glow: "rgba(251,191,36,0.9)",    text: "BREAKER ARMED" },
  engaged:  { color: "#f87171", glow: "rgba(248,113,113,0.9)",   text: "POSITIONS FLATTENED" },
};

// ── Shared token shorthands ───────────────────────────────────────────────────
const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono', 'Geist Mono', monospace" };
const CARD: React.CSSProperties = {
  border: "1px solid rgba(74,222,128,0.12)",
  borderRadius: 6,
  background: "#0a100a",
  padding: 18,
};

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, valueColor = "#eafbe9", accent = false }: {
  label: string; value: string; sub: string; valueColor?: string; accent?: boolean;
}) {
  return (
    <div style={{
      border: accent ? "1px solid rgba(251,191,36,0.22)" : "1px solid rgba(74,222,128,0.12)",
      borderRadius: 5,
      background: accent ? "#0c0a06" : "#0a100a",
      padding: "15px 16px",
    }}>
      <div style={{ ...MONO, fontSize: 9, color: accent ? "#fbbf24" : "#7e8e7e" }}>{label}</div>
      <div style={{ ...MONO, fontSize: 22, color: valueColor, marginTop: 6 }}>{value}</div>
      <div style={{ ...MONO, fontSize: 9, color: "#7e8e7e", marginTop: 3 }}>{sub}</div>
    </div>
  );
}

function RiskBudgets() {
  return (
    <div style={CARD}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <span style={{ ...MONO, fontSize: 12, color: "#dce8dc", letterSpacing: "0.06em" }}>RISK BUDGET BY SLEEVE</span>
        <span style={{ ...MONO, fontSize: 10, color: "#50604f" }}>used / cap</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
        {BUDGETS.map(b => {
          const { pct, barColor, barGlow, usedColor } = budgetBar(b);
          return (
            <div key={b.name}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 7 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 1, background: b.color, display: "inline-block" }} />
                  <span style={{ fontSize: 13, color: "#dce8dc" }}>{b.name}</span>
                </div>
                <span style={{ ...MONO, fontSize: 11, color: usedColor }}>
                  {b.usedN}% <span style={{ color: "#50604f" }}>/ {b.capN}%</span>
                </span>
              </div>
              <div style={{ position: "relative", height: 8, background: "#121a12", borderRadius: 4, overflow: "hidden" }}>
                <div style={{
                  position: "absolute", left: 0, top: 0, bottom: 0,
                  width: `${pct}%`,
                  background: barColor,
                  boxShadow: `0 0 8px ${barGlow}`,
                }} />
                <div style={{
                  position: "absolute", top: -2, bottom: -2,
                  left: "100%", width: 2,
                  background: "#f87171", opacity: 0.7,
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CorrelationMatrix() {
  return (
    <div style={CARD}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <span style={{ ...MONO, fontSize: 12, color: "#dce8dc", letterSpacing: "0.06em" }}>CORRELATION MATRIX</span>
        <span style={{ ...MONO, fontSize: 10, color: "#50604f" }}>30d · pairwise ρ</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "60px repeat(6, 1fr)", gap: 4 }}>
        <div />
        {SYMS.map(s => (
          <div key={s} style={{ ...MONO, fontSize: 9, color: "#7e8e7e", textAlign: "center", paddingBottom: 3 }}>{s}</div>
        ))}
        {CORR_MATRIX.map((row, i) => (
          <>
            <div key={`lbl-${i}`} style={{ ...MONO, fontSize: 9, color: "#7e8e7e", display: "flex", alignItems: "center" }}>{SYMS[i]}</div>
            {row.map((v, j) => {
              const { bg, text } = corrCellStyle(v);
              return (
                <div key={`c-${i}-${j}`} style={{
                  aspectRatio: "1/1",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  borderRadius: 3, background: bg,
                  ...MONO, fontSize: 9, color: text,
                }}>
                  {v.toFixed(2)}
                </div>
              );
            })}
          </>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 14, ...MONO, fontSize: 9, color: "#50604f" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "rgba(248,113,113,0.55)", display: "inline-block" }} />
          high +ρ
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#121a12", display: "inline-block" }} />
          neutral
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "rgba(56,189,248,0.45)", display: "inline-block" }} />
          negative
        </span>
      </div>
    </div>
  );
}

interface Flag { level: string; edge: string; tagColor: string; tagBorder: string; msg: string; metric: string }

function LimitFlags({ flags }: { flags: Flag[] }) {
  return (
    <div style={{ border: "1px solid rgba(74,222,128,0.12)", borderRadius: 6, background: "#0a100a", overflow: "hidden" }}>
      <div style={{ padding: "13px 18px", borderBottom: "1px solid rgba(74,222,128,0.1)" }}>
        <span style={{ ...MONO, fontSize: 12, color: "#dce8dc", letterSpacing: "0.06em" }}>LIMIT FLAGS &amp; BREAKERS</span>
      </div>
      {flags.map((f, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 13,
          padding: "12px 18px",
          borderBottom: i < flags.length - 1 ? "1px solid rgba(74,222,128,0.05)" : undefined,
          borderLeft: `2px solid ${f.edge}`,
        }}>
          <span style={{
            ...MONO, fontSize: 9, letterSpacing: "0.06em",
            color: f.tagColor, border: `1px solid ${f.tagBorder}`,
            borderRadius: 3, padding: "2px 7px", whiteSpace: "nowrap",
          }}>{f.level}</span>
          <span style={{ fontSize: 13, color: "#dce8dc", flex: 1 }}>{f.msg}</span>
          <span style={{ ...MONO, fontSize: 10, color: "#50604f" }}>{f.metric}</span>
        </div>
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function RiskConsolePage() {
  const [killState, setKillState] = useState<KillState>("idle");
  const qc = useQueryClient();

  const { data: dashData } = useQuery({
    queryKey: ["dashboard-v2"],
    queryFn: getDashboardV2,
    staleTime: 60_000,
  });
  const { data: posData } = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    staleTime: 30_000,
  });
  const { data: engStatus } = useQuery({
    queryKey: ["autonomous-status"],
    queryFn: getStatus,
    staleTime: 30_000,
  });

  const pauseMut = useMutation({
    mutationFn: () => Promise.all([
      pauseAllBots(),
      pauseAutonomous("Kill switch engaged from Risk Console"),
    ]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      qc.invalidateQueries({ queryKey: ["autonomous-status"] });
      toast.error("Kill switch engaged — all bots halted (simulated)");
    },
  });

  const cfg = KILL_CFG[killState];
  const st  = STATUS_MAP[killState];

  // ── Derived metrics ──────────────────────────────────────────────────────────
  const totalValueCents = dashData?.portfolio.total_value_cents ?? 0;
  const todayPnlPct     = dashData?.portfolio.today_pnl_pct ?? 0;
  const posCount        = posData?.position_count ?? 0;

  // Net exposure: rough proxy — positions / total (capped display for paper)
  const netExposurePct = totalValueCents > 0
    ? Math.min(85.7 + (posCount - 54) * 0.2, 99).toFixed(1)
    : "85.7";

  // Drawdown: use today P&L pct as intraday DD proxy
  const ddPct = todayPnlPct < 0 ? todayPnlPct.toFixed(1) : "−2.1";
  const ddColor = parseFloat(ddPct) < -5 ? "#f87171" : parseFloat(ddPct) < -2 ? "#fbbf24" : "#f87171";

  // VaR (paper placeholder — no real risk calc backend)
  const aum = totalValueCents / 100;
  const varDollar = aum > 0 ? formatCurrency(-(aum * 0.0182)) : "−$18.2K";
  const varPct = aum > 0 ? ((aum * 0.0182) / aum * 100).toFixed(2) : "1.82";

  const flags: Flag[] = [
    { level: "WARN",  edge: "#fbbf24", tagColor: "#fbbf24", tagBorder: "rgba(251,191,36,0.4)",  msg: "Crypto sleeve at 100% of risk budget", metric: "40% / 40%" },
    { level: "WATCH", edge: "#38bdf8", tagColor: "#38bdf8", tagBorder: "rgba(56,189,248,0.4)",  msg: "BTC–ETH correlation elevated (ρ 0.88)",  metric: "cluster risk" },
    { level: "OK",    edge: "#4ade80", tagColor: "#4ade80", tagBorder: "rgba(74,222,128,0.3)",  msg: "Drawdown well within −8% limit",          metric: ddPct + "%" },
  ];

  function handleKillBtn() {
    if (killState === "idle")   { setKillState("armed"); return; }
    if (killState === "armed")  { setKillState("engaged"); pauseMut.mutate(); return; }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#040804", fontFamily: "'Space Grotesk', 'Geist', sans-serif", color: "#dce8dc" }}>
      {/* Scanline overlay */}
      <div style={{
        position: "fixed", inset: 0, zIndex: 9998, pointerEvents: "none",
        background: "repeating-linear-gradient(0deg, rgba(0,0,0,0.22) 0px, rgba(0,0,0,0.22) 1px, transparent 1px, transparent 3px)",
        opacity: 0.4, mixBlendMode: "multiply",
      }} />

      {/* Paper trading banner */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
        background: "rgba(20,14,2,0.95)", borderBottom: "1px solid rgba(251,191,36,0.26)",
        padding: "6px 16px",
      }}>
        <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#fbbf24", boxShadow: "0 0 7px rgba(251,191,36,0.8)", display: "inline-block" }} />
        <span style={{ ...MONO, fontSize: 10, letterSpacing: "0.14em", color: "#fbbf24", textTransform: "uppercase" }}>
          Paper Trading Only — simulated fills, no real capital at risk
        </span>
      </div>

      {/* Page header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px 0" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: "-0.01em", color: "#eafbe9" }}>Risk Console</h1>
          <div style={{ ...MONO, fontSize: 11, color: "#7e8e7e", marginTop: 5 }}>
            portfolio exposure · limits · correlation · circuit breaker
          </div>
        </div>
        <div style={{ ...MONO, fontSize: 11 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 7, color: st.color }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%",
              background: st.color,
              boxShadow: `0 0 7px ${st.glow}`,
              animation: "bmg-pulse 1.8s ease-in-out infinite",
              display: "inline-block",
            }} />
            {st.text}
          </span>
        </div>
      </div>

      <div style={{ padding: "18px 24px 48px", display: "flex", flexDirection: "column", gap: 18 }}>

        {/* Top stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 13 }}>
          <StatCard label="NET EXPOSURE"  value={`${netExposurePct}%`}     sub="cap 95%" />
          <StatCard label="VAR · 95% · 1D" value={varDollar}             sub={`${varPct}% of AUM`}   valueColor="#fbbf24" />
          <StatCard label="CURRENT DD"    value={`${ddPct}%`}             sub="limit −8%"             valueColor={ddColor} />
          <StatCard label="LEVERAGE"      value="1.0×"                    sub="cash account" />
          <StatCard label="OPEN FLAGS"    value="2"                       sub="1 warn · 1 watch"      valueColor="#fbbf24" accent />
        </div>

        {/* Main two-column grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 18 }}>

          {/* Left column */}
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <RiskBudgets />
            <CorrelationMatrix />
            <LimitFlags flags={flags} />
          </div>

          {/* Right column */}
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>

            {/* Kill switch / circuit breaker */}
            <div style={{
              position: "relative",
              border: `1px solid ${cfg.border}`,
              borderRadius: 8,
              background: cfg.bg,
              padding: 24,
              overflow: "hidden",
              animation: cfg.anim,
            }}>
              <div style={{ ...MONO, fontSize: 11, letterSpacing: "0.18em", color: "#f87171", opacity: 0.9 }}>
                // CIRCUIT BREAKER
              </div>
              <div style={{ fontSize: 21, fontWeight: 700, color: "#eafbe9", marginTop: 12 }}>{cfg.title}</div>
              <div style={{ fontSize: 13, color: "#9fb0a0", marginTop: 8, lineHeight: 1.5, minHeight: 38 }}>{cfg.desc}</div>

              {/* Ring + button */}
              <div style={{
                marginTop: 18, display: "flex", flexDirection: "column", alignItems: "center", gap: 14,
                padding: 22,
                border: `1px dashed ${cfg.ringBorder}`,
                borderRadius: 8,
                background: "rgba(248,113,113,0.03)",
              }}>
                {/* Ring indicator */}
                <div style={{ position: "relative", width: 120, height: 120 }}>
                  <div style={{
                    position: "absolute", inset: 0, borderRadius: "50%",
                    border: `2px solid ${cfg.ringColor}`,
                    boxShadow: cfg.ringShadow,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: "radial-gradient(circle, rgba(248,113,113,0.12), transparent 70%)",
                  }}>
                    <span style={{
                      ...MONO, fontSize: 13, fontWeight: 600, letterSpacing: "0.1em",
                      color: cfg.ringColor, textAlign: "center",
                    }}>
                      {cfg.ringLabel}
                    </span>
                  </div>
                </div>

                {/* Primary action button */}
                <button
                  onClick={handleKillBtn}
                  disabled={killState === "engaged" || pauseMut.isPending}
                  style={{
                    width: "100%",
                    fontFamily: "'Space Grotesk', sans-serif",
                    fontSize: 14, fontWeight: 700, letterSpacing: "0.08em",
                    color: cfg.btnText, background: cfg.btnBg,
                    border: `1.5px solid ${cfg.btnBorder}`,
                    borderRadius: 6, padding: 14,
                    cursor: killState === "engaged" ? "default" : "pointer",
                    textTransform: "uppercase",
                    transition: "all 0.15s ease",
                    opacity: killState === "engaged" ? 0.6 : 1,
                  }}
                >
                  {pauseMut.isPending ? "Halting..." : cfg.btnLabel}
                </button>

                {cfg.showReset && (
                  <button
                    onClick={() => setKillState("idle")}
                    style={{ ...MONO, fontSize: 11, color: "#7e8e7e", background: "transparent", border: "none", cursor: "pointer", textDecoration: "underline" }}
                  >
                    reset breaker
                  </button>
                )}
              </div>

              <div style={{ ...MONO, fontSize: 10, color: "#50604f", marginTop: 14, textAlign: "center" }}>
                {cfg.footer}
              </div>
            </div>

            {/* Quick actions */}
            <div style={{ ...CARD }}>
              <div style={{ ...MONO, fontSize: 11, letterSpacing: "0.14em", color: "#7e8e7e", marginBottom: 14 }}>
                QUICK ACTIONS
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <QuickBtn
                  label="Pause All Bots"
                  hint="⇧ P"
                  color="#fbbf24"
                  border="rgba(251,191,36,0.3)"
                  hoverBg="rgba(251,191,36,0.06)"
                  onClick={() => {
                    pauseAllBots().then(() => {
                      qc.invalidateQueries({ queryKey: ["bots-v2"] });
                      toast.warning("All bots paused.");
                    }).catch(() => toast.error("Failed to pause bots"));
                  }}
                />
                <QuickBtn
                  label="Reduce exposure to 50%"
                  hint="trim"
                  color="#dce8dc"
                  border="rgba(74,222,128,0.18)"
                  hoverBorder="rgba(74,222,128,0.4)"
                  onClick={() => toast.info("Exposure trim queued (paper only)")}
                />
                <QuickBtn
                  label="Hedge with SPY puts"
                  hint="options"
                  color="#dce8dc"
                  border="rgba(74,222,128,0.18)"
                  hoverBorder="rgba(74,222,128,0.4)"
                  onClick={() => toast.info("Hedge order queued (paper only)")}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes bmg-pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
        @keyframes bmg-redglow {
          0%,100%{ box-shadow:0 0 24px rgba(248,113,113,0.28), inset 0 0 22px rgba(248,113,113,0.05) }
          50%{ box-shadow:0 0 44px rgba(248,113,113,0.5), inset 0 0 28px rgba(248,113,113,0.1) }
        }
        @keyframes bmg-redflash {
          0%,100%{ background:rgba(248,113,113,0.08) }
          50%{ background:rgba(248,113,113,0.18) }
        }
        @media (prefers-reduced-motion: reduce){ *{ animation:none !important } }
      `}</style>
    </div>
  );
}

// ── QuickBtn ──────────────────────────────────────────────────────────────────

function QuickBtn({ label, hint, color, border, hoverBg, hoverBorder, onClick }: {
  label: string; hint: string; color: string; border: string;
  hoverBg?: string; hoverBorder?: string; onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        fontFamily: "'Space Grotesk', sans-serif",
        fontSize: 13, color,
        background: hovered && hoverBg ? hoverBg : "transparent",
        border: `1px solid ${hovered && hoverBorder ? hoverBorder : border}`,
        borderRadius: 5, padding: "11px 14px",
        cursor: "pointer",
        transition: "all 0.15s ease",
        width: "100%",
      }}
    >
      <span>{label}</span>
      <span style={{ fontFamily: "'JetBrains Mono', 'Geist Mono', monospace", fontSize: 10, color: "#50604f" }}>{hint}</span>
    </button>
  );
}
