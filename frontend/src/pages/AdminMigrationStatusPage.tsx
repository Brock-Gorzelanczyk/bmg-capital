import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

// ─── Types ─────────────────────────────────────────────────────────────────

interface MigrationRow {
  name: string;
  applied_at: string;
}

interface OpenPositionRow {
  bot_id: string;
  symbol: string;
  open_count: number;
  notional_cents: number;
}

interface MigrationStatusResponse {
  as_of: string;
  migrations?: MigrationRow[];
  open_positions_by_bot_symbol?: OpenPositionRow[];
  migrations_error?: string;
  positions_error?: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const fmtCents = (c: number): string =>
  `$${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
};

// ─── Page ───────────────────────────────────────────────────────────────────

export default function AdminMigrationStatusPage() {
  const q = useQuery<MigrationStatusResponse>({
    queryKey: ["admin", "migration-status"],
    queryFn: async () => {
      const { data } = await client.get<MigrationStatusResponse>("/api/admin/migration-status");
      return data;
    },
    refetchInterval: 30_000,
  });

  const migrations = q.data?.migrations ?? [];
  const positions = q.data?.open_positions_by_bot_symbol ?? [];

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold mb-1">Admin · Migration Status</h1>
          <p className="text-zinc-500 text-sm">
            schema_migrations + open positions per (bot, symbol). Diagnostic only.
          </p>
        </div>
        <button
          onClick={() => q.refetch()}
          disabled={q.isFetching}
          className="px-3 py-1.5 border border-zinc-700 rounded-lg text-sm hover:bg-zinc-900 disabled:opacity-50"
        >
          {q.isFetching ? "Loading…" : "Refresh"}
        </button>
      </div>

      {q.isLoading && (
        <div className="text-zinc-500 text-sm">loading…</div>
      )}

      {q.error && (
        <div className="border border-red-800 bg-red-950/40 rounded-lg p-4 mb-6">
          <div className="text-red-300 font-semibold mb-1">Request failed</div>
          <div className="text-red-400 text-sm font-mono">
            {(q.error as Error).message}
          </div>
        </div>
      )}

      {q.data && (
        <>
          {/* Migrations table */}
          <div className="mb-8">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold">
                Migrations ({migrations.length})
              </h2>
              <span className="text-zinc-500 text-xs">as_of {fmtTime(q.data.as_of)}</span>
            </div>
            {q.data.migrations_error ? (
              <div className="text-red-400 text-sm">Error: {q.data.migrations_error}</div>
            ) : (
              <div className="border border-zinc-800 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-900 text-zinc-400 text-xs uppercase tracking-wider">
                    <tr>
                      <th className="text-left py-2 px-3">name</th>
                      <th className="text-left py-2 px-3">applied_at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {migrations.map((m) => (
                      <tr
                        key={m.name}
                        className="border-b border-zinc-900 hover:bg-zinc-900/50 font-mono"
                      >
                        <td className="py-1.5 px-3 text-zinc-200">{m.name}</td>
                        <td className="py-1.5 px-3 text-zinc-500">{fmtTime(m.applied_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Open positions table */}
          <div>
            <h2 className="text-lg font-semibold mb-2">
              Open Positions by Bot × Symbol ({positions.length})
            </h2>
            {q.data.positions_error ? (
              <div className="text-red-400 text-sm">Error: {q.data.positions_error}</div>
            ) : (
              <div className="border border-zinc-800 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-900 text-zinc-400 text-xs uppercase tracking-wider">
                    <tr>
                      <th className="text-left py-2 px-3">bot_id</th>
                      <th className="text-left py-2 px-3">symbol</th>
                      <th className="text-right py-2 px-3">open</th>
                      <th className="text-right py-2 px-3">notional</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => {
                      const isOptionsBot = p.bot_id.startsWith("options_");
                      const isEquitySymbol = /^[A-Z]{1,5}$/.test(p.symbol);
                      const violation = isOptionsBot && isEquitySymbol;
                      return (
                        <tr
                          key={`${p.bot_id}-${p.symbol}`}
                          className={
                            "border-b border-zinc-900 font-mono " +
                            (violation ? "bg-red-950/30" : "hover:bg-zinc-900/50")
                          }
                        >
                          <td className="py-1.5 px-3 text-zinc-200">
                            {p.bot_id}
                            {violation && (
                              <span className="ml-2 text-[10px] uppercase text-red-400 font-bold">
                                cross-sleeve
                              </span>
                            )}
                          </td>
                          <td className="py-1.5 px-3 text-zinc-300">{p.symbol}</td>
                          <td className="py-1.5 px-3 text-right text-zinc-400">{p.open_count}</td>
                          <td className="py-1.5 px-3 text-right text-zinc-300">
                            {fmtCents(p.notional_cents)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
