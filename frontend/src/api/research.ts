import client from "./client";

export interface Fundamentals {
  symbol: string;
  name: string;
  sector?: string;
  industry?: string;
  description?: string;
  country?: string;
  employees?: number;
  website?: string;
  market_cap?: number;
  enterprise_value?: number;
  pe_ratio?: number;
  forward_pe?: number;
  peg_ratio?: number;
  price_to_book?: number;
  price_to_sales?: number;
  eps?: number;
  forward_eps?: number;
  dividend_yield?: number;
  dividend_rate?: number;
  payout_ratio?: number;
  beta?: number;
  week_52_high?: number;
  week_52_low?: number;
  day_high?: number;
  day_low?: number;
  current_price?: number;
  previous_close?: number;
  open_price?: number;
  volume?: number;
  avg_volume?: number;
  revenue?: number;
  gross_profit?: number;
  net_income?: number;
  ebitda?: number;
  profit_margins?: number;
  operating_margins?: number;
  return_on_equity?: number;
  return_on_assets?: number;
  debt_to_equity?: number;
  current_ratio?: number;
  free_cashflow?: number;
  total_cash?: number;
  total_debt?: number;
  short_ratio?: number;
  short_percent?: number;
  analyst_target?: number;
  analyst_low?: number;
  analyst_high?: number;
  recommendation?: string;
  num_analysts?: number;
  financials?: {
    quarterly: Array<{
      period: string;
      revenue: number | null;
      gross_profit: number | null;
      operating_income: number | null;
      net_income: number | null;
      eps: number | null;
    }>;
  } | null;
  bmg_score?: {
    score: number;
    grade: string;
    components: Record<string, number>;
  } | null;
}

export async function getFundamentals(symbol: string): Promise<Fundamentals> {
  const { data } = await client.get<Fundamentals>(`/research/${symbol}`);
  return data;
}
