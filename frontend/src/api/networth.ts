import api from "./client";

export interface NWAccount {
  id: number;
  name: string;
  account_type: string;
  institution: string;
  balance: number;
  is_liability: boolean;
  currency: string;
  notes: string;
  last_updated: string;
}

export interface NWSummary {
  total_assets: number;
  total_liabilities: number;
  net_worth: number;
  change_30d: number | null;
  by_category: Record<string, { assets: number; liabilities: number }>;
}

export interface NWSnapshot {
  snapshot_date: string;
  net_worth: number;
  total_assets: number;
  total_liabilities: number;
}

export const getNWAccounts = () =>
  api.get("/net-worth/accounts").then((r) => r.data as { accounts: NWAccount[] });

export const createNWAccount = (body: Omit<NWAccount, "id" | "last_updated">) =>
  api.post("/net-worth/accounts", body).then((r) => r.data as NWAccount);

export const updateNWAccount = (id: number, body: Partial<NWAccount>) =>
  api.put(`/net-worth/accounts/${id}`, body).then((r) => r.data as NWAccount);

export const deleteNWAccount = (id: number) =>
  api.delete(`/net-worth/accounts/${id}`).then((r) => r.data);

export const getNWSummary = () =>
  api.get("/net-worth/summary").then((r) => r.data as NWSummary);

export const getNWHistory = () =>
  api.get("/net-worth/history").then((r) => r.data as { history: NWSnapshot[] });

export const takeNWSnapshot = () =>
  api.post("/net-worth/snapshot").then((r) => r.data);
