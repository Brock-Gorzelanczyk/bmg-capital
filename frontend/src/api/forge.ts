import client from "./client";

export interface ForgeBot {
  id: number;
  name: string;
  description: string | null;
  status: string;
  strategies: string[];
  watchlist: string[];
  capital_pct: number;
  created_at: string;
  last_scanned_at: string | null;
  last_fired_at: string | null;
  signal_count: number;
}

export interface ForgeSignal {
  id: number;
  forge_bot_id: number;
  bot_name: string;
  ticker: string;
  strategy_id: string;
  display_name: string;
  side: string;
  confidence: number;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  reason: string | null;
  created_at: string;
}

export interface CreateForgeBotPayload {
  name: string;
  description?: string;
  strategies: string[];
  watchlist: string[];
  capital_pct: number;
}

export const getForgeBots = () =>
  client.get<{ bots: ForgeBot[] }>("/api/forge/bots").then((r) => r.data);

export const createForgeBot = (payload: CreateForgeBotPayload) =>
  client.post<ForgeBot>("/api/forge/bots", payload).then((r) => r.data);

export const updateForgeBot = (id: number, payload: Partial<CreateForgeBotPayload>) =>
  client.put<ForgeBot>(`/api/forge/bots/${id}`, payload).then((r) => r.data);

export const updateForgeBotStatus = (id: number, status: "active" | "paused") =>
  client
    .patch<{ ok: boolean; status: string }>(`/api/forge/bots/${id}/status`, { status })
    .then((r) => r.data);

export const deleteForgeBot = (id: number) =>
  client.delete(`/api/forge/bots/${id}`).then((r) => r.data);

export const getForgeSignals = () =>
  client.get<{ signals: ForgeSignal[] }>("/api/forge/signals").then((r) => r.data);

export const getForgeBotSignals = (id: number) =>
  client.get<{ signals: ForgeSignal[] }>(`/api/forge/bots/${id}/signals`).then((r) => r.data);
