import client from "./client";

export interface CongressTrade {
  id: number;
  member_name: string;
  party: string | null;
  chamber: string | null;   // 'S' or 'H'
  state: string | null;
  ticker: string | null;
  asset_description: string | null;
  transaction_type: string;  // 'purchase', 'sale', 'exchange'
  amount_range: string | null;
  amount_lower_cents: number | null;
  amount_upper_cents: number | null;
  transaction_date: string;
  disclosure_date: string | null;
  disclosure_delay_days: number | null;
  source: string;
  source_url: string;
}

export interface CongressResponse {
  trades: CongressTrade[];
  total: number;
  last_updated_at: string | null;
  source: string;
  source_note: string;
}

export interface SmartMoneySummary {
  congress_buys_30d: number;
  congress_sells_30d: number;
  insider_buys_30d: number;
  insider_sells_30d: number;
  most_traded_ticker_30d: string | null;
  most_traded_ticker_count: number;
  last_updated: {
    congress: string | null;
    insider: string | null;
    hedge_funds: string | null;
  };
}

export interface CongressParams {
  ticker?: string;
  party?: string;
  chamber?: string;
  days?: number;
  limit?: number;
  offset?: number;
  min_amount?: number;
}

export const getCongressTrades = (params: CongressParams = {}): Promise<CongressResponse> => {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v != null) searchParams.set(k, String(v));
  });
  const qs = searchParams.toString();
  return client.get(`/smart-money/congress${qs ? `?${qs}` : ""}`).then((r) => r.data);
};

export const getSmartMoneySummary = (): Promise<SmartMoneySummary> =>
  client.get("/smart-money/summary").then((r) => r.data);

export const triggerCongressRefresh = (days_back = 30): Promise<{ status: string; days_back: number }> =>
  client.post(`/smart-money/refresh/congress?days_back=${days_back}`).then((r) => r.data);
