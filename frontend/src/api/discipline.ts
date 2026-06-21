import client from "./client";

export interface DisciplineGateBreakdown {
  count: number;
  percent: number;
  title: string;
  description: string;
  icon: "warn" | "block";
}

export interface DisciplineByStrategy {
  strategy: string;
  analyzed: number;
  executed: number;
  filtered: number;
  top_filter: string | null;
}

export interface DisciplineByBot {
  bot: string;
  analyzed: number;
  executed: number;
  filtered: number;
}

export interface DisciplineReport {
  date: string;
  window_days: number;
  signals_analyzed: number;
  trades_executed: number;
  signals_filtered: number;
  gates_triggered: number;
  breakdown: {
    regime_mismatch: DisciplineGateBreakdown;
    score_below_threshold: DisciplineGateBreakdown;
    insufficient_confluence: DisciplineGateBreakdown;
    multiple: DisciplineGateBreakdown;
  };
  by_strategy: DisciplineByStrategy[];
  by_bot: DisciplineByBot[];
  edge_quote: string;
}

export interface RecentFilteredItem {
  id: number;
  signal_id: number | null;
  bot_name: string;
  strategy: string | null;
  symbol: string;
  side: string | null;
  composite_score: number;
  composite_threshold: number;
  confluence_factors_passed: number;
  confluence_required: number;
  filter_reason: string | null;
  created_at: string | null;
}

export interface SignalTrace {
  signal_id: number;
  signal: {
    symbol: string;
    side: string;
    confidence: number;
    strategy: string | null;
    ts: string | null;
    entry_price: number | null;
    stop_price: number | null;
    target_price: number | null;
    executed_at: string | null;
  } | null;
  gate: {
    id: number;
    bot_name: string;
    regime_gate_passed: boolean;
    regime_current: string | null;
    regime_required: string | null;
    composite_score: number;
    composite_threshold: number;
    score_gate_passed: boolean;
    confluence_factors_passed: number;
    confluence_required: number;
    confluence_gate_passed: boolean;
    final_decision: string;
    filter_reason: string | null;
    created_at: string | null;
  } | null;
}

export const getDisciplineReport = (days = 1): Promise<DisciplineReport> =>
  client.get(`/admin/discipline/filter-report?days=${days}`).then((r) => r.data);

export const getRecentFiltered = (bot?: string, limit = 50): Promise<{ items: RecentFilteredItem[] }> => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (bot) params.set("bot", bot);
  return client.get(`/admin/discipline/recent-filtered?${params}`).then((r) => r.data);
};

export const getSignalTrace = (signalId: number): Promise<SignalTrace> =>
  client.get(`/admin/discipline/signal-trace/${signalId}`).then((r) => r.data);
