import client from "./client";

export interface TLHOpportunity {
  symbol: string;
  portfolio_id: number;
  shares: number;
  average_cost: number;
  current_price: number;
  market_value: number;
  cost_basis: number;
  loss_dollars: number;
  loss_pct: number;
  wash_sale_risk: boolean;
  suggested_replacement: string | null;
  replacement_symbols: string[];
  harvest_instructions: string;
}

export interface TLHOpportunitiesResponse {
  opportunities: TLHOpportunity[];
  total_harvestable_loss: number;
  estimated_tax_savings_24pct: number;
  year_to_date_harvested: number;
}

export interface TLHSummary {
  ytd_harvested_dollars: number;
  ytd_tax_saved_est: number;
  wash_sale_warnings: number;
}

export async function getTLHOpportunities(): Promise<TLHOpportunitiesResponse> {
  const { data } = await client.get<TLHOpportunitiesResponse>("/api/tlh/opportunities");
  return data;
}

export async function getTLHSummary(): Promise<TLHSummary> {
  const { data } = await client.get<TLHSummary>("/api/tlh/summary");
  return data;
}
