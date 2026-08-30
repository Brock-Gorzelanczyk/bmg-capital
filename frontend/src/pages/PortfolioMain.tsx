/**
 * PortfolioMain — /portfolio
 *
 * Clean, functional portfolio view. Pulls from live prod endpoints:
 *   - GET /portfolio/summary       — fund PV, sleeves, cash, MV
 *   - GET /portfolio/open-positions — per-position detail w/ live P&L
 *   - GET /admin/confluence/journal — closed picks for realized returns
 *
 * Replaces the empty PortfolioV2 as the primary /portfolio route.
 * Legacy pages remain at /portfolio-v2 (this file supersedes).
 */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";
import { getOpenPositions, type OpenPosition } from "@/api/bots";

const GREEN = "#4ade80";
const RED = "#f87171";
const MUTED = "#7e8e7e";
const CARD_BG = "rgba(10,15,10,0.55)";
const CARD_BORDER = "1px solid rgba(74,222,128,0.14)";

interface PortfolioSummary {
  total_value_cents: number;
  bot_sum_pv_cents: number;
  today_pnl_cents: number | null;
  today_pnl_pct: number;
  today_pnl_label: string;
  return_all_time_pct: number;
  return_30d_pct: number;
  open_positions: number;
  alpaca_cash_cents: number;
  alpaca_long_mv_cents: number;
  alpaca_short_mv_cents: number;
  portfolios: Array<{
    id: number;
    name: string;
    asset_class: string;
    portfolio_value_cents: number;
    today_pnl_cents: number;
    return_30d_pct: number;
  }>;
}

interface ConfluencePick {
  id: number;
  ticker: string;
  entry_date: string;
  entry_price: number;
  arm_state?: string;
  signals: { count: number };
  filled_price?: number | null;
  filled_at?: string | null;
  closed_at?: string | null;
  closed_price?: number | null;
  realized_pnl_usd?: number | null;
  close_reason?: string;
}

interface Journal {
  open_picks: ConfluencePick[];
  closed_picks: ConfluencePick[];
}

function fmtUsd(cents: number | null | undefined, digits = 2): string {
  if (cents == null) return "—";
  const v = cents / 100;
  return `$${v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
}

function fmtPct(pct: number | null | undefined, digits = 2): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(digits)}%`;
}

function fmtNum(n: number, digits = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${n.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
}

export default function PortfolioMain() {
  const summaryQ = useQuery<PortfolioSummary>({
    queryKey: ["portfolio-summary"],
    queryFn: async () => (await client.get<PortfolioSummary>("/portfolio/summary")).data,
    refetchInterval: 30_000,
  });

  const positionsQ = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    refetchInterval: 30_000,
  });

  const journalQ = useQuery<Journal>({
    queryKey: ["confluence-journal"],
    queryFn: async () => (await client.get<Journal>("/admin/confluence/journal")).data,
    refetchInterval: 60_000,
  });

  const s = summaryQ.data;
  const positions = positionsQ.data?.positions ?? [];
  const closed = journalQ.data?.closed_picks ?? [];
  const armed = journalQ.data?.open_picks.filter(p => p.arm_state === "ARMED") ?? [];
  const filled = journalQ.data?.open_picks.filter(p => (p.arm_state ?? "").startsWith("FILLED")) ?? [];

  // ── Derived stats ──
  const totalUnrealized = positions.reduce((a, p) => a + (p.unrealized_pnl_usd || 0), 0);
  const totalMV = positions.reduce((a, p) => a + (p.current_value_usd || 0), 0);
  const totalRealizedClosed = closed.reduce((a, p) => a + ((p.realized_pnl_usd || 0)), 0);

  const nav = (s?.total_value_cents ?? 0) / 100;
  const cash = (s?.alpaca_cash_cents ?? 0) / 100;
  const longMV = (s?.alpaca_long_mv_cents ?? 0) / 100;
  const deployedPct = nav > 0 ? (longMV / nav) * 100 : 0;

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 22px", color: "#e5e7eb" }}>
      {/* ─── Header ─── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: MUTED, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.08em" }}>
          // PORTFOLIO
        </div>
        <h1 style={{ margin: "4px 0 0", fontSize: 32, fontWeight: 700, color: "#f4f8f4", letterSpacing: "-0.02em" }}>
          Fund PV{" "}
          <span style={{ color: nav >= 10000 ? GREEN : RED, fontFamily: "'JetBrains Mono', monospace" }}>
            ${nav.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}
          </span>
          <span style={{ marginLeft: 16, fontSize: 14, color: MUTED, fontWeight: 400 }}>
            all-time {fmtPct(s?.return_all_time_pct)} · 30d {fmtPct(s?.return_30d_pct)} · today{" "}
            {s?.today_pnl_label === "market_closed"
              ? <span style={{ color: MUTED }}>market closed</span>
              : <span style={{ color: (s?.today_pnl_cents ?? 0) >= 0 ? GREEN : RED }}>
                  {fmtUsd(s?.today_pnl_cents)}
                </span>}
          </span>
        </h1>
      </div>

      {/* ─── Deployment stat cards ─── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12,
        marginBottom: 24,
      }}>
        <StatCard label="CASH" value={`$${cash.toLocaleString("en-US", { maximumFractionDigits: 2 })}`}
                  sub={`${((cash / nav) * 100).toFixed(1)}% of NAV`} />
        <StatCard label="LONG MV" value={`$${longMV.toLocaleString("en-US", { maximumFractionDigits: 2 })}`}
                  sub={`${deployedPct.toFixed(1)}% deployed`} />
        <StatCard label="OPEN POSITIONS" value={String(s?.open_positions ?? 0)}
                  sub={`unreal ${fmtNum(totalUnrealized)}`}
                  valueColor={totalUnrealized >= 0 ? GREEN : RED} />
        <StatCard label="CONFLUENCE PICKS" value={`${filled.length} filled / ${armed.length} armed`}
                  sub={`closed: ${closed.length}`} />
        <StatCard label="REALIZED (CLOSED)" value={fmtNum(totalRealizedClosed)}
                  sub={`${closed.length} closed picks`}
                  valueColor={totalRealizedClosed >= 0 ? GREEN : RED} />
      </div>

      {/* ─── Open positions table ─── */}
      <SectionCard title="OPEN POSITIONS" count={positions.length}>
        {positionsQ.isLoading && <Loading />}
        {positions.length === 0 && !positionsQ.isLoading && <Empty text="No open positions." />}
        {positions.length > 0 && (
          <table style={{ width: "100%", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: MUTED, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                <Th align="left">SYMBOL</Th>
                <Th align="right">QTY</Th>
                <Th align="right">ENTRY</Th>
                <Th align="right">MARK</Th>
                <Th align="right">MV</Th>
                <Th align="right">P&L $</Th>
                <Th align="right">P&L %</Th>
                <Th align="left">SIDE</Th>
                <Th align="left">HELD</Th>
              </tr>
            </thead>
            <tbody>
              {positions
                .sort((a: OpenPosition, b: OpenPosition) => (b.current_value_usd || 0) - (a.current_value_usd || 0))
                .map((p: OpenPosition) => (
                  <PositionRow key={p.symbol} p={p} />
                ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* ─── Confluence framework — ARMED (waiting) ─── */}
      {armed.length > 0 && (
        <SectionCard title="CONFLUENCE — ARMED (waiting for trigger or stale-fill)" count={armed.length}>
          <table style={{ width: "100%", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: MUTED, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                <Th align="left">SYMBOL</Th>
                <Th align="right">ENTRY $</Th>
                <Th align="right">SIGNALS</Th>
                <Th align="left">ENTRY DATE</Th>
              </tr>
            </thead>
            <tbody>
              {armed.sort((a, b) => b.id - a.id).map(p => (
                <tr key={p.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <Td align="left">
                    <Link to={`/positions/symbol/${p.ticker}`} style={{ color: GREEN, textDecoration: "none" }}>
                      {p.ticker}
                    </Link>
                  </Td>
                  <Td align="right">${p.entry_price?.toFixed(2)}</Td>
                  <Td align="right" color={p.signals.count >= 4 ? GREEN : "#fbbf24"}>{p.signals.count}/5</Td>
                  <Td align="left" color={MUTED}>{p.entry_date}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      {/* ─── Closed picks (realized) ─── */}
      <SectionCard title="CLOSED PICKS (realized P&L)" count={closed.length}>
        {closed.length === 0 && <Empty text="No closed picks yet. First one lands when a filled pick hits target/stop/time-stop." />}
        {closed.length > 0 && (
          <table style={{ width: "100%", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: MUTED, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                <Th align="left">SYMBOL</Th>
                <Th align="right">ENTRY $</Th>
                <Th align="right">EXIT $</Th>
                <Th align="right">RET</Th>
                <Th align="left">CLOSED</Th>
                <Th align="left">REASON</Th>
              </tr>
            </thead>
            <tbody>
              {closed.sort((a, b) => (b.closed_at || "").localeCompare(a.closed_at || "")).map(p => {
                const ret = ((p.closed_price ?? 0) - (p.entry_price ?? 0)) / (p.entry_price ?? 1) * 100;
                return (
                  <tr key={p.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <Td align="left">
                      <Link to={`/positions/symbol/${p.ticker}`} style={{ color: GREEN, textDecoration: "none" }}>
                        {p.ticker}
                      </Link>
                    </Td>
                    <Td align="right">${p.entry_price?.toFixed(2)}</Td>
                    <Td align="right">${p.closed_price?.toFixed(2)}</Td>
                    <Td align="right" color={ret >= 0 ? GREEN : RED}>{fmtPct(ret)}</Td>
                    <Td align="left" color={MUTED}>{(p.closed_at || "").slice(0, 10)}</Td>
                    <Td align="left" color={MUTED}>{p.close_reason || "—"}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* ─── Sleeves (legacy attribution — kept for reference) ─── */}
      <SectionCard title="SLEEVES (legacy allocation view)" count={s?.portfolios.length ?? 0}>
        <div style={{ fontSize: 11, color: MUTED, marginBottom: 8, fontFamily: "'JetBrains Mono', monospace" }}>
          // NOTE: legacy sleeve attribution shows $0 for all sleeves post-reset.
          // Confluence executor allocation is not mapped to any of these 4 sleeves.
          // See /admin/premarket-report for real per-allocation state.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
          {(s?.portfolios ?? []).map(p => (
            <div key={p.id} style={{
              padding: 12,
              background: CARD_BG,
              border: CARD_BORDER,
              borderRadius: 6,
            }}>
              <div style={{ fontSize: 10, color: MUTED, letterSpacing: "0.08em", fontFamily: "'JetBrains Mono', monospace" }}>
                {p.asset_class.toUpperCase()}
              </div>
              <div style={{ fontSize: 18, fontWeight: 600, color: "#f4f8f4", marginTop: 4 }}>
                ${(p.portfolio_value_cents / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>
                today {fmtUsd(p.today_pnl_cents)} · 30d {fmtPct(p.return_30d_pct)}
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

// ─── Sub-components ─────────────────────────────────────────────────────────

function StatCard({ label, value, sub, valueColor }: {
  label: string; value: string; sub?: string; valueColor?: string;
}) {
  return (
    <div style={{
      padding: "14px 16px",
      background: CARD_BG,
      border: CARD_BORDER,
      borderRadius: 6,
    }}>
      <div style={{ fontSize: 10, color: MUTED, letterSpacing: "0.08em", fontFamily: "'JetBrains Mono', monospace" }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: valueColor ?? "#f4f8f4", marginTop: 4, fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: MUTED, marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function SectionCard({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <div style={{
      marginBottom: 20,
      padding: 16,
      background: CARD_BG,
      border: CARD_BORDER,
      borderRadius: 8,
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "baseline",
        marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}>
        <div style={{ fontSize: 11, color: MUTED, letterSpacing: "0.08em", fontFamily: "'JetBrains Mono', monospace" }}>
          // {title}
        </div>
        {count != null && (
          <div style={{ fontSize: 11, color: MUTED, fontFamily: "'JetBrains Mono', monospace" }}>
            {count}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

function Loading() {
  return <div style={{ padding: 12, color: MUTED, fontSize: 12 }}>Loading…</div>;
}

function Empty({ text }: { text: string }) {
  return <div style={{ padding: 12, color: MUTED, fontSize: 12 }}>{text}</div>;
}

function Th({ children, align }: { children: React.ReactNode; align: "left" | "right" }) {
  return (
    <th style={{
      padding: "8px 10px", textAlign: align, fontSize: 10, fontWeight: 500,
      letterSpacing: "0.06em", color: MUTED, textTransform: "uppercase",
    }}>
      {children}
    </th>
  );
}

function Td({ children, align, color }: { children: React.ReactNode; align: "left" | "right"; color?: string }) {
  return (
    <td style={{ padding: "8px 10px", textAlign: align, color: color ?? "#e5e7eb", fontSize: 12 }}>
      {children}
    </td>
  );
}

function PositionRow({ p }: { p: OpenPosition }) {
  const pnl = p.unrealized_pnl_usd || 0;
  const pnlPct = p.unrealized_pnl_pct || 0;
  const held = p.opened_at ? Math.round((Date.now() - new Date(p.opened_at).getTime()) / 86400000) : null;
  return (
    <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
      <Td align="left">
        <Link to={`/positions/symbol/${p.symbol}`} style={{ color: GREEN, textDecoration: "none", fontWeight: 600 }}>
          {p.symbol}
        </Link>
      </Td>
      <Td align="right">{Number(p.qty).toFixed(0)}</Td>
      <Td align="right">${Number(p.entry_price).toFixed(2)}</Td>
      <Td align="right">${Number(p.current_price).toFixed(2)}</Td>
      <Td align="right">${Number(p.current_value_usd || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })}</Td>
      <Td align="right" color={pnl >= 0 ? GREEN : RED}>{fmtNum(pnl)}</Td>
      <Td align="right" color={pnlPct >= 0 ? GREEN : RED}>{fmtPct(pnlPct)}</Td>
      <Td align="left" color={MUTED}>{p.side}</Td>
      <Td align="left" color={MUTED}>{held != null ? `${held}d` : "—"}</Td>
    </tr>
  );
}
