import { create } from "zustand";

export interface ExplainRequest {
  term: string;
  context?: string;
}

interface ExplainState {
  open: boolean;
  request: ExplainRequest | null;
  explain: (term: string, context?: string) => void;
  close: () => void;
}

export const useExplainStore = create<ExplainState>((set) => ({
  open: false,
  request: null,

  explain: (term, context) =>
    set({ open: true, request: { term, context } }),

  close: () =>
    set({ open: false, request: null }),
}));
