import { useState, useRef, useEffect, useCallback } from "react";
import { Search } from "lucide-react";
import { TICKER_NAMES } from "@/data/tickerNames";
import { cn } from "@/lib/utils";

const ALL_SYMBOLS = Object.keys(TICKER_NAMES);

function filterSymbols(query: string): string[] {
  if (!query) return [];
  const q = query.toUpperCase();
  const exact: string[] = [];
  const prefix: string[] = [];
  const nameMatch: string[] = [];

  for (const sym of ALL_SYMBOLS) {
    if (sym === q) { exact.push(sym); continue; }
    if (sym.startsWith(q)) { prefix.push(sym); continue; }
    if (TICKER_NAMES[sym].toUpperCase().includes(q)) nameMatch.push(sym);
  }
  return [...exact, ...prefix, ...nameMatch].slice(0, 8);
}

interface Props {
  defaultValue?: string;
  onSelect: (symbol: string) => void;
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  autoFocus?: boolean;
}

export default function SymbolSearch({
  defaultValue = "",
  onSelect,
  className,
  inputClassName,
  placeholder = "Search ticker…",
  autoFocus = false,
}: Props) {
  const [query, setQuery] = useState(defaultValue);
  const [results, setResults] = useState<string[]>([]);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoFocus) {
      setTimeout(() => inputRef.current?.select(), 10);
    }
  }, [autoFocus]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value.toUpperCase();
    setQuery(val);
    const matches = filterSymbols(val);
    setResults(matches);
    setActive(-1);
    setOpen(matches.length > 0);
  };

  const commit = useCallback((sym: string) => {
    const s = sym.trim().toUpperCase();
    if (!s) return;
    setQuery(s);
    setOpen(false);
    onSelect(s);
  }, [onSelect]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0 && results[active]) {
        commit(results[active]);
      } else if (query.trim()) {
        commit(query);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <div className="flex items-center">
        <input
          ref={inputRef}
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          className={inputClassName}
        />
        <button
          type="button"
          onClick={() => commit(query)}
          className="shrink-0 h-full px-2.5 bg-white text-black rounded-r text-xs hover:bg-zinc-200 flex items-center"
        >
          <Search size={12} />
        </button>
      </div>

      {open && (
        <div className="absolute top-full left-0 z-[200] mt-0.5 w-72 bg-[#111] border border-[#1f1f1f] rounded shadow-2xl overflow-hidden">
          {results.map((sym, i) => (
            <button
              key={sym}
              onMouseDown={(e) => { e.preventDefault(); commit(sym); }}
              className={cn(
                "w-full text-left px-3 py-2 flex items-center gap-2.5 text-sm",
                i === active ? "bg-[#1a1a1a]" : "hover:bg-[#1a1a1a]"
              )}
            >
              <span className="font-bold text-white w-16 shrink-0">{sym}</span>
              <span className="text-[#555] text-xs truncate">{TICKER_NAMES[sym]}</span>
            </button>
          ))}
          {query && !results.find(s => s === query.toUpperCase()) && (
            <button
              onMouseDown={(e) => { e.preventDefault(); commit(query); }}
              className="w-full text-left px-3 py-2 flex items-center gap-2 text-sm border-t border-[#1f1f1f] text-[#555] hover:bg-[#1a1a1a]"
            >
              <Search size={11} />
              <span>Go to <strong className="text-white">{query.toUpperCase()}</strong></span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
