import client from "./client";

export interface StakingAsset {
  asset: string;
  apy: number;
  min_amount: number;
  unstake_days: number;
  validator: string;
  price_usd: number;
}

export interface StakingPosition {
  id: number;
  asset: string;
  amount_staked: number;
  apy: number;
  rewards_earned: number;
  rewards_usd: number;
  staked_value_usd: number;
  status: string;
  staked_at: string;
  estimated_unstake_at: string | null;
  validator: string;
}

export interface StakingSummary {
  total_staked_usd: number;
  total_rewards_usd: number;
  avg_apy: number;
  positions_count: number;
}

export const getStakingAssets = () =>
  client.get<StakingAsset[]>("/staking/assets").then(r => r.data);

export const getStakingPositions = () =>
  client.get<StakingPosition[]>("/staking/positions").then(r => r.data);

export const getStakingSummary = () =>
  client.get<StakingSummary>("/staking/summary").then(r => r.data);

export const stakeAsset = (asset: string, amount: number) =>
  client.post("/staking/stake", { asset, amount }).then(r => r.data);

export const unstakePosition = (id: number) =>
  client.post(`/staking/unstake/${id}`).then(r => r.data);
