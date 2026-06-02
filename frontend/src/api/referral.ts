import client from "./client";

export interface ReferralCode {
  code: string;
  total_referrals: number;
  total_rewards_earned: number;
  share_url: string;
}

export interface ReferralReward {
  id: number;
  referred_email: string;
  status: string;
  reward_amount: number | null;
  reward_symbol: string | null;
  created_at: string;
}

export interface ReferralStats {
  total_referrals: number;
  pending_rewards: number;
  qualified_rewards: number;
  total_earned: number;
}

export const getMyCode = () => client.get<ReferralCode>("/referral/my-code").then(r => r.data);
export const getRewards = () => client.get<ReferralReward[]>("/referral/rewards").then(r => r.data);
export const getStats = () => client.get<ReferralStats>("/referral/stats").then(r => r.data);
export const validateReferral = (code: string, email: string) =>
  client.post("/referral/validate", { code, email }).then(r => r.data);
