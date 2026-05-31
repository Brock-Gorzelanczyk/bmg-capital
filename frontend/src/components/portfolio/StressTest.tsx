import { useState, useMemo } from "react";
import {
  AlertTriangle,
  TrendingDown,
  TrendingUp,
  Info,
} from "lucide-react";
import { formatCurrency, cn } from "@/lib/utils";
import type { PaperPosition } from "@/api/paper";

// ---------------------------------------------------------------------------
// Scenario definitions
// ---------------------------------------------------------------------------

interface Scenario {
  name: string;
  equityDrop: number;   // percent applied to each equity position
  bondDrop: number;
  goldRise: number;
  description: string;
  emoji: string;
}

const SCENARIOS: Scenario[] = [
  {
    name: "2008 GFC",
    equityDrop: -55,
    bondDrop: 5,
    goldRise: 25,
    description: "Global financial crisis — credit freeze, housing collapse",
    emoji: "🏚️",
  },
  {
    name: "Covid Mar 2020",
    equityDrop: -34,
    bondDrop: -3,
    goldRise: 8,
    description: "Pandemic shock — fastest 30% drop in market history",
    emoji: "🦠",
  },
  {
    name: "Rate Shock +200bps",
    equityDrop: -18,
    bondDrop: -15,
    goldRise: -5,
    description: "Rapid rate hike scenario — 2022-style tech multiple compression",
    emoji: "📈",
  },
  {
    name: "BTC -50%",
    equityDrop: -5,
    bondDrop: 0,
    goldRise: 2,
    description: "Crypto winter — correlation contagion to growth names",
    emoji: "🪙",
  },
  {
    name: "USD +10%",
    equityDrop: -8,
    bondDrop: -3,
    goldRise: -6,
    description: "Dollar surge — headwind for multinationals and commodities",
    emoji: "💵",
  },
  {
    name: "Soft Landing",
    equityDrop: 8,
    bondDrop: 5,
    goldRise: -2,
    description: "Fed nails the pivot — gradual rate cuts, expansion resumes",
    emoji: "🌤️",
  },
];

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

type Severity = "severe" | "moderate" | "mild" | "positive";

function getSeverity(dropPct: number): Severity {
  if (dropPct >= 0) return "positive";
  if (dropPct < -20) return "severe";
  if (dropPct < -10) return "moderate";
  return "mild";
}

function severityColor(severity: Severity) {
  switch (severity) {
    case "severe":   return "text-[#EF4444]";
    case "moderate": return "text-[#F59E0B]";
    case "mild":     return "text-[#F97316]";
    case "positive": return "text-[#22C55E]";
  }
}

function severityBg(severity: Severity) {
  switch (severity) {
    case "severe":   return "bg-[#EF4444]/10 border-[#EF4444]/30";
    case "moderate": return "bg-[#F59E0B]/10 border-[#F59E0B]/30";
    case "mild":     return "bg-[#F97316]/10 border-[#F97316]/30";
    case "positive": return "bg-[#22C55E]/10 border-[#22C55E]/30";
  }
}

// ---------------------------------------------------------------------------
// Scenario card
// ---------------------------------------------------------------------------

function ScenarioCard({
  scenario,
  selected,
  onSelect,
}: {
  scenario: Scenario;
  selected: boolean;
  onSelect: () => void;
}) {
  const severity = getSeverity(scenario.equityDrop);
  const colorCls = severityColor(severity);

  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full text-left px-3 py-2.5 rounded-xl border transition-all cursor-pointer",
        selected
          ? "border-[#3B82F6] bg-[#3B82F6]/10 ring-1 ring-[#3B82F6]/30"
          : "border-[var(--border-subtle)] bg-[var(--bg-elevated-2)] hover:border-[var(--border-emphasis)]"
      )}
    >
      <div className="flex items-start justify-between gap-1 mb-1">
        <span className="text-xs font-semibold text-[var(--text-primary)] leading-snug">
          {scenario.name}
        </span>
        <span
          className={cn("font-mono text-xs font-bold shrink-0", colorCls)}
        >
          {scenario.equityDrop >= 0 ? "+" : ""}{scenario.equityDrop}%
        </span>
      </div>
      <p className="text-[10px] text-[var(--text-tertiary)] leading-snug line-clamp-2">
        {scenario.description}
      </p>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Position impact row
// ---------------------------------------------------------------------------

interface ImpactRow {
  symbol: string;
  marketValue: number;
  impactDollars: number;
  impactPct: number;
}

function ImpactRowItem({ row }: { row: ImpactRow }) {
  const severity = getSeverity(row.impactPct);
  const colorCls = severityColor(severity);

  return (
    <div className="flex items-center gap-3 py-2 border-b border-[var(--border-subtle)]/40 last:border-0">
      <span className="font-mono font-bold text-[var(--text-primary)] text-sm w-14 shrink-0">
        {row.symbol}
      </span>
      <div className="flex-1 text-xs text-[var(--text-tertiary)] font-mono">
        {formatCurrency(row.marketValue)}
      </div>
      <div className={cn("text-right", colorCls)}>
        <div className="font-mono text-sm font-semibold">
          {row.impactDollars >= 0 ? "+" : ""}{formatCurrency(row.impactDollars)}
        </div>
        <div className="text-[10px] font-mono">
          {row.impactPct >= 0 ? "+" : ""}{row.impactPct.toFixed(1)}%
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface StressTestProps {
  positions: PaperPosition[];
}

export default function StressTest({ positions }: StressTestProps) {
  const [selectedScenario, setSelectedScenario] = useState<Scenario>(SCENARIOS[0]);

  const totalValue = useMemo(
    () => positions.reduce((a, p) => a + p.market_value, 0),
    [positions]
  );

  const impactRows: ImpactRow[] = useMemo(() => {
    const multiplier = selectedScenario.equityDrop / 100;
    return positions
      .map((p) => ({
        symbol: p.symbol,
        marketValue: p.market_value,
        impactDollars: p.market_value * multiplier,
        impactPct: selectedScenario.equityDrop,
      }))
      .sort((a, b) => a.impactDollars - b.impactDollars); // worst first
  }, [positions, selectedScenario]);

  const totalImpact = useMemo(
    () => impactRows.reduce((a, r) => a + r.impactDollars, 0),
    [impactRows]
  );

  const totalImpactPct = totalValue > 0 ? (totalImpact / totalValue) * 100 : 0;
  const projectedValue = totalValue + totalImpact;

  const overallSeverity = getSeverity(totalImpactPct);
  const bgCls = severityBg(overallSeverity);
  const textCls = severityColor(overallSeverity);

  if (positions.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-[var(--text-tertiary)] text-sm">
        No positions to stress-test.
      </div>
    );
  }

  return (
    <div className="px-4 py-5 space-y-5">
      {/* Scenario selector grid */}
      <div>
        <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-3">
          Select a scenario
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
          {SCENARIOS.map((s) => (
            <ScenarioCard
              key={s.name}
              scenario={s}
              selected={selectedScenario.name === s.name}
              onSelect={() => setSelectedScenario(s)}
            />
          ))}
        </div>
      </div>

      {/* Selected scenario summary */}
      <div className={cn("rounded-xl border p-4 space-y-3", bgCls)}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="text-sm font-semibold text-[var(--text-primary)]">
              {selectedScenario.name}
            </div>
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5">
              {selectedScenario.description}
            </div>
          </div>
          <div className="text-right">
            <div className={cn("text-2xl font-mono font-bold", textCls)}>
              {totalImpact >= 0 ? "+" : ""}{formatCurrency(totalImpact)}
            </div>
            <div className={cn("text-sm font-mono", textCls)}>
              {totalImpactPct >= 0 ? "+" : ""}{totalImpactPct.toFixed(1)}% on portfolio
            </div>
          </div>
        </div>

        {/* Value comparison */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-[var(--bg-elevated)] rounded-lg px-3 py-2.5">
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">
              Current Value
            </div>
            <div className="font-mono text-[var(--text-primary)] text-sm font-semibold mt-0.5">
              {formatCurrency(totalValue)}
            </div>
          </div>
          <div className="bg-[var(--bg-elevated)] rounded-lg px-3 py-2.5">
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">
              Projected Value
            </div>
            <div className={cn("font-mono text-sm font-semibold mt-0.5", textCls)}>
              {formatCurrency(projectedValue)}
            </div>
          </div>
        </div>

        {/* Severity badges */}
        <div className="flex flex-wrap gap-2 text-[10px]">
          {selectedScenario.equityDrop < -20 && (
            <span className="flex items-center gap-1 bg-[#EF4444]/20 text-[#EF4444] border border-[#EF4444]/30 rounded-full px-2 py-0.5 font-semibold">
              <AlertTriangle size={9} /> Severe scenario
            </span>
          )}
          {selectedScenario.equityDrop < 0 && selectedScenario.equityDrop >= -20 && (
            <span className="flex items-center gap-1 bg-[#F59E0B]/20 text-[#F59E0B] border border-[#F59E0B]/30 rounded-full px-2 py-0.5 font-semibold">
              <TrendingDown size={9} /> Moderate drawdown
            </span>
          )}
          {selectedScenario.equityDrop >= 0 && (
            <span className="flex items-center gap-1 bg-[#22C55E]/20 text-[#22C55E] border border-[#22C55E]/30 rounded-full px-2 py-0.5 font-semibold">
              <TrendingUp size={9} /> Positive scenario
            </span>
          )}
        </div>
      </div>

      {/* Per-position breakdown */}
      <div>
        <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-3">
          Position breakdown (worst first)
        </p>
        <div className="bg-[var(--bg-elevated-2)] rounded-xl border border-[var(--border-subtle)] overflow-hidden px-3">
          {impactRows.map((row) => (
            <ImpactRowItem key={row.symbol} row={row} />
          ))}
        </div>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2 text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] rounded-lg px-3 py-2.5 border border-[var(--border-subtle)]">
        <Info size={11} className="shrink-0 mt-0.5" />
        <span>
          This is hypothetical — actual results depend on your specific holdings&apos; beta
          and correlation. A uniform equity drop is applied; real market events affect
          sectors and individual names differently.
        </span>
      </div>
    </div>
  );
}
