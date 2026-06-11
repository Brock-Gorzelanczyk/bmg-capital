import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Shield, Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { exchangeToken } from "@/api/linkedAccounts";

const INSTITUTIONS = [
  { slug: "fidelity", name: "Fidelity", abbr: "FI" },
  { slug: "schwab", name: "Charles Schwab", abbr: "CS" },
  { slug: "robinhood", name: "Robinhood", abbr: "RH" },
  { slug: "vanguard", name: "Vanguard", abbr: "VG" },
  { slug: "etrade", name: "E*Trade", abbr: "ET" },
  { slug: "ibkr", name: "IBKR", abbr: "IB" },
];

interface Props { onClose: () => void; }

export default function ConnectBrokerageModal({ onClose }: Props) {
  const qc = useQueryClient();
  const [step, setStep] = useState<"pick" | "connecting" | "done">("pick");
  const [connected, setConnected] = useState("");

  const mutation = useMutation({
    mutationFn: ({ slug }: { slug: string }) =>
      exchangeToken(`demo-public-${slug}`, slug),
    onSuccess: (_, { slug }) => {
      const inst = INSTITUTIONS.find(i => i.slug === slug);
      setConnected(inst?.name ?? slug);
      setStep("done");
      qc.invalidateQueries({ queryKey: ["linked-brokerages"] });
      qc.invalidateQueries({ queryKey: ["external-holdings"] });
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : "Connection failed";
      toast.error(msg);
      setStep("pick");
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
        <div className="flex items-center justify-between p-5 border-b border-[var(--border-subtle)]">
          <h2 className="font-bold text-[var(--text-primary)]">Connect Your Brokerage</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--bg-base)] text-[var(--text-secondary)]">
            <X className="w-4 h-4" />
          </button>
        </div>

        {step === "pick" && (
          <div className="p-5 space-y-4">
            <div className="flex items-center gap-2 text-xs text-[#4ade80] bg-[#4ade80]/10 rounded-lg px-3 py-2">
              <Shield className="w-3.5 h-3.5 shrink-0" />
              <span>Read-only access — BMG never trades your external accounts</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {INSTITUTIONS.map(inst => (
                <button
                  key={inst.slug}
                  onClick={() => { setStep("connecting"); mutation.mutate({ slug: inst.slug }); }}
                  className="flex items-center gap-3 p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-base)] hover:border-[#4ade80]/40 transition-colors text-left"
                >
                  <div className="w-9 h-9 rounded-full bg-[var(--bg-elevated)] flex items-center justify-center text-xs font-black text-[#4ade80]">
                    {inst.abbr}
                  </div>
                  <span className="text-sm font-medium text-[var(--text-primary)]">{inst.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === "connecting" && (
          <div className="p-12 flex flex-col items-center gap-4">
            <Loader2 className="w-8 h-8 text-[#4ade80] animate-spin" />
            <p className="text-sm text-[var(--text-secondary)]">Connecting securely…</p>
          </div>
        )}

        {step === "done" && (
          <div className="p-12 flex flex-col items-center gap-4">
            <div className="w-14 h-14 rounded-full bg-[#4ade80]/20 flex items-center justify-center">
              <Check className="w-7 h-7 text-[#4ade80]" />
            </div>
            <p className="text-base font-semibold text-[var(--text-primary)]">{connected} connected!</p>
            <p className="text-sm text-[var(--text-secondary)]">Syncing your holdings…</p>
            <button
              onClick={onClose}
              className="px-6 py-2 rounded-lg bg-[#4ade80] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
