import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search, LayoutDashboard, LineChart, Filter, BookMarked, Briefcase, Bell, FlaskConical, Newspaper, Calendar, Microscope, PlayCircle, TrendingUp, BookOpen, Layers, Globe, BarChart2, Shield, Zap, Users, Compass, Landmark, ScanSearch } from "lucide-react";
import { COMPANY_INFO } from "@/data/companyInfo";
import { cn } from "@/lib/utils";

interface CommandItem {
  type: "page" | "symbol";
  label: string;
  subtitle?: string;
  icon?: React.ReactNode;
  action: () => void;
}

const PAGES = [
  { label: "Dashboard", to: "/", Icon: LayoutDashboard },
  { label: "Chart", to: "/chart", Icon: LineChart },
  { label: "Screener", to: "/screener", Icon: Filter },
  { label: "Watchlist", to: "/watchlist", Icon: BookMarked },
  { label: "Portfolio", to: "/portfolio", Icon: Briefcase },
  { label: "Alerts", to: "/alerts", Icon: Bell },
  { label: "Strategy Lab", to: "/strategy", Icon: FlaskConical },
  { label: "News", to: "/news", Icon: Newspaper },
  { label: "Earnings", to: "/earnings", Icon: Calendar },
  { label: "Research", to: "/research", Icon: Microscope },
  { label: "Paper Trading", to: "/paper", Icon: PlayCircle },
  { label: "Discovery", to: "/discover", Icon: Compass },
  { label: "Trade Journal", to: "/journal", Icon: BookOpen },
  { label: "Analytics", to: "/analytics", Icon: BarChart2 },
  { label: "TA Workshop", to: "/workshop", Icon: LineChart },
  { label: "Crypto Lab", to: "/crypto", Icon: Zap },
  { label: "Options Lab", to: "/options", Icon: Layers },
  { label: "DeFi", to: "/defi", Icon: Globe },
  { label: "Social", to: "/social", Icon: Users },
  { label: "Security", to: "/security", Icon: Shield },
  { label: "Learn", to: "/learn", Icon: TrendingUp },
  { label: "Net Worth", to: "/net-worth", Icon: Landmark },
  { label: "Tax X-Ray", to: "/tax-xray", Icon: ScanSearch },
];

const SYMBOLS = Object.entries(COMPANY_INFO).map(([sym, info]) => ({ sym, name: info.name, sector: info.sector }));

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function CommandPalette({ open, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const items: CommandItem[] = (() => {
    const q = query.toLowerCase().trim();
    if (!q) {
      return PAGES.slice(0, 8).map((p) => ({
        type: "page" as const,
        label: p.label,
        icon: <p.Icon size={15} />,
        action: () => { navigate(p.to); onClose(); },
      }));
    }

    const pageMatches: CommandItem[] = PAGES
      .filter((p) => p.label.toLowerCase().includes(q))
      .map((p) => ({
        type: "page" as const,
        label: p.label,
        icon: <p.Icon size={15} />,
        action: () => { navigate(p.to); onClose(); },
      }));

    const symMatches: CommandItem[] = SYMBOLS
      .filter((s) => s.sym.toLowerCase().startsWith(q) || s.name.toLowerCase().includes(q))
      .slice(0, 5)
      .flatMap((s) => [
        {
          type: "symbol" as const,
          label: s.sym,
          subtitle: `Chart — ${s.name}`,
          action: () => { navigate(`/chart?symbol=${s.sym}`); onClose(); },
        },
        {
          type: "symbol" as const,
          label: s.sym,
          subtitle: `Research — ${s.name}`,
          action: () => { navigate(`/research?symbol=${s.sym}`); onClose(); },
        },
      ]);

    return [...pageMatches, ...symMatches].slice(0, 12);
  })();

  const select = useCallback((idx: number) => {
    items[idx]?.action();
  }, [items]);

  useEffect(() => {
    setSelected(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setSelected((s) => Math.min(s + 1, items.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setSelected((s) => Math.max(s - 1, 0)); }
      if (e.key === "Enter") { e.preventDefault(); select(selected); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, items, selected, select, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-start justify-center pt-24">
      <div className="absolute inset-0 bg-[#020617]/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg mx-4 bg-[#111] border border-[var(--border-emphasis)] rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-emphasis)]">
          <Search size={16} className="text-[var(--text-tertiary)] shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search pages or symbols…"
            className="flex-1 bg-transparent text-[var(--text-primary)] text-sm outline-none placeholder-zinc-600"
          />
          <kbd className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] px-1.5 py-0.5 rounded">esc</kbd>
        </div>
        <div className="py-1">
          {items.length === 0 ? (
            <div className="px-4 py-8 text-center text-[var(--text-tertiary)] text-sm">No results</div>
          ) : (
            items.map((item, i) => (
              <button
                key={`${item.type}-${item.label}`}
                onClick={() => select(i)}
                onMouseEnter={() => setSelected(i)}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                  i === selected ? "bg-[#334155]" : "hover:bg-[var(--bg-elevated-2)]"
                )}
              >
                {item.type === "page" ? (
                  <span className="text-[var(--text-tertiary)] shrink-0">{item.icon}</span>
                ) : (
                  <span className="w-5 h-5 rounded-sm bg-teal-500/15 text-teal-400 text-[9px] font-bold flex items-center justify-center shrink-0 border border-teal-500/20">$</span>
                )}
                <span className="text-sm font-medium text-[var(--text-primary)] truncate">{item.label}</span>
                {item.subtitle && (
                  <span className="text-xs text-[var(--text-tertiary)] truncate ml-auto shrink-0 max-w-[200px]">{item.subtitle}</span>
                )}
                {item.type === "page" && !item.subtitle && (
                  <span className="ml-auto text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider shrink-0">page</span>
                )}
              </button>
            ))
          )}
        </div>
        <div className="px-4 py-2 border-t border-[var(--border-subtle)] flex items-center gap-4 text-[11px] text-[var(--text-tertiary)]">
          <span>↑↓ navigate</span>
          <span>↵ select</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  );
}
