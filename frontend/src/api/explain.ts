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
