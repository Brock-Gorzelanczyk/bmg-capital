import client from "./client";

export interface UserRule {
  id: number;
  user_id: number;
  name: string;
  description: string | null;
  is_active: boolean;
  trigger_type: string | null;
  trigger_symbol: string | null;
  trigger_value: number | null;
  trigger_regime: string | null;
  action_type: string | null;
  action_symbol: string | null;
  action_amount: number | null;
  action_unit: string;
  last_triggered: string | null;
  trigger_count: number;
  created_at: string | null;
}

export interface RuleCreate {
  name: string;
  description?: string;
  is_active?: boolean;
  trigger_type?: string;
  trigger_symbol?: string;
  trigger_value?: number;
  trigger_regime?: string;
  action_type?: string;
  action_symbol?: string;
  action_amount?: number;
  action_unit?: string;
}

export interface TestResult {
  would_trigger: boolean;
  reason: string;
}

export const getRules = async (): Promise<UserRule[]> => {
  const res = await client.get("/api/rules");
  return Array.isArray(res.data) ? res.data : [];
};

export const createRule = async (data: RuleCreate): Promise<UserRule> => {
  const res = await client.post("/api/rules", data);
  return res.data;
};

export const updateRule = async (id: number, data: Partial<RuleCreate>): Promise<UserRule> => {
  const res = await client.put(`/api/rules/${id}`, data);
  return res.data;
};

export const deleteRule = async (id: number): Promise<void> => {
  await client.delete(`/api/rules/${id}`);
};

export const testRule = async (id: number): Promise<TestResult> => {
  const res = await client.post(`/api/rules/${id}/test`);
  return res.data;
};

// ---------------------------------------------------------------------------
// Transfer suggestions
// ---------------------------------------------------------------------------

export interface TransferSuggestion {
  type: "sweep_excess" | "rebalance_drift" | "start_investing" | string;
  description: string;
  amount: number;
}

export interface TransferSuggestionsResponse {
  suggestions: TransferSuggestion[];
}

export const getTransferSuggestions = async (): Promise<TransferSuggestionsResponse> => {
  const res = await client.get<TransferSuggestionsResponse>("/api/transfers/suggestions");
  return res.data;
};
