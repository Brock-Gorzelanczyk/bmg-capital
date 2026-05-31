import RiskParityAllocator from "@/components/portfolio/RiskParityAllocator";
import { Scale } from "lucide-react";

export default function RiskParityPage() {
  return (
    <div className="max-w-3xl mx-auto pb-20 md:pb-8 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
          <Scale size={18} className="text-blue-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight font-display">
            Risk Parity Allocator
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
            All-Weather allocation tuned to the current economic regime
          </p>
        </div>
      </div>

      {/* Allocator */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        <RiskParityAllocator />
      </div>
    </div>
  );
}
