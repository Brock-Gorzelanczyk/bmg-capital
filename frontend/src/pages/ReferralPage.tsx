import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, Check, Gift, Users, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { getMyCode, getRewards, getStats } from "@/api/referral";

export default function ReferralPage() {
  const [copied, setCopied] = useState(false);
  const { data: code } = useQuery({ queryKey: ["referral-code"], queryFn: getMyCode });
  const { data: rewards = [] } = useQuery({ queryKey: ["referral-rewards"], queryFn: getRewards });
  const { data: stats } = useQuery({ queryKey: ["referral-stats"], queryFn: getStats });

  const copy = () => {
    if (!code) return;
    navigator.clipboard.writeText(code.share_url);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-3xl mx-auto px-4 py-10 space-y-8">

        {/* Hero */}
        <div className="rounded-2xl border border-[#4ade80]/30 bg-[#4ade80]/5 p-8 text-center space-y-4">
          <div className="text-5xl">🎁</div>
          <h1 className="text-3xl font-black">Give stock. Get stock.</h1>
          <p className="text-[var(--text-secondary)] max-w-md mx-auto">
            Refer a friend who deposits $20+. You both get a random stock worth $5–$200.
          </p>
          {code && (
            <div className="flex items-center justify-center gap-3 mt-4">
              <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-6 py-3 font-mono text-2xl font-black text-[#4ade80] tracking-widest">
                {code.code}
              </div>
              <button
                onClick={copy}
                className="flex items-center gap-2 px-4 py-3 rounded-xl bg-[#4ade80] text-black font-semibold text-sm hover:bg-[#a3e635] transition-colors"
              >
                {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                {copied ? "Copied!" : "Copy link"}
              </button>
            </div>
          )}
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-3 gap-4">
            {[
              { icon: <Users className="w-4 h-4" />, label: "Referrals", value: stats.total_referrals },
              { icon: <Gift className="w-4 h-4" />, label: "Pending", value: stats.pending_rewards },
              { icon: <TrendingUp className="w-4 h-4" />, label: "Earned", value: `$${stats.total_earned.toFixed(2)}` },
            ].map(({ icon, label, value }) => (
              <div key={label} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-2">
                <div className="flex items-center gap-2 text-[var(--text-secondary)] text-xs font-bold uppercase">{icon}{label}</div>
                <div className="text-2xl font-black font-mono text-[#4ade80]">{value}</div>
              </div>
            ))}
          </div>
        )}

        {/* How it works */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
          <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-secondary)]">How It Works</h2>
          <div className="space-y-3">
            {[
              ["1", "Share your code", "Send your unique referral link to a friend"],
              ["2", "Friend signs up + deposits $20+", "They create an account and make their first deposit"],
              ["3", "You both get a random stock", "Worth $5 to $200 — 1% chance of NVDA at $200"],
            ].map(([num, title, desc]) => (
              <div key={num} className="flex items-start gap-4">
                <div className="w-7 h-7 rounded-full bg-[#4ade80] text-black text-xs font-black flex items-center justify-center shrink-0">{num}</div>
                <div>
                  <div className="font-semibold text-sm text-[var(--text-primary)]">{title}</div>
                  <div className="text-xs text-[var(--text-secondary)]">{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Rewards table */}
        {rewards.length > 0 && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
            <div className="p-4 border-b border-[var(--border-subtle)]">
              <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-secondary)]">Your Rewards</h2>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[var(--text-secondary)] border-b border-[var(--border-subtle)]">
                  <th className="text-left p-4">Referred</th>
                  <th className="text-center p-4">Status</th>
                  <th className="text-right p-4">Reward</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {rewards.map(r => (
                  <tr key={r.id}>
                    <td className="p-4 text-[var(--text-secondary)]">{r.referred_email}</td>
                    <td className="p-4 text-center">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${r.status === "rewarded" ? "bg-green-500/20 text-green-400" : r.status === "qualified" ? "bg-[#4ade80]/20 text-[#4ade80]" : "bg-[var(--bg-base)] text-[var(--text-secondary)]"}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="p-4 text-right font-mono font-bold text-[#4ade80]">
                      {r.reward_amount ? `$${r.reward_amount} ${r.reward_symbol}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-center text-[var(--text-secondary)]">
          $20 minimum deposit required. 60-day claim window. Cap $1,500/year per referrer. 3-day hold before selling.
        </p>
      </div>
    </div>
  );
}
