import { useRef, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, Check } from "lucide-react";
import { useDemoStore } from "@/lib/demo/demoStore";
import type { DemoPersona } from "@/lib/demoMode";

const PERSONA_LABELS: Record<DemoPersona, string> = {
  long_term: "Long-Term Investor",
  active_trader: "Active Trader",
  crypto: "Crypto Enthusiast",
  beginner: "Beginner Learner",
};

const PERSONA_LIST: DemoPersona[] = ["long_term", "active_trader", "crypto", "beginner"];

export default function DemoPill() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const persona = useDemoStore((s) => s.persona);
  const setPersona = useDemoStore((s) => s.setPersona);
  const resetSession = useDemoStore((s) => s.resetSession);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  function handlePersonaSwitch(p: DemoPersona) {
    setPersona(p);
    setOpen(false);
  }

  function handleReset() {
    resetSession();
    setOpen(false);
    window.location.reload();
  }

  function handleExit() {
    setOpen(false);
    navigate("/login");
  }

  return (
    <div ref={ref} className="relative hidden sm:block">
      {/* Pill trigger */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-[#22C55E]/30 bg-[#22C55E]/8 text-[#22C55E] font-medium transition-colors duration-150 hover:bg-[#22C55E]/14 cursor-pointer"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
        <span>DEMO · {PERSONA_LABELS[persona]}</span>
        <ChevronDown size={12} className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-56 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl shadow-2xl z-50 overflow-hidden">
          {/* Persona list */}
          <div className="p-1.5">
            <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider px-2 py-1.5">
              Switch Persona
            </div>
            {PERSONA_LIST.map((p) => (
              <button
                key={p}
                onClick={() => handlePersonaSwitch(p)}
                className="w-full flex items-center justify-between gap-2 px-2 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-base)] transition-colors duration-100 cursor-pointer"
              >
                <span>{PERSONA_LABELS[p]}</span>
                {persona === p && <Check size={13} className="text-[#22C55E] shrink-0" />}
              </button>
            ))}
          </div>

          {/* Divider */}
          <div className="h-px bg-[var(--border-subtle)] mx-1.5" />

          {/* Actions */}
          <div className="p-1.5">
            <button
              onClick={handleReset}
              className="w-full flex items-center px-2 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-base)] transition-colors duration-100 cursor-pointer text-left"
            >
              Reset demo
            </button>
          </div>

          {/* Divider */}
          <div className="h-px bg-[var(--border-subtle)] mx-1.5" />

          <div className="p-1.5">
            <button
              onClick={handleExit}
              className="w-full flex items-center px-2 py-2 rounded-lg text-sm text-[var(--text-tertiary)] hover:text-[#EF4444] hover:bg-[#EF4444]/6 transition-colors duration-100 cursor-pointer text-left"
            >
              Exit demo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
