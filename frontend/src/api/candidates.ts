import client from "./client";

export type CandidateState =
  | "CANDIDATE"
  | "BACKTEST_QUEUED"
  | "BACKTEST_DONE"
  | "WFA_QUEUED"
  | "WFA_DONE"
  | "SHADOW_PAPER"
  | "PROMOTED"
  | "RETIRED";

export interface LatestBacktest {
  job_id: string;
  completed_at: string | null;
  net_sharpe: number | null;
  max_drawdown_pct: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  n_trades: number | null;
}

export interface LatestWfa {
  job_id: string;
  completed_at: string | null;
  wfe: number | null;
  pbo: number | null;
  dsr: number | null;
  aggregate_oos_sharpe: number | null;
  n_walks: number | null;
}

export interface Candidate {
  id: number;
  name: string;
  file_path: string;
  asset_class: string | null;
  style: string | null;
  state: CandidateState;
  promoted_at: string | null;
  retired_at: string | null;
  created_at: string;
  updated_at: string;
  latest_backtest: LatestBacktest | null;
  latest_wfa: LatestWfa | null;
  shadow_days: number | null;
  last_failure: string | null;
}

export interface StateHistoryEntry {
  from_state: string | null;
  to_state: string | null;
  reason: string | null;
  triggered_by: string | null;
  created_at: string;
}

export interface CandidateDetail extends Candidate {
  state_history: StateHistoryEntry[];
}

export interface GateResult {
  name: string;
  passes: boolean;
  score: number;
  hard_failures: string[];
  soft_warnings: string[];
  details: Record<string, number>;
}

export const syncCandidates = () =>
  client.post<{ synced: number; new: number; total: number }>("/candidates/sync").then((r) => r.data);

export const listCandidates = () =>
  client.get<{ candidates: Candidate[] }>("/candidates/").then((r) => r.data);

export const getCandidate = (name: string) =>
  client.get<CandidateDetail>(`/candidates/${name}`).then((r) => r.data);

export const runBacktest = (name: string, start_date: string, end_date: string) =>
  client.post<{ job_id: string }>(`/candidates/${name}/run-backtest`, { start_date, end_date }).then((r) => r.data);

export const runWfa = (name: string, is_years: number, oos_years: number, embargo_days: number) =>
  client.post<{ job_id: string }>(`/candidates/${name}/run-wfa`, { is_years, oos_years, embargo_days }).then((r) => r.data);

export const getPromotionEval = (name: string) =>
  client.get<GateResult>(`/candidates/${name}/promotion-eval`).then((r) => r.data);

export const promoteCandidate = (name: string) =>
  client.post<{ ok: boolean; message: string }>(`/candidates/${name}/promote`).then((r) => r.data);

export const retireCandidate = (name: string) =>
  client.post<{ ok: boolean }>(`/candidates/${name}/retire`).then((r) => r.data);

export const runAllBacktests = () =>
  client.post<{ enqueued: number; job_ids: string[] }>("/candidates/run-all-backtests").then((r) => r.data);

export type RunStatus = "queued" | "running" | "done" | "failed";

export interface BacktestRunSummary {
  job_id: string;
  status: RunStatus;
  started_at: string;
  completed_at: string | null;
  start_date: string | null;
  end_date: string | null;
  gross_sharpe: number | null;
  net_sharpe: number | null;
  max_drawdown_pct: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  n_trades: number | null;
  total_cost_pct: number | null;
  error_message: string | null;
}

export interface BacktestRunDetail extends BacktestRunSummary {
  params_json: string | null;
  beta_spy: number | null;
  equity_curve_json: string | null;
  previous_run: { net_sharpe: number | null; max_drawdown_pct: number | null; win_rate: number | null } | null;
}

export interface WfaRunSummary {
  job_id: string;
  status: RunStatus;
  started_at: string;
  completed_at: string | null;
  is_years: number | null;
  oos_years: number | null;
  embargo_days: number | null;
  wfe: number | null;
  pbo: number | null;
  dsr: number | null;
  aggregate_oos_sharpe: number | null;
  aggregate_is_sharpe: number | null;
  n_walks: number | null;
  error_message: string | null;
}

export interface WfaRunDetail extends WfaRunSummary {
  walks_json: string | null;
}

export const getBacktestHistory = (name: string) =>
  client.get<{ runs: BacktestRunSummary[] }>(`/candidates/${name}/backtest-history`).then((r) => r.data);

export const getWfaHistory = (name: string) =>
  client.get<{ runs: WfaRunSummary[] }>(`/candidates/${name}/wfa-history`).then((r) => r.data);

export const getBacktestResult = (name: string, jobId: string) =>
  client.get<BacktestRunDetail>(`/candidates/${name}/backtest/${jobId}`).then((r) => r.data);

export const getWfaResult = (name: string, jobId: string) =>
  client.get<WfaRunDetail>(`/candidates/${name}/wfa/${jobId}`).then((r) => r.data);

export interface CatalogCandidate {
  file: string;
  name: string;
  asset_class: string;
  style: string;
  reference?: string;
  expected_sharpe?: string;
  description?: string;
  promotion_criteria?: string;
}

export const listCandidateCatalog = () =>
  client.get<{ candidates: CatalogCandidate[] }>("/strategy-lab/candidates").then((r) => r.data);

export interface StrategyDescription {
  display_name: string;
  asset_class: string;
  family: string;
  thesis: string;
  entry_rule?: string;
  exit_rule?: string;
  risk?: string;
  cadence?: string;
  academic_source?: string;
  works_best_in?: string;
  avoid_in?: string;
}

export const getStrategyDescription = (name: string) =>
  client.get<StrategyDescription>(`/strategy-lab/description/${name}`).then((r) => r.data);

// ── Strategy chart indicator spec (Scout Commit 1) ──────────────────────────

export type ScoutIndicatorPanel = "price" | "subpanel_1" | "subpanel_2" | "volume";
export type ScoutIndicatorType =
  | "sma" | "ema" | "donchian" | "bollinger" | "rsi" | "macd"
  | "vwap" | "vwap_bands" | "atr" | "bb_bandwidth" | "zscore"
  | "prior_day_high_low" | "opening_range"
  | "ofi" | "delta" | "relative_strength_vs_spy" | "session_markers" | "volume";

export interface ScoutIndicatorSpec {
  type: ScoutIndicatorType;
  params: Record<string, unknown>;
  panel: ScoutIndicatorPanel;
  color: string;
  label: string;
}

export interface ScoutIndicatorsResponse {
  strategy_id: string;
  indicators: ScoutIndicatorSpec[];
  engine_keys: string;
}

export const getStrategyIndicators = (strategyId: string) =>
  client
    .get<ScoutIndicatorsResponse>(`/strategy-lab/indicators/${strategyId}`)
    .then((r) => r.data);

export type TrafficLightStatus = "GREEN" | "YELLOW" | "RED" | "PENDING";

export interface TrafficLight {
  candidate_name: string;
  state?: string;
  status: TrafficLightStatus;
  reason: string;
  shadow_days: number;
  live_sharpe?: number | null;
  backtest_sharpe?: number | null;
  live_max_dd?: number | null;
  backtest_max_dd?: number | null;
}

export const getTrafficLight = (name: string) =>
  client.get<TrafficLight>(`/candidates/${name}/traffic-light`).then((r) => r.data);

export const getAllTrafficLights = () =>
  client.get<{ traffic_lights: TrafficLight[] }>("/candidates/traffic-lights").then((r) => r.data);
