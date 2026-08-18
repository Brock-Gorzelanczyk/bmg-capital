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
import { useMemo, useState } from "react";
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
  portfolio_rank: "#10b981",
};

const SLEEVE_ICONS: Record<string, string> = {
  stocks: "▤",
  crypto: "◍",
  options: "⚡",
  quant: "∑",
  portfolio_rank: "🎓",
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

// ─── Freshness helpers ────────────────────────────────────────────────────────

const ONE_TRADING_DAY_MS = 24 * 60 * 60 * 1000;

function fmtRelative(ts: number | null): string {
  if (!ts) return "unknown";
  const diff = Date.now() - ts;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

// ─── Portfolio Value hero band ────────────────────────────────────────────────

function PortfolioValueBand({ onUpdated }: { onUpdated?: (ts: number) => void }) {
  const query = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 30_000,
  });
  const agg = query.data;
  const dataUpdatedAt = query.dataUpdatedAt || null;

  useMemo(() => {
    if (dataUpdatedAt && onUpdated) onUpdated(dataUpdatedAt);
  }, [dataUpdatedAt, onUpdated]);

  const pv = agg?.total_value_cents ?? 0;
  const pnl = agg?.pnl;
  const freshnessTitle = `Last synced ${fmtRelative(dataUpdatedAt)} · canonical aggregate re-marks every 15m during market hours`;

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
            title={freshnessTitle}
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "44px",
              fontWeight: 600,
              letterSpacing: "-0.02em",
              color: "#f4f8f4",
              lineHeight: 1,
              textShadow: "0 0 26px rgba(74,222,128,0.28)",
              cursor: "help",
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
            <span style={{ color: GREEN }}>{fmtRelative(dataUpdatedAt)}</span>
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

function SleeveCard({ s, seed, lastSyncedAt }: { s: SleeveVals; seed: number; lastSyncedAt: number | null }) {
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

  // Data-sanity guards. Amber-flag impossible or suspicious values.
  //   - value_cents < 0            : sleeve PV can never be negative
  //   - crypto sleeve pnl == 0     : crypto marks 24/7; identical zero P&L
  //                                  means the mark job hasn't run
  //   - marks older than 1 tradday : gray-out PV number
  const pvNegative = s.value_cents < 0;
  const staleFreshness = lastSyncedAt !== null && (Date.now() - lastSyncedAt) > ONE_TRADING_DAY_MS;
  const cryptoZeroToday = s.asset_class === "crypto" && s.value_cents > 0 && s.pnl_cents === 0;
  const anySanityFlag = pvNegative || cryptoZeroToday;
  const pvColor = staleFreshness ? MUTED : "#f4f8f4";
  const pvTitle = pvNegative
    ? `⚠ Impossible value: sleeve PV should never be negative`
    : cryptoZeroToday
    ? `⚠ Crypto sleeve shows +$0 today — mark job may be frozen`
    : `Last synced ${fmtRelative(lastSyncedAt)} · ${s.asset_class} sleeve`;

  return (
    <Link
      to={`/strategy/portfolio/${s.id}`}
      className="relative rounded-[9px] overflow-hidden block group"
      style={{
        border: `1px solid ${DIM_GREEN}`,
        borderTop: `2px solid ${accent}`,
        background: "#0a100a",
        padding: "16px 17px",
        cursor: "pointer",
        textDecoration: "none",
        transition: "border-color .18s ease, transform .18s ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = accent;
        e.currentTarget.style.transform = "translateY(-1px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = DIM_GREEN;
        e.currentTarget.style.transform = "translateY(0)";
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
        title={pvTitle}
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 23,
          color: pvColor,
          marginTop: 13,
          cursor: "help",
        }}
      >
        {fmtUsd(s.value_cents)}
        {anySanityFlag && (
          <span
            title={pvTitle}
            style={{
              marginLeft: 6,
              fontSize: 12,
              color: "#f0b35a",
              verticalAlign: "middle",
            }}
          >
            ⚠
          </span>
        )}
      </div>
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9,
          color: anySanityFlag ? "#f0b35a" : "#50604f",
          letterSpacing: "0.14em",
          marginTop: 2,
        }}
      >
        SLEEVE PV
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
    </Link>
  );
}

// ─── Bot leaderboard ─────────────────────────────────────────────────────────

interface LBRow {
  rank: number;
  name: string;
  profile: string;
  totalTrades: number;
  allTimeCents: number;
  todayCents: number;
  deployedCents: number;
  return30d: number;
  assetClass: string;
  botType?: string;
  hasOpenPosition?: boolean;
  openPositionsCount?: number;
}

// 2026-08-18 Brock item 2: state-badge leaderboard using /api/leaderboard/bots.
// NULL rendering: any null value shows "—" with a tooltip explaining why.
// Never a $0.00 for an unknown. Unattributed row is separate, never absorbed.
interface LBBotV2 {
  profile: string;
  display_name: string;
  state: "TRADING" | "HOLDING" | "IDLE" | "PAUSED" | "RETIRED";
  sub_reason?: string | null;
  pause_reason?: string | null;
  has_bug: boolean;
  bug_reason?: string | null;
  trades_round_trips: number | null;
  win_rate: number | null;
  realized_cents: number | null;
  unrealized_cents: number | null;
  deployed_cents: number | null;
  return_30d_pct: number | null;
  realized_source?: string | null;
  unrealized_source?: string | null;
  deployed_source?: string | null;
  portfolio_value_cents: number | null;
  starting_capital_cents: number;
  signals_24h: number;
  trades_24h: number;
  open_positions_count: number;
}
interface LBResponseV2 {
  bots: LBBotV2[];
  unattributed: { value_cents: number; value_source: string; note: string } | null;
  fund_pv_cents: number;
  fund_pv_source: string;
  bot_sum_pv_cents: number;
  sum_bot_deployed_cents: number;
  counts_by_state: Record<string, number>;
  acceptance_flags: {
    no_zero_dollar_unknowns: boolean;
    deployed_le_fund_equity: boolean;
    unattributed_matches_delta: boolean;
  };
}

const STATE_STYLE: Record<LBBotV2["state"], { bg: string; fg: string; label: string }> = {
  TRADING: { bg: "rgba(74,222,128,0.14)", fg: "#4ade80", label: "TRADING" },
  HOLDING: { bg: "rgba(59,130,246,0.14)", fg: "#60a5fa", label: "HOLDING" },
  IDLE:    { bg: "rgba(148,163,184,0.12)", fg: "#94a3b8", label: "IDLE" },
  PAUSED:  { bg: "rgba(250,204,21,0.14)", fg: "#facc15", label: "PAUSED" },
  RETIRED: { bg: "rgba(100,116,139,0.10)", fg: "#64748b", label: "RETIRED" },
};

function StateBadge({ bot }: { bot: LBBotV2 }) {
  const s = STATE_STYLE[bot.state];
  const detail =
    bot.state === "IDLE" ? bot.sub_reason :
    bot.state === "PAUSED" ? bot.pause_reason :
    null;
  const tooltip = detail ? `${s.label}: ${detail}` : s.label;
  return (
    <span
      title={tooltip}
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 9,
        letterSpacing: "0.1em",
        color: s.fg,
        background: s.bg,
        border: `1px solid ${s.fg}33`,
        padding: "2px 6px",
        borderRadius: 3,
        whiteSpace: "nowrap",
      }}
    >
      {s.label}
      {detail && bot.state === "IDLE" && (
        <span style={{ opacity: 0.7, marginLeft: 4 }}>· {detail}</span>
      )}
    </span>
  );
}

function BugBadge({ reason }: { reason: string }) {
  return (
    <span
      title={`DATA BUG: ${reason}. Realized is 0 but there are closing trades — expected a real number. See invariant I27/I26 family.`}
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 9,
        letterSpacing: "0.05em",
        color: "#f87171",
        background: "rgba(248,113,113,0.14)",
        border: "1px solid rgba(248,113,113,0.4)",
        padding: "2px 6px",
        borderRadius: 3,
        whiteSpace: "nowrap",
      }}
    >
      ⚠ BUG
    </span>
  );
}

function CellDash({ tooltip }: { tooltip: string }) {
  return (
    <span
      title={tooltip}
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
        color: "#4a5a4a",
        textAlign: "right",
        cursor: "help",
      }}
    >
      —
    </span>
  );
}

function BotLeaderboardV2() {
  const q = useQuery({
    queryKey: ["leaderboard-v2"],
    queryFn: async () => (await client.get<LBResponseV2>("/leaderboard/bots")).data,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const data = q.data;

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
          src: {data?.fund_pv_source ?? "…"} · state counts:{" "}
          {data?.counts_by_state
            ? Object.entries(data.counts_by_state)
                .filter(([, n]) => n > 0)
                .map(([s, n]) => `${s}=${n}`)
                .join(" ")
            : "…"}
        </span>
      </div>

      {data && !data.acceptance_flags.no_zero_dollar_unknowns && (
        <div
          style={{
            marginTop: 8,
            padding: "6px 12px",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "#f87171",
            background: "rgba(248,113,113,0.10)",
            border: "1px solid rgba(248,113,113,0.3)",
            borderRadius: 4,
          }}
          title="At least one TRADING row has realized_cents=null. Endpoint acceptance flag failed."
        >
          ⚠ acceptance failed: no_zero_dollar_unknowns
        </div>
      )}

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
            gridTemplateColumns: "150px 1fr 60px 60px 100px 100px 100px 80px",
            padding: "9px 18px",
            borderBottom: `1px solid ${DIM_GREEN}`,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9,
            letterSpacing: "0.1em",
            color: MUTED,
          }}
        >
          <span>STATUS</span>
          <span>BOT</span>
          <span style={{ textAlign: "right", color: "#facc15" }}>TRADES</span>
          <span style={{ textAlign: "right" }}>WIN%</span>
          <span style={{ textAlign: "right" }}>REALIZED</span>
          <span style={{ textAlign: "right" }}>UNREALIZED</span>
          <span style={{ textAlign: "right" }}>DEPLOYED</span>
          <span style={{ textAlign: "right" }}>30D</span>
        </div>
        {(data?.bots ?? []).map((b) => {
          const featured = false;
          const isRetired = b.state === "RETIRED";
          const rowStyle: React.CSSProperties = {
            gridTemplateColumns: "150px 1fr 60px 60px 100px 100px 100px 80px",
            padding: "9px 18px",
            borderBottom: "1px solid rgba(74,222,128,0.05)",
            background: "transparent",
            opacity: isRetired ? 0.4 : 1,
            textDecoration: "none",
            color: "inherit",
            cursor: "pointer",
          };
          return (
            <Link
              key={b.profile}
              to={`/strategy/bot/${b.profile}`}
              className="grid items-center"
              style={rowStyle}
              onMouseEnter={(e) => {
                if (!isRetired) e.currentTarget.style.background = "rgba(74,222,128,0.04)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
              }}
            >
              <span className="flex items-center gap-1">
                <StateBadge bot={b} />
                {b.has_bug && b.bug_reason && <BugBadge reason={b.bug_reason} />}
              </span>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "#f4f8f4",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {b.display_name}
              </span>
              {/* TRADES (round trips) */}
              {b.trades_round_trips !== null && b.trades_round_trips > 0 ? (
                <span
                  title={`${b.trades_round_trips} closing trade${b.trades_round_trips === 1 ? "" : "s"} (round trips)`}
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: "#facc15",
                    textAlign: "right",
                    fontWeight: 600,
                  }}
                >
                  {b.trades_round_trips.toLocaleString()}
                </span>
              ) : b.trades_round_trips === 0 ? (
                <span
                  title="Zero closing trades — bot has no round trips yet"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: MUTED,
                    textAlign: "right",
                  }}
                >
                  0
                </span>
              ) : (
                <CellDash tooltip="trades count unavailable" />
              )}
              {/* WIN% */}
              {b.win_rate !== null ? (
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: "#9fb0a0",
                    textAlign: "right",
                  }}
                >
                  {(b.win_rate * 100).toFixed(0)}%
                </span>
              ) : (
                <CellDash tooltip="win rate not yet computed" />
              )}
              {/* REALIZED */}
              {b.realized_cents !== null ? (
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: b.realized_cents >= 0 ? GREEN : RED,
                    textAlign: "right",
                  }}
                  title={`source: ${b.realized_source ?? "unknown"}`}
                >
                  {fmtSignedUsd(b.realized_cents)}
                </span>
              ) : (
                <CellDash
                  tooltip={
                    b.state === "HOLDING"
                      ? "no closing trades yet — realized unknown"
                      : b.state === "IDLE"
                      ? "bot idle — no realized P&L"
                      : "realized unavailable"
                  }
                />
              )}
              {/* UNREALIZED */}
              {b.unrealized_cents !== null ? (
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: b.unrealized_cents >= 0 ? GREEN : RED,
                    textAlign: "right",
                  }}
                  title={`source: ${b.unrealized_source ?? "unknown"}`}
                >
                  {fmtSignedUsd(b.unrealized_cents)}
                </span>
              ) : (
                <CellDash tooltip="no open positions to mark" />
              )}
              {/* DEPLOYED */}
              {b.deployed_cents !== null ? (
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: "#9fb0a0",
                    textAlign: "right",
                  }}
                  title={`source: ${b.deployed_source ?? "unknown"}`}
                >
                  {fmtUsd(b.deployed_cents)}
                </span>
              ) : (
                <CellDash tooltip="nothing deployed" />
              )}
              {/* 30D */}
              {b.return_30d_pct !== null ? (
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    color: b.return_30d_pct >= 0 ? GREEN : RED,
                    textAlign: "right",
                  }}
                >
                  {(b.return_30d_pct >= 0 ? "+" : "") + b.return_30d_pct.toFixed(2)}%
                </span>
              ) : (
                <CellDash tooltip="30d return unavailable" />
              )}
            </Link>
          );
        })}

        {/* Unattributed row — separate, never absorbed into a bot row. */}
        {data?.unattributed && data.unattributed.value_cents !== 0 && (
          <div
            className="grid items-center"
            style={{
              gridTemplateColumns: "150px 1fr 60px 60px 100px 100px 100px 80px",
              padding: "11px 18px",
              borderTop: `1px solid ${DIM_GREEN}`,
              background: "rgba(250,204,21,0.04)",
            }}
            title={data.unattributed.note}
          >
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 9,
                letterSpacing: "0.1em",
                color: "#facc15",
                background: "rgba(250,204,21,0.14)",
                border: "1px solid rgba(250,204,21,0.3)",
                padding: "2px 6px",
                borderRadius: 3,
                whiteSpace: "nowrap",
              }}
            >
              UNATTRIBUTED
            </span>
            <span
              style={{
                fontSize: 13,
                fontWeight: 500,
                color: "#facc15",
                fontStyle: "italic",
              }}
            >
              broker positions no bot claims
            </span>
            <CellDash tooltip="n/a" />
            <CellDash tooltip="n/a" />
            <CellDash tooltip="not attributable" />
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12,
                color: "#facc15",
                textAlign: "right",
                fontWeight: 600,
              }}
              title={`source: ${data.unattributed.value_source}`}
            >
              {fmtSignedUsd(data.unattributed.value_cents)}
            </span>
            <CellDash tooltip="n/a" />
            <CellDash tooltip="n/a" />
          </div>
        )}
      </div>

      {q.isError && (
        <div
          style={{
            marginTop: 8,
            padding: "6px 12px",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "#f87171",
          }}
        >
          ⚠ leaderboard fetch failed
        </div>
      )}
    </>
  );
}

// Legacy row-based leaderboard — kept for backwards-compat callers only.
// New code should use BotLeaderboardV2 above. If nothing calls this after
// StrategyLabV2 swap lands, delete in a follow-up.
function BotLeaderboardLegacy({ rows }: { rows: LBRow[] }) {
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
          // BOT LEADERBOARD (legacy)
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
            gridTemplateColumns: "44px 1fr 70px 100px 100px 100px 80px",
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
          <span style={{ textAlign: "right", color: "#facc15" }}>TRADES</span>
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
            <Link
              key={l.profile + i}
              to={`/strategy/bot/${l.profile}`}
              className="grid items-center"
              style={{
                gridTemplateColumns: "44px 1fr 70px 100px 100px 100px 80px",
                padding: featured ? "13px 18px" : "9px 18px",
                background: featured ? "rgba(74,222,128,0.05)" : "transparent",
                borderBottom: "1px solid rgba(74,222,128,0.05)",
                borderLeft: featured
                  ? `2px solid ${GREEN}`
                  : "2px solid transparent",
                textDecoration: "none",
                color: "inherit",
                cursor: "pointer",
                transition: "background .15s ease",
              }}
              onMouseEnter={(e) => {
                if (!featured) {
                  e.currentTarget.style.background = "rgba(74,222,128,0.04)";
                }
              }}
              onMouseLeave={(e) => {
                if (!featured) {
                  e.currentTarget.style.background = "transparent";
                }
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
                {l.hasOpenPosition && (
                  <span
                    title={`LIVE — ${l.openPositionsCount ?? 1} open position${(l.openPositionsCount ?? 1) === 1 ? "" : "s"}`}
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: "#22c55e",
                      boxShadow: "0 0 6px rgba(34,197,94,0.9), 0 0 12px rgba(34,197,94,0.4)",
                      flexShrink: 0,
                      animation: "sl-live-pulse 1.6s ease-in-out infinite",
                    }}
                  />
                )}
                {l.botType === "portfolio_rank" && (
                  <span
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 8,
                      letterSpacing: "0.1em",
                      color: "#10b981",
                      background: "rgba(16,185,129,0.10)",
                      border: "1px solid rgba(16,185,129,0.30)",
                      padding: "1px 5px",
                      borderRadius: 3,
                      flexShrink: 0,
                    }}
                  >
                    PR
                  </span>
                )}
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
                  color: "#facc15",  // yellow — per Brock spec 2026-08-05
                  textAlign: "right",
                  fontWeight: 600,
                }}
                title={`${l.totalTrades} total trade${l.totalTrades === 1 ? "" : "s"} ever placed by this bot`}
              >
                {l.totalTrades.toLocaleString()}
              </span>
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
            </Link>
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

// ─── Data-sanity banner ───────────────────────────────────────────────────────

interface SanityFlag {
  severity: "warn" | "info";
  label: string;
  detail: string;
}

function SanityBanner({ flags }: { flags: SanityFlag[] }) {
  if (flags.length === 0) return null;
  return (
    <div
      className="rounded-[8px] mt-4"
      style={{
        border: "1px solid rgba(240,179,90,0.35)",
        background: "rgba(240,179,90,0.06)",
        padding: "10px 14px",
      }}
    >
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          letterSpacing: "0.14em",
          color: "#f0b35a",
        }}
      >
        ⚠ DATA-SANITY CHECKS · {flags.length} impossible/suspicious value{flags.length === 1 ? "" : "s"}
      </div>
      <ul style={{ margin: "6px 0 0", padding: 0, listStyle: "none" }}>
        {flags.map((f, i) => (
          <li
            key={i}
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: "#dce8dc",
              marginTop: 3,
            }}
          >
            <span style={{ color: "#f0b35a" }}>{f.label}</span>{" "}
            <span style={{ color: MUTED }}>· {f.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── Gate experiment panel ────────────────────────────────────────────────────
//
// Surfaces the 985f176d threshold experiment: for each experiment bot, show
// prior/new composite gate values, trades + expectancy in the 30-59 band
// (admitted under the loosened gate) vs 60+ band, and revert-candidate flags.
// Powered by GET /api/admin/threshold-experiment which needs admin auth.
// Falls back to a compact "requires admin" note when not authorized.

interface BandStats {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  expectancy_usd: number | null;
  total_pnl_usd: number;
}

interface ExperimentRow {
  bot: string;
  in_experiment: boolean;
  band_30_59: BandStats;
  band_60_plus: BandStats;
  band_null_pre_experiment: BandStats;
  revert_candidate: boolean;
  revert_reason: string | null;
}

interface ExperimentReport {
  as_of: string;
  days_window: number;
  experiment_bots: string[];
  revert_candidates: string[];
  per_bot: ExperimentRow[];
}

function GateExperimentPanel() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["threshold-experiment"],
    queryFn: async (): Promise<ExperimentReport> => {
      const res = await client.get<ExperimentReport>("/admin/threshold-experiment", {
        params: { days: 14 },
      });
      return res.data;
    },
    staleTime: 300_000,
    retry: false,
  });

  const experimentRows = useMemo<ExperimentRow[]>(() => {
    if (!data) return [];
    // Show experiment bots first, sorted so revert-candidates float to top.
    return [...data.per_bot]
      .filter((r) => r.in_experiment)
      .sort((a, b) => {
        if (a.revert_candidate !== b.revert_candidate) return a.revert_candidate ? -1 : 1;
        return b.band_30_59.trades - a.band_30_59.trades;
      });
  }, [data]);

  if (error) {
    return (
      <div className="mt-6">
        <div
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            letterSpacing: "0.16em",
            color: GREEN,
            opacity: 0.8,
          }}
        >
          // GATE EXPERIMENT · 30 threshold, 14d window
        </div>
        <div
          className="rounded-[8px] mt-2"
          style={{
            border: `1px solid ${DIM_GREEN}`,
            background: "#0a100a",
            padding: "10px 14px",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: MUTED,
          }}
        >
          Experiment panel requires admin auth · sign in as admin to view band-level stats.
        </div>
      </div>
    );
  }

  return (
    <div className="mt-6">
      <div className="flex items-center gap-3">
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            letterSpacing: "0.16em",
            color: GREEN,
            opacity: 0.8,
          }}
        >
          // GATE EXPERIMENT · 30 threshold, {data?.days_window ?? 14}d
        </span>
        <span
          className="flex-1"
          style={{
            height: 1,
            background: "linear-gradient(90deg,rgba(74,222,128,0.2),transparent)",
          }}
        />
        {data && data.revert_candidates.length > 0 && (
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              color: "#f0b35a",
            }}
          >
            {data.revert_candidates.length} revert candidate{data.revert_candidates.length === 1 ? "" : "s"}
          </span>
        )}
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
            gridTemplateColumns: "1.4fr 68px 90px 90px 90px 90px 90px 90px",
            padding: "9px 18px",
            borderBottom: `1px solid ${DIM_GREEN}`,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9,
            letterSpacing: "0.1em",
            color: MUTED,
          }}
        >
          <span>BOT</span>
          <span style={{ textAlign: "right" }}>GATE</span>
          <span style={{ textAlign: "right" }}>30–59 N</span>
          <span style={{ textAlign: "right" }}>30–59 WIN%</span>
          <span style={{ textAlign: "right" }}>30–59 EXP $</span>
          <span style={{ textAlign: "right" }}>60+ N</span>
          <span style={{ textAlign: "right" }}>60+ WIN%</span>
          <span style={{ textAlign: "right" }}>60+ EXP $</span>
        </div>
        {isLoading && (
          <div
            style={{
              padding: "12px 18px",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: MUTED,
            }}
          >
            Loading experiment stats…
          </div>
        )}
        {!isLoading && experimentRows.length === 0 && (
          <div
            style={{
              padding: "12px 18px",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: MUTED,
            }}
          >
            No trades yet in either band · experiment tagging accumulates as trades close.
          </div>
        )}
        {experimentRows.map((r) => {
          const lowExp = r.band_30_59.expectancy_usd;
          const hiExp = r.band_60_plus.expectancy_usd;
          const lowExpColor = lowExp === null ? MUTED : lowExp > 0 ? GREEN : RED;
          const hiExpColor = hiExp === null ? MUTED : hiExp > 0 ? GREEN : RED;
          return (
            <div
              key={r.bot}
              className="grid items-center"
              style={{
                gridTemplateColumns: "1.4fr 68px 90px 90px 90px 90px 90px 90px",
                padding: "8px 18px",
                borderBottom: "1px solid rgba(74,222,128,0.05)",
                background: r.revert_candidate ? "rgba(240,179,90,0.05)" : "transparent",
                borderLeft: r.revert_candidate
                  ? `2px solid #f0b35a`
                  : "2px solid transparent",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12,
              }}
              title={r.revert_reason || undefined}
            >
              <span style={{ color: "#f4f8f4" }}>
                {r.bot}
                {r.revert_candidate && (
                  <span style={{ marginLeft: 6, color: "#f0b35a", fontSize: 10 }}>REVERT?</span>
                )}
              </span>
              <span style={{ textAlign: "right", color: "#38bdf8" }}>30</span>
              <span style={{ textAlign: "right", color: "#dce8dc" }}>{r.band_30_59.trades}</span>
              <span style={{ textAlign: "right", color: MUTED }}>
                {r.band_30_59.win_rate !== null
                  ? `${(r.band_30_59.win_rate * 100).toFixed(0)}%`
                  : "—"}
              </span>
              <span style={{ textAlign: "right", color: lowExpColor }}>
                {lowExp !== null ? (lowExp >= 0 ? "+" : "") + lowExp.toFixed(2) : "—"}
              </span>
              <span style={{ textAlign: "right", color: "#dce8dc" }}>{r.band_60_plus.trades}</span>
              <span style={{ textAlign: "right", color: MUTED }}>
                {r.band_60_plus.win_rate !== null
                  ? `${(r.band_60_plus.win_rate * 100).toFixed(0)}%`
                  : "—"}
              </span>
              <span style={{ textAlign: "right", color: hiExpColor }}>
                {hiExp !== null ? (hiExp >= 0 ? "+" : "") + hiExp.toFixed(2) : "—"}
              </span>
            </div>
          );
        })}
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
  const { data: agg } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 30_000,
  });

  // Sleeve values from dashboard/v2 response (fallback to zeros).
  // Portfolio Rank added 2026-07-06 for Phase 2 anomaly bots so /strategy
  // shows the same 5 sleeves as /dashboard.
  const sleeves = useMemo<SleeveVals[]>(() => {
    if (!dash?.sleeves) return [];
    const order = ["stocks", "crypto", "options", "quant", "portfolio_rank"];
    const displayNames: Record<string, string> = {
      stocks: "Stocks",
      crypto: "Crypto",
      options: "Options",
      quant: "Quant",
      portfolio_rank: "Portfolio Rank",
    };
    return order.map((key) => {
      const s: any = (dash.sleeves as any)[key] || {};
      return {
        id: key,
        name: displayNames[key] ?? (key[0].toUpperCase() + key.slice(1)),
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

  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);

  const leaders = useMemo<LBRow[]>(() => {
    const lb = dash?.portfolio?.leaderboard || [];
    // 2026-07-06: was .slice(0, 8) — truncated at 8 rows even though the
    // fleet is now 25+ bots. Show all so ranks 9-25 (plus the two
    // portfolio-rank bots) are visible.
    return lb.map((l: any, i: number) => {
      // Backend tags entries with bot_type = "signal_trigger" | "portfolio_rank"
      // as of the canonical.py leaderboard integration. Fall back to name
      // heuristics for older payloads.
      const isPR =
        l.bot_type === "portfolio_rank"
        || l.profile === "momentum_umd"
        || l.profile === "quality_gross_profitability"
        || l.profile === "dummy_alpha_rank";
      return {
        rank: i + 1,
        name: l.name || l.profile,
        profile: l.profile,
        totalTrades: Number(l.total_trades || 0),
        allTimeCents: (l.portfolio_value_cents || 0) - (l.starting_capital_cents || 0),
        todayCents: l.today_pnl_cents || 0,
        deployedCents: l.deployed_cents || 0,
        return30d: l.return_30d_pct || 0,
        assetClass:
          isPR ? "portfolio_rank"
          : l.profile?.startsWith("stock") ? "stocks"
          : l.profile?.startsWith("crypto") ? "crypto"
          : l.profile?.startsWith("options") ? "options"
          : "quant",
        botType: (l.bot_type as string) || (isPR ? "portfolio_rank" : "signal_trigger"),
        hasOpenPosition: Boolean(l.has_open_position),
        openPositionsCount: Number(l.open_positions_count || 0),
      };
    });
  }, [dash]);

  // Bot count SINGLE SOURCE (spec item #4).
  // The leaderboard is the array that actually renders the table, so derive
  // the top-line count from it. Prior code summed sleeve bots_active — that
  // gave 38/41/46 depending on which snapshot the sleeve rollup landed on.
  const activeBotCount = leaders.length;
  const sleeveBotSum = useMemo(
    () => sleeves.reduce((sum, s) => sum + s.bots_active, 0),
    [sleeves],
  );

  // Data-sanity guards (spec item #1). Every check is a client-side invariant.
  const sanityFlags = useMemo<SanityFlag[]>(() => {
    const out: SanityFlag[] = [];
    // 1. Sleeve PV impossible negative
    for (const s of sleeves) {
      if (s.value_cents < 0) {
        out.push({
          severity: "warn",
          label: `${s.name} sleeve PV negative`,
          detail: `${fmtSignedUsd(s.value_cents)} — sleeve PV cannot be negative`,
        });
      }
    }
    // 2. Crypto sleeve pnl_cents == 0 while value_cents > 0 → mark frozen
    for (const s of sleeves) {
      if (s.asset_class === "crypto" && s.value_cents > 0 && s.pnl_cents === 0) {
        out.push({
          severity: "warn",
          label: "Crypto marks may be stale",
          detail: "Crypto trades 24/7 — a $0 today P&L usually means the mark job has not run",
        });
      }
    }
    // 3. Header/table count mismatch
    if (sleeveBotSum > 0 && sleeveBotSum !== activeBotCount) {
      out.push({
        severity: "warn",
        label: "Bot count mismatch",
        detail: `Sleeve rollup reports ${sleeveBotSum} bots but leaderboard renders ${activeBotCount}`,
      });
    }
    // 4. Identical P&L windows (all_time == mtd == wtd == today ≠ 0). Frozen aggregate.
    const pnl = agg?.pnl;
    if (pnl?.all_time && pnl?.today && pnl?.mtd && pnl?.wtd) {
      const at = pnl.all_time.cents;
      const t = pnl.today.cents;
      const m = pnl.mtd.cents;
      const w = pnl.wtd.cents;
      if (at !== 0 && at === t && at === m && at === w) {
        out.push({
          severity: "warn",
          label: "P&L windows identical across all periods",
          detail: `all_time = mtd = wtd = today = ${fmtSignedUsd(at)} — window computation likely broken`,
        });
      }
    }
    return out;
  }, [sleeves, activeBotCount, sleeveBotSum, agg]);

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
        @keyframes sl-live-pulse { 0%,100%{ transform:scale(1); opacity:1 } 50%{ transform:scale(1.25); opacity:0.7 } }
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
            to="/portfolio"
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
            title={`Derived from the leaderboard array (single source of truth) · sleeve rollup reports ${sleeveBotSum}`}
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: MUTED,
              cursor: "help",
            }}
          >
            {activeBotCount} bots active
          </div>
        </div>

        <SanityBanner flags={sanityFlags} />

        <PortfolioValueBand onUpdated={setLastSyncedAt} />

        <div
          className="grid gap-[14px]"
          style={{ gridTemplateColumns: "repeat(5, 1fr)", marginTop: 16 }}
        >
          {sleeves.map((s, i) => (
            <SleeveCard key={s.id} s={s} seed={7 + i * 12} lastSyncedAt={lastSyncedAt} />
          ))}
        </div>

        <BotLeaderboardV2 />

        <GateExperimentPanel />

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
