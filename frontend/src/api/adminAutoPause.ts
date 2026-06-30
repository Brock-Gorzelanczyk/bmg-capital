import client from "./client";

export interface AutoPausedRow {
  bot_id: string;
  paused_reason: string;
  paused_at: string;
  user_id: number;
}

export interface AutoPausedResponse {
  ok: boolean;
  as_of: string;
  rows: AutoPausedRow[];
}

export const getAutoPausedBots = (): Promise<AutoPausedResponse> =>
  client.get<AutoPausedResponse>("/admin/auto-pause/list").then((r) => r.data);
