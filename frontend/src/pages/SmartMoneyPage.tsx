import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, TrendingUp, TrendingDown, Search, RefreshCw, ExternalLink, Loader2 } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";
import { getCongressTrades, getSmartMoneySummary, triggerCongressRefresh } from "@/api/smartMoney";
import client from "@/api/client";

type SmartTab = "stocks" | "crypto";
type PartyFilter = "all" | "D" | "R" | "I";
type ChamberFilter = "all" | "S" | "H";

function timeAgo(isoStr: string | null | undefined): string {
  if (!isoStr) return "never";
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 2) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  return `${Math.floor(diffHrs / 24)}d ago`;
}

// ── Crypto types ──────────────────────────────────────────────────────────────

interface CryptoAsset {
  symbol: string;
  ticker: string;
  signal: "accumulating" | "distributing" | "neutral";
  large_holder_count: number;
  change_pct: number;
  funding_rate: number | null;
}

interface CryptoSmartMoneyData {
  assets: CryptoAsset[];
  source: string;
  note: string;
}

// ── Crypto tab component ──────────────────────────────────────────────────────

function CryptoSmartMoneyTab({ data, isLoading }: { data: CryptoSmartMoneyData | undefined; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-t-muted text-sm gap-2">
        <RefreshCw size={14} className="animate-spin" /> Loading whale signals…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="py-12 text-center text-t-muted text-sm">
        Failed to load crypto smart money data.
      </div>
    );
  }

  const signalBadge = (signal: CryptoAsset["signal"]) => {
    if (signal === "accumulating") {
      return (
        <span className="text-[10px] font-bold px-2 py-0.5 rounded border border-t-green/30 bg-t-green/10 text-t-green uppercase tracking-wider">
          Accumulating
        </span>
      );
    }
    if (signal === "distributing") {
      return (
        <span className="text-[10px] font-bold px-2 py-0.5 rounded border border-t-red/30 bg-t-red/10 text-t-red uppercase tracking-wider">
          Distributing
        </span>
      );
    }
    return (
      <span className="text-[10px] font-bold px-2 py-0.5 rounded border border-t-dim bg-t-bg2 text-t-muted uppercase tracking-wider">
        Neutral
      </span>
    );
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {data.assets.map((asset) => (
          <div key={asset.ticker} className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-4">
            {/* Asset header */}
            <div className="flex items-start justify-between">
              <div>
                <div className="text-base font-bold text-t-hi">{asset.symbol}</div>
                <div className="text-xs font-mono text-t-muted mt-0.5">{asset.ticker}</div>
              </div>
              {signalBadge(asset.signal)}
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-3 gap-3">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-widest text-t-muted mb-1">
                  Whale Wallets
                </div>
                <div className="text-lg font-bold font-mono-t text-t-hi">
                  {asset.large_holder_count.toLocaleString()}
                </div>
                <div className="text-[10px] text-t-muted">≥$1M balance</div>
              </div>

              <div>
                <div className="text-[10px] font-semibold uppercase tracking-widest text-t-muted mb-1">
                  7D Change
                </div>
                <div className={cn(
                  "text-lg font-bold font-mono-t",
                  asset.change_pct > 0 ? "text-t-green" : asset.change_pct < 0 ? "text-t-red" : "text-t-muted"
                )}>
                  {asset.change_pct > 0 ? "+" : ""}{asset.change_pct.toFixed(2)}%
                </div>
                <div className="text-[10px] text-t-muted">holder count</div>
              </div>

              <div>
                <div
                  className="text-[10px] font-semibold uppercase tracking-widest text-t-muted mb-1 cursor-help underline decoration-dotted"
                  title="Funding rate is a periodic payment between long and short traders in perpetual futures. Positive = longs pay shorts (market is bullish/overleveraged). Negative = shorts pay longs (market is bearish/overleveraged)."
                >
                  Funding Rate
                </div>
                {asset.funding_rate != null ? (
                  <>
                    <div className={cn(
                      "text-lg font-bold font-mono-t",
                      asset.funding_rate > 0.05 ? "text-t-green" : asset.funding_rate < -0.01 ? "text-t-red" : "text-t-muted"
                    )}>
                      {asset.funding_rate > 0 ? "+" : ""}{asset.funding_rate.toFixed(4)}%
                    </div>
                    <div className="text-[10px] text-t-muted">8h perp rate</div>
                  </>
                ) : (
                  <div className="text-lg font-bold text-t-muted">—</div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Source note */}
      <div className="text-[10px] text-t-muted px-1">
        Source: CoinMetrics Community API (AdrBal1in1MCnt) · Binance perp funding
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SmartMoneyPage() {
  const [tab, setTab] = useState<SmartTab>("stocks");
  const [search, setSearch] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [partyFilter, setPartyFilter] = useState<PartyFilter>("all");
  const [chamberFilter, setChamberFilter] = useState<ChamberFilter>("all");
  const qc = useQueryClient();

  // ── API queries ──────────────────────────────────────────────────────────────
  const { data: summary } = useQuery({
    queryKey: ["smart-money-summary"],
    queryFn: getSmartMoneySummary,
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const congressParams = {
    limit: 100,
    days: 90,
    ...(partyFilter !== "all" && { party: partyFilter }),
    ...(chamberFilter !== "all" && { chamber: chamberFilter }),
    ...(search && search.length <= 6 && /^[A-Z]+$/i.test(search) ? { ticker: search } : {}),
  };

  const { data: congressData, isLoading: congressLoading } = useQuery({
    queryKey: ["smart-money-congress", congressParams],
    queryFn: () => getCongressTrades(congressParams),
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const { data: cryptoData, isLoading: cryptoLoading } = useQuery({
    queryKey: ["smart-money-crypto"],
    queryFn: () => client.get("/smart-money/crypto").then(r => r.data),
    staleTime: 10 * 60_000,
    retry: 1,
    enabled: tab === "crypto",
  });

  // Client-side text filter (member name / ticker)
  const filteredCongress = (congressData?.trades ?? []).filter((t) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      (t.ticker ?? "").toLowerCase().includes(s) ||
      t.member_name.toLowerCase().includes(s)
    );
  });

  const refreshMut = useMutation({
    mutationFn: () => triggerCongressRefresh(365),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["smart-money-congress"] });
      qc.invalidateQueries({ queryKey: ["smart-money-summary"] });
      if (data.status === "error") {
        toast.error(`Congress refresh failed: ${data.error ?? "unknown error"}`);
      } else if (data.errors && data.errors.length > 0) {
        toast.warning(`Partial refresh: ${data.new ?? 0} new rows. Errors: ${data.errors.join("; ")}`);
      } else {
        toast.success(`Congress data refreshed — ${data.new ?? 0} new rows, ${data.skipped ?? 0} already saved`);
      }
    },
    onError: (err: any) => {
      toast.error(`Refresh failed: ${err?.response?.data?.detail ?? err?.message ?? "network error"}`);
    },
  });

  // ── Stats ─────────────────────────────────────────────────────────────────────
  const buyCount   = summary?.congress_buys_30d ?? 0;
  const sellCount  = summary?.congress_sells_30d ?? 0;
  const topTicker  = summary?.most_traded_ticker_30d ?? "—";
  const lastUpdatedCongress = summary?.last_updated?.congress;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5 animate-page-in">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5">
            // MARKETS
          </p>
          <h1 className="text-2xl font-bold text-t-hi">Smart Money</h1>
          <p className="text-t-muted text-sm mt-1">
            Congressional trades · Crypto whale signals · Institutional flows
          </p>
        </div>
        <div className="flex items-center gap-2">
          {tab === "stocks" && (
            <>
              <div className="relative">
                <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-t-muted" />
                <input value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder="Filter by ticker or name…"
                  className="bg-t-bg2 border border-t-dim text-t-hi text-xs rounded-lg pl-8 pr-3 py-2 w-52 outline-none focus:border-t-mid" />
              </div>
              <button
                onClick={() => refreshMut.mutate()}
                disabled={refreshMut.isPending}
                title="Refresh congressional trade data"
                className="flex items-center gap-1.5 bg-t-bg1 border border-t-dim hover:border-t-mid text-t-mid2 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
              >
                {refreshMut.isPending
                  ? <Loader2 size={12} className="animate-spin" />
                  : <RefreshCw size={12} />}
                {refreshMut.isPending ? "Refreshing…" : "Refresh"}
              </button>
            </>
          )}
          <button onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
            <Bot size={12} /> Ask AI
          </button>
        </div>
      </div>

      {/* Tab selector */}
      <div className="flex gap-1 bg-t-bg1 border border-t-dim rounded-xl p-1 w-fit">
        {([
          { key: "stocks", label: "// STOCKS" },
          { key: "crypto", label: "// CRYPTO" },
        ] as { key: SmartTab; label: string }[]).map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={cn("px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors",
              tab === t.key ? "bg-t-bg2 text-t-hi" : "text-t-muted hover:text-t-mid2")}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Stocks tab */}
      {tab === "stocks" && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: "Congress Buys (30d)", value: buyCount, color: "text-t-green" },
              { label: "Congress Sells (30d)", value: sellCount, color: "text-t-red" },
              { label: "Most Traded Ticker",  value: topTicker,  color: "text-t-hi" },
            ].map((s) => (
              <div key={s.label} className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3">
                <div className="text-[10px] font-bold uppercase tracking-widest text-t-muted mb-1">{s.label}</div>
                <div className={cn("text-2xl font-bold font-mono", s.color)}>{s.value}</div>
              </div>
            ))}
          </div>

          {/* Congressional trades table */}
          <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
            <div className="px-5 py-3 border-b border-t-dim flex items-center justify-between flex-wrap gap-2">
              <div className="text-xs font-bold uppercase tracking-widest text-t-muted">Senate & House Disclosures</div>
              <div className="flex items-center gap-3 flex-wrap">
                {/* Party filter */}
                <div className="flex gap-1">
                  {(["all", "D", "R", "I"] as PartyFilter[]).map((p) => (
                    <button key={p} onClick={() => setPartyFilter(p)}
                      className={cn("text-[10px] font-bold px-2 py-1 rounded border transition-colors",
                        partyFilter === p
                          ? "bg-t-bg2 border-t-mid text-t-hi"
                          : "border-t-dim text-t-muted hover:text-t-hi"
                      )}>{p === "all" ? "All" : p}</button>
                  ))}
                </div>
                {/* Chamber filter */}
                <div className="flex gap-1">
                  {([["all", "Both"], ["S", "Senate"], ["H", "House"]] as [ChamberFilter, string][]).map(([val, label]) => (
                    <button key={val} onClick={() => setChamberFilter(val)}
                      className={cn("text-[10px] font-bold px-2 py-1 rounded border transition-colors",
                        chamberFilter === val
                          ? "bg-t-bg2 border-t-mid text-t-hi"
                          : "border-t-dim text-t-muted hover:text-t-hi"
                      )}>{label}</button>
                  ))}
                </div>
                {lastUpdatedCongress && (
                  <span className="text-[10px] text-t-muted flex items-center gap-1">
                    <RefreshCw size={9} /> Updated {timeAgo(lastUpdatedCongress)}
                  </span>
                )}
              </div>
            </div>

            {congressLoading ? (
              <div className="flex items-center justify-center py-16 text-t-muted text-sm gap-2">
                <RefreshCw size={14} className="animate-spin" /> Loading disclosures…
              </div>
            ) : filteredCongress.length === 0 ? (
              <div className="py-12 text-center space-y-2">
                {congressData && congressData.last_updated_at === null ? (
                  <>
                    <div className="text-t-mid2 text-sm font-medium">Initial backfill in progress</div>
                    <div className="text-t-muted text-xs max-w-sm mx-auto">
                      Congressional trade data is being fetched for the first time. Refresh in a few minutes — or click Refresh to trigger it now.
                    </div>
                    <button
                      onClick={() => refreshMut.mutate()}
                      disabled={refreshMut.isPending}
                      className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-violet-600/20 border border-violet-600/30 text-violet-400 hover:bg-violet-600/30 transition-colors disabled:opacity-50"
                    >
                      {refreshMut.isPending ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                      {refreshMut.isPending ? "Refreshing…" : "Fetch Now"}
                    </button>
                  </>
                ) : (
                  <div className="text-t-muted text-sm">No trades found for the selected filters.</div>
                )}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-t-dim bg-t-bg2/40">
                      {["Member", "Party", "Ticker", "Transaction", "Amount", "Date", "Delay"].map((h) => (
                        <th key={h} className={cn("px-4 py-2.5 font-semibold text-t-muted tracking-wider",
                          ["Member", "Party"].includes(h) ? "text-left" : "text-right"
                        )}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCongress.map((t, i) => (
                      <tr key={t.id} className={i % 2 === 0 ? "" : "bg-t-bg2/30"}>
                        <td className="px-4 py-2.5 font-semibold text-t-hi">
                          <a href={t.source_url} target="_blank" rel="noopener noreferrer"
                            className="hover:text-violet-400 inline-flex items-center gap-1 transition-colors">
                            {t.member_name}
                            <ExternalLink size={9} className="opacity-50" />
                          </a>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded border",
                            t.party === "D" ? "text-blue-400 bg-blue-900/30 border-blue-800/40"
                            : t.party === "R" ? "text-red-400 bg-red-900/30 border-red-800/40"
                            : "text-gray-400 bg-gray-900/30 border-gray-800/40"
                          )}>{t.party ?? "?"}</span>
                          <span className="text-t-muted ml-1.5">{t.state}</span>
                          <span className="text-t-muted ml-1 opacity-60">{t.chamber === "S" ? "· Sen" : t.chamber === "H" ? "· Rep" : ""}</span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-bold font-mono text-t-hi">
                          {t.ticker ?? <span className="text-t-muted font-normal italic">N/A</span>}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded",
                            t.transaction_type === "purchase"
                              ? "text-t-green bg-t-green/10"
                              : "text-t-red bg-t-red/10"
                          )}>
                            {t.transaction_type === "purchase"
                              ? <TrendingUp className="inline w-3 h-3 mr-0.5" />
                              : <TrendingDown className="inline w-3 h-3 mr-0.5" />}
                            {t.transaction_type.charAt(0).toUpperCase() + t.transaction_type.slice(1)}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-t-mid2">
                          {t.amount_range ?? "—"}
                        </td>
                        <td className="px-4 py-2.5 text-right text-t-muted">
                          {t.transaction_date}
                        </td>
                        <td className="px-4 py-2.5 text-right text-t-muted">
                          {t.disclosure_delay_days != null
                            ? <span title={`Disclosed ${t.disclosure_delay_days} days after transaction`}>{t.disclosure_delay_days}d</span>
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="px-5 py-2.5 border-t border-t-dim text-[10px] text-t-muted flex items-center justify-between flex-wrap gap-1">
              <span>Data from Senate Stock Watcher + House Stock Watcher · SEC EDGAR STOCK Act disclosures</span>
              {congressData && (
                <span className="opacity-70">{congressData.total.toLocaleString()} total trades · showing {filteredCongress.length}</span>
              )}
            </div>
          </div>
        </>
      )}

      {/* Crypto tab */}
      {tab === "crypto" && (
        <CryptoSmartMoneyTab data={cryptoData} isLoading={cryptoLoading} />
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Smart Money"
        context="Smart Money page — congressional trades, insider transactions, 13F hedge fund filings"
        suggestedQuestions={[
          "What do congressional stock purchases signal about market direction?",
          "How reliable is insider buying as a bullish signal?",
          "How do I interpret 13F hedge fund position changes?",
          "Which sectors are getting the most institutional buying?",
          "What's the STOCK Act and why do congressional trades matter?",
        ]}
      />
    </div>
  );
}
