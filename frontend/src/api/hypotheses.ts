import client from "./client";

export type HypothesisStatus = "live" | "testing" | "retired";
export type HypothesisDirection = "long" | "short" | "both";

export interface HypothesisLastTrade {
  side: string;
  price: number | null;
  outcome: "win" | "loss" | "breakeven";
  pnl_dollars: number;
  session: "NY_AM" | "NY_PM" | "LONDON" | "OVERNIGHT" | "ASIA";
  ts: string | null;
}

export interface Hypothesis {
  id: number;
  name: string;
  strategy_id: string;
  direction: HypothesisDirection;
  status: HypothesisStatus;
  regime_preference: string | null;
  factor_exposures: Record<string, number>;
  notes: string | null;
  n_trades: number;
  n_wins: number;
  n_losses: number;
  n_breakeven: number;
  win_rate: number;       // percent
  expected_r: number;     // expectancy in R units (proxy)
  r_multiple: number;
  last_trade: HypothesisLastTrade | null;
  total_trades_all_sides: number;
  last_signal_ts: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SystemEvent {
  id: number;
  event_type: string;
  message: string;
  ts: string | null;
}

export interface HypothesesLiveResponse {
  hypotheses: Hypothesis[];
  factor_exposures: Record<string, number>;
  system_events: SystemEvent[];
  summary: {
    live: number;
    testing: number;
    retired: number;
    lessons: number;
    total: number;
  };
}

export const getLiveHypotheses = (): Promise<HypothesesLiveResponse> =>
  client.get("/hypotheses/live").then((r) => r.data);

export const promoteHypothesis = (id: number): Promise<{ id: number; status: HypothesisStatus }> =>
  client.post(`/hypotheses/${id}/promote`).then((r) => r.data);

export const retireHypothesis = (id: number): Promise<{ id: number; status: HypothesisStatus }> =>
  client.post(`/hypotheses/${id}/retire`).then((r) => r.data);

export const demoteHypothesisToTesting = (id: number): Promise<{ id: number; status: HypothesisStatus }> =>
  client.post(`/hypotheses/${id}/demote-testing`).then((r) => r.data);
