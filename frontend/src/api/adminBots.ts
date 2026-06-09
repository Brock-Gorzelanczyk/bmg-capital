import client from "./client";

export interface BotListItem {
  bot_id: string;
  category: "quant" | "crypto" | "stocks" | "options";
  enabled: boolean;
  paused: boolean;
  open_positions: number;
}

export interface BotOverride {
  key: string;
  value: unknown;
  updated_at: string;
  updated_by: string;
}

export interface BotConfig {
  bot_id: string;
  config: Record<string, unknown>;
  overrides: BotOverride[];
}

export interface AuditEntry {
  id: number;
  key: string;
  old_value: unknown;
  new_value: unknown;
  changed_at: string;
  changed_by: string;
}

// ── List ─────────────────────────────────────────────────────────────────────

export const listBots = (): Promise<{ bots: BotListItem[] }> =>
  client.get("/admin/bots").then(r => r.data);

// ── Config ───────────────────────────────────────────────────────────────────

export const getBotConfig = (botId: string): Promise<BotConfig> =>
  client.get(`/admin/bots/${botId}/config`).then(r => r.data);

export const patchBotConfig = (
  botId: string,
  key: string,
  value: unknown,
): Promise<{ ok: boolean }> =>
  client.patch(`/admin/bots/${botId}/config`, { key, value }).then(r => r.data);

export const deleteBotConfig = (
  botId: string,
  key: string,
): Promise<{ ok: boolean }> =>
  client.delete(`/admin/bots/${botId}/config/${key}`).then(r => r.data);

// ── Enable / Disable / Pause / Resume ────────────────────────────────────────

export const enableBot  = (botId: string) => client.post(`/admin/bots/${botId}/enable`).then(r => r.data);
export const disableBot = (botId: string) => client.post(`/admin/bots/${botId}/disable`).then(r => r.data);
export const pauseBot   = (botId: string) => client.post(`/admin/bots/${botId}/pause`).then(r => r.data);
export const resumeBot  = (botId: string) => client.post(`/admin/bots/${botId}/resume`).then(r => r.data);

// ── Watchlist ─────────────────────────────────────────────────────────────────

export const getBotWatchlist = (botId: string): Promise<{ symbols: string[] }> =>
  client.get(`/admin/bots/${botId}/watchlist`).then(r => r.data);

export const addWatchlistSymbol = (botId: string, symbol: string) =>
  client.post(`/admin/bots/${botId}/watchlist`, { symbol }).then(r => r.data);

export const removeWatchlistSymbol = (botId: string, symbol: string) =>
  client.delete(`/admin/bots/${botId}/watchlist/${encodeURIComponent(symbol)}`).then(r => r.data);

// ── Audit ─────────────────────────────────────────────────────────────────────

export const getBotAudit = (botId: string): Promise<{ entries: AuditEntry[] }> =>
  client.get(`/admin/bots/${botId}/audit`).then(r => r.data);
