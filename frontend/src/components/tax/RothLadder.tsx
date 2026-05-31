import { useState, useMemo } from "react";
import { AlertTriangle, Info } from "lucide-react";

// ── 2024 Tax Brackets ──────────────────────────────────────────────────────────

const BRACKETS_SINGLE = [
  { limit: 11600, rate: 0.10, label: "10%" },
  { limit: 47150, rate: 0.12, label: "12%" },
  { limit: 100525, rate: 0.22, label: "22%" },
  { limit: 191950, rate: 0.24, label: "24%" },
  { limit: 243725, rate: 0.32, label: "32%" },
  { limit: 609350, rate: 0.35, label: "35%" },
  { limit: Infinity, rate: 0.37, label: "37%" },
];

const BRACKETS_MFJ = [
  { limit: 23200, rate: 0.10, label: "10%" },
  { limit: 94300, rate: 0.12, label: "12%" },
  { limit: 201050, rate: 0.22, label: "22%" },
  { limit: 383900, rate: 0.24, label: "24%" },
  { limit: 487450, rate: 0.32, label: "32%" },
  { limit: 731200, rate: 0.35, label: "35%" },
  { limit: Infinity, rate: 0.37, label: "37%" },
];

// IRMAA cliff (2024) for MFJ
const IRMAA_MFJ = 206000;
const IRMAA_SINGLE = 103000;

function getBrackets(filingStatus: string) {
  return filingStatus === "mfj" ? BRACKETS_MFJ : BRACKETS_SINGLE;
}

function currentBracketIndex(income: number, filingStatus: string): number {
  const brackets = getBrackets(filingStatus);
  for (let i = 0; i < brackets.length; i++) {
    if (income <= brackets[i].limit) return i;
  }
  return brackets.length - 1;
}

function bracketHeadroom(income: number, filingStatus: string): number {
  const brackets = getBrackets(filingStatus);
  const idx = currentBracketIndex(income, filingStatus);
  return Math.max(0, brackets[idx].limit - income);
}

// Rough calculation: how much tax does converting `amount` cost at current income level?
function conversionTaxCost(income: number, amount: number, filingStatus: string): number {
  const brackets = getBrackets(filingStatus);
  let remaining = amount;
  let taxCost = 0;
  let currentIncome = income;

  for (const bracket of brackets) {
    if (remaining <= 0) break;
    const room = Math.max(0, bracket.limit - currentIncome);
    const taxed = Math.min(remaining, room);
    taxCost += taxed * bracket.rate;
    currentIncome += taxed;
    remaining -= taxed;
  }

  return Math.round(taxCost);
}

interface LadderRow {
  year: number;
  age: number;
  convertAmount: number;
  taxCost: number;
  bracketUsed: string;
  runningBalance: number;
  irmaWarning: boolean;
}

function computeLadder(
  currentAge: number,
  traditionalBalance: number,
  annualIncome: number,
  filingStatus: string,
  years: number
): LadderRow[] {
  const rows: LadderRow[] = [];
  let balance = traditionalBalance;
  const baseYear = new Date().getFullYear();

  for (let i = 0; i < years; i++) {
    const headroom = bracketHeadroom(annualIncome, filingStatus);
    // Convert up to the top of the current bracket (but at most 25% of balance per year)
    const maxConvert = Math.min(headroom, balance * 0.25);
    const convertAmount = Math.round(Math.max(0, maxConvert));

    const bracketIdx = currentBracketIndex(annualIncome, filingStatus);
    const bracketLabel = getBrackets(filingStatus)[bracketIdx].label;

    const taxCost = conversionTaxCost(annualIncome, convertAmount, filingStatus);

    const totalIncomeWithConversion = annualIncome + convertAmount;
    const irmaLimit = filingStatus === "mfj" ? IRMAA_MFJ : IRMAA_SINGLE;
    const irmaWarning = totalIncomeWithConversion > irmaLimit;

    balance = Math.max(0, balance - convertAmount);

    rows.push({
      year: baseYear + i,
      age: currentAge + i,
      convertAmount,
      taxCost,
      bracketUsed: bracketLabel,
      runningBalance: Math.round(balance),
      irmaWarning,
    });
  }

  return rows;
}

function lifetimeSavingsEstimate(rows: LadderRow[]): number {
  // Simplified: if they convert now at ~22% instead of withdrawing at ~24% in retirement
  // savings = total converted * (0.24 - 0.22) * assumed_growth_factor
  const totalConverted = rows.reduce((sum, r) => sum + r.convertAmount, 0);
  return Math.round(totalConverted * 0.02 * 1.4); // 1.4 = rough growth factor over retirement horizon
}

function fmt(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default function RothLadder() {
  const [age, setAge] = useState(45);
  const [balance, setBalance] = useState(500000);
  const [income, setIncome] = useState(150000);
  const [filingStatus, setFilingStatus] = useState("mfj");
  const [retirementAge, setRetirementAge] = useState(65);

  const yearsToShow = Math.min(5, Math.max(1, retirementAge - age));
  const rows = useMemo(
    () => computeLadder(age, balance, income, filingStatus, yearsToShow),
    [age, balance, income, filingStatus, yearsToShow]
  );
  const savings = useMemo(() => lifetimeSavingsEstimate(rows), [rows]);

  const hasIrmaWarning = rows.some((r) => r.irmaWarning);
  const totalConverted = rows.reduce((s, r) => s + r.convertAmount, 0);
  const totalTaxCost = rows.reduce((s, r) => s + r.taxCost, 0);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-1">Roth Conversion Ladder</h2>
        <p className="text-sm text-[var(--text-tertiary)]">
          Find your optimal multi-year Roth conversion strategy — convert up to the top of your current bracket each year.
        </p>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Current Age */}
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)]">
          <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Current Age
          </label>
          <div className="mt-2 flex items-center gap-3">
            <input
              type="range"
              min={30}
              max={70}
              value={age}
              onChange={(e) => setAge(Number(e.target.value))}
              className="flex-1 accent-[var(--accent-positive)]"
            />
            <span className="text-xl font-bold text-[var(--text-primary)] w-10 text-right">{age}</span>
          </div>
        </div>

        {/* Traditional IRA/401k Balance */}
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)]">
          <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Traditional IRA / 401k Balance
          </label>
          <div className="mt-2">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]">$</span>
              <input
                type="number"
                value={balance}
                onChange={(e) => setBalance(Math.max(0, Number(e.target.value)))}
                className="w-full pl-6 pr-3 py-2 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent-positive)]"
                min={0}
                step={10000}
              />
            </div>
          </div>
        </div>

        {/* Annual Income */}
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)]">
          <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Annual Income (W2 + Other)
          </label>
          <div className="mt-2">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]">$</span>
              <input
                type="number"
                value={income}
                onChange={(e) => setIncome(Math.max(0, Number(e.target.value)))}
                className="w-full pl-6 pr-3 py-2 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent-positive)]"
                min={0}
                step={5000}
              />
            </div>
          </div>
        </div>

        {/* Filing Status */}
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)]">
          <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Filing Status
          </label>
          <div className="mt-2">
            <select
              value={filingStatus}
              onChange={(e) => setFilingStatus(e.target.value)}
              className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent-positive)]"
            >
              <option value="mfj">Married Filing Jointly</option>
              <option value="single">Single</option>
            </select>
          </div>
        </div>

        {/* Target Retirement Age */}
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)]">
          <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Target Retirement Age
          </label>
          <div className="mt-2 flex items-center gap-3">
            <input
              type="range"
              min={Math.max(age + 1, 50)}
              max={80}
              value={retirementAge}
              onChange={(e) => setRetirementAge(Number(e.target.value))}
              className="flex-1 accent-[var(--accent-positive)]"
            />
            <span className="text-xl font-bold text-[var(--text-primary)] w-10 text-right">{retirementAge}</span>
          </div>
        </div>

        {/* Current Bracket */}
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)]">
          <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Current Marginal Bracket
          </label>
          <div className="mt-2 text-2xl font-bold text-[var(--accent-positive)]">
            {getBrackets(filingStatus)[currentBracketIndex(income, filingStatus)].label}
          </div>
          <p className="text-xs text-[var(--text-tertiary)] mt-1">
            Headroom to top of bracket:{" "}
            <span className="text-[var(--text-secondary)] font-semibold">
              {fmt(bracketHeadroom(income, filingStatus))}
            </span>
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)] text-center">
          <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Total to Convert</p>
          <p className="text-2xl font-bold text-[var(--text-primary)] mt-1">{fmt(totalConverted)}</p>
          <p className="text-xs text-[var(--text-tertiary)]">over {yearsToShow} years</p>
        </div>
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)] text-center">
          <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Tax Cost Now</p>
          <p className="text-2xl font-bold text-amber-400 mt-1">{fmt(totalTaxCost)}</p>
          <p className="text-xs text-[var(--text-tertiary)]">to convert within bracket</p>
        </div>
        <div className="bg-[var(--bg-elevated)] rounded-xl p-4 border border-[var(--border-subtle)] text-center">
          <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Est. Lifetime Savings</p>
          <p className="text-2xl font-bold text-emerald-400 mt-1">{fmt(savings)}</p>
          <p className="text-xs text-[var(--text-tertiary)]">vs. taxable withdrawal at 24%</p>
        </div>
      </div>

      {/* IRMAA Warning */}
      {hasIrmaWarning && (
        <div className="flex items-start gap-3 bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
          <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-400">Medicare IRMAA Cliff Warning</p>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              One or more years, your income + Roth conversion would exceed the Medicare IRMAA threshold (
              {filingStatus === "mfj" ? "$206,000" : "$103,000"} for {filingStatus === "mfj" ? "MFJ" : "single"}).
              This triggers higher Medicare Part B/D premiums. Consider reducing the conversion amount to stay below the cliff.
            </p>
          </div>
        </div>
      )}

      {/* Year-by-Year Table */}
      <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Year-by-Year Conversion Plan</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-subtle)]">
                {["Year", "Age", "Convert Amount", "Tax Cost", "Bracket", "Remaining Balance", ""].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.year} className="border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-elevated-2)] transition-colors">
                  <td className="px-4 py-3 text-[var(--text-primary)] font-medium">{row.year}</td>
                  <td className="px-4 py-3 text-[var(--text-secondary)]">{row.age}</td>
                  <td className="px-4 py-3 text-emerald-400 font-semibold">{fmt(row.convertAmount)}</td>
                  <td className="px-4 py-3 text-amber-400">{fmt(row.taxCost)}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs font-bold bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] px-2 py-0.5 rounded-full">
                      {row.bracketUsed}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[var(--text-secondary)]">{fmt(row.runningBalance)}</td>
                  <td className="px-4 py-3">
                    {row.irmaWarning && (
                      <span title="Medicare IRMAA cliff risk">
                        <AlertTriangle size={14} className="text-amber-400" />
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Reminder note */}
      <div className="flex items-start gap-3 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
        <Info size={16} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />
        <p className="text-xs text-[var(--text-tertiary)]">
          <span className="text-[var(--text-secondary)] font-semibold">Reminder:</span> Roth conversions must be completed by{" "}
          <span className="text-[var(--text-secondary)] font-semibold">December 31</span> of each tax year. This calculator
          uses 2024 bracket limits and does not account for state taxes, future legislative changes, or RMD impacts.
          Consult a qualified tax advisor before executing any conversion strategy.
        </p>
      </div>
    </div>
  );
}
