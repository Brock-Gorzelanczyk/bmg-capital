import client from "./client";

export interface AutonomousStatus {
  engine_running: boolean;
  strategies_active: number;
  total_assets_monitored: number;
  open_positions: number;
  last_action_at: string | null;
  last_action_summary: string | null;
  guardrail_status: "ok" | "tripped" | "paused";
  autonomous_paused: boolean;
  market_status: "open" | "pre-market" | "after-hours" | "closed";
}

export interface AutonomousAction {
  id: number;
  lab: string;
  strategy_id: string;
  action_type: string;
  asset: string;
  params: Record<string, unknown>;
  rationale: string;
  result: "success" | "skipped" | "failed";
  outcome_value: number | null;
  created_at: string;
}

export interface AutonomousGuardrail {
  daily_loss_limit_pct: number;
  weekly_loss_limit_pct: number;
  max_consecutive_losses: number;
  max_open_positions: number;
  autonomous_paused: boolean;
  paused_reason: string | null;
}

export interface AutonomousStats {
  signals_fired: number;
  paper_buys: number;
  paper_sells: number;
  stop_hits: number;
  target_hits: number;
  pnl_24h: number;
  best_action: { asset: string; pnl: number } | null;
  worst_action: { asset: string; pnl: number } | null;
  by_lab: Record<string, number>;
}

export interface AutonomousDigest {
  id: number;
  digest_date: string;
  tldr: string;
  highlights: string[];
  strategy_spotlight: string;
  signals_fired: number;
  paper_buys: number;
  paper_sells: number;
  best_action: string | null;
  tomorrow_preview: string;
  market_regime_note: string;
  full_narrative: string;
  portfolio_delta: number;
}

export const getStatus = () =>
  client.get<AutonomousStatus>("/autonomous/status").then(r => r.data);

export const getActionsFeed = () =>
  client.get<any>("/autonomous/actions/feed").then(r => {
    const raw = r.data;
    if (Array.isArray(raw)) return { actions: raw as AutonomousAction[] };
    return raw as { actions: AutonomousAction[] };
  });

export const getStats24h = () =>
  client.get<AutonomousStats>("/autonomous/stats/24h").then(r => r.data);

export const getGuardrails = () =>
  client.get<AutonomousGuardrail>("/autonomous/guardrails").then(r => r.data);

export const pauseAutonomous = (reason?: string) =>
  client.post<AutonomousGuardrail>("/autonomous/pause", { reason }).then(r => r.data);

export const resumeAutonomous = () =>
  client.post<AutonomousGuardrail>("/autonomous/resume").then(r => r.data);

export const updateGuardrails = (data: Partial<AutonomousGuardrail>) =>
  client.put<AutonomousGuardrail>("/autonomous/guardrails", data).then(r => r.data);

export const getLatestDigest = () =>
  client.get<AutonomousDigest | null>("/autonomous/digest/latest").then(r => r.data);

export const getDigestHistory = () =>
  client.get<{ digests: AutonomousDigest[] }>("/autonomous/digest/history").then(r => r.data);
