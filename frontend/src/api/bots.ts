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
  client.get<{ bots: any[] }>("/bots").then((r) => {
    const raw: any[] = r.data?.bots ?? [];
    return {
      bots: raw.map((b): BotListItem => ({
        profile: {
          id: b.id,
          name: b.name,
          description: b.description ?? "",
          asset_class: b.asset_class ?? "stock",
          position_cap: b.config?.position_cap ?? 10,
          cadence: b.config?.cadence ?? "daily",
          stop_loss_pct: b.config?.stop_loss_pct ?? null,
          take_profit_pct: b.config?.take_profit_pct ?? null,
          paper_only: true,
          enabled: b.enabled ?? true,
        },
        allocation: b.allocation ?? null,
        stats: {
          return_30d_pct: b.return_30d_pct ?? 0,
          today_pnl: b.today_pnl_usd ?? 0,
          open_positions: Array.isArray(b.open_positions) ? b.open_positions.length : 0,
          total_trades: b.total_trades ?? 0,
          win_rate_pct: b.win_rate_pct ?? 0,
        },
      })),
    };
  });

export const getBot = (name: string) =>
  client.get<any>(`/bots/${name}`).then((r) => {
    const b = r.data;
    return {
      profile: {
        id: b.id,
        name: b.name,
        description: b.description ?? "",
        asset_class: b.asset_class ?? "stock",
        position_cap: b.config?.position_cap ?? 10,
        cadence: b.config?.cadence ?? "daily",
        stop_loss_pct: b.config?.stop_loss_pct ?? null,
        take_profit_pct: b.config?.take_profit_pct ?? null,
        paper_only: true as const,
        enabled: b.enabled ?? true,
      } as BotProfile,
      allocation: b.allocation as BotAllocation | null,
      positions: (b.open_positions ?? []) as BotPosition[],
      signals: (b.recent_signals ?? []) as BotSignal[],
      stats: {
        return_30d_pct: b.return_30d_pct ?? 0,
        today_pnl: b.today_pnl_usd ?? 0,
        open_positions: Array.isArray(b.open_positions) ? b.open_positions.length : 0,
        win_rate_pct: b.win_rate_pct ?? 0,
        equity_curve: b.equity_curve ?? [],
      },
    };
  });

export const allocateBot = (
  name: string,
  data: { capital_pct: number; risk_profile: string; enabled: boolean }
) => client.post<BotAllocation>(`/bots/${name}/allocate`, data).then((r) => r.data);

export const joinWaitlist = (name: string) =>
  client.post(`/bots/waitlist/${name}`).then((r) => r.data);

export const leaveWaitlist = (name: string) =>
  client.delete(`/bots/waitlist/${name}`).then((r) => r.data);

export const migrateLegacyPositions = () =>
  client.post<{ status: string; migrated: Record<string, number>; message: string }>("/bots/migrate-legacy").then((r) => r.data);

export const getBotBacktest = (
  name: string,
  params: { from: string; to: string; capital: number }
) => client.get(`/bots/${name}/backtest`, { params }).then((r) => r.data);
