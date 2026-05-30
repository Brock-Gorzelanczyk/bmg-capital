import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Shield,
  ShieldAlert,
  ShieldCheck,
  Search,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Lock,
  Unlock,
  ChevronDown,
  Bot,
} from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import api from "@/api/client";

// ── Types ────────────────────────────────────────────────────────────────────

interface TokenSecurityResult {
  token_name: string;
  token_symbol: string;
  contract_address: string;
  risk_score: number; // 0–100
  risk_flags: string[];
  is_open_source: boolean;
  is_mintable: boolean;
  is_honeypot: boolean;
  has_blacklist: boolean;
  buy_tax: number;
  sell_tax: number;
  holders: number;
  top10_hold_pct: number;
  is_lp_locked: boolean;
}

interface ApprovalItem {
  id: string;
  token_name: string;
  token_symbol: string;
  approved_to_name: string;
  approved_to_address: string;
  amount: "unlimited" | number;
  risk: "safe" | "warning" | "danger";
}

interface ApprovalsResult {
  total: number;
  high_risk: number;
  unlimited: number;
  approvals: ApprovalItem[];
}

type Chain = "ethereum" | "bsc" | "polygon" | "arbitrum" | "base" | "optimism" | "solana";

// ── Demo data ────────────────────────────────────────────────────────────────

const DEMO_TOKEN: TokenSecurityResult = {
  token_name:       "Pepe Inu Gold",
  token_symbol:     "PEPIG",
  contract_address: "0x1234...abcd",
  risk_score:       72,
  risk_flags:       ["Sell tax > 10%", "Top 10 wallets hold 64%", "Proxy contract (upgradeable)", "No verified source code"],
  is_open_source:   false,
  is_mintable:      true,
  is_honeypot:      false,
  has_blacklist:    true,
  buy_tax:          5,
  sell_tax:         13,
  holders:          4218,
  top10_hold_pct:   64.2,
  is_lp_locked:     false,
};

const DEMO_APPROVALS: ApprovalsResult = {
  total:     7,
  high_risk: 2,
  unlimited: 5,
  approvals: [
    { id: "1", token_name: "USD Coin",   token_symbol: "USDC", approved_to_name: "Uniswap v3 Router",    approved_to_address: "0xE592427A0AEce92De3Edee1F18E0157C05861564", amount: "unlimited", risk: "safe"    },
    { id: "2", token_name: "Tether",     token_symbol: "USDT", approved_to_name: "1inch v5 Aggregator",  approved_to_address: "0x1111111254EEB25477B68fb85Ed929f73A960582", amount: "unlimited", risk: "safe"    },
    { id: "3", token_name: "Wrapped ETH",token_symbol: "WETH", approved_to_name: "Uniswap v3 Router",    approved_to_address: "0xE592427A0AEce92De3Edee1F18E0157C05861564", amount: 5.0,         risk: "safe"    },
    { id: "4", token_name: "Pepe Inu",   token_symbol: "PEPI", approved_to_name: "Unknown Contract",     approved_to_address: "0xDEAD000000000000000042069420694206942069", amount: "unlimited", risk: "danger"  },
    { id: "5", token_name: "Shiba Inu",  token_symbol: "SHIB", approved_to_name: "ShibaSwap Router",     approved_to_address: "0x03f7724180AA6b939894B5Ca4314783B0b36b329", amount: "unlimited", risk: "warning" },
    { id: "6", token_name: "Chainlink",  token_symbol: "LINK", approved_to_name: "Aave v3 Pool",         approved_to_address: "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2", amount: "unlimited", risk: "safe"    },
    { id: "7", token_name: "MemeCoin X", token_symbol: "MEMX", approved_to_name: "Unverified Proxy",     approved_to_address: "0xC0FFEE0000000000000000000000000000000000", amount: "unlimited", risk: "danger"  },
  ],
};

// ── Constants ────────────────────────────────────────────────────────────────

const CHAINS: { key: Chain; label: string; color: string }[] = [
  { key: "ethereum", label: "Ethereum", color: "#627EEA" },
  { key: "bsc",      label: "BSC",      color: "#F0B90B" },
  { key: "polygon",  label: "Polygon",  color: "#8247E5" },
  { key: "arbitrum", label: "Arbitrum", color: "#12AAFF" },
  { key: "base",     label: "Base",     color: "#0052FF" },
  { key: "optimism", label: "Optimism", color: "#FF0420" },
  { key: "solana",   label: "Solana",   color: "#9945FF" },
];

const CHAIN_IDS: Record<Chain, string> = {
  ethereum: "1",
  bsc:      "56",
  polygon:  "137",
  arbitrum: "42161",
  base:     "8453",
  optimism: "10",
  solana:   "solana",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function riskScoreColor(score: number): string {
  if (score >= 60) return "var(--accent-negative)";
  if (score >= 30) return "#FACC15";
  return "var(--accent-positive)";
}

function riskScoreLabel(score: number): { text: string; cls: string } {
  if (score >= 60) return { text: "High risk — avoid",  cls: "text-[var(--accent-negative)]" };
  if (score >= 30) return { text: "Use caution",         cls: "text-yellow-400"               };
  return                  { text: "Safe to trade",       cls: "text-[var(--accent-positive)]" };
}

function fmtAddress(addr: string): string {
  if (addr.length <= 12) return addr;
  return addr.slice(0, 6) + "..." + addr.slice(-4);
}

function fmtAmount(amount: "unlimited" | number): string {
  if (amount === "unlimited") return "Unlimited";
  return amount.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <div className="relative group inline-flex">
      {children}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2.5 py-1.5 bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] text-[11px] rounded-lg pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-50 max-w-[220px] text-center border border-[var(--border-subtle)] whitespace-normal">
        {text}
      </div>
    </div>
  );
}

// ── Chain selector ────────────────────────────────────────────────────────────

function ChainSelector({ value, onChange }: { value: Chain; onChange: (c: Chain) => void }) {
  const [open, setOpen] = useState(false);
  const selected = CHAINS.find((c) => c.key === value)!;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 h-10 px-3 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg text-sm text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors"
      >
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ background: selected.color }}
        />
        {selected.label}
        <ChevronDown size={14} className="text-[var(--text-tertiary)]" />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-36 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl shadow-xl z-30 overflow-hidden py-1">
          {CHAINS.map((c) => (
            <button
              key={c.key}
              onClick={() => { onChange(c.key); setOpen(false); }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-[var(--bg-elevated-2)] transition-colors",
                value === c.key ? "text-[var(--text-primary)] font-medium" : "text-[var(--text-secondary)]"
              )}
            >
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c.color }} />
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Risk score gauge ──────────────────────────────────────────────────────────

function RiskGauge({ score }: { score: number }) {
  const clampedScore = Math.min(100, Math.max(0, score));
  const circumference = 2 * Math.PI * 34;
  const offset = circumference - (clampedScore / 100) * circumference;
  const color = riskScoreColor(clampedScore);
  const { text, cls } = riskScoreLabel(clampedScore);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-20 h-20">
        <svg viewBox="0 0 76 76" className="w-full h-full -rotate-90">
          <circle cx="38" cy="38" r="34" fill="none" stroke="var(--bg-elevated-2)" strokeWidth="6" />
          <circle
            cx="38" cy="38" r="34"
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold" style={{ color }}>{clampedScore}</span>
        </div>
      </div>
      <span className={cn("text-xs font-semibold text-center", cls)}>{text}</span>
    </div>
  );
}

// ── Bool row ──────────────────────────────────────────────────────────────────

function BoolRow({
  label,
  value,
  dangerWhenTrue = false,
}: {
  label: string;
  value: boolean;
  dangerWhenTrue?: boolean;
}) {
  const positive = dangerWhenTrue ? !value : value;
  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--border-subtle)] last:border-0">
      <span className="text-xs text-[var(--text-secondary)]">{label}</span>
      {positive ? (
        <span className="flex items-center gap-1 text-xs font-semibold text-[var(--accent-positive)]">
          <CheckCircle size={12} /> Yes
        </span>
      ) : (
        <span className="flex items-center gap-1 text-xs font-semibold text-[var(--accent-negative)]">
          <XCircle size={12} /> No
        </span>
      )}
    </div>
  );
}

function DataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--border-subtle)] last:border-0">
      <span className="text-xs text-[var(--text-secondary)]">{label}</span>
      <span className="text-xs font-semibold text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

// ── Token security results ────────────────────────────────────────────────────

function TokenResults({ data }: { data: TokenSecurityResult }) {
  return (
    <div className="space-y-4 mt-4">
      {/* Token identity */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-[var(--text-primary)] text-lg">{data.token_name}</span>
            <span className="text-xs font-semibold bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] px-2 py-0.5 rounded-full">
              {data.token_symbol}
            </span>
          </div>
          <span className="text-[var(--text-tertiary)] text-xs font-mono">{data.contract_address}</span>
        </div>
        <RiskGauge score={data.risk_score} />
      </div>

      {/* Risk flags */}
      {data.risk_flags.length > 0 && (
        <div className="space-y-2">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Risk Flags</span>
          <div className="flex flex-wrap gap-1.5">
            {data.risk_flags.map((flag, i) => (
              <span
                key={i}
                className="flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-full bg-[var(--accent-negative-bg)] text-[var(--accent-negative)] border border-[var(--accent-negative)]/10"
              >
                <AlertTriangle size={10} /> {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Security grid */}
      <div className="bg-[var(--bg-elevated-2)]/40 rounded-xl p-3 space-y-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] block mb-2">Security Grid</span>
        <BoolRow label="Open Source"  value={data.is_open_source} />
        <BoolRow label="Mintable"     value={data.is_mintable} dangerWhenTrue />
        <BoolRow label="Honeypot"     value={data.is_honeypot}  dangerWhenTrue />
        <BoolRow label="Blacklist"    value={data.has_blacklist} dangerWhenTrue />
        <BoolRow label="LP Locked"    value={data.is_lp_locked} />
        <DataRow label="Buy Tax"      value={data.buy_tax + "%"} />
        <DataRow label="Sell Tax"     value={data.sell_tax + "%"} />
        <DataRow label="Holders"      value={data.holders.toLocaleString()} />
        <DataRow label="Top 10 Hold"  value={data.top10_hold_pct.toFixed(1) + "%"} />
      </div>
    </div>
  );
}

// ── Token security panel ──────────────────────────────────────────────────────

function TokenPanel() {
  const [address, setAddress] = useState("");
  const [chain, setChain] = useState<Chain>("ethereum");
  const [result, setResult] = useState<TokenSecurityResult | null>(null);

  const mutation = useMutation({
    mutationFn: (params: { chain_id: string; address: string }) =>
      api.get(`/security/token/${params.chain_id}/${params.address}`).then((r) => r.data as TokenSecurityResult),
    onSuccess: (data) => {
      setResult(data);
    },
    onError: () => {
      // If API isn't available yet, show demo data so the UI is still useful
      toast.info("API not connected — showing demo result");
      setResult(DEMO_TOKEN);
    },
  });

  function handleCheck() {
    const trimmed = address.trim();
    if (!trimmed) {
      toast.error("Enter a contract address first");
      return;
    }
    mutation.mutate({ chain_id: CHAIN_IDS[chain], address: trimmed });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleCheck();
  }

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Shield size={18} className="text-[var(--accent-positive)]" />
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Token Security Checker</h2>
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">Scan any contract for red flags</p>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative)]/15 rounded-lg px-3 py-2.5">
        <AlertTriangle size={13} className="text-[var(--accent-negative)] shrink-0 mt-0.5" />
        <p className="text-[11px] text-[var(--accent-negative)]/80 leading-relaxed">
          Always verify token contracts before buying. Honeypots and scam tokens can drain your wallet.
        </p>
      </div>

      {/* Inputs */}
      <div className="space-y-2">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none" />
          <input
            type="text"
            placeholder="Enter token contract address..."
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full h-10 pl-9 pr-4 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)] transition-colors font-mono"
          />
        </div>
        <div className="flex gap-2">
          <ChainSelector value={chain} onChange={setChain} />
          <button
            onClick={handleCheck}
            disabled={mutation.isPending}
            className="flex-1 h-10 rounded-lg text-sm font-semibold bg-[var(--accent-positive)] text-[#0a0a0a] hover:brightness-110 active:brightness-95 transition-all disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center gap-2"
          >
            {mutation.isPending ? (
              <span className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
            ) : (
              <>
                <ShieldCheck size={15} />
                Check Security
              </>
            )}
          </button>
        </div>
      </div>

      {/* Loading skeleton */}
      {mutation.isPending && (
        <div className="space-y-3 mt-2">
          <Skeleton height={64} className="rounded-xl" />
          <Skeleton height={32} className="rounded-lg w-3/4" />
          <Skeleton height={120} className="rounded-xl" />
        </div>
      )}

      {/* Results */}
      {!mutation.isPending && result && <TokenResults data={result} />}

      {/* Empty state */}
      {!mutation.isPending && !result && (
        <div className="text-center py-8 text-[var(--text-tertiary)]">
          <Shield className="mx-auto mb-3 opacity-20" size={40} />
          <p className="text-sm">Enter a contract address to check its security</p>
        </div>
      )}
    </div>
  );
}

// ── Approval card ─────────────────────────────────────────────────────────────

function ApprovalCard({ approval }: { approval: ApprovalItem }) {
  const riskMap = {
    safe:    { icon: ShieldCheck,  cls: "text-[var(--accent-positive)]",   badge: "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]",    label: "Safe"   },
    warning: { icon: ShieldAlert,  cls: "text-yellow-400",                  badge: "bg-yellow-500/10 text-yellow-400",                               label: "Warning" },
    danger:  { icon: ShieldAlert,  cls: "text-[var(--accent-negative)]",    badge: "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]",   label: "Danger" },
  };
  const { icon: RiskIcon, cls, badge, label } = riskMap[approval.risk];

  return (
    <div className={cn(
      "flex items-center gap-3 p-3 rounded-xl border transition-colors",
      approval.risk === "danger"
        ? "bg-[var(--accent-negative-bg)]/40 border-[var(--accent-negative)]/15"
        : approval.risk === "warning"
        ? "bg-yellow-500/5 border-yellow-500/15"
        : "bg-[var(--bg-elevated-2)]/30 border-[var(--border-subtle)]"
    )}>
      <RiskIcon size={18} className={cn("shrink-0", cls)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-[var(--text-primary)]">{approval.token_symbol}</span>
          <span className="text-xs text-[var(--text-tertiary)]">{approval.token_name}</span>
        </div>
        <div className="flex items-center gap-1.5 mt-0.5 text-xs text-[var(--text-tertiary)]">
          <span>→</span>
          <span className="text-[var(--text-secondary)]">{approval.approved_to_name}</span>
          <span className="font-mono opacity-60">{fmtAddress(approval.approved_to_address)}</span>
        </div>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className={cn(
            "text-[10px] font-semibold px-1.5 py-0.5 rounded-full flex items-center gap-1",
            approval.amount === "unlimited"
              ? "bg-orange-500/10 text-orange-400"
              : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]"
          )}>
            {approval.amount === "unlimited" ? <Unlock size={9} /> : <Lock size={9} />}
            {fmtAmount(approval.amount)}
          </span>
          <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-full", badge)}>
            {label}
          </span>
        </div>
      </div>
      <Tooltip text="Connect wallet to revoke this approval.">
        <button
          disabled
          className="shrink-0 h-7 px-3 rounded-lg text-xs font-semibold bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] opacity-50 cursor-not-allowed"
        >
          Revoke
        </button>
      </Tooltip>
    </div>
  );
}

// ── Wallet approval panel ─────────────────────────────────────────────────────

function ApprovalsPanel() {
  const [wallet, setWallet] = useState("");
  const [chain, setChain] = useState<Chain>("ethereum");
  const [result, setResult] = useState<ApprovalsResult | null>(null);

  const mutation = useMutation({
    mutationFn: (params: { chain_id: string; wallet: string }) =>
      api.get(`/security/approvals/${params.chain_id}/${params.wallet}`).then((r) => r.data as ApprovalsResult),
    onSuccess: (data) => {
      setResult(data);
    },
    onError: () => {
      toast.info("API not connected — showing demo result");
      setResult(DEMO_APPROVALS);
    },
  });

  function handleScan() {
    const trimmed = wallet.trim();
    if (!trimmed) {
      toast.error("Enter a wallet address first");
      return;
    }
    mutation.mutate({ chain_id: CHAIN_IDS[chain], wallet: trimmed });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleScan();
  }

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <ShieldAlert size={18} className="text-yellow-400" />
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Wallet Approval Scanner</h2>
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">Find and review active token approvals</p>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2 bg-yellow-500/8 border border-yellow-500/20 rounded-lg px-3 py-2.5">
        <AlertTriangle size={13} className="text-yellow-400 shrink-0 mt-0.5" />
        <p className="text-[11px] text-yellow-200/70 leading-relaxed">
          Unlimited token approvals are a security risk. Revoke approvals to protocols you no longer use.
        </p>
      </div>

      {/* Inputs */}
      <div className="space-y-2">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none" />
          <input
            type="text"
            placeholder="Enter wallet address 0x..."
            value={wallet}
            onChange={(e) => setWallet(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full h-10 pl-9 pr-4 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)] transition-colors font-mono"
          />
        </div>
        <div className="flex gap-2">
          <ChainSelector value={chain} onChange={setChain} />
          <button
            onClick={handleScan}
            disabled={mutation.isPending}
            className="flex-1 h-10 rounded-lg text-sm font-semibold bg-[var(--bg-elevated-2)] text-[var(--text-primary)] border border-[var(--border-emphasis)] hover:bg-[#52525B] active:brightness-95 transition-all disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center gap-2"
          >
            {mutation.isPending ? (
              <span className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
            ) : (
              <>
                <Search size={15} />
                Scan Approvals
              </>
            )}
          </button>
        </div>
      </div>

      {/* Loading skeleton */}
      {mutation.isPending && (
        <div className="space-y-2 mt-2">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} height={76} className="rounded-xl" />)}
        </div>
      )}

      {/* Results */}
      {!mutation.isPending && result && (
        <div className="space-y-3 mt-1">
          {/* Summary stats */}
          <div className="flex items-center justify-between gap-2 bg-[var(--bg-elevated-2)]/50 rounded-xl px-3 py-2.5">
            <div className="text-sm font-semibold text-[var(--text-primary)]">
              {result.total} active approval{result.total !== 1 ? "s" : ""} found
              {result.high_risk > 0 && (
                <span className="ml-2 text-[var(--accent-negative)] text-xs">({result.high_risk} high-risk)</span>
              )}
            </div>
            <div className="flex gap-3 text-xs text-[var(--text-tertiary)]">
              <span>
                <span className="text-orange-400 font-semibold">{result.unlimited}</span> unlimited
              </span>
              <span>
                <span className="text-[var(--accent-negative)] font-semibold">{result.high_risk}</span> dangerous
              </span>
            </div>
          </div>

          {/* Approval list */}
          <div className="space-y-2">
            {result.approvals.map((a) => (
              <ApprovalCard key={a.id} approval={a} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!mutation.isPending && !result && (
        <div className="text-center py-8 text-[var(--text-tertiary)]">
          <ShieldCheck className="mx-auto mb-3 opacity-20" size={40} />
          <p className="text-sm">Enter a wallet address to scan for approvals</p>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Security() {
  const [aiOpen, setAiOpen] = useState(false);

  return (
    <div className="max-w-6xl mx-auto space-y-5 pb-10">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] font-[var(--font-display)]">Security Suite</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-1">
            Verify token contracts and audit wallet approvals before transacting
          </p>
        </div>
        <button
          onClick={() => setAiOpen(true)}
          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors shrink-0"
        >
          <Bot size={12} /> Ask AI
        </button>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <TokenPanel />
        <ApprovalsPanel />
      </div>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask about Web3 Security"
        context="BMG Capital Security Suite — token contract security checks, wallet approval audits, DeFi risk analysis"
        suggestedQuestions={[
          "What makes a token contract a honeypot?",
          "What are unlimited token approvals and why are they dangerous?",
          "How do I read a token's security score?",
          "What red flags should I look for before buying a new token?",
          "How can I protect my wallet from crypto scams?",
        ]}
      />
    </div>
  );
}
