import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, ChevronDown, ChevronUp, BarChart2, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { TICKER_NAMES } from "@/data/tickerNames";
import SymbolSearch from "@/components/ui/SymbolSearch";
import { scanTicker, type TickerScanRow, type StrategyState } from "@/api/strategy";

interface Props {
  initialSymbol?: string;
  onClose: () => void;
  onChart: (symbol: string, preset: string, levels?: {
    entry?: number | null;
    stop?: number | null;
    target?: number | null;
  }) => void;
}

const STATE_CONFIG: Record<StrategyState, { label: string; dot: string; bg: string; border: string; text: string }> = {
  active:          { label: "Active",          dot: "🟢", bg: "bg-[var(--accent-positive)]/8",  border: "border-[var(--accent-positive)]/25", text: "text-[var(--accent-positive)]" },
  forming:         { label: "Forming",         dot: "🟡", bg: "bg-yellow-500/8",                  border: "border-yellow-500/25",               text: "text-yellow-400" },
  exit_triggered:  { label: "Exit Triggered",  dot: "🔴", bg: "bg-[var(--accent-negative)]/8",   border: "border-[var(--accent-negative)]/25",  text: "text-[var(--accent-negative)]" },
  idle:            { label: "Idle",            dot: "⚪", bg: "bg-[var(--bg-elevated)]",          border: "border-[var(--border-subtle)]",       text: "text-[var(--text-tertiary)]" },
};

const STATE_ORDER: StrategyState[] = ["exit_triggered", "active", "forming", "idle"];

function StateGroup({ state, rows, onChart, symbol }: {
  state: StrategyState;
  rows: TickerScanRow[];
  symbol: string;
  onChart: Props["onChart"];
}) {
  const [expanded, setExpanded] = useState(state !== "idle");
  const cfg = STATE_CONFIG[state];

  if (rows.length === 0) return null;

  return (
    <div className={cn("rounded-xl border overflow-hidden", cfg.border)}>
      {/* Group header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className={cn("w-full flex items-center justify-between px-4 py-2.5 text-left cursor-pointer", cfg.bg)}
      >
        <div className="flex items-center gap-2">
          <span className="text-base leading-none">{cfg.dot}</span>
          <span className={cn("text-sm font-semibold", cfg.text)}>{cfg.label}</span>
          <span className="text-xs text-[var(--text-tertiary)] font-medium">({rows.length})</span>
        </div>
        {expanded
          ? <ChevronUp size={14} className="text-[var(--text-tertiary)]" />
          : <ChevronDown size={14} className="text-[var(--text-tertiary)]" />}
      </button>

      {/* Rows */}
      {expanded && (
        <div className="divide-y divide-[var(--border-subtle)]">
          {rows.map((row) => (
            <StrategyRow key={row.preset_key} row={row} symbol={symbol} onChart={onChart} cfg={cfg} />
          ))}
        </div>
      )}
    </div>
  );
}

function StrategyRow({ row, symbol, onChart, cfg }: {
  row: TickerScanRow;
  symbol: string;
  onChart: Props["onChart"];
  cfg: (typeof STATE_CONFIG)[StrategyState];
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 bg-[var(--bg-base)] hover:bg-[var(--bg-elevated)] transition-colors group">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-[var(--text-primary)]">{row.preset_label}</span>
          {row.days_to_trigger != null && (
            <span className="text-[10px] font-medium text-yellow-400 bg-yellow-500/10 px-1.5 py-0.5 rounded-full">
              ~{row.days_to_trigger}d
            </span>
          )}
        </div>
        <p className="text-xs text-[var(--text-tertiary)] mt-0.5 leading-relaxed">{row.status_message}</p>
        {row.key_label && row.key_value != null && (
          <p className={cn("text-[10px] font-medium mt-0.5", cfg.text)}>
            {row.key_label}: {row.key_value}
          </p>
        )}
      </div>

      <button
        onClick={() => onChart(symbol, row.preset_key, {
          entry: row.entry_price,
          stop: row.stop_price,
          target: row.target_price,
        })}
        className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-all text-xs font-medium cursor-pointer opacity-0 group-hover:opacity-100"
      >
        <BarChart2 size={11} />
        Chart
      </button>
    </div>
  );
}

function ScanResults({ symbol, onChart }: { symbol: string; onChart: Props["onChart"] }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["ticker-scan", symbol],
    queryFn: () => scanTicker(symbol),
    staleTime: 300_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <Loader2 size={24} className="animate-spin text-[var(--text-tertiary)]" />
        <p className="text-sm text-[var(--text-tertiary)]">Scanning {symbol} against all strategies…</p>
        <p className="text-xs text-[var(--text-tertiary)] opacity-60">Fetching 1 year of price data</p>
      </div>
    );
  }

  if (isError) {
    const msg = (error as any)?.response?.data?.detail ?? "No price data found for this ticker.";
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <AlertCircle size={24} className="text-[var(--accent-negative)]" />
        <p className="text-sm text-[var(--text-tertiary)] text-center max-w-xs">{msg}</p>
      </div>
    );
  }

  if (!data) return null;

  const byState = STATE_ORDER.reduce<Record<StrategyState, TickerScanRow[]>>((acc, s) => {
    acc[s] = data.results.filter((r) => r.state === s);
    return acc;
  }, { exit_triggered: [], active: [], forming: [], idle: [] });

  const totalActive = byState.active.length + byState.exit_triggered.length;

  return (
    <div className="space-y-3">
      {totalActive === 0 && byState.forming.length === 0 && (
        <div className="text-center py-6">
          <p className="text-sm text-[var(--text-tertiary)]">No active signals or forming setups for {symbol}</p>
        </div>
      )}
      {STATE_ORDER.map((state) => (
        <StateGroup
          key={state}
          state={state}
          rows={byState[state]}
          symbol={symbol}
          onChart={onChart}
        />
      ))}
    </div>
  );
}

export default function TickerScanPanel({ initialSymbol, onClose, onChart }: Props) {
  const [symbol, setSymbol] = useState(initialSymbol ?? "");

  return (
    /* Overlay */
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} />

      {/* Panel */}
      <div className="relative z-10 flex flex-col w-full max-w-md h-full bg-[var(--bg-base)] border-l border-[var(--border-subtle)] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)] shrink-0">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">Strategy Scanner</h2>
            <p className="text-xs text-[var(--text-tertiary)] mt-0.5">Check any ticker against all 19 strategies</p>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors p-1 rounded cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-4 border-b border-[var(--border-subtle)] shrink-0">
          <SymbolSearch
            key={symbol}
            defaultValue={symbol}
            onSelect={(s) => setSymbol(s)}
            placeholder="Search ticker… (AAPL, NVDA, MSFT)"
            autoFocus
            className="w-full"
            inputClassName="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-l-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--border-emphasis)] placeholder:text-[var(--text-tertiary)] font-mono"
          />
          {symbol && TICKER_NAMES[symbol] && (
            <p className="text-xs text-[var(--text-tertiary)] mt-2 pl-0.5">{TICKER_NAMES[symbol]}</p>
          )}
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-5">
          {symbol ? (
            <ScanResults symbol={symbol} onChart={onChart} />
          ) : (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
              <BarChart2 size={32} className="text-[var(--border-emphasis)]" />
              <p className="text-sm text-[var(--text-tertiary)]">Search for a ticker above</p>
              <p className="text-xs text-[var(--text-tertiary)] opacity-60">
                We'll scan all 19 strategies and show you which ones are active, forming, or idle
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
