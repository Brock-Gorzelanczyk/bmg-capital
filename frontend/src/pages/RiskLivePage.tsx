import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getRiskConsole, flattenAll } from "@/api/risk";
import { toast } from "sonner";

function fmtUsdRaw(usd: number): string {
  const sign = usd >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(usd).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pctClass(v: number): string {
  if (v > 0.001) return "text-[#4ade80]";
  if (v < -0.001) return "text-[#f87171]";
  return "text-t-hi";
}

function corrClass(v: number): string {
  const a = Math.abs(v);
  if (a >= 0.7) return "text-[#f87171]";
  if (a >= 0.4) return "text-[#facc15]";
  return "text-t-muted";
}

export default function RiskLivePage() {
  const qc = useQueryClient();
  const [showFlattenModal, setShowFlattenModal] = useState(false);
  const [flattenReason, setFlattenReason] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["risk-console-live"],
    queryFn: getRiskConsole,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const flatMut = useMutation({
    mutationFn: (r: string) => flattenAll(r),
    onSuccess: (res) => {
      toast.success(`Closed ${res.closed}/${res.attempted} positions`);
      setShowFlattenModal(false);
      setFlattenReason("");
      qc.invalidateQueries({ queryKey: ["risk-console-live"] });
    },
    onError: (err: any) => {
      toast.error(`Flatten failed: ${err?.message || "unknown"}`);
    },
  });

  if (isLoading) {
    return (
      <div className="p-6 space-y-4 max-w-[1400px] mx-auto">
        <h1 className="text-2xl font-bold text-t-hi">// RISK CONSOLE</h1>
        <div className="animate-pulse h-32 rounded-xl bg-t-bg0 border border-t-dim" />
        <div className="animate-pulse h-64 rounded-xl bg-t-bg0 border border-t-dim" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-6 max-w-[1400px] mx-auto">
        <h1 className="text-2xl font-bold text-t-hi mb-3">// RISK CONSOLE</h1>
        <p className="text-t-red">Failed to load risk data.</p>
      </div>
    );
  }

  const { fund, deployment, drawdown, var: varData, correlation, net_exposure_by_symbol } = data;
  const pvUsd = fund.pv_cents / 100;
  const allTimeUsd = fund.all_time_pnl_cents / 100;

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-[1400px] mx-auto">
      <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-t-hi tracking-tight">// RISK CONSOLE</h1>
          <p className="text-xs text-t-muted mt-1 font-ui-t">
            Top-of-book portfolio risk · live data · updates every 30s · as of {new Date(data.as_of).toLocaleString()}
          </p>
        </div>
        <button
          onClick={() => setShowFlattenModal(true)}
          className="min-h-[48px] px-6 py-3 rounded-xl bg-t-red text-white text-base font-bold hover:bg-t-red/80 shadow-lg shadow-t-red/30 focus:outline-none focus:ring-2 focus:ring-t-red"
          aria-label="Flatten all positions"
        >
          ⚠️ FLATTEN ALL POSITIONS
        </button>
      </header>

      <section className="bg-t-bg0 border border-t-dim rounded-xl p-5">
        <h2 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-3">// FUND STATE</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div>
            <p className="text-3xl font-bold text-t-hi tabular-nums font-mono-t">
              ${pvUsd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
            </p>
            <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Portfolio Value</p>
          </div>
          <div>
            <p className={`text-2xl font-bold tabular-nums font-mono-t ${pctClass(allTimeUsd)}`}>
              {fmtUsdRaw(allTimeUsd)}
            </p>
            <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">All-Time P&L</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">
              ${deployment.deployed_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
            </p>
            <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">
              Deployed ({deployment.deployment_pct.toFixed(1)}%)
            </p>
          </div>
          <div>
            <p className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">
              {deployment.open_positions_count}
            </p>
            <p className="text-[10px] tracking-widest text-t-muted mt-1 uppercase">Open Positions</p>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-4">
          <h3 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-2">
            // MAX DRAWDOWN ({drawdown.days_of_data}d)
          </h3>
          <p className={`text-2xl font-bold tabular-nums font-mono-t ${drawdown.max_drawdown_pct > 0.03 ? "text-t-red" : "text-t-hi"}`}>
            {drawdown.max_drawdown_pct > 0 ? `-${(drawdown.max_drawdown_pct * 100).toFixed(2)}%` : "0.00%"}
          </p>
          <p className="text-xs text-t-muted mt-1 font-ui-t">
            {drawdown.max_drawdown_cents > 0
              ? `Peak ${drawdown.peak_date} → Trough ${drawdown.trough_date}`
              : "No drawdown history yet"}
          </p>
        </div>
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-4">
          <h3 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-2">// VaR (95%, 1-day)</h3>
          <p className="text-2xl font-bold tabular-nums font-mono-t text-t-hi">
            ${(varData.var_95_1d_cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}
          </p>
          <p className="text-xs text-t-muted mt-1 font-ui-t">
            {varData.note || `Historical VaR · ${varData.days_of_data} days`}
          </p>
        </div>
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-4">
          <h3 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-2">// TOP-5 CONCENTRATION</h3>
          <p className={`text-2xl font-bold tabular-nums font-mono-t ${deployment.top5_concentration_pct > 40 ? "text-t-red" : "text-t-hi"}`}>
            {deployment.top5_concentration_pct.toFixed(1)}%
          </p>
          <p className="text-xs text-t-muted mt-1 font-ui-t">Notional of top-5 symbols / fund PV</p>
        </div>
      </section>

      <section className="bg-t-bg0 border border-t-dim rounded-xl p-5">
        <h2 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-3">// NET EXPOSURE BY SYMBOL</h2>
        {net_exposure_by_symbol.length === 0 ? (
          <p className="text-t-muted font-ui-t text-sm">No open positions.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-mono-t">
              <thead>
                <tr className="text-t-muted text-[10px] uppercase tracking-widest border-b border-t-dim">
                  <th className="text-left py-2 pr-3">Symbol</th>
                  <th className="text-right py-2 px-3">Notional</th>
                  <th className="text-right py-2 px-3">Unrealized</th>
                  <th className="text-right py-2 px-3">Positions</th>
                  <th className="text-left py-2 pl-3">Bots</th>
                </tr>
              </thead>
              <tbody>
                {net_exposure_by_symbol.map((row) => (
                  <tr key={row.symbol} className="border-b border-t-dim/50">
                    <td className="py-2 pr-3 text-t-hi font-bold">{row.symbol}</td>
                    <td className="py-2 px-3 text-right text-t-hi tabular-nums">
                      ${row.notional_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                    </td>
                    <td className={`py-2 px-3 text-right tabular-nums ${row.unrealized_usd >= 0 ? "text-[#4ade80]" : "text-[#f87171]"}`}>
                      {fmtUsdRaw(row.unrealized_usd)}
                    </td>
                    <td className="py-2 px-3 text-right text-t-muted tabular-nums">{row.positions_count}</td>
                    <td className="py-2 pl-3 text-t-muted text-xs">{row.bots.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="bg-t-bg0 border border-t-dim rounded-xl p-5">
        <h2 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-3">
          // TOP BOT-PAIR CORRELATIONS (30-day daily returns)
        </h2>
        {correlation.top_correlated.length === 0 ? (
          <p className="text-t-muted font-ui-t text-sm">
            Insufficient data — need &ge; 5 shared days across bots. Available once daily P&L snapshots accumulate.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-mono-t">
              <thead>
                <tr className="text-t-muted text-[10px] uppercase tracking-widest border-b border-t-dim">
                  <th className="text-left py-2 pr-3">Bot A</th>
                  <th className="text-left py-2 px-3">Bot B</th>
                  <th className="text-right py-2 px-3">Correlation</th>
                  <th className="text-right py-2 pl-3">Days</th>
                </tr>
              </thead>
              <tbody>
                {correlation.top_correlated.map((c) => (
                  <tr key={`${c.bot_a}-${c.bot_b}`} className="border-b border-t-dim/50">
                    <td className="py-2 pr-3 text-t-hi text-xs">{c.bot_a}</td>
                    <td className="py-2 px-3 text-t-hi text-xs">{c.bot_b}</td>
                    <td className={`py-2 px-3 text-right tabular-nums font-bold ${corrClass(c.corr)}`}>
                      {c.corr > 0 ? "+" : ""}
                      {c.corr.toFixed(3)}
                    </td>
                    <td className="py-2 pl-3 text-right text-t-muted">{c.n_days}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-t-muted mt-3">
              🟥 |ρ| &ge; 0.7 = correlated bets · 🟨 0.4 &le; |ρ| &lt; 0.7 · gray &lt; 0.4
            </p>
          </div>
        )}
      </section>

      <section className="bg-t-bg0 border border-t-dim rounded-xl p-5">
        <h2 className="text-xs font-mono-t text-t-muted uppercase tracking-widest mb-3">// SLEEVE NOTIONAL</h2>
        {Object.keys(deployment.sleeve_notional_usd).length === 0 ? (
          <p className="text-t-muted font-ui-t text-sm">No open positions.</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {Object.entries(deployment.sleeve_notional_usd).map(([sleeve, usd]) => (
              <div key={sleeve} className="border border-t-dim rounded-lg p-3">
                <p className="text-[10px] tracking-widest text-t-muted uppercase">{sleeve}</p>
                <p className="text-lg font-bold text-t-hi tabular-nums font-mono-t mt-1">
                  ${(usd as number).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {showFlattenModal && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="bg-t-bg0 border-2 border-t-red rounded-2xl p-6 max-w-md w-full space-y-4">
            <h2 className="text-2xl font-bold text-t-red">⚠️ FLATTEN ALL POSITIONS</h2>
            <p className="text-sm text-t-hi font-ui-t">
              This will close <b>every open position</b> across all {deployment.open_positions_count} bots
              (${deployment.deployed_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })} at risk).
            </p>
            <p className="text-xs text-t-muted font-ui-t">
              Paper trading. But still a real database mutation. Positions can't be un-closed.
            </p>
            <input
              type="text"
              placeholder="Reason (optional) — e.g. news event, drawdown breach"
              value={flattenReason}
              onChange={(e) => setFlattenReason(e.target.value)}
              className="w-full min-h-[48px] px-4 py-3 bg-t-bg1 border border-t-dim rounded-lg text-t-hi text-sm font-ui-t focus:outline-none focus:ring-2 focus:ring-t-red"
            />
            <div className="flex gap-3">
              <button
                onClick={() => setShowFlattenModal(false)}
                disabled={flatMut.isPending}
                className="flex-1 min-h-[48px] px-4 rounded-lg bg-t-bg1 text-t-hi text-sm font-bold hover:bg-t-bg2 border border-t-dim"
              >
                Cancel
              </button>
              <button
                onClick={() => flatMut.mutate(flattenReason)}
                disabled={flatMut.isPending}
                className="flex-1 min-h-[48px] px-4 rounded-lg bg-t-red text-white text-sm font-bold hover:bg-t-red/80 shadow-lg shadow-t-red/30 disabled:opacity-50"
              >
                {flatMut.isPending ? "Closing…" : "CONFIRM FLATTEN"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
