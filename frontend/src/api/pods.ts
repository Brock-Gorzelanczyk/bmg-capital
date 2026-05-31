import api from "./client";

export interface Pod {
  id: number;
  user_id: number;
  name: string;
  description: string | null;
  color: string;
  emoji: string;
  allocated_capital: number;
  drawdown_stop_pct: number;
  is_active: boolean;
  is_derisked: boolean;
  derisked_at: string | null;
  created_at: string | null;
}

export interface PodPosition {
  id: number;
  pod_id: number;
  symbol: string;
  shares: number;
  average_cost: number;
  cost_basis: number;
  current_price: number | null;
  market_value: number | null;
  gain_pct: number | null;
  opened_at: string | null;
}

export interface PodSummary extends Pod {
  total_value: number;
  total_cost: number;
  gain_pct: number;
  drawdown_pct: number;
  at_risk: boolean;
  positions: PodPosition[];
}

export interface DeriskRecommendation {
  symbol: string;
  current_shares: number;
  sell_shares: number;
  keep_shares: number;
  action: string;
}

export interface DeriskResult {
  pod: Pod;
  message: string;
  recommendations: DeriskRecommendation[];
}

export const getPods = () =>
  api.get("/pods").then((r) => r.data as { pods: Pod[] });

export const createPod = (body: Omit<Pod, "id" | "user_id" | "is_active" | "is_derisked" | "derisked_at" | "created_at">) =>
  api.post("/pods", body).then((r) => r.data as Pod);

export const updatePod = (id: number, body: Partial<Pod>) =>
  api.put(`/pods/${id}`, body).then((r) => r.data as Pod);

export const deletePod = (id: number) =>
  api.delete(`/pods/${id}`).then((r) => r.data as { ok: boolean });

export const getPodSummary = (id: number) =>
  api.get(`/pods/${id}/summary`).then((r) => r.data as PodSummary);

export const getPodPositions = (id: number) =>
  api.get(`/pods/${id}/positions`).then((r) => r.data as { positions: PodPosition[] });

export const addPodPosition = (
  id: number,
  body: { symbol: string; shares: number; average_cost: number }
) => api.post(`/pods/${id}/positions`, body).then((r) => r.data);

export const removePodPosition = (id: number, symbol: string) =>
  api.delete(`/pods/${id}/positions/${symbol}`).then((r) => r.data as { ok: boolean });

export const deriskPod = (id: number) =>
  api.post(`/pods/${id}/derisk`).then((r) => r.data as DeriskResult);
