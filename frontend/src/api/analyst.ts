import client from "./client";

export interface WatchlistAnalysis {
  id: number;
  bot_profile_id: number;
  symbol: string;
  ts: string;
  thesis_md: string;
  conviction_score: number | null;
  reasons_to_own: string[];
  risks: string[];
  suggested_hold: string;
  concerns_flag: boolean;
  model_used: string | null;
  cost_usd: number | null;
}

export interface AnalystSummary {
  total_analyzed: number;
  num_high_conviction: number;
  num_flagged: number;
  top_picks: AnalystSummaryItem[];
  concerns: AnalystSummaryItem[];
}

export interface AnalystSummaryItem {
  id: number;
  symbol: string;
  bot_name: string;
  bot_profile_id: number;
  conviction_score: number | null;
  concerns_flag: boolean;
  thesis_preview: string;
  suggested_hold: string;
  ts: string;
}

export interface AnalystDailyRun {
  id: number;
  date: string;
  bot_profile_id: number;
  num_analyzed: number;
  num_high_conviction: number;
  num_flagged_concerns: number;
  total_cost_usd: number;
  completed_at: string | null;
}

export const analyzeSymbol = (
  symbol: string,
  bot_profile_id: number,
  force = false,
): Promise<WatchlistAnalysis> =>
  client.post<WatchlistAnalysis>("/analyst/analyze", { symbol, bot_profile_id, force })
    .then(r => r.data);

export const getWatchlistAnalyses = (bot_profile_id: number): Promise<WatchlistAnalysis[]> =>
  client.get<WatchlistAnalysis[]>(`/analyst/watchlist/${bot_profile_id}`)
    .then(r => Array.isArray(r.data) ? r.data : [])
    .catch(() => []);

export const getSymbolAnalysis = (symbol: string) =>
  client.get<{ symbol: string; per_bot: WatchlistAnalysis[]; consensus: { avg_conviction: number | null; bot_count: number; concerns_flagged: number } }>(
    `/analyst/symbol/${symbol}`
  ).then(r => r.data);

export const refreshBotAnalyses = (bot_profile_id: number): Promise<{ analyzed: number; cost_usd: number }> =>
  client.post<{ analyzed: number; cost_usd: number }>(`/analyst/refresh/${bot_profile_id}`)
    .then(r => r.data);

export const getAnalystSummary = (): Promise<AnalystSummary> =>
  client.get<AnalystSummary>("/analyst/summary")
    .then(r => r.data)
    .catch(() => ({ total_analyzed: 0, num_high_conviction: 0, num_flagged: 0, top_picks: [], concerns: [] }));

export const getAnalystRuns = (bot_profile_id?: number): Promise<AnalystDailyRun[]> =>
  client.get<AnalystDailyRun[]>("/analyst/runs", { params: bot_profile_id ? { bot_profile_id } : undefined })
    .then(r => Array.isArray(r.data) ? r.data : [])
    .catch(() => []);
