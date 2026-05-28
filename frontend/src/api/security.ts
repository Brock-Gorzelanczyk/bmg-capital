import api from "./client";

export interface TokenSecurityResult {
  address: string;
  name: string;
  symbol: string;
  is_open_source: boolean;
  is_proxy: boolean;
  is_mintable: boolean;
  is_honeypot: boolean;
  buy_tax: number;
  sell_tax: number;
  is_blacklisted: boolean;
  is_whitelisted: boolean;
  holder_count: number;
  top_holder_concentration: number;
  lp_locked: boolean;
  lp_lock_pct: number;
  creator_balance_pct: number;
  risk_score: number;
  risk_flags: string[];
  chain_id: string;
  ok: boolean;
  error?: string;
}

export interface WalletApproval {
  token_address: string;
  token_name: string;
  token_symbol: string;
  spender_address: string;
  spender_name: string;
  approved_amount: string;
  risk_level: "safe" | "warning" | "danger";
  is_open_source: boolean;
  last_used?: string;
}

export interface WalletApprovalsResult {
  wallet: string;
  chain_id: string;
  approvals: WalletApproval[];
  total: number;
  high_risk_count: number;
  ok: boolean;
}

export const checkTokenSecurity = (chain: string, address: string): Promise<TokenSecurityResult> =>
  api.get(`/security/token/${chain}/${address}`).then((r) => r.data);

export const checkWalletApprovals = (chain: string, wallet: string): Promise<WalletApprovalsResult> =>
  api.get(`/security/approvals/${chain}/${wallet}`).then((r) => r.data);
