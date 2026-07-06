/**
 * PortfolioV2 — /portfolio-v2
 *
 * Direct React implementation of Brock's Claude Design mockup
 * (Portfolio View.dc). Wired to real API:
 *   - getRiskConsole for deployment ratio + net exposure + sleeve breakdown
 *   - getDashboardV2 for portfolio value + bot counts
 *   - /api/portfolio/allocation-live for per-symbol PnL if available
 *
 * Existing /portfolio (Portfolio page) left untouched.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getRiskConsole } from "@/api/risk";
import { getDashboardV2 } from "@/api/dashboard";

const GREEN = "#4ade80";
const RED = "#f87171";
const MUTED = "#7e8e7e";

const SLEEVE_COLORS: Record<string, string> = {
  stock: "#9fb0cf",
  stocks: "#9fb0cf",
  crypto: "#f0b35a",
  options: "#c79bf0",
  option: "#c79bf0",
  quant: "#38bdf8",
  cash: "#3a4a3a",
};

function fmtUsd(usd: number, digits = 0): string {
  return `$${usd.toLocaleString("en-US", { maximumFractionDigits: digits })}`;
}

function fmtSigned(usd: number): string {
  const s = usd >= 0 ? "+$" : "-$";
  return `${s}${Math.abs(usd).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function sparkPoints(seed: number, up: boolean): string {
  let s = seed >>> 0;
  let y = 11;
  const out: string[] = [];
  for (let i = 0; i <= 10; i++) {
    s = (s * 1664525 + 1013904223) >>> 0;
    y += ((s / 4294967296) - 0.5) * 4 - (up ? 0.6 : -0.6);
    y = Math.max(3, Math.min(19, y));
    out.push(`${(i / 10 * 90).toFixed(0)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

// ─── Stat cards ─────────────────────────────────────────────────────────────

interface StatCard {
  label: string;
  value: string;
  color: string;
  sub: string;
  accent: string;
  seed: number;
  up: boolean;
}

function StatCard({ s }: { s: StatCard }) {
  return (
    <div
      className="rounded-[9px]"
      style={{
        border: "1px solid rgba(74,222,128,0.12)",
        borderTop: `2px solid ${s.accent}`,
        background: "#0a100a",
        padding: "15px 17px",
      }}
    >
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9,
          letterSpacing: "0.12em",
          color: MUTED,
        }}
      >
        {s.label}
      </div>
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 28,
          fontWeight: 600,
          color: s.color,
          marginTop: 8,
        }}
      >
        {s.value}
      </div>
      <div className="flex items-end justify-between" style={{ marginTop: 6 }}>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: MUTED,
          }}
        >
          {s.sub}
        </span>
        <svg
          viewBox="0 0 90 22"
          preserveAspectRatio="none"
          style={{ width: 74, height: 20 }}
        >
          <polyline
            points={sparkPoints(s.seed, s.up)}
            fill="none"
            stroke={s.accent}
            strokeWidth={1.3}
            opacity={0.75}
          />
        </svg>
      </div>
    </div>
  );
}

// ─── Capital allocation donut ────────────────────────────────────────────────

interface AllocSlice {
  name: string;
  pctN: number;
  amt: number;
  color: string;
}

function CapitalAllocation({ alloc, hover, onHover, onLeave, deployedPct, deployedUsd, overexposed }: {
  alloc: AllocSlice[];
  hover: number;
  onHover: (i: number) => void;
  onLeave: () => void;
  deployedPct: number;
  deployedUsd: number;
  overexposed: boolean;
}) {
  const CIRC = 2 * Math.PI * 76;
  let acc = 0;
  const arcs = alloc.map((a, i) => {
    const len = (a.pctN / 100) * CIRC;
    const seg = {
      color: a.color,
      width: hover === i ? 20 : 15,
      dash: `${len} ${CIRC - len}`,
      offset: -acc,
      opacity: hover === -1 || hover === i ? 1 : 0.32,
    };
    acc += len;
    return seg;
  });
  const AMBER = "#f0b35a";
  const center = hover >= 0
    ? {
        label: alloc[hover].name.toUpperCase(),
        pct: `${alloc[hover].pctN.toFixed(1)}%`,
        amt: fmtUsd(alloc[hover].amt),
        color: alloc[hover].color,
      }
    : {
        label: overexposed ? "OVEREXPOSED" : "DEPLOYED",
        pct: `${deployedPct.toFixed(1)}%`,
        amt: `${fmtUsd(deployedUsd)} live`,
        color: overexposed ? AMBER : GREEN,
      };

  return (
    <div
      className="rounded-[11px]"
      style={{
        border: "1px solid rgba(74,222,128,0.14)",
        background: "#0a100a",
        marginTop: 16,
        padding: "20px 24px",
      }}
    >
      <div className="flex items-center justify-between">
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            letterSpacing: "0.14em",
            color: MUTED,
          }}
        >
          CAPITAL DEPLOYED
        </span>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "#50604f",
          }}
        >
          hover a sleeve to inspect
        </span>
      </div>
      <div className="flex items-center gap-10" style={{ marginTop: 16 }}>
        <div
          className="relative"
          style={{ width: 200, height: 200, flex: "none" }}
        >
          <svg
            viewBox="0 0 200 200"
            style={{ width: 200, height: 200, transform: "rotate(-90deg)" }}
          >
            {arcs.map((a, i) => (
              <circle
                key={i}
                cx={100}
                cy={100}
                r={76}
                fill="none"
                stroke={a.color}
                strokeWidth={a.width}
                strokeDasharray={a.dash}
                strokeDashoffset={a.offset}
                opacity={a.opacity}
                style={{ transition: "all .18s ease" }}
              />
            ))}
          </svg>
          <div
            className="absolute inset-0 flex flex-col items-center justify-center"
            style={{ textAlign: "center" }}
          >
            <div
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 9,
                letterSpacing: "0.1em",
                color: MUTED,
              }}
            >
              {center.label}
            </div>
            <div
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 24,
                fontWeight: 600,
                color: center.color,
                marginTop: 3,
              }}
            >
              {center.pct}
            </div>
            <div
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12,
                color: "#9fb0a0",
                marginTop: 2,
              }}
            >
              {center.amt}
            </div>
          </div>
        </div>
        <div className="flex-1 flex flex-col gap-[3px]">
          {alloc.map((a, i) => (
            <div
              key={a.name}
              onMouseEnter={() => onHover(i)}
              onMouseLeave={onLeave}
              className="flex items-center gap-3"
              style={{
                padding: "9px 12px",
                borderRadius: 6,
                background: hover === i ? "rgba(74,222,128,0.05)" : "transparent",
                cursor: "pointer",
                transition: "background .15s ease",
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 3,
                  background: a.color,
                  boxShadow: hover === i ? `0 0 8px ${a.color}` : "none",
                }}
              />
              <span style={{ fontSize: 14, color: "#f4f8f4", width: 80 }}>
                {a.name}
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 13,
                  color: a.color,
                }}
              >
                {a.pctN.toFixed(1)}%
              </span>
              <div
                className="flex-1"
                style={{
                  height: 5,
                  background: "#121a12",
                  borderRadius: 3,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${a.pctN.toFixed(1)}%`,
                    height: "100%",
                    background: a.color,
                    opacity: 0.8,
                  }}
                />
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 13,
                  color: "#9fb0a0",
                  width: 70,
                  textAlign: "right",
                }}
              >
                {fmtUsd(a.amt)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Exposure by symbol ─────────────────────────────────────────────────────

interface ExpRow {
  symbol: string;
  qty: number;
  bots: number;
  botsList: string[];
  exposureUsd: number;
  unrealizedUsd: number;
  assetClass: string;
}

function ExposureBySymbol({ rows: rawRows }: { rows: ExpRow[] }) {
  const [sort, setSort] = useState<"sym" | "exp" | "pnl">("exp");
  const [dir, setDir] = useState<-1 | 1>(-1);
  const [filter, setFilter] = useState<string>("ALL");

  const rows = useMemo(() => {
    let r = [...rawRows];
    if (filter !== "ALL") {
      const FILTER_CLASS: Record<string, string[]> = {
        Stocks: ["stock", "stocks"],
        Crypto: ["crypto"],
        Options: ["option", "options"],
        Quant: ["quant"],
      };
      const allowed = FILTER_CLASS[filter] ?? [filter.toLowerCase()];
      r = r.filter((x) => allowed.includes(x.assetClass.toLowerCase()));
    }
    if (sort === "sym") {
      r.sort((a, b) => dir * a.symbol.localeCompare(b.symbol));
    } else if (sort === "pnl") {
      r.sort((a, b) => dir * (a.unrealizedUsd - b.unrealizedUsd));
    } else {
      r.sort((a, b) => dir * (a.exposureUsd - b.exposureUsd));
    }
    return r;
  }, [rawRows, sort, dir, filter]);

  const maxExp = Math.max(1, ...rows.map((r) => r.exposureUsd));
  const FILT = ["ALL", "Stocks", "Crypto", "Options", "Quant"];

  function toggleSort(key: "sym" | "pnl") {
    if (sort === key) setDir((d) => (d === 1 ? -1 : 1));
    else {
      setSort(key);
      setDir(-1);
    }
  }

  return (
    <div
      className="rounded-[11px] overflow-hidden"
      style={{
        border: "1px solid rgba(74,222,128,0.14)",
        background: "#0a100a",
        marginTop: 16,
      }}
    >
      <div
        className="flex items-center justify-between"
        style={{ padding: "16px 22px 12px" }}
      >
        <span style={{ fontSize: 17, fontWeight: 600, color: "#f4f8f4" }}>
          Exposure by Symbol
        </span>
        <div className="flex gap-[6px]">
          {FILT.map((f) => {
            const on = filter === f;
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 10,
                  color: on ? "#040804" : "#9fb0a0",
                  background: on ? GREEN : "transparent",
                  border: `1px solid ${on ? GREEN : "rgba(74,222,128,0.16)"}`,
                  borderRadius: 5,
                  padding: "5px 10px",
                  cursor: "pointer",
                  transition: "all .15s ease",
                }}
              >
                {f.toUpperCase()}
              </button>
            );
          })}
        </div>
      </div>
      <div
        className="grid items-center"
        style={{
          gridTemplateColumns: "1.2fr 1fr 1fr 1.6fr 1fr",
          padding: "8px 22px",
          borderTop: "1px solid rgba(74,222,128,0.08)",
          borderBottom: "1px solid rgba(74,222,128,0.1)",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9,
          letterSpacing: "0.1em",
          color: MUTED,
        }}
      >
        <span onClick={() => toggleSort("sym")} style={{ cursor: "pointer" }}>
          SYMBOL {sort === "sym" ? (dir > 0 ? "▲" : "▼") : ""}
        </span>
        <span style={{ textAlign: "right" }}>TOTAL QTY</span>
        <span style={{ textAlign: "right" }}>BOTS HOLDING</span>
        <span style={{ textAlign: "right" }}>EXPOSURE</span>
        <span
          onClick={() => toggleSort("pnl")}
          style={{ textAlign: "right", cursor: "pointer" }}
        >
          P&L {sort === "pnl" ? (dir > 0 ? "▲" : "▼") : ""}
        </span>
      </div>
      {rows.length === 0 ? (
        <div
          style={{
            padding: "24px 22px",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12,
            color: MUTED,
          }}
        >
          No positions match the filter.
        </div>
      ) : (
        rows.map((r) => {
          const accent = SLEEVE_COLORS[r.assetClass] || GREEN;
          return (
            <div
              key={r.symbol}
              className="grid items-center"
              style={{
                gridTemplateColumns: "1.2fr 1fr 1fr 1.6fr 1fr",
                padding: "11px 22px",
                borderBottom: "1px solid rgba(74,222,128,0.05)",
                transition: "background .15s ease",
              }}
            >
              <span className="flex items-center gap-[9px]">
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 1,
                    background: accent,
                  }}
                />
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 13,
                    color: "#f4f8f4",
                  }}
                >
                  {r.symbol}
                </span>
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  color: "#dce8dc",
                  textAlign: "right",
                }}
              >
                {r.qty.toLocaleString("en-US", { maximumFractionDigits: 4 })}
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  color: "#9fb0a0",
                  textAlign: "right",
                }}
              >
                {r.bots}
              </span>
              <span
                className="flex items-center gap-[10px] justify-end"
              >
                <div
                  style={{
                    width: 90,
                    height: 6,
                    background: "#121a12",
                    borderRadius: 3,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${(r.exposureUsd / maxExp * 100).toFixed(0)}%`,
                      height: "100%",
                      background: accent,
                      opacity: 0.85,
                    }}
                  />
                </div>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: "#dce8dc",
                    width: 74,
                    textAlign: "right",
                  }}
                >
                  {fmtUsd(r.exposureUsd)}
                </span>
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  color: r.unrealizedUsd >= 0 ? GREEN : RED,
                  textAlign: "right",
                }}
              >
                {fmtSigned(r.unrealizedUsd)}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PortfolioV2() {
  const { data: risk } = useQuery({
    queryKey: ["risk-console-v2"],
    queryFn: getRiskConsole,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const { data: dash } = useQuery({
    queryKey: ["dashboard-v2"],
    queryFn: getDashboardV2,
    staleTime: 60_000,
    retry: 1,
  });

  const [hover, setHover] = useState<number>(-1);

  const stats = useMemo<StatCard[]>(() => {
    const unreal = risk?.deployment?.unrealized_usd ?? 0;
    const deployPct = risk?.deployment?.deployment_pct ?? 0;
    const openPos = risk?.deployment?.open_positions_count ?? 0;
    const active = dash?.health?.bots_active ?? 0;
    const total = dash?.health?.bots_total ?? 0;

    return [
      {
        label: "TOTAL UNREALIZED P&L",
        value: fmtSigned(unreal),
        color: unreal >= 0 ? GREEN : RED,
        sub: "all bots combined",
        accent: unreal >= 0 ? GREEN : RED,
        seed: 5,
        up: unreal >= 0,
      },
      {
        label: "DEPLOYMENT",
        value: `${deployPct.toFixed(1)}%`,
        color: "#f4f8f4",
        sub: "weighted across portfolio",
        accent: "#f0b35a",
        seed: 12,
        up: true,
      },
      {
        label: "OPEN POSITIONS",
        value: String(openPos),
        color: "#f4f8f4",
        sub: "across all bots",
        accent: "#38bdf8",
        seed: 21,
        up: true,
      },
      {
        label: "BOTS ACTIVE",
        value: `${active} / ${total}`,
        color: "#f4f8f4",
        sub: `${Math.max(0, total - active)} paused`,
        accent: "#a78bfa",
        seed: 33,
        up: false,
      },
    ];
  }, [risk, dash]);

  const alloc = useMemo<AllocSlice[]>(() => {
    if (!risk) return [];
    const sleeves = risk.deployment?.sleeve_notional_usd || {};
    const pvUsd = (risk.fund?.pv_cents || 0) / 100;
    const deployedUsd = risk.deployment?.deployed_usd ?? 0;
    const cashUsd = Math.max(0, pvUsd - deployedUsd);
    const items: AllocSlice[] = [];
    const known: [string, string][] = [
      ["Quant", "quant"],
      ["Stocks", "stock"],
      ["Crypto", "crypto"],
      ["Options", "option"],
    ];
    for (const [name, key] of known) {
      const amt = (sleeves[key] || 0) + (key === "option" ? (sleeves["options"] || 0) : 0);
      if (amt > 0) {
        items.push({
          name,
          pctN: (amt / pvUsd) * 100,
          amt,
          color: SLEEVE_COLORS[key] || GREEN,
        });
      }
    }
    if (cashUsd > 0) {
      items.push({
        name: "Cash",
        pctN: (cashUsd / pvUsd) * 100,
        amt: cashUsd,
        color: SLEEVE_COLORS.cash,
      });
    }
    return items;
  }, [risk]);

  const expRows = useMemo<ExpRow[]>(() => {
    if (!risk?.net_exposure_by_symbol) return [];
    return risk.net_exposure_by_symbol.slice(0, 20).map((r) => ({
      symbol: r.symbol,
      qty: r.positions_count, // Real qty not on this endpoint, use positions count as proxy
      bots: r.bots.length,
      botsList: r.bots,
      exposureUsd: r.notional_usd,
      unrealizedUsd: r.unrealized_usd,
      assetClass: r.is_option ? "option" : (r.symbol.includes("/") ? "crypto" : "stock"),
    }));
  }, [risk]);

  const deployedUsd = risk?.deployment?.deployed_usd ?? 0;
  const deployedPct = risk?.deployment?.deployment_pct ?? 0;
  const overexposed = Boolean(risk?.deployment?.deployment_overexposed);

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
        @keyframes pv-pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
      `}</style>

      {/* Scanline */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1,
          pointerEvents: "none",
          background:
            "repeating-linear-gradient(0deg, rgba(0,0,0,0.22) 0px, rgba(0,0,0,0.22) 1px, transparent 1px, transparent 3px)",
          opacity: 0.32,
          mixBlendMode: "multiply",
        }}
      />

      {/* Top bar */}
      <div
        className="flex items-center gap-3"
        style={{
          padding: "11px 22px",
          borderBottom: "1px solid rgba(74,222,128,0.12)",
          background: "rgba(6,11,7,0.75)",
        }}
      >
        <div
          className="flex items-center gap-2"
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: "#50604f",
          }}
        >
          <Link to="/strategy" style={{ color: "#7e8e7e", textDecoration: "none" }}>
            Strategy Lab
          </Link>
          <span>/</span>
          <span style={{ color: GREEN }}>Portfolio View</span>
        </div>
        <div className="flex-1" />
        <span
          className="flex items-center gap-[6px]"
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: GREEN,
            border: "1px solid rgba(74,222,128,0.3)",
            borderRadius: 6,
            padding: "7px 11px",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: GREEN,
              boxShadow: "0 0 7px rgba(74,222,128,0.9)",
              animation: "pv-pulse 1.5s ease-in-out infinite",
            }}
          />
          24/7 LIVE
        </span>
      </div>

      <div
        className="mx-auto"
        style={{ maxWidth: 1180, padding: "26px 22px 60px", position: "relative", zIndex: 2 }}
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
          Portfolio View
        </h1>
        <p style={{ margin: "9px 0 0", fontSize: 14, color: MUTED }}>
          Consolidated paper-trading positions across all active bots.
        </p>

        {/* Paper banner */}
        <div
          className="flex items-center gap-3"
          style={{
            marginTop: 18,
            padding: "12px 18px",
            border: "1px solid rgba(251,191,36,0.28)",
            borderRadius: 8,
            background: "rgba(251,191,36,0.05)",
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "#fbbf24",
              boxShadow: "0 0 7px rgba(251,191,36,0.8)",
            }}
          />
          <span style={{ fontSize: 13, color: "#fbbf24", fontWeight: 600 }}>
            Paper trading only.
          </span>
          <span style={{ fontSize: 13, color: "#9fb0a0" }}>
            Live trading coming soon — paper trading only until RIA registration.
          </span>
        </div>

        <div
          className="grid gap-[14px]"
          style={{ gridTemplateColumns: "repeat(4, 1fr)", marginTop: 18 }}
        >
          {stats.map((s) => (
            <StatCard key={s.label} s={s} />
          ))}
        </div>

        <CapitalAllocation
          alloc={alloc}
          hover={hover}
          onHover={setHover}
          onLeave={() => setHover(-1)}
          deployedPct={deployedPct}
          deployedUsd={deployedUsd}
          overexposed={overexposed}
        />

        <ExposureBySymbol rows={expRows} />

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
        </div>
      </div>
    </div>
  );
}
