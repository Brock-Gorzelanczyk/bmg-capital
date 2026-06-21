import client from "./client";

export type BrainNodeType =
  | "session"
  | "trade"
  | "signal"
  | "strategy"
  | "symbol"
  | "lesson";

export interface BrainNode {
  id: string;
  type: BrainNodeType;
  label: string;
  size: number;          // 4-40
  color: string;         // hex like "#22c55e"
  meta: Record<string, any>;
}

export interface BrainEdge {
  source: string;        // node id
  target: string;        // node id
  type: string;          // "contains" | "from_signal" | "uses_strategy" | "on_symbol" | etc
}

export interface BrainGraphPayload {
  nodes: BrainNode[];
  edges: BrainEdge[];
  stats: {
    node_count: number;
    edge_count: number;
    generated_at?: string;   // ISO
    error?: string;          // only on backend failure
  };
}

export const getBrainGraph = (days: number = 30): Promise<BrainGraphPayload> =>
  client.get(`/brain/graph?days=${days}`).then((r) => r.data);
