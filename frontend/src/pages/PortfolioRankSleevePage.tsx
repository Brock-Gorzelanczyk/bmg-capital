/**
 * PortfolioRankSleevePage — sleeve-level view for factor-based bots.
 *
 * PortfolioDetailPage filters by bot_profile.asset_class, which
 * portfolio-rank bots don't have — they live in portfolio_rank_bots.
 * This component renders the sleeve view for them: list of bots +
 * their key stats. Click a bot to drill into PortfolioRankDetailPage.
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
  starting_capital_cents: number;
  enabled: boolean;
  paper_citation: string | null;
  ssrn_id: string | null;
  last_rebalanced_at: string | null;
}

function fmtUsd(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export default function PortfolioRankSleevePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["portfolio-rank-bots"],
    queryFn: () => client.get<{ bots: PRBot[] }>("/admin/portfolio-rank/bots").then(r => r.data),
    staleTime: 60_000,
    retry: 1,
  });

  const bots = data?.bots ?? [];
  const enabled = bots.filter(b => b.enabled);
  const totalCapital = bots.reduce((s, b) => s + (b.starting_capital_cents || 0), 0);

  return (
    <div style={{ minHeight: "100vh", background: "#040705", color: "#dce8dc", fontFamily: "'Space Grotesk', sans-serif" }}>
      <div className="max-w-5xl mx-auto px-6 py-8">
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
              PORTFOLIO RANK SLEEVE
            </span>
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 12, color: "#f4f8f4" }}>
            Factor-Based Bots
          </h1>
          <p style={{ marginTop: 8, color: "#9fb0a0", fontSize: 14 }}>
            Rank a universe by a factor score, hold the top decile long, rebalance on a fixed schedule.
            Each bot is backed by a peer-reviewed academic paper. See{" "}
            <code style={{ color: "#10b981" }}>Strategy Library/BMG-Strategy-Knowledge-Vault-v1.md</code> for the full reference.
          </p>
        </div>

        {/* Summary stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 24 }}>
          <StatTile label="TOTAL CAPITAL" value={fmtUsd(totalCapital)} />
          <StatTile label="BOTS" value={`${bots.length}`} />
          <StatTile label="ENABLED" value={`${enabled.length}/${bots.length}`} />
        </div>

        {/* Bots list */}
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, letterSpacing: "0.16em", color: "#4ade80", marginBottom: 12 }}>
          // BOTS
        </div>

        {isLoading ? (
          <div style={{ color: "#7e8e7e", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>
            Loading portfolio-rank bots…
          </div>
        ) : bots.length === 0 ? (
          <div style={{ color: "#7e8e7e", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>
            No portfolio-rank bots yet.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {bots.map(bot => (
              <Link
                key={bot.id}
                to={`/strategy/bot/${bot.name}`}
                style={{
                  textDecoration: "none",
                  color: "inherit",
                  display: "block",
                  border: "1px solid rgba(74,222,128,0.14)",
                  background: "#0a100a",
                  padding: "16px 18px",
                  borderRadius: 8,
                  transition: "border-color .18s ease, transform .18s ease",
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.borderColor = "#10b981";
                  e.currentTarget.style.transform = "translateY(-1px)";
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.borderColor = "rgba(74,222,128,0.14)";
                  e.currentTarget.style.transform = "translateY(0)";
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 15, fontWeight: 600, color: "#f4f8f4" }}>
                    {bot.name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                  </span>
                  <span style={{
                    fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: "0.10em",
                    color: bot.enabled ? "#4ade80" : "#f0b35a",
                    background: bot.enabled ? "rgba(74,222,128,0.10)" : "rgba(240,179,90,0.10)",
                    padding: "2px 6px", borderRadius: 3,
                  }}>
                    {bot.enabled ? "ON" : "OFF"}
                  </span>
                </div>
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 20, color: "#f4f8f4", marginTop: 10,
                }}>
                  {fmtUsd(bot.starting_capital_cents)}
                </div>
                <div style={{ fontSize: 11, color: "#7e8e7e", marginTop: 4 }}>
                  {String(bot.factor_definition?.["kind"] ?? bot.factor_definition?.["type"] ?? "—")}
                  {" · "}
                  {bot.rebalance_schedule}
                </div>
                {bot.paper_citation && (
                  <div style={{ marginTop: 10, fontSize: 11, color: "#10b981" }}>
                    {bot.paper_citation}
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      border: "1px solid rgba(74,222,128,0.14)", background: "#0a100a",
      padding: "14px 16px", borderRadius: 8,
    }}>
      <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "#7e8e7e", fontFamily: "'JetBrains Mono', monospace" }}>
        {label}
      </div>
      <div style={{ marginTop: 6, fontFamily: "'JetBrains Mono', monospace", fontSize: 20, color: "#f4f8f4" }}>
        {value}
      </div>
    </div>
  );
}
