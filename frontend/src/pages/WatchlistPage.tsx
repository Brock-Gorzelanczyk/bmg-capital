import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getWatchlists, createWatchlist, addSymbol, removeSymbol, getSnapshot } from "@/api/watchlist";
import { useMarketStore } from "@/store";
import { useIsViewer } from "@/store/authStore";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Plus, X, TrendingUp, TrendingDown, Microscope, BookMarked, Bot } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { COMPANY_INFO } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import Sparkline from "@/components/ui/Sparkline";
import { Button } from "@/components/ui/Button";

// ── Template data ─────────────────────────────────────────────────────────────

const TEMPLATES = [
  { name: "Magnificent 7", desc: "The 7 mega-cap tech stocks driving the market", symbols: ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"] },
  { name: "AI & Semiconductors", desc: "Pure-play AI and chip companies", symbols: ["NVDA", "AMD", "AVGO", "INTC", "QCOM", "MU", "ARM", "SMCI"] },
  { name: "Dividend Aristocrats", desc: "25+ consecutive years of dividend growth", symbols: ["JNJ", "KO", "PG", "MCD", "WMT", "CL", "T", "VZ", "XOM"] },
  { name: "High-Growth Tech", desc: "Fast-growing tech with strong revenue momentum", symbols: ["SHOP", "SNOW", "DDOG", "NET", "CRWD", "ZS", "MDB", "TTD"] },
  { name: "Value Picks", desc: "Undervalued companies with strong fundamentals", symbols: ["BRK-B", "JPM", "BAC", "C", "WFC", "CVX", "XOM", "VZ"] },
  { name: "Crypto Majors", desc: "Top cryptocurrencies by market cap", symbols: ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD"] },
  { name: "DeFi & Web3", desc: "Decentralized finance and Web3 tokens", symbols: ["ETH-USD", "UNI-USD", "AAVE-USD", "MKR-USD", "CRV-USD", "LDO-USD"] },
  { name: "Earnings This Week", desc: "Companies reporting earnings this week", symbols: ["AAPL", "MSFT", "AMZN", "META", "GOOGL"] },
];

// ── TemplateGallery modal ─────────────────────────────────────────────────────

interface TemplateGalleryProps {
  onClose: () => void;
}

function TemplateGallery({ onClose }: TemplateGalleryProps) {
  const qc = useQueryClient();
  const [loadingTemplate, setLoadingTemplate] = useState<string | null>(null);
  const [successTemplate, setSuccessTemplate] = useState<string | null>(null);

  async function handleAdd(tpl: typeof TEMPLATES[number]) {
    if (loadingTemplate) return;
    setLoadingTemplate(tpl.name);
    try {
      // Create the list
      const res = await createWatchlist(tpl.name);
      const wlId = res.id;
      // Add each symbol sequentially (batched)
      for (const sym of tpl.symbols) {
        try {
          await addSymbol(wlId, sym);
        } catch {
          // ignore duplicate errors
        }
      }
      setSuccessTemplate(tpl.name);
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      setTimeout(() => {
        setSuccessTemplate(null);
        onClose();
      }, 1200);
    } catch {
      // silently fail
    } finally {
      setLoadingTemplate(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)] shrink-0">
          <div>
            <h2 className="text-[var(--text-primary)] font-semibold text-base font-display">Browse Templates</h2>
            <p className="text-[var(--text-tertiary)] text-xs mt-0.5">Pick a pre-built watchlist to add to your account</p>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors p-1 rounded-lg hover:bg-[var(--bg-elevated-2)]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Grid */}
        <div className="overflow-y-auto p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {TEMPLATES.map((tpl) => {
            const isLoading = loadingTemplate === tpl.name;
            const isSuccess = successTemplate === tpl.name;
            return (
              <div
                key={tpl.name}
                className="bg-[var(--bg-elevated-2)]/50 border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-3 hover:border-[var(--border-emphasis)] transition-colors"
              >
                <div>
                  <p className="text-[var(--text-primary)] font-semibold text-sm">{tpl.name}</p>
                  <p className="text-[var(--text-tertiary)] text-xs mt-0.5 leading-relaxed">{tpl.desc}</p>
                </div>
                {/* Symbol chips (first 5) */}
                <div className="flex flex-wrap gap-1">
                  {tpl.symbols.slice(0, 5).map((sym) => (
                    <span
                      key={sym}
                      className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]"
                    >
                      {sym}
                    </span>
                  ))}
                  {tpl.symbols.length > 5 && (
                    <span className="text-[10px] text-[var(--text-tertiary)] px-1.5 py-0.5">
                      +{tpl.symbols.length - 5} more
                    </span>
                  )}
                </div>
                {/* CTA */}
                <button
                  onClick={() => handleAdd(tpl)}
                  disabled={!!loadingTemplate}
                  className={cn(
                    "mt-auto text-xs font-semibold px-3 py-1.5 rounded-lg transition-all",
                    isSuccess
                      ? "bg-[var(--accent-positive)]/20 text-[var(--accent-positive)] cursor-default"
                      : "bg-[var(--accent-positive)] text-black hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  {isLoading ? "Adding…" : isSuccess ? "Added!" : "Add to my watchlists"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── WatchlistRow ──────────────────────────────────────────────────────────────

function WatchlistRow({ symbol, watchlistId }: { symbol: string; watchlistId: number }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const isViewer = useIsViewer();
  const quote = useMarketStore((s) => s.quotes[symbol]);
  const { data: snapshots } = useQuery({
    queryKey: ["snapshot", watchlistId],
    queryFn: () => getSnapshot(watchlistId),
    staleTime: 30_000,
  });
  const snap = snapshots?.find((s) => s.symbol === symbol);
  const price = quote?.price ?? snap?.price ?? 0;
  const changePct = snap?.change_pct ?? 0;
  const isPos = changePct >= 0;

  const remove = useMutation({
    mutationFn: () => removeSymbol(watchlistId, symbol),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists"] }),
  });

  return (
    <div
      className="flex items-center px-4 py-3 min-h-[44px] hover:bg-[var(--bg-elevated-2)]/40 group cursor-pointer border-b border-[var(--border-subtle)] last:border-0"
      onClick={() => navigate(`/chart?symbol=${symbol}`)}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-[var(--text-primary)]">{symbol}</span>
          <SectorPill symbol={symbol} />
        </div>
        {COMPANY_INFO[symbol] && (
          <div className="text-xs text-[var(--text-tertiary)] truncate mt-0.5">{COMPANY_INFO[symbol].name}</div>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <Sparkline symbol={symbol} width={60} height={26} />
        <div className="text-right min-w-[72px]">
          <div className="text-sm font-medium text-[var(--text-primary)]">{price > 0 ? formatCurrency(price) : "—"}</div>
          <div className={cn("text-xs flex items-center gap-0.5 justify-end",
            isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
          )}>
            {isPos ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {formatPercent(changePct)}
          </div>
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/research?symbol=${symbol}`); }}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors p-1"
            title="Research"
          >
            <Microscope size={13} />
          </button>
          {!isViewer && (
            <button
              onClick={(e) => { e.stopPropagation(); remove.mutate(); }}
              className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors p-1"
              title="Remove"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── WatchlistPage ─────────────────────────────────────────────────────────────

export default function WatchlistPage() {
  const qc = useQueryClient();
  const isViewer = useIsViewer();
  const { data, isLoading } = useQuery({ queryKey: ["watchlists"], queryFn: getWatchlists });
  const [newName, setNewName] = useState("");
  const [addingSymbol, setAddingSymbol] = useState<number | null>(null);
  const [symbolInput, setSymbolInput] = useState("");
  const [showNewForm, setShowNewForm] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);

  const watchlists = data ?? [];

  const createMut = useMutation({
    mutationFn: createWatchlist,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      setNewName("");
      setShowNewForm(false);
    },
  });

  const addMut = useMutation({
    mutationFn: ({ id, sym }: { id: number; sym: string }) => addSymbol(id, sym),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlists"] }); setSymbolInput(""); setAddingSymbol(null); },
  });

  // ── Empty state ───────────────────────────────────────────────────────────
  if (!isLoading && watchlists.length === 0) {
    return (
      <>
        {showTemplates && <TemplateGallery onClose={() => setShowTemplates(false)} />}
        <div className="max-w-3xl mx-auto">
          {/* Page header still visible so user can create via form if they want */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)] mb-6">
            <h2 className="text-xl font-bold text-[var(--text-primary)] font-display">Watchlists</h2>
            {showNewForm ? (
              <form
                onSubmit={(e) => { e.preventDefault(); if (newName.trim()) createMut.mutate(newName.trim()); }}
                className="flex gap-2"
              >
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="New list name"
                  className="bg-[var(--bg-elevated-2)] text-[var(--text-primary)] text-sm px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] focus:border-[var(--accent-positive)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-positive)]/40 w-40 placeholder:text-[var(--text-tertiary)] transition-colors"
                />
                <Button type="submit" variant="primary" size="sm">
                  <Plus size={14} />
                </Button>
                <button type="button" onClick={() => setShowNewForm(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm px-2">Cancel</button>
              </form>
            ) : (
              <button
                onClick={() => setShowNewForm(true)}
                className="flex items-center gap-1 text-sm text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Plus size={14} /> New list
              </button>
            )}
          </div>

          {/* Empty state hero */}
          <div className="flex-1 flex flex-col items-center justify-center gap-5 px-8 text-center min-h-[60vh]">
            <div className="w-16 h-16 rounded-2xl bg-[var(--accent-positive)]/10 flex items-center justify-center">
              <BookMarked size={28} className="text-[var(--accent-positive)]" />
            </div>
            <div>
              <h2 className="text-[var(--text-primary)] font-semibold text-lg">Build your first watchlist</h2>
              <p className="text-[var(--text-tertiary)] text-sm mt-1 max-w-xs">
                Track tickers, sparklines, and price changes in one view.
              </p>
            </div>
            <div className="flex flex-col items-center gap-2">
              <button
                onClick={() => setShowNewForm(true)}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--accent-positive)] text-black text-sm font-semibold hover:opacity-90 transition-opacity"
              >
                <Plus size={16} /> New Watchlist
              </button>
              <button
                onClick={() => setShowTemplates(true)}
                className="text-[var(--text-tertiary)] text-xs hover:text-[var(--text-secondary)] transition-colors"
              >
                Or browse templates
              </button>
            </div>
          </div>
        </div>
      </>
    );
  }

  // ── Normal state ──────────────────────────────────────────────────────────
  return (
    <>
      {showTemplates && <TemplateGallery onClose={() => setShowTemplates(false)} />}
      <div className="max-w-3xl mx-auto space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)]">
          <h2 className="text-xl font-bold text-[var(--text-primary)] font-display">Watchlists</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAiOpen(true)}
              className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
            >
              <Bot size={12} /> Ask AI
            </button>
            <button
              onClick={() => setShowTemplates(true)}
              className="text-[var(--text-tertiary)] text-xs hover:text-[var(--text-secondary)] transition-colors px-2 py-1 rounded-lg border border-transparent hover:border-[var(--border-subtle)]"
            >
              Browse templates
            </button>
            <form
              onSubmit={(e) => { e.preventDefault(); if (newName.trim()) createMut.mutate(newName.trim()); }}
              className="flex gap-2"
            >
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="New list name"
                className="bg-[var(--bg-elevated-2)] text-[var(--text-primary)] text-sm px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] focus:border-[var(--accent-positive)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-positive)]/40 w-40 placeholder:text-[var(--text-tertiary)] transition-colors"
              />
              <Button type="submit" variant="primary" size="sm">
                <Plus size={14} />
              </Button>
            </form>
          </div>
        </div>

        {watchlists.map((wl) => (
          <div key={wl.id} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
              <div>
                <span className="font-semibold text-[var(--text-primary)]">{wl.name}</span>
                <span className="ml-2 text-xs text-[var(--text-tertiary)]">{wl.items.length} symbol{wl.items.length !== 1 ? "s" : ""}</span>
              </div>
              {!isViewer && (
                <button
                  onClick={() => setAddingSymbol(addingSymbol === wl.id ? null : wl.id)}
                  className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm flex items-center gap-1 transition-colors"
                >
                  <Plus size={14} /> Add symbol
                </button>
              )}
            </div>

            {addingSymbol === wl.id && (
              <div className="px-4 py-2.5 bg-[var(--bg-elevated-2)]/50 border-b border-[var(--border-subtle)]">
                <form
                  onSubmit={(e) => { e.preventDefault(); if (symbolInput.trim()) addMut.mutate({ id: wl.id, sym: symbolInput.trim() }); }}
                  className="flex gap-2"
                >
                  <input
                    autoFocus
                    value={symbolInput}
                    onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
                    placeholder="Symbol (e.g. TSLA)"
                    className="bg-[var(--bg-base)] text-[var(--text-primary)] text-sm px-2 py-1.5 rounded-lg border border-[var(--border-subtle)] w-36 uppercase placeholder:text-[var(--text-tertiary)] hover:border-[var(--border-emphasis)] focus:border-[var(--accent-positive)] focus:ring-1 focus:ring-[var(--accent-positive)]/40 focus:outline-none transition-colors"
                  />
                  <Button type="submit" variant="primary" size="sm">Add</Button>
                  <button type="button" onClick={() => setAddingSymbol(null)} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm px-2 py-1">Cancel</button>
                </form>
              </div>
            )}

            {wl.items.length === 0 ? (
              <div className="px-4 py-8 text-center text-[var(--text-tertiary)] text-sm">
                <p>No symbols yet.</p>
                <button onClick={() => setAddingSymbol(wl.id)} className="mt-2 text-[var(--text-primary)] hover:underline text-xs">
                  Add your first symbol
                </button>
              </div>
            ) : (
              <div>
                <div className="grid grid-cols-[1fr_auto] text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider px-4 py-1.5 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/30">
                  <span>Symbol</span>
                  <span className="mr-16">Price / Change</span>
                </div>
                {wl.items.map((item) => (
                  <WatchlistRow key={item.symbol} symbol={item.symbol} watchlistId={wl.id} />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Stocks"
        context="Watchlist — researching and tracking stocks"
        suggestedQuestions={[
          "What makes a good watchlist stock to monitor?",
          "How should I organize my watchlists by strategy?",
          "What signals should I watch for on these stocks?",
          "How do I identify the best entry point for a stock I'm watching?",
          "What's the difference between a position list and a watchlist?",
        ]}
      />
    </>
  );
}
