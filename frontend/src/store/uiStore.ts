import { create } from "zustand";

export type AppMode = "simple" | "pro";

interface UiState {
  mode: AppMode;
  toggleMode: () => void;
  setMode: (mode: AppMode) => void;
}

const stored = (localStorage.getItem("bmg_ui_mode") as AppMode) || "simple";

export const useUiStore = create<UiState>((set) => ({
  mode: stored,

  toggleMode: () =>
    set((s) => {
      const next: AppMode = s.mode === "simple" ? "pro" : "simple";
      localStorage.setItem("bmg_ui_mode", next);
      return { mode: next };
    }),

  setMode: (mode) => {
    localStorage.setItem("bmg_ui_mode", mode);
    set({ mode });
  },
}));
