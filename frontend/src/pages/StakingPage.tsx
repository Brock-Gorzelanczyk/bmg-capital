import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  getStakingAssets,
  getStakingPositions,
  getStakingSummary,
  stakeAsset,
  unstakePosition,
  type StakingAsset,
  type StakingPosition,
} from "@/api/staking";

// ── Formatters ─────────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ── StatusPill ─────────────────────────────────────────────────────────────────

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
    unstaking: "bg-amber-500/15 text-amber-400 border-amber-500/25",
    unstaked: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
  };
  return (
    <span className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border ${colors[status] ?? colors.unstaked}`}>
      {status}
    </span>
  );
}

// ── StakeModal ────────────────────────────────────────────────────────────────

interface StakeModalProps {
  asset: StakingAsset;
  onClose: () => void;
  onSuccess: () => void;
}

function StakeModal({ asset, onClose, onSuccess }: StakeModalProps) {
  const [amount, setAmount] = useState<string>("");
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => stakeAsset(asset.asset, parseFloat(amount)),
    onSuccess: () => {
      toast.success(`Successfully staked ${amount} ${asset.asset}`);
      qc.invalidateQueries({ queryKey: ["staking-positions"] });
      qc.invalidateQueries({ queryKey: ["staking-summary"] });
      onSuccess();
      onClose();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err?.response?.data?.detail ?? "Staking failed");
    },
  });

  const parsed = parseFloat(amount) || 0;
  const annualEarnings = parsed * asset.apy / 100;
  const annualEarningsUsd = annualEarnings * asset.price_usd;
  const isValid = parsed >= asset.min_amount;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-6 w-full max-w-md space-y-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-[var(--text-primary)]">Stake {asset.asset}</h2>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer text-xl leading-none">&times;</button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="bg-[var(--bg-base)] rounded-xl p-3">
            <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider">APY</p>
            <p className="text-[#4ade80] font-bold text-lg">{asset.apy}%</p>
          </div>
          <div className="bg-[var(--bg-base)] rounded-xl p-3">
            <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider">Unstake Period</p>
            <p className="text-[var(--text-primary)] font-semibold">{asset.unstake_days} days</p>
          </div>
          <div className="bg-[var(--bg-base)] rounded-xl p-3 col-span-2">
            <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider">Validator</p>
            <p className="text-[var(--text-primary)] font-semibold">{asset.validator}</p>
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)] mb-1.5">
            Amount to Stake
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              min={asset.min_amount}
              step="any"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              placeholder={`Min: ${asset.min_amount}`}
              className="flex-1 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-xl px-3 py-2.5 text-[var(--text-primary)] text-sm focus:outline-none focus:border-[#4ade80] transition-colors"
            />
            <button
              onClick={() => setAmount(String(asset.min_amount * 10))}
              className="px-3 py-2.5 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-xl text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer transition-colors"
            >
              Max
            </button>
          </div>
          <p className="text-xs text-[var(--text-tertiary)] mt-1">Minimum: {asset.min_amount} {asset.asset}</p>
        </div>

        {parsed > 0 && (
          <div className="bg-[#4ade80]/5 border border-[#4ade80]/20 rounded-xl p-3 space-y-1">
            <p className="text-xs text-[var(--text-tertiary)] font-semibold uppercase tracking-wider">Projected Annual Earnings</p>
            <p className="text-[#4ade80] font-bold text-lg">
              {annualEarnings.toFixed(6)} {asset.asset}
              <span className="text-sm font-normal text-[var(--text-secondary)] ml-2">
                ({fmtUsd(annualEarningsUsd)} / yr)
              </span>
            </p>
          </div>
        )}

        <button
          disabled={!isValid || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="w-full py-3 rounded-xl font-bold text-sm bg-[#4ade80] text-black hover:bg-[#a3e635] disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
        >
          {mutation.isPending ? "Staking…" : `Stake ${asset.asset}`}
        </button>
      </div>
    </div>
  );
}

// ── AssetCard ─────────────────────────────────────────────────────────────────

function AssetCard({ asset, onStake }: { asset: StakingAsset; onStake: (a: StakingAsset) => void }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-lg font-black text-[var(--text-primary)]">{asset.asset}</span>
        <span className="text-xl font-black text-[#4ade80]">{asset.apy}%</span>
      </div>
      <div className="space-y-1 text-sm">
        <div className="flex justify-between text-[var(--text-secondary)]">
          <span>Validator</span>
          <span className="font-semibold text-[var(--text-primary)]">{asset.validator}</span>
        </div>
        <div className="flex justify-between text-[var(--text-secondary)]">
          <span>Min amount</span>
          <span className="font-semibold text-[var(--text-primary)]">{asset.min_amount} {asset.asset}</span>
        </div>
        <div className="flex justify-between text-[var(--text-secondary)]">
          <span>Unstake period</span>
          <span className="font-semibold text-[var(--text-primary)]">{asset.unstake_days} days</span>
        </div>
        <div className="flex justify-between text-[var(--text-secondary)]">
          <span>Price</span>
          <span className="font-semibold text-[var(--text-primary)]">{fmtUsd(asset.price_usd)}</span>
        </div>
      </div>
      <button
        onClick={() => onStake(asset)}
        className="w-full py-2.5 rounded-xl bg-[#4ade80] text-black font-bold text-sm hover:bg-[#a3e635] transition-colors cursor-pointer"
      >
        Stake {asset.asset}
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function StakingPage() {
  const [stakeTarget, setStakeTarget] = useState<StakingAsset | null>(null);
  const qc = useQueryClient();

  const { data: assets = [], isLoading: assetsLoading } = useQuery({
    queryKey: ["staking-assets"],
    queryFn: getStakingAssets,
    staleTime: 60_000,
  });

  const { data: positions = [], isLoading: positionsLoading } = useQuery({
    queryKey: ["staking-positions"],
    queryFn: getStakingPositions,
    staleTime: 30_000,
  });

  const { data: summary } = useQuery({
    queryKey: ["staking-summary"],
    queryFn: getStakingSummary,
    staleTime: 30_000,
  });

  const unstakeMutation = useMutation({
    mutationFn: (id: number) => unstakePosition(id),
    onSuccess: () => {
      toast.success("Unstake requested");
      qc.invalidateQueries({ queryKey: ["staking-positions"] });
      qc.invalidateQueries({ queryKey: ["staking-summary"] });
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err?.response?.data?.detail ?? "Unstake failed");
    },
  });

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">Earn Yield on Your Crypto</h1>
        <p className="text-sm text-[var(--text-tertiary)] mt-1">Native staking powered by institutional validators — Figment, Kiln, and P2P Validator.</p>
      </div>

      {/* Summary stats */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Total Staked", value: fmtUsd(summary.total_staked_usd) },
            { label: "Total Rewards", value: fmtUsd(summary.total_rewards_usd), accent: "text-[#4ade80]" },
            { label: "Avg APY", value: `${summary.avg_apy}%`, accent: "text-[#4ade80]" },
            { label: "Active Positions", value: String(summary.positions_count) },
          ].map(s => (
            <div key={s.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">{s.label}</p>
              <p className={`text-2xl font-bold mt-1 ${s.accent ?? "text-[var(--text-primary)]"}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Asset cards */}
      <div>
        <h2 className="text-base font-semibold text-[var(--text-primary)] mb-3">Available Assets</h2>
        {assetsLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-44 bg-[var(--bg-elevated)] rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {assets.map(asset => (
              <AssetCard key={asset.asset} asset={asset} onStake={setStakeTarget} />
            ))}
          </div>
        )}
      </div>

      {/* Positions table */}
      <div>
        <h2 className="text-base font-semibold text-[var(--text-primary)] mb-3">Your Positions</h2>
        {positionsLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-12 bg-[var(--bg-elevated)] rounded-xl animate-pulse" />
            ))}
          </div>
        ) : positions.length === 0 ? (
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-8 text-center">
            <p className="text-[var(--text-tertiary)] text-sm">No staking positions yet. Choose an asset above to start earning.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-[var(--border-subtle)]">
                  {["Asset", "Amount", "Value (USD)", "Rewards Earned", "Status", ""].map(h => (
                    <th key={h} className="pb-2 pr-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {positions.map((pos: StakingPosition) => (
                  <tr key={pos.id} className="hover:bg-[var(--bg-elevated-2)] transition-colors">
                    <td className="py-3 pr-4 font-bold text-[var(--text-primary)]">{pos.asset}</td>
                    <td className="py-3 pr-4 text-[var(--text-secondary)]">{pos.amount_staked} {pos.asset}</td>
                    <td className="py-3 pr-4 text-[var(--text-primary)]">{fmtUsd(pos.staked_value_usd)}</td>
                    <td className="py-3 pr-4 text-[#4ade80] font-semibold">
                      {pos.rewards_earned.toFixed(6)} ({fmtUsd(pos.rewards_usd)})
                    </td>
                    <td className="py-3 pr-4"><StatusPill status={pos.status} /></td>
                    <td className="py-3">
                      {pos.status === "active" && (
                        <button
                          onClick={() => unstakeMutation.mutate(pos.id)}
                          disabled={unstakeMutation.isPending}
                          className="text-xs px-3 py-1.5 rounded-lg border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-colors cursor-pointer disabled:opacity-40"
                        >
                          Request Unstake
                        </button>
                      )}
                      {pos.status === "unstaking" && pos.estimated_unstake_at && (
                        <span className="text-xs text-[var(--text-tertiary)]">
                          Ready {new Date(pos.estimated_unstake_at).toLocaleDateString()}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Stake modal */}
      {stakeTarget && (
        <StakeModal
          asset={stakeTarget}
          onClose={() => setStakeTarget(null)}
          onSuccess={() => setStakeTarget(null)}
        />
      )}
    </div>
  );
}
