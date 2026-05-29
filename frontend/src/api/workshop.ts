import client from "./client";
import type { Drawing } from "@/types/chart";

export interface ChartAnalysis {
  id: number;
  symbol: string;
  timeframe: string;
  name: string;
  thesis: string;
  drawings: Drawing[];
  ai_analysis: AIAnalysis | Record<string, never>;
  created_at: string;
  updated_at: string;
}

export interface AIAnalysis {
  thesis_summary: string;
  supporting: string[];
  counterarguments: string[];
  invalidation: string;
  suggested_additions: string[];
  setup_quality: "strong" | "moderate" | "weak";
  setup_quality_reason: string;
}

export const listAnalyses = (symbol?: string): Promise<ChartAnalysis[]> =>
  client.get("/api/workshop/analyses", { params: symbol ? { symbol } : {} }).then((r) => r.data);

export const createAnalysis = (body: {
  symbol: string;
  timeframe: string;
  name: string;
  thesis?: string;
  drawings?: Drawing[];
}): Promise<{ id: number; name: string; symbol: string; timeframe: string }> =>
  client.post("/api/workshop/analyses", body).then((r) => r.data);

export const updateAnalysis = (id: number, body: {
  name?: string;
  thesis?: string;
  drawings?: Drawing[];
}): Promise<{ ok: boolean }> =>
  client.put(`/api/workshop/analyses/${id}`, body).then((r) => r.data);

export const deleteAnalysis = (id: number): Promise<{ ok: boolean }> =>
  client.delete(`/api/workshop/analyses/${id}`).then((r) => r.data);

export const analyzeChart = (body: {
  symbol: string;
  timeframe: string;
  current_price?: number;
  drawings: Drawing[];
  indicators: string[];
  thesis?: string;
}): Promise<{ analysis: AIAnalysis }> =>
  client.post("/api/workshop/analyze", body).then((r) => r.data);

export const analyzeAndSave = (analysisId: number, body: {
  symbol: string;
  timeframe: string;
  current_price?: number;
  drawings: Drawing[];
  indicators: string[];
  thesis?: string;
}): Promise<{ analysis: AIAnalysis }> =>
  client.post(`/api/workshop/analyses/${analysisId}/analyze`, body).then((r) => r.data);
