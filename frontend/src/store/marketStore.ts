import { create } from "zustand";
import type { Quote, LiveBar } from "@/types/market";

interface MarketState {
  quotes: Record<string, Quote>;
  liveBars: Record<string, LiveBar>;
  updateQuote: (symbol: string, quote: Quote) => void;
  updateBar: (symbol: string, bar: LiveBar) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
  quotes: {},
  liveBars: {},
  updateQuote: (symbol, quote) =>
    set((s) => ({ quotes: { ...s.quotes, [symbol]: quote } })),
  updateBar: (symbol, bar) =>
    set((s) => ({ liveBars: { ...s.liveBars, [symbol]: bar } })),
}));
