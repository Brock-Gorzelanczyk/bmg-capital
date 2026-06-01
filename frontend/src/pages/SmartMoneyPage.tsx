import { useState } from "react";
import { Bot, Eye, TrendingUp, TrendingDown, Search } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";

// ── Data ───────────────────────────────────────────────────────────────────────

const CONGRESS_TRADES = [
  { member: "Nancy Pelosi",    party: "D", state: "CA", ticker: "NVDA", type: "Purchase", amount: "$1M–$5M", date: "Jan 12, 2025", sector: "Technology" },
  { member: "Dan Crenshaw",    party: "R", state: "TX", ticker: "XOM",  type: "Purchase", amount: "$50K–$100K", date: "Jan 15, 2025", sector: "Energy" },
  { member: "Josh Gottheimer", party: "D", state: "NJ", ticker: "MSFT", type: "Purchase", amount: "$500K–$1M",  date: "Jan 18, 2025", sector: "Technology" },
  { member: "Marjorie Greene",  party: "R", state: "GA", ticker: "TSLA", type: "Purchase", amount: "$15K–$50K",  date: "Jan 22, 2025", sector: "Consumer Disc" },
  { member: "Ro Khanna",       party: "D", state: "CA", ticker: "GOOGL",type: "Sale",     amount: "$100K–$250K",date: "Jan 24, 2025", sector: "Communication" },
  { member: "Tommy Tuberville", party: "R", state: "AL", ticker: "SPY",  type: "Purchase", amount: "$50K–$100K", date: "Jan 28, 2025", sector: "ETF" },
  { member: "Shelley Capito",   party: "R", state: "WV", ticker: "CVX",  type: "Purchase", amount: "$15K–$50K",  date: "Feb 3, 2025",  sector: "Energy" },
  { member: "Mark Warner",     party: "D", state: "VA", ticker: "AMZN", type: "Sale",     amount: "$250K–$500K",date: "Feb 5, 2025",  sector: "Consumer Disc" },
  { member: "Pete Sessions",   party: "R", state: "TX", ticker: "JPM",  type: "Purchase", amount: "$15K–$50K",  date: "Feb 10, 2025", sector: "Financials" },
  { member: "David Rouzer",    party: "R", state: "NC", ticker: "AAPL", type: "Sale",     amount: "$50K–$100K", date: "Feb 14, 2025", sector: "Technology" },
  { member: "Marie Gluesenkamp", party:"D", state: "WA", ticker: "META", type: "Purchase", amount: "$100K–$250K",date: "Feb 18, 2025", sector: "Communication" },
  { member: "Suzan DelBene",   party: "D", state: "WA", ticker: "AMD",  type: "Purchase", amount: "$1M–$5M",    date: "Feb 21, 2025", sector: "Technology" },
];

const INSIDER_TRADES = [
  { name: "Jensen Huang",    title: "CEO",     company: "NVIDIA",    ticker: "NVDA", shares: 280000, value: "$40.3M", type: "Sale",     date: "Jan 8" },
  { name: "Tim Cook",        title: "CEO",     company: "Apple",     ticker: "AAPL", shares: 150000, value: "$30.1M", type: "Sale",     date: "Jan 12" },
  { name: "Elon Musk",       title: "CEO",     company: "Tesla",     ticker: "TSLA", shares: 500000, value: "$135M",  type: "Sale",     date: "Jan 15" },
  { name: "Mark Zuckerberg", title: "CEO",     company: "Meta",      ticker: "META", shares: 220000, value: "$127M",  type: "Sale",     date: "Jan 19" },
  { name: "Andy Jassy",      title: "CEO",     company: "Amazon",    ticker: "AMZN", shares: 80000,  value: "$17.6M", type: "Sale",     date: "Jan 22" },
  { name: "Satya Nadella",   title: "CEO",     company: "Microsoft", ticker: "MSFT", shares: 42000,  value: "$18.4M", type: "Sale",     date: "Jan 25" },
  { name: "Lisa Su",         title: "CEO",     company: "AMD",       ticker: "AMD",  shares: 120000, value: "$20.9M", type: "Sale",     date: "Feb 2" },
  { name: "Brian Moynihan",  title: "CEO",     company: "B of A",    ticker: "BAC",  shares: 180000, value: "$7.8M",  type: "Purchase", date: "Feb 8" },
  { name: "Jamie Dimon",     title: "CEO",     company: "JPMorgan",  ticker: "JPM",  shares: 95000,  value: "$21.4M", type: "Purchase", date: "Feb 12" },
  { name: "Pat Gelsinger",   title: "CEO",     company: "Intel",     ticker: "INTC", shares: 250000, value: "$5.1M",  type: "Purchase", date: "Feb 18" },
];

const HEDGE_FUNDS = [
  { fund: "Bridgewater",      ticker: "SPY",   action: "Added",   chg: "+2.4M", pct: "8.2%",   est: "$1.38B" },
  { fund: "Renaissance Tech", ticker: "NVDA",  action: "New",     chg: "+840K",  pct: "2.1%",   est: "$121M"  },
  { fund: "Pershing Square",  ticker: "GOOGL", action: "Added",   chg: "+1.2M", pct: "11.4%",  est: "$220M"  },
  { fund: "Ackman/PSQ",       ticker: "UNH",   action: "Reduced", chg: "-500K",  pct: "6.8%",   est: "$184M"  },
  { fund: "Tiger Global",     ticker: "META",  action: "Added",   chg: "+620K",  pct: "4.3%",   est: "$358M"  },
  { fund: "Druckenmiller",    ticker: "MSFT",  action: "New",     chg: "+380K",  pct: "3.9%",   est: "$166M"  },
  { fund: "Baupost Group",    ticker: "AMZN",  action: "Reduced", chg: "-1.4M", pct: "5.1%",   est: "$307M"  },
  { fund: "Appaloosa",        ticker: "TSLA",  action: "Sold",    chg: "-2.8M", pct: "0%",     est: "$0"     },
  { fund: "Viking Global",    ticker: "AMD",   action: "Added",   chg: "+940K",  pct: "3.2%",   est: "$164M"  },
  { fund: "Soros Fund",       ticker: "COIN",  action: "New",     chg: "+280K",  pct: "1.8%",   est: "$67M"   },
];

type Tab = "congress" | "insider" | "hedge";

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SmartMoneyPage() {
  const [tab, setTab] = useState<Tab>("congress");
  const [search, setSearch] = useState("");
  const [aiOpen, setAiOpen] = useState(false);

  const TABS: { id: Tab; label: string }[] = [
    { id: "congress", label: "Congressional Trades" },
    { id: "insider",  label: "Insider Transactions" },
    { id: "hedge",    label: "13F Hedge Funds" },
  ];

  const filteredCongress = CONGRESS_TRADES.filter((t) =>
    !search || t.ticker.includes(search.toUpperCase()) || t.member.toLowerCase().includes(search.toLowerCase())
  );
  const filteredInsider = INSIDER_TRADES.filter((t) =>
    !search || t.ticker.includes(search.toUpperCase()) || t.name.toLowerCase().includes(search.toLowerCase())
  );
  const filteredHedge = HEDGE_FUNDS.filter((t) =>
    !search || t.ticker.includes(search.toUpperCase()) || t.fund.toLowerCase().includes(search.toLowerCase())
  );

  const buyCount   = CONGRESS_TRADES.filter((t) => t.type === "Purchase").length;
  const sellCount  = CONGRESS_TRADES.filter((t) => t.type === "Sale").length;
  const insiderBuy = INSIDER_TRADES.filter((t) => t.type === "Purchase").length;
  const topTicker  = "NVDA";

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
          <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Senate & House Disclosures</div>
            <span className="text-[10px] text-[var(--text-tertiary)]">STOCK Act filings · Last 60 days</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                  {["Member", "Party", "Ticker", "Transaction", "Amount", "Date", "Sector"].map((h) => (
                    <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", h==="Member"?"text-left":"text-right", h==="Party"||h==="Sector"?"text-left":"")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredCongress.map((t, i) => (
                  <tr key={i} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                    <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">{t.member}</td>
                    <td className="px-4 py-2.5">
                      <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded border", t.party==="D"?"text-blue-400 bg-blue-900/30 border-blue-800/40":"text-red-400 bg-red-900/30 border-red-800/40")}>{t.party}</span>
                      <span className="text-[var(--text-tertiary)] ml-1.5">{t.state}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-bold font-mono text-[var(--text-primary)]">{t.ticker}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded", t.type==="Purchase"?"text-[var(--accent-positive)] bg-[var(--accent-positive)]/10":"text-[var(--accent-negative)] bg-[var(--accent-negative)]/10")}>
                        {t.type === "Purchase" ? <TrendingUp className="inline w-3 h-3 mr-0.5" /> : <TrendingDown className="inline w-3 h-3 mr-0.5" />}{t.type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">{t.amount}</td>
                    <td className="px-4 py-2.5 text-right text-[var(--text-tertiary)]">{t.date}</td>
                    <td className="px-4 py-2.5 text-[var(--text-tertiary)]">{t.sector}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-2.5 border-t border-[var(--border-subtle)] text-[10px] text-[var(--text-tertiary)]">
            Data sourced from STOCK Act disclosures filed with the Clerk of the House and Secretary of the Senate.
          </div>
        </div>
      )}

      {/* Insider transactions */}
      {tab === "insider" && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">SEC Form 4 Filings</div>
            <span className="text-[10px] text-[var(--text-tertiary)]">Officer & director transactions · Last 60 days</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                  {["Insider", "Title", "Company", "Ticker", "Shares", "Value", "Type", "Date"].map((h) => (
                    <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", ["Insider","Title","Company"].includes(h)?"text-left":"text-right")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredInsider.map((t, i) => (
                  <tr key={i} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                    <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">{t.name}</td>
                    <td className="px-4 py-2.5 text-[var(--text-tertiary)]">{t.title}</td>
                    <td className="px-4 py-2.5 text-[var(--text-secondary)]">{t.company}</td>
                    <td className="px-4 py-2.5 text-right font-bold font-mono text-[var(--text-primary)]">{t.ticker}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">{t.shares.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right font-mono font-bold text-[var(--text-primary)]">{t.value}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded", t.type==="Purchase"?"text-[var(--accent-positive)] bg-[var(--accent-positive)]/10":"text-[var(--accent-negative)] bg-[var(--accent-negative)]/10")}>{t.type}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right text-[var(--text-tertiary)]">{t.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 13F Hedge funds */}
      {tab === "hedge" && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">13F Institutional Holdings — Q4 2024</div>
            <span className="text-[10px] text-[var(--text-tertiary)]">Quarterly SEC filings · Notable position changes</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                  {["Fund", "Ticker", "Action", "Share Change", "% Portfolio", "Est. Value"].map((h) => (
                    <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", ["Fund","Ticker"].includes(h)?"text-left":"text-right")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredHedge.map((t, i) => {
                  const actionColor = t.action==="New"?"text-violet-400 bg-violet-900/30 border-violet-800/40":t.action==="Added"?"text-[var(--accent-positive)] bg-[var(--accent-positive)]/10 border-[var(--accent-positive)]/20":t.action==="Reduced"?"text-amber-400 bg-amber-900/30 border-amber-800/40":"text-[var(--accent-negative)] bg-[var(--accent-negative)]/10 border-[var(--accent-negative)]/20";
                  return (
                    <tr key={i} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                      <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">{t.fund}</td>
                      <td className="px-4 py-2.5 font-bold font-mono text-[var(--text-primary)]">{t.ticker}</td>
                      <td className="px-4 py-2.5 text-right">
                        <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded border", actionColor)}>{t.action}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">{t.chg}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">{t.pct}</td>
                      <td className="px-4 py-2.5 text-right font-mono font-bold text-[var(--text-primary)]">{t.est}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-2.5 border-t border-[var(--border-subtle)] text-[10px] text-[var(--text-tertiary)]">
            13F filings are submitted 45 days after each quarter end. Holdings represent positions as of the filing date.
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
