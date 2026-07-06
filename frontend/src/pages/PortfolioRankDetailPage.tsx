/**
 * PortfolioRankDetailPage — detail view for factor-based rank bots.
 *
 * Signal-trigger bots (crypto_quant_scalp_1m, stock_day, options_income, etc.)
 * render via BotDetailPage — it assumes bot_profiles + bot_allocations +
 * bot_signals + bot_positions. Portfolio-rank bots (momentum_umd,
 * quality_gross_profitability, dummy_alpha_rank) live in a different
 * shape: portfolio_rank_bots + portfolio_rank_holdings +
 * portfolio_rank_rebalance_log. This component reads them.
 *
 * Layout (deliberately compact):
 *   1. Header: bot name, factor kind, universe, rebalance schedule, capital
 *   2. Vault reference: paper citation + SSRN link
 *   3. Current holdings table (up to 60 rows)
 *   4. Rebalance log (last 5 runs)
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import client from "@/api/client";

interface PRBot {
  id: number;
  name: string;
  description: string | null;
  factor_definition: Record<string, unknown>;
  universe: Record<string, unknown>;
  rebalance_schedule: string;
  long_decile: number;
  short_decile: number;
  position_sizing: string;
  starting_capital_cents: number;
  enabled: boolean;
  paper_citation: string | null;
  ssrn_id: string | null;
  last_rebalanced_at: string | null;
}

interface PRHolding {
  symbol: string;
  side: string;
  target_weight: number;
  actual_weight: number;
  entry_price_cents: number | null;
  current_price_cents: number | null;
  entry_ts: string | null;
  last_marked_at: string | null;
  current_pnl_cents: number;
}

interface PRRebalanceLog {
  id: number;
  triggered_by: string;
  target_basket: Record<string, unknown>;
  adds: Array<Record<string, unknown>>;
  removes: string[];
  latency_ms: number;
  error: string | null;
  created_at: string | null;
}

function fmtUsd(cents: number | null | undefined): string {
  if (cents == null) return "—";
  return `$${(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function fmtPct(x: number | null | undefined, digits = 2): string {
  if (x == null) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export default function PortfolioRankDetailPage({ botName }: { botName: string }) {
  const { data: allBots, isLoading: botsLoading } = useQuery({
    queryKey: ["portfolio-rank-bots"],
    queryFn: () => client.get<{ bots: PRBot[] }>("/admin/portfolio-rank/bots").then(r => r.data),
    staleTime: 60_000,
    retry: 1,
  });

  const bot = allBots?.bots?.find(b => b.name === botName);

  const { data: holdingsData } = useQuery({
    queryKey: ["portfolio-rank-holdings", bot?.id],
    queryFn: () => client.get<{ holdings: PRHolding[]; count: number }>(
      `/admin/portfolio-rank/bots/${bot!.id}/holdings`
    ).then(r => r.data),
    enabled: !!bot?.id,
    staleTime: 60_000,
    retry: 1,
  });

  const { data: logData } = useQuery({
    queryKey: ["portfolio-rank-log", bot?.id],
    queryFn: () => client.get<{ entries: PRRebalanceLog[] }>(
      `/admin/portfolio-rank/bots/${bot!.id}/rebalance-log?limit=5`
    ).then(r => r.data),
    enabled: !!bot?.id,
    staleTime: 60_000,
    retry: 1,
  });

  if (botsLoading) {
    return (
      <div className="min-h-screen bg-t-bg0 text-t-hi p-8">
        <div className="text-t-muted font-mono-t text-sm">Loading portfolio-rank bot…</div>
      </div>
    );
  }
  if (!bot) {
    return (
      <div className="min-h-screen bg-t-bg0 text-t-hi p-8">
        <div className="text-t-red font-mono-t">Bot not found: {botName}</div>
        <Link to="/strategy" className="text-t-green underline text-sm mt-4 inline-block">← Strategy Lab</Link>
      </div>
    );
  }

  const holdings = holdingsData?.holdings ?? [];
  const logs = logData?.entries ?? [];
  const factorKind = String(bot.factor_definition?.["kind"] ?? bot.factor_definition?.["type"] ?? "unknown");
  const universeName = String(bot.universe?.["list_name"] ?? bot.universe?.["type"] ?? "custom");
  const displayName = botName.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div className="min-h-screen" style={{ background: "#040705", color: "#dce8dc", fontFamily: "'Space Grotesk', sans-serif" }}>
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Breadcrumb */}
        <Link to="/strategy" style={{ color: "#4ade80", fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
          ← STRATEGY LAB
        </Link>

        {/* Header */}
        <div style={{ marginTop: 20, marginBottom: 24, borderBottom: "1px solid rgba(74,222,128,0.12)", paddingBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: "0.14em",
              color: "#10b981", background: "rgba(16,185,129,0.10)",
              border: "1px solid rgba(16,185,129,0.30)", padding: "2px 8px", borderRadius: 3,
            }}>
              PORTFOLIO RANK
            </span>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: "0.14em",
              color: bot.enabled ? "#4ade80" : "#f0b35a",
              background: bot.enabled ? "rgba(74,222,128,0.10)" : "rgba(240,179,90,0.10)",
              border: `1px solid ${bot.enabled ? "rgba(74,222,128,0.30)" : "rgba(240,179,90,0.30)"}`,
              padding: "2px 8px", borderRadius: 3,
            }}>
              {bot.enabled ? "ENABLED" : "DISABLED"}
            </span>
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 12, color: "#f4f8f4" }}>{displayName}</h1>
          {bot.description && (
            <p style={{ marginTop: 8, color: "#9fb0a0", fontSize: 14 }}>{bot.description}</p>
          )}
        </div>

        {/* Key stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
          {[
            { label: "STARTING CAPITAL", value: fmtUsd(bot.starting_capital_cents) },
            { label: "REBALANCE", value: bot.rebalance_schedule.toUpperCase() },
            { label: "FACTOR", value: factorKind },
            { label: "UNIVERSE", value: universeName },
          ].map(s => (
            <div key={s.label} style={{
              border: "1px solid rgba(74,222,128,0.14)", background: "#0a100a",
              padding: "14px 16px", borderRadius: 8,
            }}>
              <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "#7e8e7e", fontFamily: "'JetBrains Mono', monospace" }}>
                {s.label}
              </div>
              <div style={{ marginTop: 6, fontFamily: "'JetBrains Mono', monospace", fontSize: 16, color: "#f4f8f4" }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>

        {/* Vault reference */}
        {bot.paper_citation && (
          <div style={{
            border: "1px solid rgba(16,185,129,0.20)", background: "rgba(16,185,129,0.04)",
            padding: "14px 16px", borderRadius: 8, marginBottom: 24,
          }}>
            <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "#10b981", fontFamily: "'JetBrains Mono', monospace" }}>
              // VAULT REFERENCE
            </div>
            <div style={{ marginTop: 6, color: "#dce8dc", fontSize: 13 }}>
              {bot.paper_citation}
              {bot.ssrn_id && (
                <>
                  {" — "}
                  <a
                    href={`https://ssrn.com/abstract=${bot.ssrn_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "#10b981", textDecoration: "underline" }}
                  >
                    SSRN {bot.ssrn_id} →
                  </a>
                </>
              )}
            </div>
          </div>
        )}

        {/* Holdings table */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, letterSpacing: "0.16em", color: "#4ade80" }}>
              // CURRENT HOLDINGS ({holdings.length})
            </div>
            {bot.last_rebalanced_at && (
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#7e8e7e" }}>
                last rebalanced {new Date(bot.last_rebalanced_at).toLocaleString()}
              </div>
            )}
          </div>
          {holdings.length === 0 ? (
            <div style={{
              border: "1px solid rgba(74,222,128,0.14)", background: "#0a100a",
              padding: 24, borderRadius: 8, color: "#7e8e7e", fontSize: 12, textAlign: "center",
            }}>
              No holdings yet. First rebalance runs on the next {bot.rebalance_schedule} cadence.
            </div>
          ) : (
            <div style={{ border: "1px solid rgba(74,222,128,0.14)", background: "#0a100a", borderRadius: 8, overflow: "hidden" }}>
              <div style={{
                display: "grid", gridTemplateColumns: "80px 60px 100px 100px 120px 100px",
                padding: "10px 16px", borderBottom: "1px solid rgba(74,222,128,0.10)",
                fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: "0.10em", color: "#7e8e7e",
              }}>
                <span>SYMBOL</span>
                <span>SIDE</span>
                <span style={{ textAlign: "right" }}>WEIGHT</span>
                <span style={{ textAlign: "right" }}>ENTRY</span>
                <span style={{ textAlign: "right" }}>CURRENT</span>
                <span style={{ textAlign: "right" }}>PNL</span>
              </div>
              {holdings.slice(0, 60).map((h, i) => (
                <div key={h.symbol + i} style={{
                  display: "grid", gridTemplateColumns: "80px 60px 100px 100px 120px 100px",
                  padding: "8px 16px", borderBottom: "1px solid rgba(74,222,128,0.05)",
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
                }}>
                  <span style={{ color: "#f4f8f4", fontWeight: 500 }}>{h.symbol}</span>
                  <span style={{ color: h.side === "long" ? "#4ade80" : "#ef4444" }}>{h.side.toUpperCase()}</span>
                  <span style={{ textAlign: "right", color: "#9fb0a0" }}>{fmtPct(h.target_weight)}</span>
                  <span style={{ textAlign: "right", color: "#9fb0a0" }}>{fmtUsd(h.entry_price_cents)}</span>
                  <span style={{ textAlign: "right", color: "#9fb0a0" }}>{fmtUsd(h.current_price_cents)}</span>
                  <span style={{
                    textAlign: "right",
                    color: h.current_pnl_cents > 0 ? "#4ade80" : h.current_pnl_cents < 0 ? "#ef4444" : "#7e8e7e",
                  }}>
                    {fmtUsd(h.current_pnl_cents)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Rebalance history */}
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, letterSpacing: "0.16em", color: "#4ade80", marginBottom: 12 }}>
            // RECENT REBALANCES
          </div>
          {logs.length === 0 ? (
            <div style={{
              border: "1px solid rgba(74,222,128,0.14)", background: "#0a100a",
              padding: 24, borderRadius: 8, color: "#7e8e7e", fontSize: 12, textAlign: "center",
            }}>
              No rebalance history yet.
            </div>
          ) : (
            <div style={{ border: "1px solid rgba(74,222,128,0.14)", background: "#0a100a", borderRadius: 8, overflow: "hidden" }}>
              {logs.map(log => (
                <div key={log.id} style={{
                  padding: "12px 16px", borderBottom: "1px solid rgba(74,222,128,0.05)",
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#dce8dc" }}>
                      {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
                    </span>
                    <span style={{ color: "#7e8e7e" }}>
                      trigger: {log.triggered_by} · latency: {log.latency_ms}ms
                    </span>
                  </div>
                  <div style={{ marginTop: 6, color: "#9fb0a0" }}>
                    {log.error
                      ? <span style={{ color: "#ef4444" }}>ERROR: {log.error}</span>
                      : <>+{log.adds?.length ?? 0} adds · -{log.removes?.length ?? 0} removes</>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
