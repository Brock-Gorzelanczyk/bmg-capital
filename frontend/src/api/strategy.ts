import client from "./client";

export const getTrades = () =>
  client.get("/strategy/trades").then((r) => r.data);

export const getCandidates = () =>
  client.get("/strategy/candidates").then((r) => r.data);

export const getSummary = () =>
  client.get("/strategy/summary").then((r) => r.data);

export const getLog = (limit = 60) =>
  client.get(`/strategy/log?limit=${limit}`).then((r) => r.data);

export const getEquity = () =>
  client.get("/strategy/equity").then((r) => r.data);

export const getRegime = () =>
  client.get("/strategy/regime").then((r) => r.data);

export const runNow = () =>
  client.post("/strategy/run-now").then((r) => r.data);

export interface PnlDay {
  date: string;
  day_pnl: number;
  day_pnl_pct: number;
  portfolio_value: number;
  new_entries: number;
  exits_today: number;
  open_positions: number;
  trades: Array<{
    event_type: string;
    symbol: string;
    preset_label: string;
    price: number | null;
    pnl_pct: number | null;
    notes: string;
  }>;
}

export const getPnlCalendar = (): Promise<{ days: PnlDay[] }> =>
  client.get("/strategy/pnl-calendar").then((r) => r.data);

export const closeTrade = (id: number) =>
  client.delete(`/strategy/trades/${id}`).then((r) => r.data);

export const getBacktestStatus = () =>
  client.get("/backtest/status").then((r) => r.data);

export const runBacktest = (periodYears = 3) =>
  client.post(`/backtest/run?period_years=${periodYears}`).then((r) => r.data);

export const getBacktestResults = () =>
  client.get("/backtest/results").then((r) => r.data);

export const getBacktestDetail = (strategyKey: string) =>
  client.get(`/backtest/results/${strategyKey}`).then((r) => r.data);
