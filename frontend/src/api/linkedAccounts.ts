import client from "./client";

export interface LinkedBrokerage {
  id: number;
  institution_name: string;
  status: string;
  last_synced_at: string | null;
  holdings_count: number;
}

export interface ExternalHolding {
  symbol: string;
  name: string;
  institution: string;
  quantity: number;
  cost_basis: number | null;
  current_value: number | null;
  security_type: string;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
}

export interface HoldingsResponse {
  holdings: ExternalHolding[];
  total_value: number;
  count: number;
}

export interface InsightsResponse {
  what_to_sell: Array<{ symbol: string; name: string; loss_pct: number; unrealized_loss: number }>;
  tax_loss_candidates: Array<{ symbol: string; loss_pct: number; potential_savings: number }>;
  concentration_risks: Array<{ symbol: string; pct_of_portfolio: number; value: number }>;
  total_external_aum: number;
}

export const getLinkToken = () =>
  client.get<{ link_token: string }>("/linked-accounts/link-token").then(r => r.data);

export const exchangeToken = (public_token: string, institution_slug: string) =>
  client.post<LinkedBrokerage>("/linked-accounts/exchange", { public_token, institution_slug }).then(r => r.data);

export const getBrokerages = () =>
  client.get<LinkedBrokerage[]>("/linked-accounts/").then(r => r.data);

export const deleteBrokerage = (id: number) =>
  client.delete(`/linked-accounts/${id}`);

export const syncBrokerage = (id: number) =>
  client.post(`/linked-accounts/${id}/sync`).then(r => r.data);

export const getAllHoldings = () =>
  client.get<HoldingsResponse>("/linked-accounts/holdings").then(r => r.data);

export const getInsights = () =>
  client.get<InsightsResponse>("/linked-accounts/insights").then(r => r.data);
