import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X, ChevronDown, Minus } from "lucide-react";
import { getWatchlists, createWatchlist, addSymbol, removeSymbol, getSnapshot } from "@/api/watchlist";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { COMPANY_INFO, SECTOR_COLOR } from "@/data/companyInfo";

interface Props {
  activeSymbol: string;
  onSymbolClick: (symbol: string) => void;
  onClose: () => void;
}

export default function WatchlistPanel({ activeSymbol, onSymbolClick, onClose }: Props) {
  const qc = useQueryClient();
  const [activeWlId, setActiveWlId] = useState<number | null>(null);
  const [addInput, setAddInput] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newWlInput, setNewWlInput] = useState("");
  const [showNewWl, setShowNewWl] = useState(false);
  const [wlMenuOpen, setWlMenuOpen] = useState(false);

  const quotes = useMarketStore((s) => s.quotes);

  const { data: watchlists = [] } = useQuery({
    queryKey: ["watchlists"],
    queryFn: getWatchlists,
  });

  useEffect(() => {
    if (!activeWlId && watchlists.length > 0) setActiveWlId((watchlists[0] as any).id);
  }, [watchlists, activeWlId]);

  const activeWl = watchlists.find((w: any) => w.id === activeWlId) ?? watchlists[0];

  const { data: snaps = [] } = useQuery({
    queryKey: ["wl-snapshot", activeWl?.id],
    queryFn: () => getSnapshot(activeWl!.id),
    enabled: !!activeWl,
    staleTime: 30_000,
  });

  const snapMap = Object.fromEntries(snaps.map((s: any) => [s.symbol, s]));

  const createWlMutation = useMutation({
    mutationFn: (name: string) => createWatchlist(name),
    onSuccess: (wl: any) => { qc.invalidateQueries({ queryKey: ["watchlists"] }); setActiveWlId(wl.id); setNewWlInput(""); setShowNewWl(false); },
  });

  const addSymbolMutation = useMutation({
    mutationFn: (sym: string) => addSymbol(activeWl!.id, sym),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlists"] }); qc.invalidateQueries({ queryKey: ["wl-snapshot"] }); setAddInput(""); setShowAdd(false); },
  });

  const removeSymbolMutation = useMutation({
    mutationFn: (sym: string) => removeSymbol(activeWl!.id, sym),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlists"] }); qc.invalidateQueries({ queryKey: ["wl-snapshot"] }); },
  });

  const symbols: string[] = activeWl?.symbols?.map((s: any) => s.symbol) ?? [];

  return (
    <div className="w-56 flex flex-col border-l border-[#1f1f1f] bg-[#0a0a0a] shrink-0 overflow-hidden">
      {/* Watchlist selector */}
      <div className="px-2 py-2 border-b border-[#1f1f1f] flex items-center gap-1">
        <div className="relative flex-1">
          <button
            onClick={() => setWlMenuOpen((o) => !o)}
            className="w-full flex items-center justify-between px-2 py-1 rounded text-xs text-[#d4d4d4] hover:bg-[#111]"
          >
            <span className="truncate font-medium">{activeWl?.name ?? "No watchlist"}</span>
            <ChevronDown size={11} className="shrink-0 text-[#555]" />
          </button>
          {wlMenuOpen && (
            <div className="absolute top-full left-0 right-0 z-50 bg-[#111] border border-[#1f1f1f] rounded shadow-xl py-1 mt-0.5">
              {watchlists.map((wl: any) => (
                <button
                  key={wl.id}
                  onClick={() => { setActiveWlId(wl.id); setWlMenuOpen(false); }}
                  className={cn("w-full text-left px-3 py-1.5 text-xs hover:bg-[#1f1f1f]", activeWl?.id === wl.id ? "text-white" : "text-[#d4d4d4]")}
                >
                  {wl.name}
                </button>
              ))}
              <div className="border-t border-[#1f1f1f] my-1" />
              <button
                onClick={() => { setShowNewWl(true); setWlMenuOpen(false); }}
                className="w-full text-left px-3 py-1.5 text-xs text-[#555] hover:bg-[#1f1f1f] flex items-center gap-1.5"
              >
                <Plus size={11} /> New watchlist
              </button>
            </div>
          )}
        </div>
        <button
          onClick={() => setShowAdd((s) => !s)}
          title="Add symbol"
          className="w-6 h-6 flex items-center justify-center text-[#555] hover:text-[#d4d4d4] hover:bg-[#111] rounded"
        >
          <Plus size={14} />
        </button>
        <button
          onClick={onClose}
          title="Minimize watchlist"
          className="w-6 h-6 flex items-center justify-center text-[#555] hover:text-[#d4d4d4] hover:bg-[#111] rounded"
        >
          <Minus size={14} />
        </button>
      </div>

      {/* New watchlist input */}
      {showNewWl && (
        <form
          onSubmit={(e) => { e.preventDefault(); if (newWlInput.trim()) createWlMutation.mutate(newWlInput.trim()); }}
          className="px-2 py-1.5 border-b border-[#1f1f1f] flex gap-1"
        >
          <input
            autoFocus
            value={newWlInput}
            onChange={(e) => setNewWlInput(e.target.value)}
            placeholder="Watchlist name..."
            className="flex-1 bg-[#111] border border-[#1f1f1f] rounded px-2 py-1 text-xs text-[#d4d4d4] placeholder-[#555] focus:outline-none focus:border-white/30"
          />
          <button type="submit" className="px-2 py-1 bg-white text-black text-xs rounded hover:bg-zinc-200">+</button>
          <button type="button" onClick={() => setShowNewWl(false)} className="px-1 text-[#555] hover:text-[#d4d4d4]"><X size={12} /></button>
        </form>
      )}

      {/* Add symbol */}
      {showAdd && activeWl && (
        <form
          onSubmit={(e) => { e.preventDefault(); const s = addInput.trim().toUpperCase(); if (s) addSymbolMutation.mutate(s); }}
          className="px-2 py-1.5 border-b border-[#1f1f1f] flex gap-1"
        >
          <input
            autoFocus
            value={addInput}
            onChange={(e) => setAddInput(e.target.value.toUpperCase())}
            placeholder="Symbol (e.g. AAPL)"
            className="flex-1 bg-[#111] border border-[#1f1f1f] rounded px-2 py-1 text-xs text-[#d4d4d4] placeholder-[#555] focus:outline-none focus:border-white/30 uppercase"
          />
          <button type="submit" className="px-2 py-1 bg-white text-black text-xs rounded hover:bg-zinc-200">Add</button>
          <button type="button" onClick={() => setShowAdd(false)} className="px-1 text-[#555] hover:text-[#d4d4d4]"><X size={12} /></button>
        </form>
      )}

      {/* Symbol list */}
      <div className="flex-1 overflow-y-auto">
        {symbols.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 gap-2">
            <p className="text-[#555] text-xs text-center">No symbols</p>
            <button onClick={() => setShowAdd(true)} className="text-xs text-white hover:underline">Add a symbol</button>
          </div>
        ) : (
          symbols.map((sym: string) => {
            const liveQuote = quotes[sym];
            const snap = snapMap[sym];
            const price = liveQuote?.price ?? snap?.price ?? 0;
            const changePct = snap?.change_pct ?? 0;
            const isPos = changePct >= 0;
            const isActive = sym === activeSymbol;
            return (
              <div
                key={sym}
                onClick={() => onSymbolClick(sym)}
                className={cn(
                  "flex items-center px-3 py-2 cursor-pointer border-b border-[#1f1f1f]/50 group",
                  isActive ? "bg-[#1f1f1f]" : "hover:bg-[#111]"
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-semibold text-[#d4d4d4] truncate">{sym}</span>
                    {COMPANY_INFO[sym]?.sector && (
                      <span
                        className="text-[9px] font-medium px-1 py-px rounded-full shrink-0"
                        style={{
                          backgroundColor: (SECTOR_COLOR[COMPANY_INFO[sym].sector] ?? "#6b7280") + "22",
                          color: SECTOR_COLOR[COMPANY_INFO[sym].sector] ?? "#9ca3af",
                        }}
                      >
                        {COMPANY_INFO[sym].sector}
                      </span>
                    )}
                  </div>
                  <div className={cn("text-[10px] font-medium", isPos ? "text-[#26a69a]" : "text-[#ef5350]")}>
                    {isPos ? "+" : ""}{formatPercent(changePct)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-medium text-[#d4d4d4]">{price > 0 ? formatCurrency(price) : "—"}</div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); removeSymbolMutation.mutate(sym); }}
                  className="ml-1 opacity-0 group-hover:opacity-100 text-[#555] hover:text-[#ef5350] transition-opacity"
                >
                  <X size={11} />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="px-3 py-1.5 border-t border-[#1f1f1f] text-[10px] text-[#555]">
        {symbols.length} symbol{symbols.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}
