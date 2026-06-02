import client from "./client";

export interface DepositMatchSummary {
  current_match_pct: number;
  pending_match: number;
  credited_ytd: number;
  next_tier_match_pct: number | null;
}

export interface SimulateResult {
  deposit_amount: number;
  match_pct: number;
  match_amount: number;
  annual_match: number;
  lock_days: number;
  total_after_match: number;
}

export const getDepositMatchSummary = () =>
  client.get<DepositMatchSummary>("/deposit-match/summary").then(r => r.data);

export const simulateDepositMatch = (deposit_amount: number, deposit_type = "recurring") =>
  client.post<SimulateResult>("/deposit-match/simulate", { deposit_amount, deposit_type }).then(r => r.data);
