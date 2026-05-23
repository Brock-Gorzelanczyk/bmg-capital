export interface Position {
  id: number;
  portfolio_id: number;
  symbol: string;
  shares: number;
  average_cost: number;
  cost_basis: number;
  opened_at: string;
  current_price?: number;
  market_value?: number;
  unrealized_gain?: number;
  unrealized_gain_pct?: number;
}

export interface Portfolio {
  id: number;
  name: string;
  created_at: string;
  positions: Position[];
}
