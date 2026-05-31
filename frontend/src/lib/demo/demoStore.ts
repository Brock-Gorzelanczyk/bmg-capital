import { create } from "zustand";
import type { DemoPersona } from "@/lib/demoMode";
import { LONG_TERM_DATA, ACTIVE_TRADER_DATA, CRYPTO_DATA, BEGINNER_DATA } from "./fixtures";
import type { DemoData } from "./fixtures";

interface DemoState {
  persona: DemoPersona;
  data: DemoData;
  setPersona: (p: DemoPersona) => void;
  resetSession: () => void;
}

const FIXTURE_MAP: Record<DemoPersona, DemoData> = {
  long_term: LONG_TERM_DATA,
  active_trader: ACTIVE_TRADER_DATA,
  crypto: CRYPTO_DATA,
  beginner: BEGINNER_DATA,
};

const stored = (sessionStorage.getItem("bmg_demo_persona") as DemoPersona | null) ?? "long_term";

export const useDemoStore = create<DemoState>((set) => ({
  persona: stored,
  data: FIXTURE_MAP[stored],
  setPersona: (p) => {
    sessionStorage.setItem("bmg_demo_persona", p);
    set({ persona: p, data: FIXTURE_MAP[p] });
  },
  resetSession: () => {
    sessionStorage.removeItem("bmg_demo_persona");
    set({ persona: "long_term", data: LONG_TERM_DATA });
  },
}));
