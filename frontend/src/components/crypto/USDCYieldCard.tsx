import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

interface USDCBalance { usdc_balance: number; apy: number; daily_yield: number; ytd_earned: number; }
interface USDCRates { current_user_apy: number; fdic_note: string; partner: string; }

export default function USDCYieldCard() {
  const { data: balance } = useQuery<USDCBalance>({
    queryKey: ["usdc-balance"],
    queryFn: () => client.get("/crypto/usdc-yield/balance").then(r => r.data),
    staleTime: 30_000,
  });
  const { data: rates } = useQuery<USDCRates>({
    queryKey: ["usdc-rates"],
    queryFn: () => client.get("/crypto/usdc-yield/rates").then(r => r.data),
    staleTime: 60_000,
  });

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold uppercase tracking-widest text-[var(--text-secondary)]">USDC Yield</span>
        <span className="text-xs font-semibold text-[#84cc16]">{rates?.current_user_apy ?? 4.0}% APY</span>
      </div>
      <div className="text-3xl font-black font-mono" style={{ color: "#84cc16" }}>
        ${(balance?.usdc_balance ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </div>
      <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
        <span>Daily: +${(balance?.daily_yield ?? 0).toFixed(4)}</span>
        <span>YTD: +${(balance?.ytd_earned ?? 0).toFixed(2)}</span>
      </div>
      <div className="text-xs text-[var(--text-secondary)] leading-relaxed border-t border-[var(--border-subtle)] pt-2">
        {rates?.fdic_note ?? "Not FDIC insured. USDC backed 1:1 by USD via Circle."}
      </div>
    </div>
  );
}
