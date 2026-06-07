import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, Eye, TrendingUp, TrendingDown, Search, RefreshCw, ExternalLink } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";
import { getCongressTrades, getSmartMoneySummary } from "@/api/smartMoney";

type Tab = "congress" | "insider" | "hedge";
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SmartMoneyPage() {
  const [tab, setTab] = useState<Tab>("congress");
  const [search, setSearch] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [partyFilter, setPartyFilter] = useState<PartyFilter>("all");
  const [chamberFilter, setChamberFilter] = useState<ChamberFilter>("all");

  const TABS: { id: Tab; label: string }[] = [
    { id: "congress", label: "Congressional Trades" },
    { id: "insider",  label: "Insider Transactions" },
    { id: "hedge",    label: "13F Hedge Funds" },
  ];

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

  // Client-side text filter (member name / ticker)
  const filteredCongress = (congressData?.trades ?? []).filter((t) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      (t.ticker ?? "").toLowerCase().includes(s) ||
      t.member_name.toLowerCase().includes(s)
    );
  });

  // ── Stats ─────────────────────────────────────────────────────────────────────
  const buyCount   = summary?.congress_buys_30d ?? 0;
  const sellCount  = summary?.congress_sells_30d ?? 0;
  const insiderBuy = summary?.insider_buys_30d ?? 0;
  const topTicker  = summary?.most_traded_ticker_30d ?? "—";
  const lastUpdatedCongress = summary?.last_updated?.congress;

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6 space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <Eye size={20} className="text-violet-400" /> Smart Money
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Congressional trades · Insider transactions · Hedge fund 13F filings</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by ticker or name…"
              className="bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg pl-8 pr-3 py-2 w-52 outline-none focus:border-[var(--border-emphasis)]" />
          </div>
          <button onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
            <Bot size={12} /> Ask AI
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Congress Buys (30d)", value: buyCount, color: "text-[var(--accent-positive)]" },
          { label: "Congress Sells (30d)", value: sellCount, color: "text-[var(--accent-negative)]" },
          { label: "Insider Buys (30d)", value: insiderBuy, color: "text-[var(--accent-positive)]" },
          { label: "Most Traded Ticker",  value: topTicker,  color: "text-[var(--text-primary)]" },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{s.label}</div>
            <div className={cn("text-2xl font-bold font-mono", s.color)}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl w-fit">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={cn("px-4 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer whitespace-nowrap",
              tab === t.id ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            )}>{t.label}</button>
        ))}
      </div>

      {/* Congressional trades */}
      {tab === "congress" && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between flex-wrap gap-2">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Senate & House Disclosures</div>
            <div className="flex items-center gap-3 flex-wrap">
              {/* Party filter */}
              <div className="flex gap-1">
                {(["all", "D", "R", "I"] as PartyFilter[]).map((p) => (
                  <button key={p} onClick={() => setPartyFilter(p)}
                    className={cn("text-[10px] font-bold px-2 py-1 rounded border transition-colors",
                      partyFilter === p
                        ? "bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)] text-[var(--text-primary)]"
                        : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                    )}>{p === "all" ? "All" : p}</button>
                ))}
              </div>
              {/* Chamber filter */}
              <div className="flex gap-1">
                {([["all", "Both"], ["S", "Senate"], ["H", "House"]] as [ChamberFilter, string][]).map(([val, label]) => (
                  <button key={val} onClick={() => setChamberFilter(val)}
                    className={cn("text-[10px] font-bold px-2 py-1 rounded border transition-colors",
                      chamberFilter === val
                        ? "bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)] text-[var(--text-primary)]"
                        : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                    )}>{label}</button>
                ))}
              </div>
              {lastUpdatedCongress && (
                <span className="text-[10px] text-[var(--text-tertiary)] flex items-center gap-1">
                  <RefreshCw size={9} /> Updated {timeAgo(lastUpdatedCongress)}
                </span>
              )}
            </div>
          </div>

          {congressLoading ? (
            <div className="flex items-center justify-center py-16 text-[var(--text-tertiary)] text-sm gap-2">
              <RefreshCw size={14} className="animate-spin" /> Loading disclosures…
            </div>
          ) : filteredCongress.length === 0 ? (
            <div className="py-12 text-center text-[var(--text-tertiary)] text-sm">
              No trades found for the selected filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                    {["Member", "Party", "Ticker", "Transaction", "Amount", "Date", "Delay"].map((h) => (
                      <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider",
                        ["Member", "Party"].includes(h) ? "text-left" : "text-right"
                      )}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredCongress.map((t, i) => (
                    <tr key={t.id} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                      <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">
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
                        <span className="text-[var(--text-tertiary)] ml-1.5">{t.state}</span>
                        <span className="text-[var(--text-tertiary)] ml-1 opacity-60">{t.chamber === "S" ? "· Sen" : t.chamber === "H" ? "· Rep" : ""}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-bold font-mono text-[var(--text-primary)]">
                        {t.ticker ?? <span className="text-[var(--text-tertiary)] font-normal italic">N/A</span>}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded",
                          t.transaction_type === "purchase"
                            ? "text-[var(--accent-positive)] bg-[var(--accent-positive)]/10"
                            : "text-[var(--accent-negative)] bg-[var(--accent-negative)]/10"
                        )}>
                          {t.transaction_type === "purchase"
                            ? <TrendingUp className="inline w-3 h-3 mr-0.5" />
                            : <TrendingDown className="inline w-3 h-3 mr-0.5" />}
                          {t.transaction_type.charAt(0).toUpperCase() + t.transaction_type.slice(1)}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">
                        {t.amount_range ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right text-[var(--text-tertiary)]">
                        {t.transaction_date}
                      </td>
                      <td className="px-4 py-2.5 text-right text-[var(--text-tertiary)]">
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

          <div className="px-5 py-2.5 border-t border-[var(--border-subtle)] text-[10px] text-[var(--text-tertiary)] flex items-center justify-between flex-wrap gap-1">
            <span>Data from Senate Stock Watcher + House Stock Watcher · SEC EDGAR STOCK Act disclosures</span>
            {congressData && (
              <span className="opacity-70">{congressData.total.toLocaleString()} total trades · showing {filteredCongress.length}</span>
            )}
          </div>
        </div>
      )}

      {/* Insider transactions — coming soon */}
      {tab === "insider" && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">SEC Form 4 Filings</div>
            <span className="text-[10px] text-[var(--text-tertiary)]">Officer & director transactions</span>
          </div>
          <div className="py-16 text-center space-y-2">
            <div className="text-2xl">🔜</div>
            <div className="text-sm font-semibold text-[var(--text-secondary)]">Coming Soon</div>
            <div className="text-xs text-[var(--text-tertiary)] max-w-sm mx-auto">
              Real SEC EDGAR Form 4 insider transaction data in the next release.
            </div>
          </div>
        </div>
      )}

      {/* 13F Hedge funds — coming soon */}
      {tab === "hedge" && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">13F Institutional Holdings</div>
            <span className="text-[10px] text-[var(--text-tertiary)]">Quarterly SEC filings · Notable position changes</span>
          </div>
          <div className="py-16 text-center space-y-2">
            <div className="text-2xl">🔜</div>
            <div className="text-sm font-semibold text-[var(--text-secondary)]">Coming Soon</div>
            <div className="text-xs text-[var(--text-tertiary)] max-w-sm mx-auto">
              Real SEC EDGAR Form 13F hedge fund filing data in the next release.
            </div>
          </div>
        </div>
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
