import client from "./client";

export type Severity = "ok" | "info" | "warn" | "red";

export interface SuggestedAction {
  severity: Severity;
  label: string;
  detail: string;
}

export interface TuningRow {
  strategy: string;
  analyzed: number;
  executed: number;
  filtered: number;
  by_reason: Record<string, number>;
  reject_rate: number;
  avg_score: number;
  top_filter_reason: string;
  top_filter_count: number;
  status: string;
  action: SuggestedAction;
}

export interface TuningRecommendations {
  window_days: number;
  as_of: string;
  total_strategies_with_activity: number;
  total_analyzed: number;
  total_executed: number;
  by_volume: TuningRow[];
  by_reject_rate: TuningRow[];
  red_flags: TuningRow[];
  volume_bombs: TuningRow[];
  too_loose: TuningRow[];
  thresholds: {
    volume_red_line: number;
    reject_rate_warn: number;
    reject_rate_red: number;
  };
  error?: string;
}

export interface PromotionCandidate {
  id: number;
  name: string;
  strategy_id: string;
  n_trades: number;
  win_rate: number;
  expected_r: number;
  last_trade: { pnl_dollars: number; outcome: string; session: string } | null;
  why?: string;
  why_not?: string;
}

export interface PromotionCandidatesResponse {
  candidates: PromotionCandidate[];
  rejected: PromotionCandidate[];
  rules: {
    min_trades: number;
    min_win_rate: number;
    min_expected_r: number;
  };
  as_of: string;
  error?: string;
}

export const getTuningRecommendations = (days = 1): Promise<TuningRecommendations> =>
  client.get(`/admin/tuning/recommendations?days=${days}`).then((r) => r.data);

export const getPromotionCandidates = (): Promise<PromotionCandidatesResponse> =>
  client.get(`/admin/tuning/promotion-candidates`).then((r) => r.data);
