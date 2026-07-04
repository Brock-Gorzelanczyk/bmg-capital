/**
 * StrategyLabV2 — /strategy-v2
 *
 * Direct React implementation of Brock's Claude Design mockup
 * (Strategy Lab Redesign.dc). Wired to real API data:
 *   - getDashboardV2 for portfolio value + leaderboard + sleeves
 *   - getStrategyLabPortfolio for the 5-col PnL windows
 *
 * Existing /strategy page (StrategyLab.tsx) left untouched per memory rule.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getDashboardV2 } from "@/api/dashboard";
import { getStrategyLabPortfolio } from "@/api/bots";
import client from "@/api/client";

// ─── Types + constants ────────────────────────────────────────────────────────

const GREEN = "#4ade80";
const RED = "#f87171";
const MUTED = "#7e8e7e";
const DIM_GREEN = "rgba(74,222,128,0.12)";

const SLEEVE_ACCENTS: Record<string, string> = {
  stocks: "#9fb0cf",
  crypto: "#f0b35a",
  options: "#c79bf0",
  quant: "#38bdf8",
};

const SLEEVE_ICONS: Record<string, string> = {
  stocks: "▤",
  crypto: "◍",
  options: "⚡",
  quant: "∑",
};

// Utilities

function fmtUsd(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function fmtSignedUsd(cents: number): string {
  const s = cents >= 0 ? "+" : "-";
  return `${s}$${Math.abs(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function fmtPct(pct: number, digits = 3): string {
  const shown = pct * 100;
  const sign = shown >= 0 ? "+" : "";
  return `${sign}${shown.toFixed(digits)}%`;
}

function sparkPoints(seed: number, up: boolean, width = 120, height = 22): string {
  let s = seed >>> 0;
  let y = height / 2;
  const out: string[] = [];
  for (let i = 0; i <= 11; i++) {
    s = (s * 1664525 + 1013904223) >>> 0;
    y += ((s / 4294967296) - 0.5) * 4 - (up ? 0.5 : -0.5);
    y = Math.max(3, Math.min(height - 3, y));
    out.push(`${(i / 11 * width).toFixed(0)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

function sleeveSpark(seed: number, up: boolean): string {
  let s = seed >>> 0;
  let y = 30;
  const out: string[] = [];
  for (let i = 0; i <= 15; i++) {
    s = (s * 1664525 + 1013904223) >>> 0;
    y += ((s / 4294967296) - 0.5) * 7 - (up ? 1.1 : -1.1);
    y = Math.max(5, Math.min(37, y));
    out.push(`${(i / 15 * 240).toFixed(0)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

// ─── Portfolio Value hero band ────────────────────────────────────────────────

function PortfolioValueBand() {
  const { data: agg } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 30_000,
  });

  const pv = agg?.total_value_cents ?? 0;
  const pnl = agg?.pnl;

  const deltas = [
    { label: "ALL-TIME", data: pnl?.all_time, seed: 11 },
    { label: "MONTHLY", data: pnl?.mtd, seed: 23 },
    { label: "WEEKLY", data: pnl?.wtd, seed: 37 },
    { label: "DAILY", data: pnl?.today, seed: 53 },
  ];

  return (
    <div
      className="rounded-[10px] mt-5"
      style={{
        border: "1px solid rgba(74,222,128,0.22)",
        background: "linear-gradient(180deg,#0a130b,#070d08)",
        padding: "20px 24px",
        animation: "sl-glow 4s ease-in-out infinite",
      }}
    >
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "10px",
          letterSpacing: "0.16em",
          color: GREEN,
          opacity: 0.75,
        }}
      >
        // PORTFOLIO VALUE
      </div>
      <div
        className="grid gap-5 items-end mt-3"
        style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr 1fr" }}
      >
        <div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "44px",
              fontWeight: 600,
              letterSpacing: "-0.02em",
              color: "#f4f8f4",
              lineHeight: 1,
              textShadow: "0 0 26px rgba(74,222,128,0.28)",
            }}
          >
            {fmtUsd(pv)}
          </div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "11px",
              color: MUTED,
              marginTop: 8,
            }}
          >
            Canonical aggregate ·{" "}
            <span style={{ color: GREEN }}>updates live</span>
          </div>
        </div>
        {deltas.map((d) => {
          const cents = d.data?.cents ?? 0;
          const pct = d.data?.pct ?? 0;
          const isUp = cents >= 0;
          const color = isUp ? GREEN : RED;
          return (
            <div key={d.label}>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "22px",
                  fontWeight: 600,
                  color,
                }}
              >
                {fmtSignedUsd(cents)}
              </div>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "9px",
                  letterSpacing: "0.14em",
                  color: MUTED,
                  marginTop: 5,
                }}
              >
                {d.label}
              </div>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "11px",
                  color,
                  marginTop: 2,
                }}
              >
                {fmtPct(pct, Math.abs(pct * 100) < 0.01 ? 4 : 3)}
              </div>
              <svg
                viewBox="0 0 120 22"
                preserveAspectRatio="none"
                style={{ width: "100%", height: "18px", marginTop: 6 }}
              >
                <polyline
                  points={sparkPoints(d.seed, isUp)}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.3}
                  opacity={0.8}
                />
              </svg>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Sleeve card ──────────────────────────────────────────────────────────────

interface SleeveVals {
  id: string;
  name: string;
  value_cents: number;
  pnl_cents: number;
  bots_active: number;
  bots_total: number;
  deploy_pct: number;
  asset_class: string;
}

function SleeveCard({ s, seed }: { s: SleeveVals; seed: number }) {
  const accent = SLEEVE_ACCENTS[s.asset_class] || GREEN;
  const icon = SLEEVE_ICONS[s.asset_class] || "•";
  const isUp = s.pnl_cents >= 0;
  const spark = sleeveSpark(seed, isUp);
  const sparkFill = `0,42 ${spark} 240,42`;
  const gradId = `slf${s.id}`;
  const heat = `${Math.min(100, s.deploy_pct).toFixed(0)}%`;
  const deployColor = s.deploy_pct >= 85 ? "#f0b35a" : MUTED;
  const live = s.bots_active > 0;
  const dotGlow = live ? "0 0 6px rgba(74,222,128,0.9)" : "none";
  const dotColor = live ? GREEN : "#fbbf24";

  return (
    <div
      className="relative rounded-[9px] overflow-hidden"
      style={{
        border: `1px solid ${DIM_GREEN}`,
        borderTop: `2px solid ${accent}`,
        background: "#0a100a",
        padding: "16px 17px",
      }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-[9px]">
          <span
            className="flex items-center justify-center"
            style={{
              width: 22,
              height: 22,
              borderRadius: 6,
              background: `${accent}29`,
              fontSize: 12,
            }}
          >
            {icon}
          </span>
          <span style={{ fontSize: 15, fontWeight: 600, color: "#f4f8f4" }}>
            {s.name}
          </span>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: dotColor,
              boxShadow: dotGlow,
              animation: "sl-pulse 1.7s ease-in-out infinite",
            }}
          />
        </div>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 13,
            color: "#50604f",
          }}
        >
          →
        </span>
      </div>
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 23,
          color: "#f4f8f4",
          marginTop: 13,
        }}
      >
        {fmtUsd(s.value_cents)}
      </div>
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 12,
          color: isUp ? GREEN : RED,
          marginTop: 4,
        }}
      >
        {fmtSignedUsd(s.pnl_cents)} today
      </div>
      <svg
        viewBox="0 0 240 42"
        preserveAspectRatio="none"
        style={{ width: "100%", height: 40, margin: "11px 0 8px" }}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={accent} stopOpacity={0.18} />
            <stop offset="100%" stopColor={accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <polygon points={sparkFill} fill={`url(#${gradId})`} />
        <polyline
          points={spark}
          fill="none"
          stroke={accent}
          strokeWidth={1.5}
          opacity={0.95}
        />
      </svg>
      <div
        className="flex items-center justify-between"
        style={{
          paddingTop: 9,
          borderTop: "1px solid rgba(74,222,128,0.07)",
        }}
      >
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9,
            color: MUTED,
          }}
        >
          {s.bots_active} bots
        </span>
        <span className="flex items-center gap-[6px]">
          <span
            style={{
              width: 34,
              height: 4,
              background: "#121a12",
              borderRadius: 2,
              overflow: "hidden",
            }}
          >
            <span
              style={{
                display: "block",
                width: heat,
                height: "100%",
                background: accent,
              }}
            />
          </span>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 9,
              color: deployColor,
            }}
          >
            {heat}
          </span>
        </span>
      </div>
    </div>
  );
}

// ─── Bot leaderboard ─────────────────────────────────────────────────────────

interface LBRow {
  rank: number;
  name: string;
  profile: string;
  allTimeCents: number;
  todayCents: number;
  deployedCents: number;
  return30d: number;
  assetClass: string;
}

function BotLeaderboard({ rows }: { rows: LBRow[] }) {
  return (
    <>
      <div className="flex items-center gap-3 mt-[26px]">
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            letterSpacing: "0.16em",
            color: GREEN,
            opacity: 0.8,
          }}
        >
          // BOT LEADERBOARD
        </span>
        <span
          className="flex-1"
          style={{
            height: 1,
            background: "linear-gradient(90deg,rgba(74,222,128,0.2),transparent)",
          }}
        />
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "#50604f",
          }}
        >
          30d · vs yesterday
        </span>
      </div>

      <div
        className="rounded-[10px] mt-3 overflow-hidden"
        style={{
          border: `1px solid ${DIM_GREEN}`,
          background: "#0a100a",
        }}
      >
        <div
          className="grid items-center"
          style={{
            gridTemplateColumns: "44px 1fr 100px 100px 100px 80px",
            padding: "9px 18px",
            borderBottom: `1px solid ${DIM_GREEN}`,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9,
            letterSpacing: "0.1em",
            color: MUTED,
          }}
        >
          <span>#</span>
          <span>BOT</span>
          <span style={{ textAlign: "right" }}>ALL-TIME</span>
          <span style={{ textAlign: "right" }}>TODAY</span>
          <span style={{ textAlign: "right" }}>DEPLOYED</span>
          <span style={{ textAlign: "right" }}>30D</span>
        </div>
        {rows.map((l, i) => {
          const featured = i === 0;
          const accent = SLEEVE_ACCENTS[l.assetClass] || GREEN;
          const atColor = l.allTimeCents >= 0 ? GREEN : RED;
          const todayColor =
            l.todayCents > 0 ? GREEN : l.todayCents < 0 ? RED : MUTED;
          const spark = sparkPoints(l.rank * 17 + 3, l.return30d >= 0);
          return (
            <div
              key={l.profile + i}
              className="grid items-center"
              style={{
                gridTemplateColumns: "44px 1fr 100px 100px 100px 80px",
                padding: featured ? "13px 18px" : "9px 18px",
                background: featured ? "rgba(74,222,128,0.05)" : "transparent",
                borderBottom: "1px solid rgba(74,222,128,0.05)",
                borderLeft: featured
                  ? `2px solid ${GREEN}`
                  : "2px solid transparent",
              }}
            >
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: featured ? 17 : 13,
                  fontWeight: 600,
                  color: featured ? GREEN : "#50604f",
                }}
              >
                {l.rank}
              </span>
              <div className="flex items-center gap-[9px] min-w-0">
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 1,
                    background: accent,
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    fontSize: featured ? 14 : 13,
                    fontWeight: 600,
                    color: "#f4f8f4",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {l.name}
                </span>
                <svg
                  viewBox="0 0 70 20"
                  preserveAspectRatio="none"
                  style={{ width: 58, height: 18, flex: "none" }}
                >
                  <polyline
                    points={spark}
                    fill="none"
                    stroke={accent}
                    strokeWidth={1.4}
                    opacity={0.8}
                  />
                </svg>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  color: atColor,
                  textAlign: "right",
                }}
              >
                {fmtSignedUsd(l.allTimeCents)}
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  color: todayColor,
                  textAlign: "right",
                }}
              >
                {l.todayCents === 0 ? "+$0" : fmtSignedUsd(l.todayCents)}
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  color: "#9fb0a0",
                  textAlign: "right",
                }}
              >
                {fmtUsd(l.deployedCents)}
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: featured ? 14 : 12,
                  color: l.return30d >= 0 ? GREEN : RED,
                  textAlign: "right",
                }}
              >
                {fmtPct(l.return30d / 100, 2)}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}

// ─── Regime strip ─────────────────────────────────────────────────────────────

function RegimeStrip() {
  const { data: regime } = useQuery({
    queryKey: ["portfolio-regime-v2"],
    queryFn: () =>
      client
        .get<{
          regime: string;
          vix_level: number | null;
          confidence: number | null;
        }>("/portfolio/regime/current")
        .then((r) => r.data),
    staleTime: 120_000,
    retry: 0,
  });

  const vix = regime?.vix_level ?? null;
  const label = (regime?.regime || "risk_on").toUpperCase().replace(/_/g, "-");

  return (
    <div
      className="flex items-center gap-[14px] overflow-hidden"
      style={{
        height: 34,
        padding: "0 22px",
        borderBottom: `1px solid ${DIM_GREEN}`,
        background: "#060c07",
      }}
    >
      <span
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          letterSpacing: "0.14em",
          color: GREEN,
          whiteSpace: "nowrap",
        }}
      >
        REGIME · {label}
      </span>
      <div style={{ flex: 1, minWidth: 0, height: 22, overflow: "hidden" }}>
        <svg
          viewBox="0 0 1200 24"
          preserveAspectRatio="none"
          style={{
            width: "300%",
            height: 22,
            animation: "sl-regime 16s linear infinite",
          }}
        >
          <polyline
            points="0,12 25,7 50,15 75,5 100,17 125,9 150,13 175,6 200,18 225,10 250,13 275,5 300,16 325,11 350,8 375,17 400,9 425,14 450,6 475,15 500,11 525,12 550,6 575,17 600,8 625,14 650,7 675,16 700,10 725,13 750,6 775,17 800,9 825,14 850,6 875,15 900,11 925,12 950,5 975,16 1000,11 1025,8 1050,17 1075,9 1100,14 1125,6 1150,15 1175,11 1200,12"
            fill="none"
            stroke={GREEN}
            strokeWidth={1.4}
            opacity={0.5}
          />
        </svg>
      </div>
      <div
        className="flex gap-[14px]"
        style={{
          whiteSpace: "nowrap",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
        }}
      >
        <span style={{ color: "#50604f" }}>
          VIX{" "}
          <span style={{ color: vix && vix >= 20 ? "#fbbf24" : GREEN }}>
            {vix != null ? vix.toFixed(1) : "—"}
          </span>
        </span>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function StrategyLabV2() {
  const { data: dash } = useQuery({
    queryKey: ["dashboard-v2"],
    queryFn: getDashboardV2,
    staleTime: 60_000,
    retry: 1,
  });

  // Sleeve values from dashboard/v2 response (fallback to zeros)
  const sleeves = useMemo<SleeveVals[]>(() => {
    if (!dash?.sleeves) return [];
    const order = ["stocks", "crypto", "options", "quant"];
    return order.map((key) => {
      const s: any = (dash.sleeves as any)[key] || {};
      return {
        id: key,
        name: key[0].toUpperCase() + key.slice(1),
        value_cents: s.value_cents || 0,
        pnl_cents: s.pnl_cents || 0,
        bots_active: s.bots_active || 0,
        bots_total: s.bots_total || 0,
        deploy_pct:
          s.value_cents > 0
            ? Math.min(100, (s.value_cents / (dash.portfolio?.total_value_cents || 1)) * 100)
            : 0,
        asset_class: key,
      };
    });
  }, [dash]);

  const activeBotCount = useMemo(() => {
    return sleeves.reduce((sum, s) => sum + s.bots_active, 0);
  }, [sleeves]);

  const leaders = useMemo<LBRow[]>(() => {
    const lb = dash?.portfolio?.leaderboard || [];
    return lb.slice(0, 8).map((l: any, i: number) => ({
      rank: i + 1,
      name: l.name || l.profile,
      profile: l.profile,
      allTimeCents: (l.portfolio_value_cents || 0) - (l.starting_capital_cents || 0),
      todayCents: l.today_pnl_cents || 0,
      deployedCents: l.deployed_cents || 0,
      return30d: l.return_30d_pct || 0,
      assetClass:
        l.profile?.startsWith("stock") ? "stocks"
        : l.profile?.startsWith("crypto") ? "crypto"
        : l.profile?.startsWith("options") ? "options"
        : "quant",
    }));
  }, [dash]);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "radial-gradient(120% 70% at 50% -5%, #08130b 0%, #040705 55%)",
        fontFamily: "'Space Grotesk', sans-serif",
        color: "#dce8dc",
      }}
    >
      <style>{`
        @keyframes sl-pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
        @keyframes sl-regime { 0%{transform:translateX(0)} 100%{transform:translateX(-33.33%)} }
        @keyframes sl-glow { 0%,100%{ box-shadow:0 0 22px rgba(74,222,128,0.14), inset 0 0 26px rgba(74,222,128,0.03) } 50%{ box-shadow:0 0 34px rgba(74,222,128,0.24), inset 0 0 30px rgba(74,222,128,0.06) } }
      `}</style>

      {/* Scanline overlay */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1,
          pointerEvents: "none",
          background:
            "repeating-linear-gradient(0deg, rgba(0,0,0,0.22) 0px, rgba(0,0,0,0.22) 1px, transparent 1px, transparent 3px)",
          opacity: 0.34,
          mixBlendMode: "multiply",
        }}
      />

      <RegimeStrip />

      <div
        className="mx-auto"
        style={{ maxWidth: 1200, padding: "26px 22px 60px", position: "relative", zIndex: 2 }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: 30,
            fontWeight: 700,
            letterSpacing: "-0.02em",
            color: "#f4f8f4",
          }}
        >
          Strategy Lab
        </h1>
        <p
          style={{
            margin: "9px 0 0",
            fontSize: 14,
            color: MUTED,
            maxWidth: 620,
          }}
        >
          Four independent portfolios — Stocks, Crypto, Options, and Quant —
          each running dedicated bots on real market data.
        </p>

        <div className="flex items-center gap-[10px] flex-wrap" style={{ marginTop: 18 }}>
          <Link
            to="/strategy/candidates"
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: 12,
              fontWeight: 600,
              color: "#38bdf8",
              background: "rgba(56,189,248,0.08)",
              border: "1px solid rgba(56,189,248,0.35)",
              borderRadius: 6,
              padding: "8px 14px",
              cursor: "pointer",
              textDecoration: "none",
            }}
          >
            Strategy Library →
          </Link>
          <Link
            to="/portfolio-v2"
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: 12,
              fontWeight: 500,
              color: "#9fb0a0",
              background: "transparent",
              border: "1px solid rgba(74,222,128,0.14)",
              borderRadius: 6,
              padding: "8px 14px",
              textDecoration: "none",
            }}
          >
            Portfolio View →
          </Link>
          <div className="flex-1" />
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: MUTED,
            }}
          >
            {activeBotCount} bots active
          </div>
        </div>

        <PortfolioValueBand />

        <div
          className="grid gap-[14px]"
          style={{ gridTemplateColumns: "repeat(4, 1fr)", marginTop: 16 }}
        >
          {sleeves.map((s, i) => (
            <SleeveCard key={s.id} s={s} seed={7 + i * 12} />
          ))}
        </div>

        <BotLeaderboard rows={leaders} />

        <div
          className="flex items-center gap-4"
          style={{
            marginTop: 24,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "#50604f",
          }}
        >
          <span style={{ color: "#fbbf24" }}>▮ PAPER TRADING SIMULATION</span>
          <span>Not financial advice</span>
          <span>Past performance is not indicative of future results</span>
          <span>Bots run autonomously — review risk before deployment</span>
        </div>
      </div>
    </div>
  );
}
