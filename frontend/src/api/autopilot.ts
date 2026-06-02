import client from "./client";

export interface AutopilotStatus {
  total_actions_today: number;
  categories: {
    name: string;
    enabled: boolean;
    last_action: string | null;
    actions_today: number;
  }[];
  global_paused: boolean;
  guardrail_status: "ok" | "tripped" | "paused";
  health_score: number;
}

export interface AutopilotAction {
  id: number;
  category: string;
  action_type: string;
  asset: string | null;
  params: Record<string, unknown>;
  ai_rationale: string;
  result: "success" | "skipped" | "failed";
  outcome_value: number | null;
  created_at: string;
}

export interface AutopilotPolicy {
  id: number;
  category: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

export interface AutopilotGuardrail {
  daily_loss_limit_pct: number;
  weekly_loss_limit_pct: number;
  max_open_positions: number;
  cash_drain_per_week: number;
  max_position_concentration_pct: number;
  max_subscriptions_cancel_per_week: number;
  global_paused: boolean;
}

export interface AutopilotSummary {
  total_actions: number;
  by_category: Record<string, number>;
  highlights: string[];
}

export const getAutopilotStatus = () =>
  client.get<AutopilotStatus>("/autopilot/status").then(r => r.data);

export const getAutopilotActivity = (params?: { category?: string; page?: number }) =>
  client
    .get<{ items: AutopilotAction[]; total: number; page: number; pages: number } | AutopilotAction[]>(
      "/autopilot/activity",
      { params }
    )
    .then(r => {
      const d = r.data as any;
      return (Array.isArray(d) ? d : (d?.items ?? [])) as AutopilotAction[];
    });

export const getAutopilotPolicies = () =>
  client.get<AutopilotPolicy[]>("/autopilot/policies").then(r => r.data);

export const updatePolicy = (category: string, data: { enabled?: boolean; config?: Record<string, unknown> }) =>
  client.patch<AutopilotPolicy>(`/autopilot/policies/${category}`, data).then(r => r.data);

export const getGuardrails = () =>
  client.get<AutopilotGuardrail>("/autopilot/guardrails").then(r => r.data);

export const updateGuardrails = (data: Partial<AutopilotGuardrail>) =>
  client.patch<AutopilotGuardrail>("/autopilot/guardrails", data).then(r => r.data);

export const pauseAll = () =>
  client.post("/autopilot/pause").then(r => r.data);

export const resumeAll = () =>
  client.post("/autopilot/resume").then(r => r.data);

export const getTodaySummary = () =>
  client.get<AutopilotSummary>("/autopilot/summary/today").then(r => r.data);
