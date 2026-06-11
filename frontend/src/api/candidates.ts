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
  client.post<{ synced: number; total: number }>("/api/candidates/sync").then((r) => r.data);

export const listCandidates = () =>
  client.get<{ candidates: Candidate[] }>("/api/candidates/").then((r) => r.data);

export const getCandidate = (name: string) =>
  client.get<CandidateDetail>(`/api/candidates/${name}`).then((r) => r.data);

export const runBacktest = (name: string, start_date: string, end_date: string) =>
  client.post<{ job_id: string }>(`/api/candidates/${name}/run-backtest`, { start_date, end_date }).then((r) => r.data);

export const runWfa = (name: string, is_years: number, oos_years: number, embargo_days: number) =>
  client.post<{ job_id: string }>(`/api/candidates/${name}/run-wfa`, { is_years, oos_years, embargo_days }).then((r) => r.data);

export const getPromotionEval = (name: string) =>
  client.get<GateResult>(`/api/candidates/${name}/promotion-eval`).then((r) => r.data);

export const promoteCandidate = (name: string) =>
  client.post<{ ok: boolean; message: string }>(`/api/candidates/${name}/promote`).then((r) => r.data);

export const retireCandidate = (name: string) =>
  client.post<{ ok: boolean }>(`/api/candidates/${name}/retire`).then((r) => r.data);

export const runAllBacktests = () =>
  client.post<{ enqueued: number; job_ids: string[] }>("/api/candidates/run-all-backtests").then((r) => r.data);

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
  client.get<{ runs: BacktestRunSummary[] }>(`/api/candidates/${name}/backtest-history`).then((r) => r.data);

export const getWfaHistory = (name: string) =>
  client.get<{ runs: WfaRunSummary[] }>(`/api/candidates/${name}/wfa-history`).then((r) => r.data);

export const getBacktestResult = (name: string, jobId: string) =>
  client.get<BacktestRunDetail>(`/api/candidates/${name}/backtest/${jobId}`).then((r) => r.data);

export const getWfaResult = (name: string, jobId: string) =>
  client.get<WfaRunDetail>(`/api/candidates/${name}/wfa/${jobId}`).then((r) => r.data);

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
  client.get<{ candidates: CatalogCandidate[] }>("/api/strategy-lab/candidates").then((r) => r.data);
