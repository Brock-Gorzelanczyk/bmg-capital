import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ExternalLink, X, FileText, TrendingUp, Users, DollarSign, Shield, Phone } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const DATA_ROOM_DOCS = [
  {
    icon: FileText,
    name: "Pitch Deck",
    description: "Full investor presentation, May 2026 seed round",
  },
  {
    icon: TrendingUp,
    name: "Financial Model",
    description: "3-year projections, unit economics, LTV/CAC analysis",
  },
  {
    icon: Users,
    name: "Cap Table",
    description: "Current ownership structure and option pool",
  },
  {
    icon: FileText,
    name: "Term Sheet",
    description: "Proposed seed terms — SAFE, $6M cap, 20% discount",
  },
  {
    icon: Shield,
    name: "Due Diligence Pack",
    description: "Incorporation docs, IP assignments, user agreements",
  },
  {
    icon: Phone,
    name: "Reference Calls",
    description: "5 beta users available for investor calls",
  },
];

const METRICS = [
  { value: "$2.4B", label: "TAM" },
  { value: "47K", label: "Beta Users" },
  { value: "4.2×", label: "Avg Portfolio Alpha" },
];

export default function PitchPage() {
  const navigate = useNavigate();
  const [demoMode, setDemoMode] = useState(false);
  const [dataRoomOpen, setDataRoomOpen] = useState(false);

  const tagline = demoMode
    ? "Live demo — all data is real-time"
    : "The intelligent trading platform for serious investors";

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ background: "var(--bg-base, #18181B)", color: "var(--text-primary, #FAFAFA)" }}
    >
      {/* Top bar */}
      <header className="flex items-center justify-between px-8 pt-8 pb-0">
        <div className="flex items-center gap-3">
          {/* Logo */}
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center font-black text-xl"
            style={{ background: "#4ade80", color: "#0a0a0f" }}
          >
            B
          </div>
          <span className="text-lg font-bold tracking-tight" style={{ color: "var(--text-primary, #FAFAFA)" }}>
            BMG Capital
          </span>
        </div>

        {/* Demo mode toggle */}
        <button
          onClick={() => setDemoMode((v) => !v)}
          className={cn(
            "flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-medium transition-all duration-200",
            demoMode
              ? "border-[#4ade80] text-[#4ade80]"
              : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
          )}
        >
          {demoMode && (
            <span
              className="w-2 h-2 rounded-full bg-[#4ade80] animate-pulse"
              style={{ boxShadow: "0 0 6px #4ade80" }}
            />
          )}
          Demo Mode
        </button>
      </header>

      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center px-8 py-16 text-center max-w-4xl mx-auto w-full">
        {/* Logo mark */}
        <div
          className="w-24 h-24 rounded-full flex items-center justify-center font-black text-5xl mb-8 shadow-2xl"
          style={{
            background: "#4ade80",
            color: "#0a0a0f",
            boxShadow: "0 0 80px rgba(74,222,128,0.25)",
          }}
        >
          B
        </div>

        {/* Wordmark */}
        <h1 className="text-6xl md:text-7xl font-black tracking-tight mb-4" style={{ color: "var(--text-primary, #FAFAFA)" }}>
          BMG Capital
        </h1>

        {/* Tagline */}
        <div className="flex items-center justify-center gap-3 mb-10">
          {demoMode && (
            <span
              className="px-2 py-0.5 rounded text-xs font-bold tracking-widest animate-pulse"
              style={{ background: "rgba(74,222,128,0.15)", color: "#4ade80", border: "1px solid #4ade80" }}
            >
              LIVE
            </span>
          )}
          <p className="text-xl md:text-2xl font-medium" style={{ color: "var(--text-secondary, #A1A1AA)" }}>
            {tagline}
          </p>
        </div>

        {/* CTAs */}
        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <button
            onClick={() => navigate("/pitch/deck")}
            className="px-8 py-4 rounded-xl font-bold text-base transition-all duration-200 hover:scale-105"
            style={{
              background: "#4ade80",
              color: "#0a0a0f",
              boxShadow: "0 0 32px rgba(74,222,128,0.3)",
            }}
          >
            Start Pitch Demo →
          </button>
          <button
            onClick={() => setDataRoomOpen(true)}
            className="px-8 py-4 rounded-xl font-bold text-base border transition-all duration-200 hover:scale-105 flex items-center gap-2"
            style={{
              border: "1px solid var(--border-emphasis, #52525B)",
              color: "var(--text-primary, #FAFAFA)",
              background: "var(--bg-elevated, #27272A)",
            }}
          >
            Open Data Room
            <ExternalLink size={16} />
          </button>
        </div>

        {/* Metric cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-2xl">
          {METRICS.map((m) => (
            <div
              key={m.label}
              className="rounded-2xl p-6 text-center border"
              style={{
                background: "var(--bg-elevated, #27272A)",
                border: "1px solid var(--border-subtle, #3F3F46)",
              }}
            >
              <div
                className="text-3xl font-black mb-1"
                style={{ color: "#4ade80" }}
              >
                {m.value}
              </div>
              <div className="text-sm font-medium" style={{ color: "var(--text-secondary, #A1A1AA)" }}>
                {m.label}
              </div>
            </div>
          ))}
        </div>
      </main>

      {/* Footer disclaimer */}
      <footer className="text-center py-6 px-8">
        <p className="text-xs" style={{ color: "var(--text-tertiary, #71717A)" }}>
          Confidential — For Authorized Investors Only. Not an offer to sell securities.
        </p>
      </footer>

      {/* Data Room Modal */}
      {dataRoomOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.75)", backdropFilter: "blur(8px)" }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setDataRoomOpen(false);
          }}
        >
          <div
            className="w-full max-w-lg rounded-2xl p-6 shadow-2xl"
            style={{
              background: "var(--bg-elevated, #27272A)",
              border: "1px solid var(--border-emphasis, #52525B)",
            }}
          >
            {/* Modal header */}
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold" style={{ color: "var(--text-primary, #FAFAFA)" }}>
                Investor Data Room
              </h2>
              <button
                onClick={() => setDataRoomOpen(false)}
                className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors hover:bg-zinc-700"
                style={{ color: "var(--text-secondary, #A1A1AA)" }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Document list */}
            <div className="space-y-3 mb-6">
              {DATA_ROOM_DOCS.map((doc) => {
                const Icon = doc.icon;
                return (
                  <div
                    key={doc.name}
                    className="flex items-center gap-4 p-4 rounded-xl border"
                    style={{
                      background: "var(--bg-elevated-2, #3F3F46)",
                      border: "1px solid var(--border-subtle, #52525B)",
                    }}
                  >
                    <div
                      className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: "rgba(74,222,128,0.1)", color: "#4ade80" }}
                    >
                      <Icon size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold" style={{ color: "var(--text-primary, #FAFAFA)" }}>
                        {doc.name}
                      </p>
                      <p className="text-xs truncate" style={{ color: "var(--text-secondary, #A1A1AA)" }}>
                        {doc.description}
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        toast.success("Access request sent", {
                          description: `You'll receive access to "${doc.name}" within 24 hours.`,
                        });
                      }}
                      className="flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all hover:scale-105"
                      style={{ background: "#4ade80", color: "#0a0a0f" }}
                    >
                      Request Access
                    </button>
                  </div>
                );
              })}
            </div>

            {/* NDA note */}
            <p className="text-xs text-center" style={{ color: "var(--text-tertiary, #71717A)" }}>
              All documents NDA-protected. Access granted within 24h.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
