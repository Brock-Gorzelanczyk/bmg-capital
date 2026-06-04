import client from "./client";

export interface DailyRecap {
  id: number;
  recap_date: string; // "YYYY-MM-DD"
  market_summary: {
    spy: number | null;
    qqq: number | null;
    iwm: number | null;
    vix: number | null;
    breadth: "advancing" | "declining" | "mixed" | null;
  } | null;
  strategy_summary: {
    new_entries: number;
    exits: number;
    open_positions: number;
    portfolio_value: number;
    day_pnl: number;
    day_pnl_pct: number;
  } | null;
  top_setups: Array<{ symbol: string; preset: string }> | null;
  narrative: string | null;
  created_at: string;
}

export interface MonitorStatus {
  last_scan_at: string | null;
  stocks_scanned: number;
  signals_today: number;
  market_status: "open" | "pre-market" | "after-hours" | "closed";
}

export async function getRecaps(): Promise<DailyRecap[]> {
  const { data } = await client.get<{ recaps: DailyRecap[] }>("/recap");
  return Array.isArray(data?.recaps) ? data.recaps : [];
}

export async function getLatestRecap(): Promise<DailyRecap | null> {
  const { data } = await client.get<DailyRecap | null>("/recap/latest");
  return data;
}

export async function generateRecap(): Promise<DailyRecap> {
  const { data } = await client.post<DailyRecap>("/recap/generate");
  return data;
}

export async function getMonitorStatus(): Promise<MonitorStatus> {
  const { data } = await client.get<MonitorStatus>("/strategy/monitor-status");
  return data;
}
