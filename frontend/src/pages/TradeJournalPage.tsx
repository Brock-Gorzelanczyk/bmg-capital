import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

interface JournalTrade {
  trade_id: number;
  position_id: number;
  bot: string;
  asset_class: string;
  symbol: string;
  side: string;
  qty: number;
  entry_price_usd: number;
  exit_price_usd: number;
  opened_at: string | null;
  closed_at: string | null;
  hold_hours: number | null;
  exit_reason: string | null;
  pnl_usd: number;
  pnl_pct: number;
  is_option: boolean;
  signal_id: number | null;
}

interface JournalResponse {
  count: number;
  filters: any;
  trades: JournalTrade[];
}

interface StatsResponse {
  trades: number;
  wins: number;
  losses: number;
  scratches: number;
  win_rate: number | null;
  avg_winner_usd: number | null;
  avg_loser_usd: number | null;
  profit_factor: number | null;
  expectancy_usd: number | null;
  avg_hold_hours: number | null;
  total_pnl_usd: number;
  bot: string | null;
  days: number;
}

function fmtDollar(v: number): string {
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function pctClass(v: number): string {
  if (v > 0) return "text-[#4ade80]";
  if (v < 0) return "text-[#f87171]";
  return "text-t-hi";
}

export default function TradeJournalPage() {
  const [bot, setBot] = useState<string>("");
  const [symbol, setSymbol] = useState<string>("");
  const [days, setDays] = useState<number>(30);
  const [outcome, setOutcome] = useState<string>("all");

  const params = new URLSearchParams();
  if (bot) params.set("bot", bot);
  if (symbol) params.set("symbol", symbol);
  params.set("days", String(days));
  params.set("outcome", outcome);
  params.set("limit", "200");

  const { data: journal, isLoading } = useQuery({
    queryKey: ["trades-journal", bot, symbol, days, outcome],
    queryFn: () => client.get<JournalResponse>(`/trades?${params}`).then((r) => r.data),
    staleTime: 30_000,
  });

  const statsParams = new URLSearchParams();
  if (bot) statsParams.set("bot", bot);
  statsParams.set("days", String(days));
  const { data: stats } = useQuery({
    queryKey: ["trades-stats", bot, days],
    queryFn: () => client.get<StatsResponse>(`/trades/stats?${statsParams}`).then((r) => r.data),
    staleTime: 30_000,
  });

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-[1400px] mx-auto">
      <header>
        <h1 className="text-3xl font-bold text-t-hi tracking-tight">// TRADE JOURNAL</h1>
        <p className="text-xs text-t-muted mt-1 font-ui-t">
          Closed trades · win-rate + hold time + expectancy · last {days} days
        </p>
      </header>

      {/* ── Filters ────────────────────────────────────────────────────── */}
      <section className="bg-t-bg0 border border-t-dim rounded-xl p-4 grid grid-cols-1 md:grid-cols-4 gap-3">
        <div>
          <label className="text-[10px] tracking-widest text-t-muted uppercase block mb-1">Bot</label>
          <input
            value={bot}
            onChange={(e) => setBot(e.target.value)}
            placeholder="e.g. crypto_quant_aggressive"
            className="w-full min-h-[40px] px-3 bg-t-bg1 border border-t-dim rounded-lg text-t-hi text-sm font-mono-t focus:outline-none focus:ring-1 focus:ring-t-blue"
          />
        </div>
        <div>
          <label className="text-[10px] tracking-widest text-t-muted uppercase block mb-1">Symbol</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="AAPL / BTC/USD"
            className="w-full min-h-[40px] px-3 bg-t-bg1 border border-t-dim rounded-lg text-t-hi text-sm font-mono-t focus:outline-none focus:ring-1 focus:ring-t-blue"
          />
        </div>
        <div>
          <label className="text-[10px] tracking-widest text-t-muted uppercase block mb-1">Window</label>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-full min-h-[40px] px-3 bg-t-bg1 border border-t-dim rounded-lg text-t-hi text-sm font-mono-t focus:outline-none focus:ring-1 focus:ring-t-blue"
          >
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>1 year</option>
          </select>
        </div>
        <div>
          <label className="text-[10px] tracking-widest text-t-muted uppercase block mb-1">Outcome</label>
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            className="w-full min-h-[40px] px-3 bg-t-bg1 border border-t-dim rounded-lg text-t-hi text-sm font-mono-t focus:outline-none focus:ring-1 focus:ring-t-blue"
          >
            <option value="all">All</option>
            <option value="win">Wins only</option>
            <option value="loss">Losses only</option>
          </select>
        </div>
      </section>

      {/* ── Stats row ──────────────────────────────────────────────────── */}
      {stats && (
        <section className="bg-t-bg0 border border-t-dim rounded-xl p-5">
          <h2 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-3">
            // AGGREGATE STATS
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <div>
              <p className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">{stats.trades}</p>
              <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Trades</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">
                {stats.win_rate !== null ? `${(stats.win_rate * 100).toFixed(1)}%` : "—"}
              </p>
              <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">
                Win Rate ({stats.wins}W / {stats.losses}L)
              </p>
            </div>
            <div>
              <p className={`text-2xl font-bold tabular-nums font-mono-t ${pctClass(stats.total_pnl_usd)}`}>
                {fmtDollar(stats.total_pnl_usd)}
              </p>
              <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Total P&L</p>
            </div>
            <div>
              <p className={`text-2xl font-bold tabular-nums font-mono-t ${(stats.expectancy_usd || 0) >= 0 ? "text-[#4ade80]" : "text-[#f87171]"}`}>
                {stats.expectancy_usd !== null ? fmtDollar(stats.expectancy_usd) : "—"}
              </p>
              <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Expectancy / trade</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">
                {stats.profit_factor !== null ? stats.profit_factor.toFixed(2) : "—"}
              </p>
              <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Profit Factor</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">
                {stats.avg_hold_hours !== null
                  ? stats.avg_hold_hours < 24
                    ? `${stats.avg_hold_hours.toFixed(1)}h`
                    : `${(stats.avg_hold_hours / 24).toFixed(1)}d`
                  : "—"}
              </p>
              <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Avg Hold</p>
            </div>
          </div>
          {stats.avg_winner_usd !== null && stats.avg_loser_usd !== null && (
            <p className="text-xs text-t-muted mt-3 font-ui-t">
              Avg winner {fmtDollar(stats.avg_winner_usd)} · Avg loser {fmtDollar(stats.avg_loser_usd)}
            </p>
          )}
        </section>
      )}

      {/* ── Trades table ──────────────────────────────────────────────── */}
      <section className="bg-t-bg0 border border-t-dim rounded-xl p-5">
        <h2 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-3">
          // TRADES ({journal?.count ?? "…"})
        </h2>
        {isLoading ? (
          <div className="animate-pulse h-64 rounded-lg bg-t-bg1" />
        ) : !journal || journal.trades.length === 0 ? (
          <p className="text-t-muted font-ui-t text-sm">No closed trades in this window.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-mono-t">
              <thead>
                <tr className="text-t-muted text-[10px] uppercase tracking-widest border-b border-t-dim">
                  <th className="text-left py-2 pr-3">Closed</th>
                  <th className="text-left py-2 px-3">Bot</th>
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-left py-2 px-3">Side</th>
                  <th className="text-right py-2 px-3">Entry</th>
                  <th className="text-right py-2 px-3">Exit</th>
                  <th className="text-right py-2 px-3">P&L</th>
                  <th className="text-right py-2 px-3">%</th>
                  <th className="text-right py-2 px-3">Hold</th>
                  <th className="text-left py-2 pl-3">Reason</th>
                </tr>
              </thead>
              <tbody>
                {journal.trades.map((t) => (
                  <tr key={t.trade_id} className="border-b border-t-dim/50">
                    <td className="py-2 pr-3 text-t-muted text-xs whitespace-nowrap">
                      {t.closed_at ? new Date(t.closed_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                    </td>
                    <td className="py-2 px-3 text-t-hi text-xs">{t.bot}</td>
                    <td className="py-2 px-3 text-t-hi font-bold">{t.symbol}</td>
                    <td className="py-2 px-3 text-t-muted text-xs">{t.side}</td>
                    <td className="py-2 px-3 text-right text-t-hi tabular-nums">${t.entry_price_usd.toFixed(4)}</td>
                    <td className="py-2 px-3 text-right text-t-hi tabular-nums">${t.exit_price_usd.toFixed(4)}</td>
                    <td className={`py-2 px-3 text-right tabular-nums font-bold ${pctClass(t.pnl_usd)}`}>
                      {fmtDollar(t.pnl_usd)}
                    </td>
                    <td className={`py-2 px-3 text-right tabular-nums ${pctClass(t.pnl_pct)}`}>
                      {t.pnl_pct >= 0 ? "+" : ""}
                      {t.pnl_pct.toFixed(2)}%
                    </td>
                    <td className="py-2 px-3 text-right text-t-muted tabular-nums">
                      {t.hold_hours !== null
                        ? t.hold_hours < 24
                          ? `${t.hold_hours.toFixed(1)}h`
                          : `${(t.hold_hours / 24).toFixed(1)}d`
                        : "—"}
                    </td>
                    <td className="py-2 pl-3 text-t-muted text-xs">{t.exit_reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
