import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  BarChart2,
  X,
  Plus,
  ArrowUpRight,
  ArrowDownRight,
  TrendingDown,
  Sparkles,
  ChevronRight,
  Save,
} from "lucide-react";
import { cn, formatCurrency } from "@/lib/utils";
import client from "@/api/client";
import { getTLHSummary } from "@/api/tlh";
import type { TLHSummary } from "@/api/tlh";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DirectIndexInfo {
  available: boolean;
  total_value: number;
  position_count: number;
  tracking_error_pct: number;
  ytd_tlh_dollars: number;
  current_balance?: number;
  sector_exclusions?: string[];
  ticker_exclusions?: string[];
  tilts?: Record<string, number>;
}

interface TiltConfig {
  esg: number;
  value: number;
  momentum: number;
  smallCap: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ALL_SECTORS = [
  "Oil & Gas",
  "Tobacco",
  "Firearms",
  "Gambling",
  "Fossil Fuels",
  "Alcohol",
  "Defense",
  "Private Prisons",
];

const TOP_POSITIONS = [
  { symbol: "MSFT", weight: 5.2, up: true },
  { symbol: "AAPL", weight: 5.0, up: true },
  { symbol: "AMZN", weight: 3.8, up: false },
  { symbol: "NVDA", weight: 3.6, up: true },
  { symbol: "GOOGL", weight: 3.4, up: true },
  { symbol: "META", weight: 2.9, up: false },
  { symbol: "BRK-B", weight: 1.8, up: true },
  { symbol: "JPM", weight: 1.7, up: true },
  { symbol: "LLY", weight: 1.6, up: false },
  { symbol: "AVGO", weight: 1.5, up: true },
];

const MIN_BALANCE = 25_000;

// ── Sub-components ─────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-xs font-semibold tracking-widest text-[var(--text-tertiary)] uppercase">
        {children}
      </span>
      <div className="flex-1 h-px bg-[var(--border-subtle)]" />
    </div>
  );
}

function Chip({
  label,
  onRemove,
}: {
  label: string;
  onRemove?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-700/60 border border-[var(--border-subtle)] text-[var(--text-primary)]">
      {label}
      {onRemove && (
        <button
          onClick={onRemove}
          className="ml-0.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <X size={11} />
        </button>
      )}
    </span>
  );
}

function TiltSlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 text-sm text-[var(--text-secondary)] shrink-0">{label}</span>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-blue-500 h-1.5 rounded cursor-pointer"
      />
      <span className="w-10 text-right text-sm font-medium text-[var(--text-primary)]">
        {value}%
      </span>
    </div>
  );
}

// ── Not-yet-enabled hero ───────────────────────────────────────────────────────

function NotEnabledHero({ currentBalance }: { currentBalance: number }) {
  const progress = Math.min((currentBalance / MIN_BALANCE) * 100, 100);

  return (
    <div className="space-y-6">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6 space-y-5">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold">
          <BarChart2 size={13} />
          Direct Indexing — The $25k Opportunity
        </div>

        <div>
          <h2 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">
            Wealthfront gates this at $100k.{" "}
            <span className="text-blue-400">We open it at $25k.</span>
          </h2>
          <p className="mt-2 text-[var(--text-secondary)] text-sm leading-relaxed">
            Stop hiding behind ETFs. Own every stock directly — and harvest losses every single
            day.
          </p>
        </div>

        {/* Bullets */}
        <ul className="space-y-2.5">
          {[
            "Own 200 individual S&P 500 stocks in your name",
            "Daily tax-loss harvesting at the lot level",
            "10–20× more harvest opportunities than ETF TLH",
          ].map((item) => (
            <li key={item} className="flex items-start gap-2.5 text-sm text-[var(--text-secondary)]">
              <span className="mt-0.5 w-4 h-4 rounded-full bg-green-500/15 border border-green-500/25 text-green-400 flex items-center justify-center text-[10px] shrink-0">
                ✓
              </span>
              {item}
            </li>
          ))}
        </ul>

        {/* Fee comparison */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-green-500/5 border border-green-500/15 rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-green-400">0.09%</div>
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5">BMG Capital — all-in</div>
            <div className="text-[10px] text-green-500 mt-1">Cheapest in the market</div>
          </div>
          <div className="bg-red-500/5 border border-red-500/15 rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-red-400">0.25%</div>
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5">Wealthfront</div>
            <div className="text-[10px] text-red-500 mt-1">2.8× more expensive</div>
          </div>
        </div>

        {/* Progress */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">Your balance</span>
            <span className="font-semibold text-[var(--text-primary)]">
              {formatCurrency(currentBalance, 0)}{" "}
              <span className="text-[var(--text-tertiary)] font-normal">
                / {formatCurrency(MIN_BALANCE, 0)} needed
              </span>
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-slate-700/60 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-xs text-[var(--text-tertiary)]">
            {formatCurrency(Math.max(MIN_BALANCE - currentBalance, 0), 0)} more to unlock
          </p>
        </div>

        <button className="w-full py-2.5 rounded-lg bg-blue-500/10 border border-blue-500/25 text-blue-400 text-sm font-semibold hover:bg-blue-500/15 transition-colors">
          Learn More
        </button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DirectIndexingPage() {
  // ── Data fetching ──────────────────────────────────────────────────────────
  const { data: diInfo } = useQuery<DirectIndexInfo>({
    queryKey: ["robo-direct-index"],
    queryFn: () => client.get("/api/robo/direct-index/info").then((r) => r.data),
  });

  const { data: tlhSummary } = useQuery<TLHSummary>({
    queryKey: ["tlh-summary"],
    queryFn: getTLHSummary,
  });

  // ── Local state ────────────────────────────────────────────────────────────
  const [sectorExclusions, setSectorExclusions] = useState<string[]>(
    diInfo?.sector_exclusions ?? []
  );
  const [tickerExclusions, setTickerExclusions] = useState<string[]>(
    diInfo?.ticker_exclusions ?? []
  );
  const [tickerInput, setTickerInput] = useState("");
  const [showSectorDropdown, setShowSectorDropdown] = useState(false);
  const [tilts, setTilts] = useState<TiltConfig>({
    esg: diInfo?.tilts?.esg ?? 40,
    value: diInfo?.tilts?.value ?? 20,
    momentum: diInfo?.tilts?.momentum ?? 0,
    smallCap: diInfo?.tilts?.smallCap ?? 0,
  });
  const [aiPrompt, setAiPrompt] = useState("");
  const [savedToast, setSavedToast] = useState(false);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const customizeMutation = useMutation({
    mutationFn: (payload: {
      nl_prompt?: string;
      sector_exclusions: string[];
      ticker_exclusions: string[];
      tilts: object;
    }) => client.post("/api/robo/direct-index/customize", payload).then((r) => r.data),
    onSuccess: () => {
      setSavedToast(true);
      setTimeout(() => setSavedToast(false), 2500);
    },
  });

  const handleSave = () => {
    customizeMutation.mutate({
      sector_exclusions: sectorExclusions,
      ticker_exclusions: tickerExclusions,
      tilts,
    });
  };

  const handleApplyWithAI = () => {
    customizeMutation.mutate({
      nl_prompt: aiPrompt,
      sector_exclusions: sectorExclusions,
      ticker_exclusions: tickerExclusions,
      tilts,
    });
  };

  const addSector = (sector: string) => {
    setSectorExclusions((prev) => [...prev, sector]);
    setShowSectorDropdown(false);
  };

  const removeSector = (sector: string) => {
    setSectorExclusions((prev) => prev.filter((s) => s !== sector));
  };

  const addTicker = () => {
    const t = tickerInput.trim().toUpperCase();
    if (t && !tickerExclusions.includes(t)) {
      setTickerExclusions((prev) => [...prev, t]);
    }
    setTickerInput("");
  };

  const removeTicker = (ticker: string) => {
    setTickerExclusions((prev) => prev.filter((t) => t !== ticker));
  };

  const remainingSectors = ALL_SECTORS.filter((s) => !sectorExclusions.includes(s));

  const ytdSaved = tlhSummary?.ytd_harvested_dollars ?? diInfo?.ytd_tlh_dollars ?? 0;
  const estimatedTaxSavings = ytdSaved * 0.24;

  // ── Not enabled state ──────────────────────────────────────────────────────
  if (diInfo && !diInfo.available) {
    return (
      <div className="max-w-2xl mx-auto pb-20 md:pb-8 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <BarChart2 size={18} className="text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
              Direct Indexing
            </h1>
            <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
              Own 200 S&P 500 stocks individually
            </p>
          </div>
        </div>
        <NotEnabledHero currentBalance={diInfo.current_balance ?? 0} />
      </div>
    );
  }

  // ── Enabled state ──────────────────────────────────────────────────────────
  return (
    <div className="max-w-2xl mx-auto pb-32 md:pb-12 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <BarChart2 size={18} className="text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
              Direct Indexing
            </h1>
            <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
              Own 200 S&P 500 stocks individually · Harvest losses daily · 1–2% tax alpha/yr
            </p>
          </div>
        </div>
        <button className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors">
          Tracking Error <ArrowUpRight size={13} />
        </button>
      </div>

      {/* Summary card */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-lg font-bold text-[var(--text-primary)]">
            {formatCurrency(diInfo?.total_value ?? 52_278, 0)} total
          </span>
          <span className="text-[var(--text-tertiary)] text-sm">·</span>
          <span className="text-sm text-[var(--text-secondary)]">
            {diInfo?.position_count ?? 187} positions
          </span>
        </div>
        <div className="flex items-center gap-4 flex-wrap text-sm">
          <span className="text-[var(--text-secondary)]">
            Tracking Error:{" "}
            <span className="font-semibold text-green-400">
              {(diInfo?.tracking_error_pct ?? 0.41).toFixed(2)}%
            </span>{" "}
            <span className="text-[var(--text-tertiary)]">(target &lt;1%)</span>
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <TrendingDown size={14} className="text-green-400" />
          <span className="text-[var(--text-secondary)]">
            YTD TLH:{" "}
            <span className="font-semibold text-[var(--text-primary)]">
              {formatCurrency(ytdSaved, 0)} losses
            </span>{" "}
            <span className="text-green-400">
              ≈ {formatCurrency(estimatedTaxSavings, 0)} saved
            </span>
          </span>
        </div>
      </div>

      {/* Customization */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-5">
        <SectionLabel>Customization</SectionLabel>

        {/* Sector Exclusions */}
        <div className="space-y-2">
          <p className="text-sm font-medium text-[var(--text-secondary)]">Sector Exclusions</p>
          <div className="flex flex-wrap gap-2">
            {sectorExclusions.map((s) => (
              <Chip key={s} label={s} onRemove={() => removeSector(s)} />
            ))}
            <div className="relative">
              <button
                onClick={() => setShowSectorDropdown((v) => !v)}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border border-dashed border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:border-slate-500 transition-colors"
              >
                <Plus size={11} /> Add Exclusion
              </button>
              {showSectorDropdown && remainingSectors.length > 0 && (
                <div className="absolute top-8 left-0 z-20 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg shadow-xl min-w-[160px] overflow-hidden">
                  {remainingSectors.map((sector) => (
                    <button
                      key={sector}
                      onClick={() => addSector(sector)}
                      className="w-full text-left px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-slate-700/40 hover:text-[var(--text-primary)] transition-colors"
                    >
                      {sector}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Ticker Exclusions */}
        <div className="space-y-2">
          <p className="text-sm font-medium text-[var(--text-secondary)]">Ticker Exclusions</p>
          <div className="flex flex-wrap gap-2 mb-2">
            {tickerExclusions.map((t) => (
              <Chip key={t} label={t} onRemove={() => removeTicker(t)} />
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && addTicker()}
              placeholder="e.g. AAPL"
              className="flex-1 bg-slate-800/60 border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-blue-500/50 transition-colors"
            />
            <button
              onClick={addTicker}
              className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/20 text-blue-400 text-sm rounded-lg hover:bg-blue-500/15 transition-colors"
            >
              Add
            </button>
          </div>
        </div>

        {/* Tilts */}
        <div className="space-y-3">
          <p className="text-sm font-medium text-[var(--text-secondary)]">
            Tilts (Factor Exposure)
          </p>
          <div className="space-y-3">
            <TiltSlider label="ESG" value={tilts.esg} onChange={(v) => setTilts((t) => ({ ...t, esg: v }))} />
            <TiltSlider label="Value" value={tilts.value} onChange={(v) => setTilts((t) => ({ ...t, value: v }))} />
            <TiltSlider label="Momentum" value={tilts.momentum} onChange={(v) => setTilts((t) => ({ ...t, momentum: v }))} />
            <TiltSlider label="Small-Cap" value={tilts.smallCap} onChange={(v) => setTilts((t) => ({ ...t, smallCap: v }))} />
          </div>
        </div>

        {/* AI Customization */}
        <div className="space-y-2 pt-1">
          <p className="text-sm font-medium text-[var(--text-secondary)] flex items-center gap-1.5">
            <Sparkles size={14} className="text-blue-400" />
            AI Customization
          </p>
          <textarea
            value={aiPrompt}
            onChange={(e) => setAiPrompt(e.target.value)}
            rows={2}
            placeholder="Describe your preferences... e.g. no oil, no tobacco, tilt small-cap value"
            className="w-full bg-slate-800/60 border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-blue-500/50 resize-none transition-colors"
          />
          <button
            onClick={handleApplyWithAI}
            disabled={customizeMutation.isPending || !aiPrompt.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-400 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors"
          >
            {customizeMutation.isPending ? (
              <>
                <span className="animate-pulse">AI is parsing your preferences...</span>
              </>
            ) : (
              <>
                <Sparkles size={14} />
                Apply with AI
              </>
            )}
          </button>
        </div>
      </div>

      {/* TLH Activity */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
        <SectionLabel>TLH Activity</SectionLabel>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">Today</span>
            <span className="text-[var(--text-primary)] font-medium">
              3 harvests · $840 losses captured
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">MTD</span>
            <span className="text-[var(--text-primary)] font-medium">
              14 harvests · {formatCurrency(ytdSaved, 0)} total
            </span>
          </div>
          <div className="pt-1 border-t border-[var(--border-subtle)] flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">Estimated tax savings (24% bracket)</span>
            <span className="text-green-400 font-semibold">{formatCurrency(estimatedTaxSavings, 0)}</span>
          </div>
        </div>
      </div>

      {/* Positions grid */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
        <SectionLabel>Positions (Top 10)</SectionLabel>
        <div className="grid grid-cols-2 gap-2">
          {TOP_POSITIONS.map((pos) => (
            <div
              key={pos.symbol}
              className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-800/40 border border-[var(--border-subtle)]"
            >
              <span className="text-sm font-semibold text-[var(--text-primary)]">{pos.symbol}</span>
              <div className="flex items-center gap-1.5">
                <span className="text-sm text-[var(--text-secondary)]">{pos.weight}%</span>
                {pos.up ? (
                  <ArrowUpRight size={13} className="text-green-400" />
                ) : (
                  <ArrowDownRight size={13} className="text-red-400" />
                )}
              </div>
            </div>
          ))}
        </div>
        <button className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors mt-1">
          View All {diInfo?.position_count ?? 187} Positions <ChevronRight size={13} />
        </button>
      </div>

      {/* Fixed bottom save bar */}
      <div className="fixed bottom-0 left-0 right-0 z-30 bg-[var(--bg-elevated)] border-t border-[var(--border-subtle)] px-4 py-3 flex items-center justify-between gap-4">
        <span className="text-sm text-[var(--text-tertiary)]">
          {sectorExclusions.length + tickerExclusions.length} exclusions active
        </span>
        <button
          onClick={handleSave}
          disabled={customizeMutation.isPending}
          className={cn(
            "flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all",
            savedToast
              ? "bg-green-500/15 border border-green-500/25 text-green-400"
              : "bg-blue-500 hover:bg-blue-400 text-white disabled:opacity-50"
          )}
        >
          <Save size={14} />
          {savedToast ? "Saved!" : customizeMutation.isPending ? "Saving..." : "Save Customization"}
        </button>
      </div>
    </div>
  );
}
