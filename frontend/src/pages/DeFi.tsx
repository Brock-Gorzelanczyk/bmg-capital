import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp,
  Layers,
  Zap,
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton, SkeletonCard } from "@/components/ui/Skeleton";
import api from "@/api/client";

// ── Types ───────────────────────────────────────────────────────────────────

interface StakingProtocol {
  id: string;
  name: string;
  chain: "Ethereum" | "Solana";
  asset: string;
  apy: number;
  apy_base: number;
  apy_reward: number;
  tvl: number;
  staked_token: string;
}

interface LendingRate {
  id: string;
  protocol: string;
  asset: string;
  chain: string;
  supply_apy: number;
  borrow_apy: number;
  tvl: number;
}

interface YieldOpportunity {
  id: string;
  protocol: string;
  pool: string;
  apy: number;
  tvl: number;
  chain: string;
  il_risk: "none" | "low" | "medium" | "high";
  category: "Lending" | "Staking" | "DEX LP" | "Yield Aggregator";
}

type Tab = "staking" | "lending" | "yields";
type LendingSort = "protocol" | "asset" | "chain" | "supply_apy" | "borrow_apy" | "tvl";
type SortDir = "asc" | "desc";

// ── Formatters ───────────────────────────────────────────────────────────────

function fmtTvl(n: number): string {
  if (n >= 1e12) return "$" + (n / 1e12).toFixed(2) + "T";
  if (n >= 1e9) return "$" + (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return "$" + (n / 1e6).toFixed(1) + "M";
  return "$" + n.toLocaleString();
}

function fmtApy(n: number): string {
  return n.toFixed(2) + "%";
}

function apyColor(apy: number): string {
  if (apy > 50) return "text-[var(--accent-negative)]";
  if (apy > 15) return "text-yellow-400";
  if (apy >= 5) return "text-[var(--accent-positive)]";
  return "text-[var(--text-secondary)]";
}

// ── Demo / fallback data ─────────────────────────────────────────────────────

const STAKING_FALLBACK: StakingProtocol[] = [
  { id: "lido",        name: "Lido",        chain: "Ethereum", asset: "ETH", apy: 3.92, apy_base: 3.12, apy_reward: 0.80, tvl: 32_400_000_000, staked_token: "stETH"   },
  { id: "rocketpool",  name: "Rocket Pool", chain: "Ethereum", asset: "ETH", apy: 3.61, apy_base: 3.61, apy_reward: 0.00, tvl: 3_800_000_000,  staked_token: "rETH"    },
  { id: "frax",        name: "Frax",        chain: "Ethereum", asset: "ETH", apy: 4.15, apy_base: 3.12, apy_reward: 1.03, tvl: 980_000_000,    staked_token: "frxETH"  },
  { id: "marinade",    name: "Marinade",    chain: "Solana",   asset: "SOL", apy: 7.45, apy_base: 6.80, apy_reward: 0.65, tvl: 1_200_000_000,  staked_token: "mSOL"    },
  { id: "jito",        name: "Jito",        chain: "Solana",   asset: "SOL", apy: 8.12, apy_base: 6.80, apy_reward: 1.32, tvl: 2_600_000_000,  staked_token: "jitoSOL" },
];

const LENDING_FALLBACK: LendingRate[] = [
  { id: "aave-usdc-eth",  protocol: "Aave v3",   asset: "USDC",  chain: "Ethereum", supply_apy: 4.82, borrow_apy: 6.14, tvl: 5_200_000_000 },
  { id: "comp-usdc-eth",  protocol: "Compound",  asset: "USDC",  chain: "Ethereum", supply_apy: 4.61, borrow_apy: 5.93, tvl: 2_100_000_000 },
  { id: "aave-usdt-eth",  protocol: "Aave v3",   asset: "USDT",  chain: "Ethereum", supply_apy: 4.30, borrow_apy: 5.72, tvl: 3_400_000_000 },
  { id: "aave-eth-eth",   protocol: "Aave v3",   asset: "ETH",   chain: "Ethereum", supply_apy: 2.10, borrow_apy: 2.84, tvl: 4_700_000_000 },
  { id: "aave-wbtc-eth",  protocol: "Aave v3",   asset: "WBTC",  chain: "Ethereum", supply_apy: 0.38, borrow_apy: 1.12, tvl: 1_800_000_000 },
  { id: "aave-usdc-arb",  protocol: "Aave v3",   asset: "USDC",  chain: "Arbitrum", supply_apy: 5.14, borrow_apy: 6.52, tvl: 820_000_000   },
  { id: "spark-usdc",     protocol: "Spark",     asset: "USDC",  chain: "Ethereum", supply_apy: 5.00, borrow_apy: 5.50, tvl: 1_100_000_000 },
  { id: "morpho-usdc",    protocol: "Morpho",    asset: "USDC",  chain: "Ethereum", supply_apy: 5.72, borrow_apy: 7.01, tvl: 670_000_000   },
];

const YIELDS_FALLBACK: YieldOpportunity[] = [
  { id: "cvx-eth-steth",   protocol: "Convex",          pool: "ETH/stETH",      apy: 6.21,  tvl: 1_400_000_000, chain: "Ethereum", il_risk: "low",    category: "DEX LP"           },
  { id: "aura-usdc-usdt",  protocol: "Aura Finance",    pool: "USDC/USDT/DAI",  apy: 5.84,  tvl: 540_000_000,   chain: "Ethereum", il_risk: "none",   category: "Yield Aggregator" },
  { id: "pendle-eth",      protocol: "Pendle",          pool: "PT-stETH 2025",  apy: 8.45,  tvl: 320_000_000,   chain: "Ethereum", il_risk: "none",   category: "Yield Aggregator" },
  { id: "jito-sol",        protocol: "Jito",            pool: "jitoSOL",        apy: 8.12,  tvl: 2_600_000_000, chain: "Solana",   il_risk: "none",   category: "Staking"          },
  { id: "orca-sol-usdc",   protocol: "Orca",            pool: "SOL/USDC",       apy: 14.30, tvl: 180_000_000,   chain: "Solana",   il_risk: "medium", category: "DEX LP"           },
  { id: "uni-eth-usdc",    protocol: "Uniswap v3",      pool: "ETH/USDC 0.05%", apy: 9.80,  tvl: 650_000_000,   chain: "Ethereum", il_risk: "medium", category: "DEX LP"           },
  { id: "yearn-usdc",      protocol: "Yearn",           pool: "USDC Vault",     apy: 5.62,  tvl: 420_000_000,   chain: "Ethereum", il_risk: "none",   category: "Yield Aggregator" },
  { id: "crvusd-crveth",   protocol: "Curve",           pool: "crvUSD/ETH",     apy: 18.40, tvl: 90_000_000,    chain: "Ethereum", il_risk: "high",   category: "DEX LP"           },
  { id: "gmx-glp",         protocol: "GMX",             pool: "GLP",            apy: 21.50, tvl: 460_000_000,   chain: "Arbitrum", il_risk: "high",   category: "Yield Aggregator" },
  { id: "raydium-sol-ray", protocol: "Raydium",         pool: "SOL/RAY",        apy: 38.70, tvl: 55_000_000,    chain: "Solana",   il_risk: "high",   category: "DEX LP"           },
];

// ── Tooltip ──────────────────────────────────────────────────────────────────

function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <div className="relative group inline-flex">
      {children}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2.5 py-1.5 bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] text-[11px] rounded-lg whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-50 max-w-[220px] text-center border border-[var(--border-subtle)]">
        {text}
      </div>
    </div>
  );
}

// ── Protocol emoji map ───────────────────────────────────────────────────────

const PROTOCOL_EMOJI: Record<string, string> = {
  Lido:        "🔷",
  "Rocket Pool": "🚀",
  Marinade:    "🌊",
  Jito:        "🌪️",
  Frax:        "❄️",
};

const CHAIN_COLORS: Record<string, string> = {
  Ethereum: "#627EEA",
  Solana:   "#9945FF",
  Arbitrum: "#12AAFF",
  Base:     "#0052FF",
  Polygon:  "#8247E5",
  Optimism: "#FF0420",
  BSC:      "#F0B90B",
};

// ── Stat chip ────────────────────────────────────────────────────────────────

function StatChip({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">{label}</span>
      <span className={cn("text-xl font-bold font-[var(--font-display)]", accent ? "text-[var(--accent-positive)]" : "text-[var(--text-primary)]")}>
        {value}
      </span>
    </div>
  );
}

// ── Sort button ───────────────────────────────────────────────────────────────

function SortButton({
  col,
  active,
  dir,
  onSort,
  children,
}: {
  col: string;
  active: boolean;
  dir: SortDir;
  onSort: (col: string) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={() => onSort(col)}
      className="flex items-center gap-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors text-xs font-semibold uppercase tracking-wider"
    >
      {children}
      {active ? (
        dir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />
      ) : (
        <ChevronsUpDown size={12} className="opacity-40" />
      )}
    </button>
  );
}

// ── IL Risk badge ─────────────────────────────────────────────────────────────

function ILBadge({ risk }: { risk: YieldOpportunity["il_risk"] }) {
  const map = {
    none:   { label: "No IL",     cls: "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]" },
    low:    { label: "Low IL",    cls: "bg-blue-500/10 text-blue-400" },
    medium: { label: "Medium IL", cls: "bg-yellow-500/10 text-yellow-400" },
    high:   { label: "High IL",   cls: "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]" },
  };
  const { label, cls } = map[risk];
  return <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full", cls)}>{label}</span>;
}

function CategoryBadge({ cat }: { cat: YieldOpportunity["category"] }) {
  const map: Record<string, string> = {
    Staking:          "bg-purple-500/10 text-purple-400",
    Lending:          "bg-blue-500/10 text-blue-400",
    "DEX LP":         "bg-yellow-500/10 text-yellow-400",
    "Yield Aggregator": "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]",
  };
  return <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full", map[cat] ?? "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)]")}>{cat}</span>;
}

// ── Staking tab ───────────────────────────────────────────────────────────────

function StakingTab({ protocols, isLoading }: { protocols: StakingProtocol[]; isLoading: boolean }) {
  const bestEth = useMemo(
    () => protocols.filter((p) => p.chain === "Ethereum").sort((a, b) => b.apy - a.apy)[0],
    [protocols]
  );
  const bestSol = useMemo(
    () => protocols.filter((p) => p.chain === "Solana").sort((a, b) => b.apy - a.apy)[0],
    [protocols]
  );
  const totalTvl = useMemo(() => protocols.reduce((s, p) => s + p.tvl, 0), [protocols]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} height={72} className="rounded-xl" />)}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2, 3, 4].map((i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatChip label="Best ETH APY" value={bestEth ? fmtApy(bestEth.apy) : "—"} accent />
        <StatChip label="Best SOL APY" value={bestSol ? fmtApy(bestSol.apy) : "—"} accent />
        <StatChip label="Featured TVL" value={fmtTvl(totalTvl)} />
      </div>

      {/* Protocol cards */}
      {protocols.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-tertiary)]">
          <Layers className="mx-auto mb-3 opacity-30" size={36} />
          <p>No staking data available</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {protocols.map((p) => {
            const emoji = PROTOCOL_EMOJI[p.name] ?? "🔵";
            const chainColor = CHAIN_COLORS[p.chain] ?? "#888";
            return (
              <div
                key={p.id}
                className="relative bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-3 card-glow hover:border-[var(--border-emphasis)] transition-colors"
              >
                {/* Header */}
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{emoji}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-[var(--text-primary)] text-sm">{p.name}</span>
                      <span
                        className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                        style={{ background: chainColor + "22", color: chainColor }}
                      >
                        {p.chain}
                      </span>
                    </div>
                    <span className="text-[var(--text-tertiary)] text-xs">{p.asset} → {p.staked_token}</span>
                  </div>
                </div>

                {/* APY */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">APY</span>
                  <div className="text-3xl font-bold text-[var(--accent-positive)] font-[var(--font-display)] leading-tight">
                    {fmtApy(p.apy)}
                  </div>
                  <div className="flex gap-3 mt-1 text-xs text-[var(--text-tertiary)]">
                    <span>Base <span className="text-[var(--text-secondary)]">{fmtApy(p.apy_base)}</span></span>
                    {p.apy_reward > 0 && (
                      <span>+ Reward <span className="text-[var(--text-secondary)]">{fmtApy(p.apy_reward)}</span></span>
                    )}
                  </div>
                </div>

                {/* TVL */}
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--text-tertiary)]">TVL</span>
                  <span className="text-[var(--text-secondary)] font-medium">{fmtTvl(p.tvl)}</span>
                </div>

                {/* Stake button */}
                <Tooltip text="Wallet integration coming soon — view rates and plan your strategy.">
                  <button
                    disabled
                    className="w-full mt-auto h-8 rounded-lg text-xs font-semibold bg-[var(--accent-positive)] text-[#0a0a0a] opacity-40 cursor-not-allowed"
                  >
                    Stake {p.asset}
                  </button>
                </Tooltip>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Lending tab ───────────────────────────────────────────────────────────────

const LENDING_ASSETS = ["All", "USDC", "USDT", "ETH", "WBTC"];

function LendingTab({ rates, isLoading }: { rates: LendingRate[]; isLoading: boolean }) {
  const [assetFilter, setAssetFilter] = useState("All");
  const [sortCol, setSortCol] = useState<LendingSort>("supply_apy");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(col: string) {
    if (col === sortCol) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col as LendingSort);
      setSortDir("desc");
    }
  }

  const filtered = useMemo(() => {
    let out = assetFilter === "All" ? rates : rates.filter((r) => r.asset === assetFilter);
    out = [...out].sort((a, b) => {
      const va = a[sortCol as keyof LendingRate] as number | string;
      const vb = b[sortCol as keyof LendingRate] as number | string;
      if (typeof va === "number" && typeof vb === "number") {
        return sortDir === "asc" ? va - vb : vb - va;
      }
      return sortDir === "asc"
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va));
    });
    return out;
  }, [rates, assetFilter, sortCol, sortDir]);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton height={36} className="w-80 rounded-lg" />
        <Skeleton height={360} className="rounded-xl" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Asset filter pills */}
      <div className="flex flex-wrap gap-2">
        {LENDING_ASSETS.map((a) => (
          <button
            key={a}
            onClick={() => setAssetFilter(a)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-semibold transition-colors",
              assetFilter === a
                ? "bg-[var(--accent-positive)] text-[#0a0a0a]"
                : "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)]"
            )}
          >
            {a}
          </button>
        ))}
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-tertiary)]">
          <TrendingUp className="mx-auto mb-3 opacity-30" size={36} />
          <p>No lending rates match this filter</p>
        </div>
      ) : (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-subtle)]">
                  {[
                    { key: "protocol", label: "Protocol" },
                    { key: "asset",    label: "Asset"    },
                    { key: "chain",    label: "Chain"    },
                    { key: "supply_apy", label: "Supply APY" },
                    { key: "borrow_apy", label: "Borrow APY" },
                    { key: "tvl",      label: "TVL"      },
                  ].map(({ key, label }) => (
                    <th key={key} className="px-4 py-3 text-left">
                      <SortButton col={key} active={sortCol === key} dir={sortDir} onSort={handleSort}>
                        {label}
                      </SortButton>
                    </th>
                  ))}
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {filtered.map((r) => {
                  const chainColor = CHAIN_COLORS[r.chain] ?? "#888";
                  return (
                    <tr key={r.id} className="hover:bg-[var(--bg-elevated-2)]/40 transition-colors">
                      <td className="px-4 py-3 font-medium text-[var(--text-primary)]">{r.protocol}</td>
                      <td className="px-4 py-3 text-[var(--text-secondary)]">{r.asset}</td>
                      <td className="px-4 py-3">
                        <span
                          className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: chainColor + "22", color: chainColor }}
                        >
                          {r.chain}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-semibold text-[var(--accent-positive)]">{fmtApy(r.supply_apy)}</td>
                      <td className="px-4 py-3 text-[var(--accent-negative)]">{fmtApy(r.borrow_apy)}</td>
                      <td className="px-4 py-3 text-[var(--text-secondary)]">{fmtTvl(r.tvl)}</td>
                      <td className="px-4 py-3">
                        <Tooltip text="Wallet integration coming soon — view rates and plan your strategy.">
                          <button
                            disabled
                            className="h-7 px-3 rounded-lg text-xs font-semibold bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] border border-[var(--border-subtle)] opacity-50 cursor-not-allowed"
                          >
                            Supply
                          </button>
                        </Tooltip>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Top Yields tab ────────────────────────────────────────────────────────────

const YIELD_CATEGORIES = ["All", "Lending", "Staking", "DEX LP", "Yield Aggregator"];
const RISK_FILTERS = [
  { key: "all",    label: "All Risk"  },
  { key: "low",    label: "Low IL"    },
  { key: "medium", label: "Medium IL" },
  { key: "high",   label: "High IL"   },
];

function YieldsTab({ yields, isLoading }: { yields: YieldOpportunity[]; isLoading: boolean }) {
  const [catFilter, setCatFilter] = useState("All");
  const [riskFilter, setRiskFilter] = useState("all");

  const filtered = useMemo(() => {
    let out = yields;
    if (catFilter !== "All") out = out.filter((y) => y.category === catFilter);
    if (riskFilter !== "all") {
      if (riskFilter === "low")    out = out.filter((y) => y.il_risk === "none" || y.il_risk === "low");
      if (riskFilter === "medium") out = out.filter((y) => y.il_risk === "medium");
      if (riskFilter === "high")   out = out.filter((y) => y.il_risk === "high");
    }
    return [...out].sort((a, b) => b.apy - a.apy);
  }, [yields, catFilter, riskFilter]);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton height={36} className="w-full max-w-lg rounded-lg" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2, 3, 4, 5].map((i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-4">
        <div className="flex flex-wrap gap-2">
          {YIELD_CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCatFilter(c)}
              className={cn(
                "px-3 py-1 rounded-full text-xs font-semibold transition-colors",
                catFilter === c
                  ? "bg-[var(--accent-positive)] text-[#0a0a0a]"
                  : "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)]"
              )}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {RISK_FILTERS.map((r) => (
            <button
              key={r.key}
              onClick={() => setRiskFilter(r.key)}
              className={cn(
                "px-3 py-1 rounded-full text-xs font-semibold transition-colors",
                riskFilter === r.key
                  ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] border border-[var(--border-emphasis)]"
                  : "bg-transparent border border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Cards */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-tertiary)]">
          <Zap className="mx-auto mb-3 opacity-30" size={36} />
          <p>No yield opportunities match your filters</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((y) => {
            const chainColor = CHAIN_COLORS[y.chain] ?? "#888";
            return (
              <div
                key={y.id}
                className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-3 hover:border-[var(--border-emphasis)] transition-colors card-glow"
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-[var(--text-primary)]">{y.protocol}</div>
                    <div className="text-xs text-[var(--text-tertiary)] mt-0.5">{y.pool}</div>
                  </div>
                  <span
                    className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0"
                    style={{ background: chainColor + "22", color: chainColor }}
                  >
                    {y.chain}
                  </span>
                </div>

                {/* APY */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">APY</span>
                  <div className={cn("text-3xl font-bold font-[var(--font-display)] leading-tight", apyColor(y.apy))}>
                    {fmtApy(y.apy)}
                  </div>
                  {y.apy > 50 && (
                    <p className="text-[10px] text-[var(--accent-negative)] mt-0.5 flex items-center gap-1">
                      <AlertTriangle size={10} /> Extremely high — significant risk
                    </p>
                  )}
                </div>

                {/* TVL */}
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--text-tertiary)]">TVL</span>
                  <span className="text-[var(--text-secondary)] font-medium">{fmtTvl(y.tvl)}</span>
                </div>

                {/* Badges */}
                <div className="flex flex-wrap gap-1.5">
                  <ILBadge risk={y.il_risk} />
                  <CategoryBadge cat={y.category} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
  { key: "staking", label: "Staking",    icon: Layers    },
  { key: "lending", label: "Lending",    icon: TrendingUp },
  { key: "yields",  label: "Top Yields", icon: Zap       },
];

export default function DeFi() {
  const [activeTab, setActiveTab] = useState<Tab>("staking");

  const stakingQuery = useQuery({
    queryKey: ["defi-staking"],
    queryFn: () => api.get("/defi/staking").then((r) => r.data as StakingProtocol[]),
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });

  const lendingQuery = useQuery({
    queryKey: ["defi-lending"],
    queryFn: () => api.get("/defi/lending").then((r) => r.data as LendingRate[]),
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });

  const yieldsQuery = useQuery({
    queryKey: ["defi-yields"],
    queryFn: () => api.get("/defi/yields").then((r) => r.data as YieldOpportunity[]),
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });

  // Use API data if available, otherwise fall back to demo data
  const stakingData: StakingProtocol[] = stakingQuery.data ?? STAKING_FALLBACK;
  const lendingData: LendingRate[]     = lendingQuery.data ?? LENDING_FALLBACK;
  const yieldsData: YieldOpportunity[] = yieldsQuery.data  ?? YIELDS_FALLBACK;

  const isLoadingStaking = stakingQuery.isLoading;
  const isLoadingLending = lendingQuery.isLoading;
  const isLoadingYields  = yieldsQuery.isLoading;

  return (
    <div className="max-w-6xl mx-auto space-y-5 pb-10">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)] font-[var(--font-display)]">DeFi Dashboard</h1>
        <p className="text-[var(--text-tertiary)] text-sm mt-1">
          Live staking rates, lending markets, and top yield opportunities
        </p>
      </div>

      {/* Disclaimer banner */}
      <div className="flex items-start gap-3 bg-yellow-500/8 border border-yellow-500/20 rounded-xl px-4 py-3">
        <Info size={15} className="text-yellow-400 shrink-0 mt-0.5" />
        <p className="text-yellow-200/80 text-xs leading-relaxed">
          These are live rates from on-chain protocols. Yields change constantly. Not financial advice — always do your own research before depositing funds.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-1 w-fit">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
              activeTab === key
                ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] shadow-sm"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            )}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "staking" && (
        <StakingTab protocols={stakingData} isLoading={isLoadingStaking} />
      )}
      {activeTab === "lending" && (
        <LendingTab rates={lendingData} isLoading={isLoadingLending} />
      )}
      {activeTab === "yields" && (
        <YieldsTab yields={yieldsData} isLoading={isLoadingYields} />
      )}
    </div>
  );
}
