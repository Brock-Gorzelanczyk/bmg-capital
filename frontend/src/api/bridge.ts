import api from "./client";

export interface BridgeRoute {
  bridge: string;
  estimated_time_min: number;
  output_amount_usd: number;
  fee_usd: number;
  gas_cost_usd: number;
  total_cost_usd: number;
  steps: string[];
  score: number;
  tags: string[];
}

export interface BridgeQuoteResult {
  from_chain: string;
  to_chain: string;
  token: string;
  amount_usd: number;
  routes: BridgeRoute[];
  ok: boolean;
  error?: string;
}

export interface ChainInfo {
  chainId: number;
  name: string;
  logoURI: string;
  nativeToken: string;
}

export const getBridgeQuote = (
  from_chain: string,
  to_chain: string,
  token: string,
  amount_usd: number,
): Promise<BridgeQuoteResult> =>
  api.get("/bridge/quote", { params: { from_chain, to_chain, token, amount_usd } }).then((r) => r.data);

export const getSupportedChains = (): Promise<{ chains: ChainInfo[] }> =>
  api.get("/bridge/chains").then((r) => r.data);
