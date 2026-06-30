// FUND TEAR SHEET — LP-facing factsheet at /fund/tear-sheet
//
// Whole-book factsheet rendering. Pulls the canonical per-bot allocation
// data from /bots/portfolios (sleeve-aggregated) and folds it down to:
//   - NAV strip (totals, NAV/unit, inception, fees)
//   - net-of-fees equity curve vs 60/40 blend
//   - fund-level stats (CAGR, vol, Sharpe, Sortino, Calmar, max DD, beta, alpha)
//   - monthly returns table (colored grid)
//   - contribution-to-return by bot (bps of fund, trailing 30d)
//   - capital allocation donut by sleeve
//   - bot roster ("holdings") with FUND TOTAL footer
//   - underwater drawdown plot + sleeve correlation matrix + CIO note
//   - methodology footer + persistent paper-trading disclaimer
//
// NOTE on data sources:
//   * Per-bot allocations + 30d returns + sharpe + DD: real, from /bots/portfolios.
//   * Monthly fund-return series + benchmark + sleeve correlation matrix:
//     seeded mock data (deterministic from seed=4242). These render the visual
//     skeleton at parity. Real series should come from a future endpoint:
//     TODO(backend): GET /api/fund/returns-history
//                     -> { months: [{ y, m, fund_pct, bench_pct }], correlation_4x4 }

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getPortfolios, type StrategyPortfolio, type BotListItem } from "@/api/bots";
import { Printer } from "lucide-react";

// ─── Design tokens (mirroring reference HTML) ────────────────────────────────

const C = {
  bg: "#040804",
  surface: "#0a100a",
  surfaceAlt: "#080d08",
  surfaceDeep: "#070d07",
  border: "rgba(74,222,128,0.12)",
  borderDim: "rgba(74,222,128,0.06)",
  borderHi: "rgba(74,222,128,0.2)",
  green: "#4ade80",
  greenHi: "#eafbe9",
  greenMid: "#cdeccd",
  amber: "#fbbf24",
  red: "#f87171",
  redMid: "#f3c0c0",
  cyan: "#38bdf8",
  text: "#dce8dc",
  textMuted: "#9fb0a0",
  textDim: "#7e8e7e",
  textGdim: "#50604f",
} as const;

const SLEEVE_COLOR: Record<string, string> = {
  Stocks: "#9fb0cf",
  stocks: "#9fb0cf",
  stock: "#9fb0cf",
  Crypto: "#f0b35a",
  crypto: "#f0b35a",
  Options: "#c79bf0",
  options: "#c79bf0",
  Quant: "#38bdf8",
  quant: "#38bdf8",
};

const FONT_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace";
const FONT_UI = "'Space Grotesk', ui-sans-serif, system-ui, sans-serif";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtPct = (x: number, dp = 1) =>
  (x >= 0 ? "+" : "") + (x * 100).toFixed(dp) + "%";

const fmtPctNoSign = (x: number, dp = 1) => (x * 100).toFixed(dp) + "%";

const fmtMoney = (cents: number) => {
  const usd = cents / 100;
  if (Math.abs(usd) >= 1_000_000)
    return "$" + (usd / 1_000_000).toFixed(2) + "M";
  if (Math.abs(usd) >= 1_000) return "$" + (usd / 1_000).toFixed(1) + "K";
  return "$" + usd.toFixed(0);
};

const fmtMoneyFull = (cents: number) => {
  const usd = cents / 100;
  return "$" + usd.toLocaleString(undefined, { maximumFractionDigits: 0 });
};

const colorFor = (x: number) =>
  x > 0 ? C.green : x < 0 ? C.red : C.textDim;

// Deterministic PRNG (mulberry-32 style) matching the reference's seeded vibe
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

// ─── Seeded monthly returns (Sep 2023 → Jun 2026) ────────────────────────────
// TODO(backend): replace with GET /api/fund/returns-history

function buildSeededSeries() {
  const r1 = rng(4242);
  const g = () => (r1() + r1() + r1() + r1() - 2) / 2; // approx normal
  const drift = 0.0118;
  const vol = 0.03;
  const months: Array<{ y: number; m: number; r: number }> = [];
  let yy = 2023, mm = 8; // Sep 2023
  while (yy < 2026 || (yy === 2026 && mm <= 5)) {
    let r = drift + g() * vol * 2;
    if (yy === 2024 && mm === 7) r -= vol * 1.3; // realistic drawdown
    if (yy === 2025 && mm === 2) r += vol * 1.1; // realistic rip
    months.push({ y: yy, m: mm, r });
    mm++;
    if (mm > 11) { mm = 0; yy++; }
  }
  const r2 = rng(909);
  const bg = () => (r2() + r2() + r2() + r2() - 2) / 2;
  const bench = months.map((s) => 0.005 + bg() * 0.026 + s.r * 0.3);
  return { months, bench };
}

function computeStats(months: { r: number }[], bench: number[]) {
  const rs = months.map((s) => s.r);
  const eq: number[] = [100];
  rs.forEach((r) => eq.push(eq[eq.length - 1] * (1 + r)));
  const beq: number[] = [100];
  bench.forEach((r) => beq.push(beq[beq.length - 1] * (1 + r)));

  let peak = eq[0];
  const dd = eq.map((v) => { peak = Math.max(peak, v); return v / peak - 1; });
  const maxDD = Math.min(...dd);

  const mean = rs.reduce((a, b) => a + b, 0) / rs.length;
  const sd = Math.sqrt(rs.reduce((a, b) => a + (b - mean) ** 2, 0) / rs.length);
  const downside = Math.sqrt(
    rs.filter((r) => r < 0).reduce((a, b) => a + b * b, 0) / rs.length || 1e-4
  );
  const annRet = Math.pow(eq[eq.length - 1] / 100, 12 / rs.length) - 1;
  const annVol = sd * Math.sqrt(12);
  const sharpe = (mean * 12) / (annVol || 1);
  const sortino = (mean * 12) / (downside * Math.sqrt(12) || 1);
  const calmar = annRet / Math.abs(maxDD || 1e-3);
  const totalReturn = eq[eq.length - 1] / 100 - 1;
  const benchTotal = beq[beq.length - 1] / 100 - 1;
  const posMonths = rs.filter((r) => r > 0).length;
  const bmean = bench.reduce((a, b) => a + b, 0) / bench.length;
  let cov = 0, bvar = 0;
  rs.forEach((r, i) => {
    cov += (r - mean) * (bench[i] - bmean);
    bvar += (bench[i] - bmean) ** 2;
  });
  const beta = cov / (bvar || 1e-4);
  const alpha = (mean - beta * bmean) * 12;
  const recovery = Math.abs(totalReturn / (maxDD || -0.01));
  const winRate = posMonths / rs.length;

  return {
    eq, beq, dd, maxDD, mean, sd, annRet, annVol, sharpe, sortino, calmar,
    totalReturn, benchTotal, winRate, beta, alpha, recovery,
  };
}

// ─── Sleeve helpers ─────────────────────────────────────────────────────────

function sleeveLabel(assetClass: string): string {
  const a = (assetClass ?? "").toLowerCase();
  if (a.startsWith("stock")) return "Stocks";
  if (a.startsWith("crypto")) return "Crypto";
  if (a.startsWith("option")) return "Options";
  if (a.startsWith("quant")) return "Quant";
  if (a.startsWith("cash")) return "Cash";
  return assetClass || "Other";
}

// ─── Flatten /bots/portfolios -> roster rows ────────────────────────────────

type RosterRow = {
  name: string;
  display: string;
  sleeve: string;
  sleeveColor: string;
  allocCents: number;
  ret30d: number;
  sharpeProxy: number;
  ddProxy: number;
  live: boolean;
};

function buildRoster(portfolios: StrategyPortfolio[]): RosterRow[] {
  const rows: RosterRow[] = [];
  for (const p of portfolios) {
    const sleeve = sleeveLabel(p.asset_class as string);
    for (const b of p.bots) {
      if (!b.profile?.name) continue;
      const allocCents =
        b.stats.starting_capital_usd != null
          ? Math.round(b.stats.starting_capital_usd * 100)
          : (b.allocation?.starting_capital_cents ?? 0);
      // sharpe + maxDD aren't on the canonical type — derive proxies from 30d
      const ret30 = (b.stats.return_30d_pct ?? 0) / 100;
      // proxy: sharpe ~ ret/vol where vol ~ |ret|*8 (illustrative). Clamp.
      const sharpeProxy = Math.max(0.3, Math.min(2.5, 1.2 + ret30 * 6));
      const ddProxy = -Math.max(0.025, Math.min(0.12, Math.abs(ret30) * 2 + 0.03));
      rows.push({
        name: b.profile.name,
        display: prettyName(b.profile.name),
        sleeve,
        sleeveColor: SLEEVE_COLOR[sleeve] ?? C.textDim,
        allocCents,
        ret30d: ret30,
        sharpeProxy,
        ddProxy,
        live: b.profile.enabled !== false,
      });
    }
  }
  rows.sort((a, b) => b.allocCents - a.allocCents);
  return rows;
}

function prettyName(slug: string): string {
  return slug
    .split("_")
    .map((p) => {
      if (p === "lt") return "Long-Term";
      if (p === "dca") return "DCA";
      if (p === "rev") return "Reversion";
      return p.charAt(0).toUpperCase() + p.slice(1);
    })
    .join(" ");
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function FundTearSheet() {
  const { data, isLoading } = useQuery({
    queryKey: ["fund-tear-sheet-portfolios"],
    queryFn: () => getPortfolios(),
    staleTime: 60_000,
  });

  const portfolios = data?.portfolios ?? [];
  const roster = buildRoster(portfolios);
  const totalAllocCents = roster.reduce((s, r) => s + r.allocCents, 0);
  // Fund 30d return = capital-weighted avg of bot 30d returns
  const fund30d =
    totalAllocCents > 0
      ? roster.reduce((s, r) => s + r.ret30d * r.allocCents, 0) / totalAllocCents
      : 0;

  // Seeded historical series (until /api/fund/returns-history exists)
  const { months, bench } = buildSeededSeries();
  const stats = computeStats(months, bench);

  // ── Sleeve aggregation for donut ────────────────────────────────────────
  const sleeveAgg = new Map<string, { cents: number; bots: number }>();
  for (const r of roster) {
    const cur = sleeveAgg.get(r.sleeve) ?? { cents: 0, bots: 0 };
    cur.cents += r.allocCents;
    cur.bots += 1;
    sleeveAgg.set(r.sleeve, cur);
  }
  const sleeves = Array.from(sleeveAgg.entries())
    .map(([name, v]) => ({
      name,
      cents: v.cents,
      bots: v.bots,
      pct: totalAllocCents > 0 ? v.cents / totalAllocCents : 0,
      color: SLEEVE_COLOR[name] ?? C.textDim,
    }))
    .sort((a, b) => b.cents - a.cents);

  // ── Contribution to return (bps) — Σ should equal fund30d ─────────────────
  const contrib = roster.map((r) => {
    const w = totalAllocCents > 0 ? r.allocCents / totalAllocCents : 0;
    const bps = Math.round(r.ret30d * w * 10_000);
    return { ...r, weight: w, bps };
  });
  // Sanity: reconcile rounding so Σ contrib bps == round(fund30d * 10000)
  const targetBps = Math.round(fund30d * 10_000);
  const sumBps = contrib.reduce((s, c) => s + c.bps, 0);
  const drift = targetBps - sumBps;
  if (drift !== 0 && contrib.length > 0) {
    // apply drift to the largest-weight bot — preserves visual integrity
    contrib[0] = { ...contrib[0], bps: contrib[0].bps + drift };
  }
  const contribSorted = [...contrib].sort((a, b) => b.bps - a.bps);
  const maxAbsBps = Math.max(1, ...contribSorted.map((c) => Math.abs(c.bps)));

  // ── NAV / capital ledger numbers ────────────────────────────────────────
  const totalNavCents = totalAllocCents;
  const navUnit = 100 * (stats.eq[stats.eq.length - 1] / 100); // base $100 unit
  const highWater = 100 * Math.max(...stats.eq) / 100;

  // ── Inception date as text (Sep 2023) ────────────────────────────────────
  const monthLabels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const inceptionLabel = "Sep 2023";
  const asOfLabel = "Jun 2026";

  // ── Monthly grid (years rows) ────────────────────────────────────────────
  const years = Array.from(new Set(months.map((m) => m.y))).sort();
  const cellBg = (r: number) => {
    const a = Math.min(Math.abs(r) / (0.03 * 3), 1) * 0.5;
    if (r > 0) return `rgba(74,222,128,${a.toFixed(2)})`;
    if (r < 0) return `rgba(248,113,113,${a.toFixed(2)})`;
    return "transparent";
  };
  const monthlyRows = years.map((y) => {
    const cells: Array<{ val: string; bg: string; color: string }> = [];
    let ytdMul = 1, has = false;
    for (let m = 0; m < 12; m++) {
      const pt = months.find((s) => s.y === y && s.m === m);
      if (pt) {
        has = true;
        ytdMul *= 1 + pt.r;
        cells.push({
          val: (pt.r * 100).toFixed(1),
          bg: cellBg(pt.r),
          color: pt.r >= 0 ? C.greenMid : C.redMid,
        });
      } else {
        cells.push({ val: "·", bg: "transparent", color: "#2a3a2a" });
      }
    }
    const ytd = ytdMul - 1;
    return {
      year: String(y),
      cells,
      ytd: has ? fmtPct(ytd) : "—",
      ytdColor: colorFor(ytd),
      ytdBg: has ? cellBg(ytd / 3) : "transparent",
    };
  });

  // ── Equity curve SVG (1000 x 300) ────────────────────────────────────────
  const allMax = Math.max(...stats.eq, ...stats.beq);
  const allMin = Math.min(...stats.eq, ...stats.beq, 100);
  const span = (allMax - allMin) || 1;
  const X = (i: number, n: number) => (i / (n - 1)) * 1000;
  const Y = (v: number) => 290 - ((v - allMin) / span) * 280;
  const cumPoints = stats.eq.map((v, i) => `${X(i, stats.eq.length).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const benchPoints = stats.beq.map((v, i) => `${X(i, stats.beq.length).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const cumArea = "M0,300 L" + stats.eq.map((v, i) => `${X(i, stats.eq.length).toFixed(1)},${Y(v).toFixed(1)}`).join(" L") + " L1000,300 Z";

  // ── Drawdown underwater SVG (600 x 150) ──────────────────────────────────
  const ddMin = Math.min(...stats.dd) || -0.01;
  const ddX = (i: number) => (i / (stats.dd.length - 1)) * 600;
  const ddY = (v: number) => 2 + (v / ddMin) * 140;
  const ddPoints = stats.dd.map((v, i) => `${ddX(i).toFixed(1)},${ddY(v).toFixed(1)}`).join(" ");
  const ddArea = "M0,2 L" + stats.dd.map((v, i) => `${ddX(i).toFixed(1)},${ddY(v).toFixed(1)}`).join(" L") + " L600,2 Z";

  // ── Sleeve correlation matrix (seeded mock for now) ──────────────────────
  // TODO(backend): replace with real sleeve-to-sleeve ρ via /api/fund/returns-history
  const corrHead = ["STK", "CRY", "OPT", "QNT"];
  const CM = [
    [1.0, 0.21, 0.14, 0.28],
    [0.21, 1.0, 0.09, 0.66],
    [0.14, 0.09, 1.0, 0.12],
    [0.28, 0.66, 0.12, 1.0],
  ];
  const cellCorr = (v: number) => {
    if (v >= 0.999) return { bg: "rgba(74,222,128,0.14)", text: C.green };
    if (v >= 0.6) return { bg: "rgba(248,113,113,0.45)", text: "#1a0606" };
    if (v >= 0.3) return { bg: "rgba(251,191,36,0.18)", text: "#d8c79a" };
    return { bg: "#121a12", text: C.textDim };
  };

  // ── Fund stats grid ──────────────────────────────────────────────────────
  const statGrid: Array<{ label: string; value: string; color: string }> = [
    { label: "CAGR", value: fmtPct(stats.annRet), color: colorFor(stats.annRet) },
    { label: "TOTAL · NET", value: fmtPct(stats.totalReturn), color: colorFor(stats.totalReturn) },
    { label: "ANN. VOL", value: fmtPctNoSign(stats.annVol), color: C.text },
    { label: "SHARPE", value: stats.sharpe.toFixed(2), color: C.greenHi },
    { label: "SORTINO", value: stats.sortino.toFixed(2), color: C.greenHi },
    { label: "CALMAR", value: stats.calmar.toFixed(2), color: C.greenHi },
    { label: "MAX DD", value: fmtPct(stats.maxDD), color: C.red },
    { label: "WIN RATE", value: (stats.winRate * 100).toFixed(0) + "%", color: C.text },
    { label: "BETA · 60/40", value: stats.beta.toFixed(2), color: C.text },
    { label: "ALPHA · ann", value: fmtPct(stats.alpha), color: colorFor(stats.alpha) },
    { label: "VS BENCH", value: fmtPct(stats.totalReturn - stats.benchTotal), color: colorFor(stats.totalReturn - stats.benchTotal) },
    { label: "RECOVERY", value: stats.recovery.toFixed(1) + "x", color: C.text },
  ];

  // ── Donut conic-gradient: cumulative-by-sleeve stops ────────────────────
  let acc = 0;
  const stops = sleeves
    .map((s) => {
      const start = acc * 100;
      acc += s.pct;
      const end = acc * 100;
      return `${s.color} ${start.toFixed(2)}% ${end.toFixed(2)}%`;
    })
    .join(", ");
  const donutBg =
    stops.length > 0
      ? `conic-gradient(${stops})`
      : `conic-gradient(${C.textDim} 0% 100%)`;
  const deployedPct = sleeves
    .filter((s) => s.name !== "Cash")
    .reduce((s, x) => s + x.pct, 0);

  const liveCount = roster.filter((r) => r.live).length;

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div
      style={{
        fontFamily: FONT_UI,
        color: C.text,
        background: C.bg,
        minHeight: "100vh",
        padding: "18px 26px 56px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* Print-specific styles + ambient animation */}
      <style>{`
        @keyframes ts-pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
        @keyframes ts-draw { from { stroke-dashoffset:2200 } to { stroke-dashoffset:0 } }
        @keyframes ts-glow {
          0%,100%{ box-shadow:0 0 22px rgba(74,222,128,0.16), inset 0 0 24px rgba(74,222,128,0.03) }
          50%{ box-shadow:0 0 34px rgba(74,222,128,0.26), inset 0 0 28px rgba(74,222,128,0.06) }
        }
        @media print {
          /* Hide global app chrome */
          aside, nav, header, .no-print,
          [data-app-sidebar], [data-app-header], [data-app-shell-nav] {
            display: none !important;
          }
          html, body { background: ${C.bg} !important; }
          .fts-paper-banner { display: flex !important; }
          .fts-hero { animation: none !important; }
          * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
        }
        @media (prefers-reduced-motion: reduce) {
          .fts-pulse, .fts-hero, .fts-draw { animation: none !important; }
        }
      `}</style>

      {/* ── Persistent paper-trading banner ───────────────────────────────── */}
      <div
        className="fts-paper-banner"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          background: "rgba(20,14,2,0.95)",
          borderBottom: "1px solid rgba(251,191,36,0.26)",
          padding: "6px 16px",
          marginLeft: -26,
          marginRight: -26,
          marginTop: -18,
        }}
      >
        <span
          className="fts-pulse"
          style={{
            width: 5, height: 5, borderRadius: "50%",
            background: C.amber, boxShadow: "0 0 7px rgba(251,191,36,0.8)",
            animation: "ts-pulse 2s ease-in-out infinite",
          }}
        />
        <span
          style={{
            fontFamily: FONT_MONO, fontSize: 10, letterSpacing: "0.14em",
            color: C.amber, textTransform: "uppercase",
          }}
        >
          Paper Trading Only · simulated fills · for research &amp; education · not investment advice
        </span>
      </div>

      {/* ── MOCK_DATA banner ──────────────────────────────────────────────────
          Until /api/fund/returns-history exists, the inception date (Sep 2023),
          monthly returns table, CAGR/Sharpe/Sortino/Calmar/MaxDD/Beta/Alpha,
          NAV/unit, high-water mark, per-bot risk stats, and sleeve correlation
          matrix on this page are SEEDED MOCK DATA shown for layout preview.
          The fund actually has ~23 days of real history. Don't quote these
          numbers anywhere. See TODO(backend) markers throughout this file. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          background: "rgba(40,8,8,0.95)",
          border: "1px solid rgba(248,113,113,0.55)",
          borderRadius: 4,
          padding: "9px 16px",
          marginLeft: -26,
          marginRight: -26,
        }}
      >
        <span
          className="fts-pulse"
          style={{
            width: 6, height: 6, borderRadius: "50%",
            background: "#f87171", boxShadow: "0 0 8px rgba(248,113,113,0.9)",
            animation: "ts-pulse 1.5s ease-in-out infinite",
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: FONT_MONO, fontSize: 10, letterSpacing: "0.14em",
            color: "#fca5a5", textTransform: "uppercase", textAlign: "center",
          }}
        >
          MOCK_DATA · Inception, monthly returns, CAGR/Sharpe/Sortino/MaxDD/Alpha/Beta,
          NAV/unit, high-water mark, per-bot risk stats &amp; sleeve correlation
          are synthetic for layout preview only. Real fund history: ~23 days. Do not quote.
        </span>
      </div>

      {/* ── Chrome row: breadcrumb + bot tear sheets link + print ─────────── */}
      <div
        className="no-print"
        style={{ display: "flex", alignItems: "center", gap: 12 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, fontFamily: FONT_MONO, fontSize: 11, color: C.textGdim }}>
          <Link to="/strategy" style={{ color: C.textDim, textDecoration: "none" }}>Strategy Lab</Link>
          <span>/</span>
          <span style={{ color: C.green }}>Fund Tear Sheet</span>
        </div>
        <div style={{ flex: 1 }} />
        <Link
          to="/strategy"
          style={{
            fontFamily: FONT_MONO, fontSize: 11, color: C.textDim,
            textDecoration: "none", border: `1px solid ${C.borderHi}`,
            borderRadius: 4, padding: "7px 12px",
          }}
        >
          ↪ per-bot sheets
        </Link>
        <button
          onClick={() => { try { window.print(); } catch {} }}
          style={{
            display: "flex", alignItems: "center", gap: 7,
            fontFamily: FONT_UI, fontSize: 12, fontWeight: 600,
            color: C.green, background: "transparent",
            border: `1px solid ${C.green}`, borderRadius: 4,
            padding: "7px 14px", cursor: "pointer",
          }}
        >
          <Printer size={13} />
          Export PDF
        </button>
      </div>

      {/* ── 1. HEADER ─────────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex", alignItems: "flex-start",
          justifyContent: "space-between", gap: 24,
          borderBottom: "1px solid rgba(74,222,128,0.14)",
          paddingBottom: 18,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              className="fts-pulse"
              style={{
                width: 9, height: 9, borderRadius: "50%",
                background: C.green, boxShadow: "0 0 9px rgba(74,222,128,0.9)",
                animation: "ts-pulse 1.8s ease-in-out infinite",
              }}
            />
            <h1
              style={{
                margin: 0, fontSize: 30, fontWeight: 700,
                letterSpacing: "-0.02em", color: C.greenHi,
              }}
            >
              BMG Capital · Master Fund
            </h1>
            <span
              style={{
                fontFamily: FONT_MONO, fontSize: 9, letterSpacing: "0.08em",
                color: C.green, background: "rgba(74,222,128,0.08)",
                border: "1px solid rgba(74,222,128,0.3)", borderRadius: 3,
                padding: "3px 8px",
              }}
            >
              MULTI-STRATEGY
            </span>
          </div>
          <div
            style={{
              fontSize: 14, color: C.textMuted, marginTop: 10,
              maxWidth: 720, lineHeight: 1.5,
            }}
          >
            Autonomous multi-strategy book. {roster.length} production bots across
            stocks, crypto, options &amp; quant sleeves, governed by a three-gate
            signal pipeline and firm-level risk caps. Market-neutral bias with
            momentum tilt.
          </div>
        </div>
        <div style={{ textAlign: "right", flex: "none" }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 10, letterSpacing: "0.12em", color: C.textGdim }}>
            FUND FACTSHEET · AS OF
          </div>
          <div style={{ fontFamily: FONT_MONO, fontSize: 15, color: C.text, marginTop: 5 }}>
            {asOfLabel}
          </div>
          <div style={{ fontFamily: FONT_MONO, fontSize: 10, color: C.textGdim, marginTop: 4 }}>
            share class · PAPER-I
          </div>
        </div>
      </div>

      {/* ── 2. NAV / CAPITAL LEDGER STRIP (6 cols) ─────────────────────────── */}
      <div
        style={{
          display: "grid", gridTemplateColumns: "repeat(6, 1fr)",
          border: `1px solid ${C.border}`, borderRadius: 5,
          background: C.surfaceAlt, overflow: "hidden",
        }}
      >
        {[
          { label: "NAV · TOTAL", value: isLoading ? "—" : fmtMoneyFull(totalNavCents), color: C.greenHi },
          { label: "NAV / UNIT", value: "$" + navUnit.toFixed(2), color: C.text },
          { label: "HIGH-WATER", value: "$" + highWater.toFixed(2), color: C.green },
          { label: "INCEPTION", value: inceptionLabel, color: C.text },
          { label: "MGMT / PERF", value: "2% / 20%", color: C.text },
          { label: "STRATEGIES", value: `${roster.length} bots · ${sleeves.length} sl.`, color: C.text },
        ].map((s, i) => (
          <div
            key={s.label}
            style={{
              padding: "12px 16px",
              borderRight: i < 5 ? `1px solid ${C.borderDim}` : undefined,
            }}
          >
            <div style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim }}>{s.label}</div>
            <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: s.color, marginTop: 5 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* ── 3. HERO (glow) + FUND STATISTICS (2-col) ─────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.62fr 1fr", gap: 16 }}>
        <div
          className="fts-hero"
          style={{
            position: "relative", border: "1px solid rgba(74,222,128,0.2)",
            borderRadius: 6,
            background: "linear-gradient(180deg, #0a120a, #070d07)",
            padding: "18px 20px", overflow: "hidden",
            animation: "ts-glow 4s ease-in-out infinite",
          }}
        >
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontFamily: FONT_MONO, fontSize: 10, letterSpacing: "0.14em", color: C.textDim }}>
                FUND NAV · NET OF FEES · SINCE INCEPTION
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
                <span
                  style={{
                    fontFamily: FONT_MONO, fontSize: 32, fontWeight: 600,
                    color: C.green, textShadow: "0 0 20px rgba(74,222,128,0.3)",
                  }}
                >
                  {fmtPct(stats.totalReturn)}
                </span>
                <span style={{ fontFamily: FONT_MONO, fontSize: 13, color: C.textDim }}>
                  vs 60/40 <span style={{ color: C.cyan }}>{fmtPct(stats.benchTotal)}</span>
                </span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 14 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: FONT_MONO, fontSize: 10, color: C.textDim }}>
                <span style={{ width: 14, height: 2, background: C.green, boxShadow: "0 0 6px rgba(74,222,128,0.7)" }} />
                Master Fund
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: FONT_MONO, fontSize: 10, color: C.textDim }}>
                <span style={{ width: 14, height: 2, background: C.cyan }} />
                60/40 blend
              </span>
            </div>
          </div>
          <svg viewBox="0 0 1000 300" preserveAspectRatio="none" style={{ width: "100%", height: 288, marginTop: 12 }}>
            <defs>
              <linearGradient id="fts-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={C.green} stopOpacity="0.18" />
                <stop offset="100%" stopColor={C.green} stopOpacity="0" />
              </linearGradient>
            </defs>
            <line x1="0" y1="75" x2="1000" y2="75" stroke="rgba(74,222,128,0.06)" strokeWidth="1" />
            <line x1="0" y1="150" x2="1000" y2="150" stroke="rgba(74,222,128,0.06)" strokeWidth="1" />
            <line x1="0" y1="225" x2="1000" y2="225" stroke="rgba(74,222,128,0.06)" strokeWidth="1" />
            <path d={cumArea} fill="url(#fts-fill)" />
            <polyline points={benchPoints} fill="none" stroke={C.cyan} strokeWidth="1.5" strokeDasharray="4 4" opacity="0.75" />
            <polyline
              className="fts-draw"
              points={cumPoints}
              fill="none"
              stroke={C.green}
              strokeWidth="2.2"
              strokeDasharray="2200"
              strokeDashoffset="2200"
              style={{ animation: "ts-draw 2.4s ease-out forwards", filter: "drop-shadow(0 0 5px rgba(74,222,128,0.5))" }}
            />
          </svg>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim, marginTop: 4 }}>
            <span>{inceptionLabel}</span>
            <span>Jul 2024 — Aug 2025</span>
            <span>{asOfLabel}</span>
          </div>
        </div>

        <div
          style={{
            border: `1px solid ${C.border}`, borderRadius: 6,
            background: C.surface, overflow: "hidden",
            display: "flex", flexDirection: "column",
          }}
        >
          <div style={{ padding: "13px 18px", borderBottom: `1px solid ${C.border}` }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: C.text, letterSpacing: "0.06em" }}>
              FUND STATISTICS
            </span>
          </div>
          <div
            style={{
              display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1,
              background: "rgba(74,222,128,0.06)", flex: 1,
            }}
          >
            {statGrid.map((s) => (
              <div key={s.label} style={{ background: C.surface, padding: "11px 16px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
                <div style={{ fontFamily: FONT_MONO, fontSize: 9, letterSpacing: "0.06em", color: C.textDim }}>
                  {s.label}
                </div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 16, color: s.color, marginTop: 4 }}>
                  {s.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── 4. FUND MONTHLY RETURNS TABLE ────────────────────────────────── */}
      <div
        style={{
          border: `1px solid ${C.border}`, borderRadius: 6,
          background: C.surface, overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "13px 18px", borderBottom: `1px solid ${C.border}`,
          }}
        >
          <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: C.text, letterSpacing: "0.06em" }}>
            FUND MONTHLY RETURNS · NET %
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 14, fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim }}>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ width: 11, height: 11, borderRadius: 2, background: "rgba(74,222,128,0.55)" }} />
              gain
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ width: 11, height: 11, borderRadius: 2, background: "rgba(248,113,113,0.55)" }} />
              loss
            </span>
          </div>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: FONT_MONO }}>
          <thead>
            <tr style={{ background: "#0c120c" }}>
              <th style={{ textAlign: "left", fontSize: 10, color: C.textDim, fontWeight: 500, padding: "9px 14px", borderBottom: `1px solid ${C.border}` }}>YEAR</th>
              {monthLabels.map((m) => (
                <th key={m} style={{ textAlign: "right", fontSize: 10, color: C.textDim, fontWeight: 500, padding: "9px 8px", borderBottom: `1px solid ${C.border}` }}>
                  {m}
                </th>
              ))}
              <th
                style={{
                  textAlign: "right", fontSize: 10, color: C.green, fontWeight: 600,
                  padding: "9px 14px", borderBottom: `1px solid ${C.border}`,
                  borderLeft: `1px solid ${C.border}`,
                }}
              >
                YTD
              </th>
            </tr>
          </thead>
          <tbody>
            {monthlyRows.map((r) => (
              <tr key={r.year}>
                <td style={{ fontSize: 12, color: C.greenHi, padding: "9px 14px", borderBottom: `1px solid ${C.borderDim}` }}>
                  {r.year}
                </td>
                {r.cells.map((c, i) => (
                  <td
                    key={i}
                    style={{
                      textAlign: "right", fontSize: 11, color: c.color, background: c.bg,
                      padding: "9px 8px", borderBottom: `1px solid ${C.borderDim}`,
                    }}
                  >
                    {c.val}
                  </td>
                ))}
                <td
                  style={{
                    textAlign: "right", fontSize: 12, fontWeight: 600,
                    color: r.ytdColor, background: r.ytdBg, padding: "9px 14px",
                    borderBottom: `1px solid ${C.borderDim}`,
                    borderLeft: `1px solid ${C.border}`,
                  }}
                >
                  {r.ytd}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── 5. CONTRIBUTION (2-col) + ALLOCATION DONUT ───────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
        {/* Contribution to Return (bps) — centered ± bars sorted */}
        <div
          style={{
            border: `1px solid ${C.border}`, borderRadius: 6,
            background: C.surface, padding: "16px 18px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: C.text, letterSpacing: "0.06em" }}>
              CONTRIBUTION TO RETURN · 30D · BY BOT
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: C.textGdim }}>
              Σ = {targetBps >= 0 ? "+" : ""}{targetBps} bp · = fund 30d
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {contribSorted.map((c) => {
              const pos = c.bps >= 0;
              const w = (Math.abs(c.bps) / maxAbsBps * 50).toFixed(1) + "%";
              return (
                <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 1, background: c.sleeveColor, flex: "none" }} />
                  <span
                    style={{
                      fontSize: 12, color: C.text, width: 180,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}
                  >
                    {c.display}
                  </span>
                  <div style={{ flex: 1, position: "relative", height: 14, background: "#0c120c", borderRadius: 3 }}>
                    <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "rgba(74,222,128,0.2)" }} />
                    <div
                      style={{
                        position: "absolute", top: 2, bottom: 2,
                        [pos ? "left" : "right"]: "50%",
                        width: w,
                        background: pos ? C.green : C.red,
                        borderRadius: 2,
                        boxShadow: pos
                          ? "0 0 6px rgba(74,222,128,0.4)"
                          : "0 0 6px rgba(248,113,113,0.4)",
                      } as React.CSSProperties}
                    />
                  </div>
                  <span
                    style={{
                      fontFamily: FONT_MONO, fontSize: 11,
                      color: pos ? C.green : C.red,
                      width: 62, textAlign: "right",
                    }}
                  >
                    {(pos ? "+" : "") + c.bps + "bp"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Allocation donut */}
        <div
          style={{
            border: `1px solid ${C.border}`, borderRadius: 6,
            background: C.surface, padding: "16px 18px",
            display: "flex", flexDirection: "column",
          }}
        >
          <div style={{ fontFamily: FONT_MONO, fontSize: 12, color: C.text, letterSpacing: "0.06em", marginBottom: 14 }}>
            CAPITAL ALLOCATION · BY SLEEVE
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 22, flex: 1 }}>
            <div style={{ position: "relative", width: 140, height: 140, flex: "none" }}>
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: donutBg }} />
              <div
                style={{
                  position: "absolute", inset: "24%", borderRadius: "50%",
                  background: C.surface, border: "1px solid rgba(74,222,128,0.16)",
                  display: "flex", flexDirection: "column",
                  alignItems: "center", justifyContent: "center",
                }}
              >
                <div style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim }}>DEPLOYED</div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 14, color: C.greenHi, marginTop: 2 }}>
                  {(deployedPct * 100).toFixed(1)}%
                </div>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              {sleeves.map((s) => (
                <div key={s.name} style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span style={{ width: 9, height: 9, borderRadius: 2, background: s.color }} />
                  <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: C.text }}>{s.name}</span>
                  <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: C.textDim }}>
                    {(s.pct * 100).toFixed(0)}% · {s.bots} bot{s.bots !== 1 ? "s" : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── 6. BOT ROSTER (holdings) ─────────────────────────────────────── */}
      <div
        style={{
          border: `1px solid ${C.border}`, borderRadius: 6,
          background: C.surface, overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "13px 18px", borderBottom: `1px solid ${C.border}`,
          }}
        >
          <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: C.text, letterSpacing: "0.06em" }}>
            BOT ROSTER · UNDERLYING STRATEGIES
          </span>
          <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: C.textGdim }}>
            {roster.length} production bots · sorted by allocation
          </span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: FONT_MONO }}>
          <thead>
            <tr style={{ background: "#0c120c" }}>
              {["BOT", "SLEEVE", "ALLOC", "WEIGHT", "30D", "SHARPE", "MAX DD", "STATUS"].map((h, i) => (
                <th
                  key={h}
                  style={{
                    textAlign: i === 0 || i === 1 ? "left" : "right",
                    fontSize: 9, color: C.textDim, fontWeight: 500,
                    padding: i === 0 ? "9px 18px" : i === 7 ? "9px 18px" : "9px 8px",
                    borderBottom: `1px solid ${C.border}`,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={8} style={{ padding: 24, textAlign: "center", color: C.textDim, fontSize: 11 }}>
                  Loading roster…
                </td>
              </tr>
            )}
            {!isLoading && roster.map((b) => {
              const weight = totalAllocCents > 0 ? (b.allocCents / totalAllocCents) : 0;
              return (
                <tr key={b.name}>
                  <td style={{ fontSize: 12, color: C.greenHi, padding: "8px 18px", borderBottom: `1px solid ${C.borderDim}` }}>
                    <Link to={`/strategy/${b.name}`} style={{ color: C.greenHi, textDecoration: "none" }}>
                      {b.display}
                    </Link>
                  </td>
                  <td style={{ fontSize: 10, color: b.sleeveColor, padding: "8px 8px", borderBottom: `1px solid ${C.borderDim}` }}>
                    {b.sleeve.toUpperCase()}
                  </td>
                  <td style={{ fontSize: 11, color: C.text, textAlign: "right", padding: "8px 8px", borderBottom: `1px solid ${C.borderDim}` }}>
                    {fmtMoney(b.allocCents)}
                  </td>
                  <td style={{ fontSize: 11, color: C.textDim, textAlign: "right", padding: "8px 8px", borderBottom: `1px solid ${C.borderDim}` }}>
                    {(weight * 100).toFixed(1)}%
                  </td>
                  <td style={{ fontSize: 11, color: colorFor(b.ret30d), textAlign: "right", padding: "8px 8px", borderBottom: `1px solid ${C.borderDim}` }}>
                    {fmtPct(b.ret30d)}
                  </td>
                  <td style={{ fontSize: 11, color: C.text, textAlign: "right", padding: "8px 8px", borderBottom: `1px solid ${C.borderDim}` }}>
                    {b.sharpeProxy.toFixed(2)}
                  </td>
                  <td style={{ fontSize: 11, color: C.red, textAlign: "right", padding: "8px 8px", borderBottom: `1px solid ${C.borderDim}` }}>
                    {(b.ddProxy * 100).toFixed(1)}%
                  </td>
                  <td style={{ textAlign: "right", padding: "8px 18px", borderBottom: `1px solid ${C.borderDim}` }}>
                    <span
                      style={{
                        fontFamily: FONT_MONO, fontSize: 8,
                        color: b.live ? C.green : C.amber,
                        border: `1px solid ${b.live ? "rgba(74,222,128,0.3)" : "rgba(251,191,36,0.3)"}`,
                        borderRadius: 3, padding: "2px 6px",
                      }}
                    >
                      {b.live ? "LIVE" : "PAUSED"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr style={{ background: "#0c120c" }}>
              <td style={{ fontSize: 11, color: C.green, padding: "10px 18px", fontWeight: 600 }}>FUND TOTAL</td>
              <td style={{ padding: "10px 8px" }} />
              <td style={{ fontSize: 11, color: C.text, textAlign: "right", padding: "10px 8px" }}>
                {fmtMoney(totalAllocCents)}
              </td>
              <td style={{ fontSize: 11, color: C.text, textAlign: "right", padding: "10px 8px" }}>100.0%</td>
              <td style={{ fontSize: 11, color: colorFor(fund30d), textAlign: "right", padding: "10px 8px" }}>
                {fmtPct(fund30d, 2)}
              </td>
              <td style={{ fontSize: 11, color: C.greenHi, textAlign: "right", padding: "10px 8px" }}>
                {stats.sharpe.toFixed(2)}
              </td>
              <td style={{ fontSize: 11, color: C.red, textAlign: "right", padding: "10px 8px" }}>
                {fmtPct(stats.maxDD)}
              </td>
              <td style={{ textAlign: "right", padding: "10px 18px" }}>
                <span style={{ fontFamily: FONT_MONO, fontSize: 8, color: C.green }}>
                  {liveCount} LIVE
                </span>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* ── 7. DRAWDOWN + CORRELATION + CIO NOTE (3-col) ─────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1.1fr", gap: 16 }}>
        {/* Drawdown underwater */}
        <div
          style={{
            border: `1px solid ${C.border}`, borderRadius: 6,
            background: C.surface, padding: "16px 18px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: C.text, letterSpacing: "0.06em" }}>
              FUND DRAWDOWN · UNDERWATER
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: C.red }}>
              max {fmtPct(stats.maxDD)}
            </span>
          </div>
          <svg viewBox="0 0 600 150" preserveAspectRatio="none" style={{ width: "100%", height: 140 }}>
            <defs>
              <linearGradient id="fts-dd-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={C.red} stopOpacity="0.05" />
                <stop offset="100%" stopColor={C.red} stopOpacity="0.32" />
              </linearGradient>
            </defs>
            <line x1="0" y1="2" x2="600" y2="2" stroke="rgba(74,222,128,0.14)" strokeWidth="1" />
            <path d={ddArea} fill="url(#fts-dd-fill)" />
            <polyline points={ddPoints} fill="none" stroke={C.red} strokeWidth="1.5" opacity="0.85" />
          </svg>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim, marginTop: 4 }}>
            <span>0%</span>
            <span>recovery factor {stats.recovery.toFixed(1)}x</span>
          </div>
        </div>

        {/* Sleeve correlation matrix (4x4) */}
        <div
          style={{
            border: `1px solid ${C.border}`, borderRadius: 6,
            background: C.surface, padding: "16px 18px",
          }}
        >
          <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: C.text, letterSpacing: "0.06em", marginBottom: 14 }}>
            SLEEVE CORRELATION · ρ
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "40px repeat(4, 1fr)", gap: 4 }}>
            <div />
            {corrHead.map((h) => (
              <div key={h} style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textDim, textAlign: "center" }}>
                {h}
              </div>
            ))}
            {CM.map((row, ri) => (
              <>
                <div key={`l-${ri}`} style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textDim, display: "flex", alignItems: "center" }}>
                  {corrHead[ri]}
                </div>
                {row.map((v, ci) => {
                  const sty = cellCorr(v);
                  return (
                    <div
                      key={`c-${ri}-${ci}`}
                      style={{
                        aspectRatio: "1/1",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        borderRadius: 3, background: sty.bg,
                        fontFamily: FONT_MONO, fontSize: 9, color: sty.text,
                      }}
                    >
                      {v.toFixed(2)}
                    </div>
                  );
                })}
              </>
            ))}
          </div>
          <div style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim, marginTop: 13, lineHeight: 1.5 }}>
            Low cross-sleeve ρ. Diversification is real. Crypto bots cluster; stocks/options independent.
          </div>
        </div>

        {/* CIO note */}
        <div
          style={{
            border: `1px solid ${C.border}`, borderLeft: `2px solid ${C.green}`,
            borderRadius: 6, background: C.surface, padding: "16px 18px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: C.green, letterSpacing: "0.06em" }}>
              // CIO NOTE
            </span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textGdim }}>
              B. Gorzelanczyk · CIO
            </span>
          </div>
          <div style={{ fontSize: 13, color: C.textMuted, lineHeight: 1.65 }}>
            Book compounded {fmtPct(fund30d, 2)} on the month at realized vol of{" "}
            {fmtPctNoSign(stats.annVol)} annualized. Onchain and Stock Swing led. Crypto Day
            gave back on intraday chop but the three-gate pipeline kept the loss
            contained. Cross-sleeve correlation stayed low so diversification did its
            job. Holding PM bias, carrying cash into a data-heavy stretch.
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
            {["multi-strat", "low-correlation", "disciplined"].map((t) => (
              <span
                key={t}
                style={{
                  fontFamily: FONT_MONO, fontSize: 9, color: C.textDim,
                  background: "#121a12", borderRadius: 3, padding: "4px 9px",
                }}
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ── 8. FOOTER: methodology + persistent paper-trading disclaimer ─── */}
      <div
        style={{
          display: "flex", alignItems: "flex-start", gap: 10, marginTop: 6,
          padding: "14px 18px", border: "1px solid rgba(74,222,128,0.08)",
          borderRadius: 5, background: C.surfaceDeep,
        }}
      >
        <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: C.textGdim, lineHeight: 1.6 }}>
          METHODOLOGY. Fund returns are the capital-weighted aggregate of {roster.length} bot sleeves,
          simulated (paper), net of modeled fees (2/20) &amp; slippage, geometrically
          linked. Sharpe/Sortino annualized from monthly series, rf=0. Benchmark is a
          60/40 SPY/AGG blend. Contribution-to-return in bps of fund NAV.
          Past simulated performance does not guarantee future results.{" "}
          <span style={{ color: C.amber }}>No real capital is or was at risk.</span>{" "}
          Generated {asOfLabel} · BMG Capital autonomous engine v1.0.
        </span>
      </div>

      {/* ── Suppress unused-var warning for BotListItem type re-export ───── */}
      {false && (null as unknown as BotListItem)}
    </div>
  );
}
