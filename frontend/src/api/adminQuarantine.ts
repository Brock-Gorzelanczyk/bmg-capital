import client from "./client";

export interface CrossSleeveQuarantineRow {
  id: number;
  position_id: number;
  bot_id: string;
  user_id: number;
  declared_asset_class: string;
  actual_symbol: string;
  actual_asset_class: string;
  detected_at: string;
  action: string;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface CrossSleeveQuarantineResponse {
  as_of: string;
  unresolved_count: number;
  rows: CrossSleeveQuarantineRow[];
}

export const getCrossSleeveQuarantine = (limit = 10): Promise<CrossSleeveQuarantineResponse> =>
  client.get<CrossSleeveQuarantineResponse>("/admin/cross-sleeve-quarantine", { params: { limit } })
        .then((r) => r.data);
