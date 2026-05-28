import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getWatchlists, createWatchlist, addSymbol, removeSymbol, getSnapshot } from "@/api/watchlist";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Plus, X, TrendingUp, TrendingDown, Microscope } from "lucide-react";
import { COMPANY_INFO } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import Sparkline from "@/components/ui/Sparkline";
import { Button } from "@/components/ui/Button";

function WatchlistRow({ symbol, watchlistId }: { symbol: string; watchlistId: number }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
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
          <button
            onClick={(e) => { e.stopPropagation(); remove.mutate(); }}
            className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors p-1"
            title="Remove"
          >
            <X size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function WatchlistPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["watchlists"], queryFn: getWatchlists });
  const [newName, setNewName] = useState("");
  const [addingSymbol, setAddingSymbol] = useState<number | null>(null);
  const [symbolInput, setSymbolInput] = useState("");

  const createMut = useMutation({
    mutationFn: createWatchlist,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlists"] }); setNewName(""); },
  });

  const addMut = useMutation({
    mutationFn: ({ id, sym }: { id: number; sym: string }) => addSymbol(id, sym),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlists"] }); setSymbolInput(""); setAddingSymbol(null); },
  });

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)]">
        <h2 className="text-xl font-bold text-[var(--text-primary)] font-display">Watchlists</h2>
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

      {data?.map((wl) => (
        <div key={wl.id} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
            <div>
              <span className="font-semibold text-[var(--text-primary)]">{wl.name}</span>
              <span className="ml-2 text-xs text-[var(--text-tertiary)]">{wl.items.length} symbol{wl.items.length !== 1 ? "s" : ""}</span>
            </div>
            <button
              onClick={() => setAddingSymbol(addingSymbol === wl.id ? null : wl.id)}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm flex items-center gap-1 transition-colors"
            >
              <Plus size={14} /> Add symbol
            </button>
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
  );
}
