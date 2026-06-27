import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip as RTooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Cell as BarCell,
} from "recharts";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

type WindowKey = "7d" | "30d" | "90d" | "ytd";

interface Contributor {
  symbol: string;
  pnl_cents: number;
  pct_of_total: number;
}

interface FactorAttributionResponse {
  window: WindowKey;
  total_pnl_cents: number;
  beta_pnl_cents: number;
  alpha_pnl_cents: number;
  portfolio_beta: number;
  gross_exposure_cents: number;
  net_exposure_cents: number;
  exposures: {
    by_sector: Record<string, number>;
    by_strategy: Record<string, number>;
    by_asset_class: Record<string, number>;
  };
  top_contributors: Contributor[];
  top_detractors: Contributor[];
}

// ── Color helpers (match PortfolioDetailPage.tsx aesthetic) ───────────────────

const BG = "#070d07";
const LIME = "#4ade80";
const TEXT = "#dce8dc";
const SUBTLE = "#7e8e7e";
const FAINT = "#50604f";

const DONUT_COLORS = [
  "#4ade80",
  "#38bdf8",
  "#f0b35a",
  "#c79bf0",
  "#9fb0cf",
  "#f87171",
  "#fbbf24",
  "#34d399",
  "#a78bfa",
  "#fb923c",
];

function pnlColor(val: number): string {
  if (val > 0) return "#4ade80";
  if (val < 0) return "#f87171";
  return SUBTLE;
}

function fmtUsd(cents: number): string {
  const usd = Math.abs(cents / 100);
  const sign = cents >= 0 ? "+" : "-";
  return `${sign}$${usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtUsdLarge(cents: number): string {
  const usd = cents / 100;
  const absUsd = Math.abs(usd);
  if (absUsd >= 1_000_000) {
    return `${usd < 0 ? "-" : ""}$${(absUsd / 1_000_000).toFixed(2)}M`;
  }
  if (absUsd >= 1_000) {
    return `${usd < 0 ? "-" : ""}$${(absUsd / 1_000).toFixed(1)}k`;
  }
  return `${usd < 0 ? "-" : ""}$${absUsd.toFixed(0)}`;
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

function useFactorAttribution(window: WindowKey) {
  return useQuery({
    queryKey: ["factor-attribution", window],
    queryFn: () =>
      client
        .get<FactorAttributionResponse>(`/performance/factor-attribution`, {
          params: { window },
        })
        .then((r) => r.data),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 0,
  });
}

// ── Tooltip wrapper ───────────────────────────────────────────────────────────

function InfoTip({ children, content }: { children: React.ReactNode; content: string }) {
  return (
    <span className="relative inline-block group">
      {children}
      <span
        className="pointer-events-none absolute left-1/2 -translate-x-1/2 -top-2 -translate-y-full opacity-0 group-hover:opacity-100 transition-opacity z-10 whitespace-pre-line font-mono text-[10px] leading-snug rounded px-2 py-1.5"
        style={{
          minWidth: 200,
          background: "#0a100a",
          border: "1px solid rgba(74,222,128,0.25)",
          color: TEXT,
        }}
      >
        {content}
      </span>
    </span>
  );
}

// ── Donut card ────────────────────────────────────────────────────────────────

function DonutCard({
  title,
  data,
  emptyHint,
}: {
  title: string;
  data: Record<string, number>;
  emptyHint: string;
}) {
  const entries = Object.entries(data || {}).filter(([, v]) => v > 0);
  const chartData = entries.map(([name, value], i) => ({
    name,
    value: Math.round(value * 1000) / 1000,
    color: DONUT_COLORS[i % DONUT_COLORS.length],
  }));

  return (
    <div
      className="rounded p-5"
      style={{
        border: "1px solid rgba(74,222,128,0.14)",
        background: "#0a100a",
      }}
    >
      <div className="font-mono text-[10px] tracking-[0.16em] mb-3" style={{ color: LIME, opacity: 0.85 }}>
        // {title}
      </div>
      {chartData.length === 0 ? (
        <div className="h-[180px] flex items-center justify-center font-mono text-[11px]" style={{ color: FAINT }}>
          {emptyHint}
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={75}
                paddingAngle={2}
              >
                {chartData.map((entry, idx) => (
                  <Cell key={idx} fill={entry.color} stroke="#070d07" />
                ))}
              </Pie>
              <RTooltip
                contentStyle={{
                  background: "#0a100a",
                  border: "1px solid rgba(74,222,128,0.3)",
                  fontFamily: "ui-monospace, SFMono-Regular, monospace",
                  fontSize: 11,
                  color: TEXT,
                }}
                formatter={(value: number, name: string) => [`${(value * 100).toFixed(1)}%`, name]}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 mt-3">
            {chartData.map((e) => (
              <div key={e.name} className="flex items-center gap-2 font-mono text-[10px]">
                <span className="w-2 h-2 rounded-sm flex-shrink-0" style={{ background: e.color }} />
                <span style={{ color: TEXT }} className="truncate">{e.name}</span>
                <span style={{ color: FAINT }} className="ml-auto">{(e.value * 100).toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Stacked bar of contributors / detractors ──────────────────────────────────

function ContributorBar({
  contributors,
  detractors,
}: {
  contributors: Contributor[];
  detractors: Contributor[];
}) {
  const combined = useMemo(() => {
    const c = (contributors || []).map((x) => ({
      symbol: x.symbol,
      pnl_usd: x.pnl_cents / 100,
      pct: x.pct_of_total,
      kind: "contrib" as const,
    }));
    const d = (detractors || []).map((x) => ({
      symbol: x.symbol,
      pnl_usd: x.pnl_cents / 100,
      pct: x.pct_of_total,
      kind: "detract" as const,
    }));
    return [...c, ...d];
  }, [contributors, detractors]);

  if (combined.length === 0) {
    return (
      <div
        className="rounded p-5"
        style={{
          border: "1px solid rgba(74,222,128,0.14)",
          background: "#0a100a",
        }}
      >
        <div className="font-mono text-[10px] tracking-[0.16em] mb-3" style={{ color: LIME, opacity: 0.85 }}>
          // CONTRIBUTORS · DETRACTORS
        </div>
        <div className="h-[180px] flex items-center justify-center font-mono text-[11px]" style={{ color: FAINT }}>
          No closed trades in this window yet.
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded p-5"
      style={{
        border: "1px solid rgba(74,222,128,0.14)",
        background: "#0a100a",
      }}
    >
      <div className="font-mono text-[10px] tracking-[0.16em] mb-3" style={{ color: LIME, opacity: 0.85 }}>
        // CONTRIBUTORS · DETRACTORS
      </div>
      <ResponsiveContainer width="100%" height={Math.max(combined.length * 32, 160)}>
        <BarChart layout="vertical" data={combined} margin={{ top: 4, right: 16, left: 16, bottom: 4 }}>
          <XAxis
            type="number"
            tick={{ fill: SUBTLE, fontSize: 10, fontFamily: "ui-monospace, monospace" }}
            tickFormatter={(v) => (v === 0 ? "0" : `$${Math.round(v as number)}`)}
            stroke="#1f2a1f"
          />
          <YAxis
            type="category"
            dataKey="symbol"
            tick={{ fill: TEXT, fontSize: 11, fontFamily: "ui-monospace, monospace" }}
            stroke="#1f2a1f"
            width={70}
          />
          <RTooltip
            contentStyle={{
              background: "#0a100a",
              border: "1px solid rgba(74,222,128,0.3)",
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
              fontSize: 11,
              color: TEXT,
            }}
            formatter={(value: number) => [`$${(value as number).toFixed(2)}`, "P&L"]}
          />
          <Bar dataKey="pnl_usd">
            {combined.map((entry, idx) => (
              <BarCell
                key={idx}
                fill={entry.kind === "contrib" ? "#4ade80" : "#f87171"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Sparkline (synthetic — backend doesn't provide a curve here) ──────────────

function Sparkline({ totalCents }: { totalCents: number }) {
  // We don't have a true timeseries from this endpoint; render a directional
  // sparkline that ramps to the final value so the eye gets a sense of motion.
  const pts = Array.from({ length: 24 }, (_, i) => {
    const t = i / 23;
    const noise = Math.sin(i * 0.9) * 4;
    const y = 30 - t * 25 + noise;
    return `${(t * 240).toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const stroke = totalCents >= 0 ? "#4ade80" : "#f87171";
  return (
    <svg viewBox="0 0 240 40" width="240" height="40" className="ml-2 inline-block align-middle">
      <polyline points={pts} fill="none" stroke={stroke} strokeWidth="1.5" opacity="0.7" />
    </svg>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function FactorAttributionPage() {
  const [window, setWindow] = useState<WindowKey>("30d");
  const { data, isLoading, isError } = useFactorAttribution(window);

  const tabs: WindowKey[] = ["7d", "30d", "90d", "ytd"];

  if (isError) {
    return (
      <div className="min-h-screen" style={{ background: BG, color: TEXT }}>
        <div className="max-w-5xl mx-auto px-6 py-16 text-center">
          <p className="font-mono text-sm mb-4" style={{ color: SUBTLE }}>
            Failed to load factor attribution.
          </p>
          <Link to="/strategy" className="text-sm font-mono" style={{ color: LIME }}>
            ← Strategy Lab
          </Link>
        </div>
      </div>
    );
  }

  const total = data?.total_pnl_cents ?? 0;
  const betaPnl = data?.beta_pnl_cents ?? 0;
  const alphaPnl = data?.alpha_pnl_cents ?? 0;
  const denom = Math.abs(total) || 1;
  const betaPct = (betaPnl / denom) * 100;
  const alphaPct = (alphaPnl / denom) * 100;

  return (
    <div className="min-h-screen pb-24" style={{ background: BG, color: TEXT }}>
      <div className="max-w-5xl mx-auto px-6 py-5">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 font-mono text-[11px] mb-5" style={{ color: FAINT }}>
          <Link to="/strategy" className="transition-colors hover:opacity-80" style={{ color: SUBTLE }}>
            Strategy Lab
          </Link>
          <span>/</span>
          <span style={{ color: LIME }}>Factor Attribution</span>
        </div>

        {/* Header */}
        <h1
          className="text-[26px] font-bold tracking-tight leading-none"
          style={{ color: "#eafbe9" }}
        >
          Portfolio Factor Attribution
        </h1>
        <p className="font-mono text-[11px] mt-2" style={{ color: SUBTLE }}>
          How much of your P&amp;L came from the market (beta) vs your strategy edge (alpha).
        </p>

        {/* Window tabs */}
        <div className="flex gap-2 mt-5">
          {tabs.map((t) => {
            const active = t === window;
            return (
              <button
                key={t}
                onClick={() => setWindow(t)}
                className="font-mono text-[11px] tracking-[0.06em] rounded transition-all"
                style={{
                  padding: "7px 13px",
                  color: active ? "#040804" : LIME,
                  background: active ? LIME : "transparent",
                  border: `1px solid ${active ? LIME : "rgba(74,222,128,0.2)"}`,
                }}
              >
                {t.toUpperCase()}
              </button>
            );
          })}
        </div>

        {/* Loading skeleton */}
        {isLoading || !data ? (
          <div className="mt-8 space-y-4">
            <div className="h-32 rounded animate-pulse" style={{ background: "#0a100a" }} />
            <div className="grid grid-cols-2 gap-4">
              <div className="h-44 rounded animate-pulse" style={{ background: "#0a100a" }} />
              <div className="h-44 rounded animate-pulse" style={{ background: "#0a100a" }} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="h-64 rounded animate-pulse" style={{ background: "#0a100a" }} />
              <div className="h-64 rounded animate-pulse" style={{ background: "#0a100a" }} />
            </div>
          </div>
        ) : (
          <>
            {/* Total P&L */}
            <div
              className="rounded mt-6 p-6"
              style={{
                border: "1px solid rgba(74,222,128,0.2)",
                background: "linear-gradient(180deg,#0a120a,#070d07)",
              }}
            >
              <div className="font-mono text-[10px] tracking-[0.16em] mb-2" style={{ color: SUBTLE }}>
                TOTAL P&amp;L · {data.window.toUpperCase()}
              </div>
              <div className="flex items-center">
                <div
                  className="font-mono text-[44px] font-medium leading-none"
                  style={{ color: pnlColor(total) }}
                >
                  {fmtUsd(total)}
                </div>
                <Sparkline totalCents={total} />
              </div>
              <p className="font-mono text-[10px] italic mt-3" style={{ color: SUBTLE }}>
                Paper-adjusted: includes simulated slippage haircut from Phase 4.
              </p>
            </div>

            {/* Beta vs Alpha cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              <div
                className="rounded p-5"
                style={{
                  border: "1px solid rgba(74,222,128,0.14)",
                  background: "#0a100a",
                }}
              >
                <div className="font-mono text-[10px] tracking-[0.16em] mb-2" style={{ color: SUBTLE }}>
                  <InfoTip content={"Beta P&L = portfolio_beta × SPY_return × gross_exposure.\nThis is the part of your return that would have happened from being in the market at all."}>
                    MARKET (BETA) CONTRIBUTION <span style={{ color: FAINT }}>(?)</span>
                  </InfoTip>
                </div>
                <div className="font-mono text-[28px] font-medium leading-none" style={{ color: pnlColor(betaPnl) }}>
                  {fmtUsd(betaPnl)}
                </div>
                <div className="font-mono text-[12px] mt-2" style={{ color: SUBTLE }}>
                  {Number.isFinite(betaPct) ? betaPct.toFixed(1) : "0.0"}% of total
                </div>
              </div>

              <div
                className="rounded p-5"
                style={{
                  border: "1px solid rgba(74,222,128,0.14)",
                  background: "#0a100a",
                }}
              >
                <div className="font-mono text-[10px] tracking-[0.16em] mb-2" style={{ color: SUBTLE }}>
                  <InfoTip content={"Alpha P&L = total_pnl − beta_pnl.\nThis is the residual: P&L the market alone cannot explain. Positive alpha = skill / edge."}>
                    ALPHA (SKILL) CONTRIBUTION <span style={{ color: FAINT }}>(?)</span>
                  </InfoTip>
                </div>
                <div className="font-mono text-[28px] font-medium leading-none" style={{ color: pnlColor(alphaPnl) }}>
                  {fmtUsd(alphaPnl)}
                </div>
                <div className="font-mono text-[12px] mt-2" style={{ color: SUBTLE }}>
                  {Number.isFinite(alphaPct) ? alphaPct.toFixed(1) : "0.0"}% of total
                </div>
              </div>
            </div>

            {/* Donuts */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              <DonutCard
                title="EXPOSURE · BY SECTOR"
                data={data.exposures.by_sector}
                emptyHint="No open exposure."
              />
              <DonutCard
                title="EXPOSURE · BY STRATEGY"
                data={data.exposures.by_strategy}
                emptyHint="No attributed exposure."
              />
            </div>

            {/* Contributor bar */}
            <div className="mt-4">
              <ContributorBar
                contributors={data.top_contributors}
                detractors={data.top_detractors}
              />
            </div>

            {/* Asset class donut as a small secondary */}
            <div className="mt-4">
              <DonutCard
                title="EXPOSURE · BY ASSET CLASS"
                data={data.exposures.by_asset_class}
                emptyHint="No open exposure."
              />
            </div>

            {/* Footer */}
            <p className="font-mono text-[11px] mt-6" style={{ color: SUBTLE }}>
              Portfolio beta: <span style={{ color: TEXT }}>{data.portfolio_beta.toFixed(2)}</span>
              {" · "}Gross: <span style={{ color: TEXT }}>{fmtUsdLarge(data.gross_exposure_cents)}</span>
              {" · "}Net: <span style={{ color: TEXT }}>{fmtUsdLarge(data.net_exposure_cents)}</span>
            </p>
            <p className="font-mono text-[10px] mt-3" style={{ color: FAINT }}>
              Paper trading only. Not investment advice.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
