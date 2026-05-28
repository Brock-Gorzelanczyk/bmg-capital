import api from "./client";

export interface StakingRate {
  protocol: string;
  asset: string;
  apy: number;
  apy_base: number;
  apy_reward?: number;
  tvl_usd: number;
  chain: string;
  staked_token: string;
  url: string;
  logo?: string;
}

export interface LendingRate {
  protocol: string;
  asset: string;
  apy_supply: number;
  apy_borrow: number;
  tvl_usd: number;
  chain: string;
  pool_id: string;
}

export interface YieldOpportunity {
  protocol: string;
  pool_name: string;
  apy: number;
  apy_base: number;
  apy_reward: number;
  tvl_usd: number;
  chain: string;
  category: string;
  exposure: string[];
  il_risk: string;
}

export const getStakingRates = (): Promise<{ rates: StakingRate[] }> =>
  api.get("/defi/staking").then((r) => r.data);

export const getLendingRates = (assets?: string): Promise<{ rates: LendingRate[] }> =>
  api.get("/defi/lending", { params: assets ? { assets } : {} }).then((r) => r.data);

export const getTopYields = (min_tvl?: number, limit?: number): Promise<{ yields: YieldOpportunity[] }> =>
  api.get("/defi/yields", { params: { min_tvl, limit } }).then((r) => r.data);
