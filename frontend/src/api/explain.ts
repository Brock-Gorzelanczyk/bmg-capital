import client from "./client";

export interface ExplainResult {
  term: string;
  explanation: string;
  source: "ai" | "glossary" | "fallback";
  mode: "simple" | "detailed";
  related: string[];
}

export const explainTerm = (
  term: string,
  mode: "simple" | "detailed" = "simple",
  context?: string,
): Promise<ExplainResult> =>
  client.post("/explain", { term, mode, context }).then((r) => r.data);

export const getGlossaryTerms = (): Promise<string[]> =>
  client.get("/explain/terms").then((r) => r.data);

// ── Signal explanation ─────────────────────────────────────────────────────────

export type SignalSource = "bot" | "scout" | "forge";

export interface SignalExplainResult {
  signal_id: number;
  source: SignalSource;
  explanation: string;
  model: string;
  cached: boolean;
}

export const explainSignal = (
  signalId: number,
  source: SignalSource,
): Promise<SignalExplainResult> =>
  client
    .post(`/explain/signal/${signalId}?source=${source}`)
    .then((r) => r.data);
