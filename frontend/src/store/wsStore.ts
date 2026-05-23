import { create } from "zustand";

type WsStatus = "disconnected" | "connecting" | "connected" | "error";

interface WsState {
  status: WsStatus;
  subscribedSymbols: Set<string>;
  setStatus: (s: WsStatus) => void;
  addSymbols: (symbols: string[]) => void;
  removeSymbols: (symbols: string[]) => void;
}

export const useWsStore = create<WsState>((set) => ({
  status: "disconnected",
  subscribedSymbols: new Set(),
  setStatus: (status) => set({ status }),
  addSymbols: (symbols) =>
    set((s) => {
      const next = new Set(s.subscribedSymbols);
      symbols.forEach((sym) => next.add(sym));
      return { subscribedSymbols: next };
    }),
  removeSymbols: (symbols) =>
    set((s) => {
      const next = new Set(s.subscribedSymbols);
      symbols.forEach((sym) => next.delete(sym));
      return { subscribedSymbols: next };
    }),
}));
