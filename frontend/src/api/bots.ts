import client from "./client";

export interface BotProfile {
  id: number;
  name: string;           // stock_swing, stock_day, etc.
  description: string;
  asset_class: "stock" | "crypto";
  position_cap: number;
  cadence: string;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  paper_only: true;
  enabled: boolean;
}

export interface BotAllocation {
  id: number;
  profile_id: number;
  capital_pct: number;
  risk_profile: "conservative" | "standard" | "aggressive";
  paper_mode: true;        // always true in v1
  go_live_requested: boolean;
  enabled: boolean;
}

export interface BotListItem {
  profile: BotProfile;
  allocation: BotAllocation | null;
  stats: {
    return_30d_pct: number;
    today_pnl: number;
    open_positions: number;
    total_trades: number;
    win_rate_pct: number;
  };
}

export interface BotSignal {
  id: number;
  ts: string;
  symbol: string;
  side: "buy" | "sell" | "hold";
  confidence: number;
  reason: string;
  strategy: string;
}

export interface BotPosition {
  id: number;
  symbol: string;
  qty: number;
  avg_cost_cents: number;
  opened_at: string;
  is_paper: true;
}

export const getBots = () =>
  client.get<{ bots: BotListItem[] }>("/bots").then((r) => r.data);

export const getBot = (name: string) =>
  client
    .get<{
      profile: BotProfile;
      allocation: BotAllocation | null;
      positions: BotPosition[];
      signals: BotSignal[];
      stats: Record<string, unknown>;
    }>(`/bots/${name}`)
    .then((r) => r.data);

export const allocateBot = (
  name: string,
  data: { capital_pct: number; risk_profile: string; enabled: boolean }
) => client.post<BotAllocation>(`/bots/${name}/allocate`, data).then((r) => r.data);

export const joinWaitlist = (name: string) =>
  client.post(`/bots/waitlist/${name}`).then((r) => r.data);

export const leaveWaitlist = (name: string) =>
  client.delete(`/bots/waitlist/${name}`).then((r) => r.data);

export const getBotBacktest = (
  name: string,
  params: { from: string; to: string; capital: number }
) => client.get(`/bots/${name}/backtest`, { params }).then((r) => r.data);
