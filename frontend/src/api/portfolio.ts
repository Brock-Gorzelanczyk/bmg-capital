import client from "./client";
import type { Portfolio, Position } from "@/types/portfolio";

export async function getPortfolios(): Promise<Portfolio[]> {
  const { data } = await client.get<{ portfolios: Portfolio[] }>("/portfolio");
  return Array.isArray(data?.portfolios) ? data.portfolios : [];
}

export async function createPortfolio(name: string): Promise<Portfolio> {
  const { data } = await client.post<Portfolio>("/portfolio", { name });
  return data;
}

export async function addPosition(
  portfolioId: number,
  symbol: string,
  shares: number,
  average_cost: number
): Promise<Position> {
  const { data } = await client.post<Position>(`/portfolio/${portfolioId}/positions`, {
    symbol, shares, average_cost,
  });
  return data;
}

export async function deletePosition(portfolioId: number, symbol: string): Promise<void> {
  await client.delete(`/portfolio/${portfolioId}/positions/${symbol}`);
}

export async function getPortfolioSummary(portfolioId: number) {
  const { data } = await client.get(`/portfolio/${portfolioId}/summary`);
  return data;
}

export interface PerformanceContributor {
  symbol: string;
  gain_dollars: number;
  gain_pct: number;
}

export interface PortfolioPerformance {
  portfolio_id: number;
  name: string;
  simple_return_pct: number;
  mwr_annualized_pct: number;
  twr_pct: number;
  twr_note: string;
  total_gain_dollars: number;
  benchmark_ytd: number;
  benchmark_1y: number;
  days_held: number;
  best_contributor: PerformanceContributor | null;
  worst_contributor: PerformanceContributor | null;
  winners: number;
  losers: number;
  concentration_pct: number;
  concentration_warning: boolean;
}

export async function getPortfolioPerformance(portfolioId: number): Promise<PortfolioPerformance> {
  const { data } = await client.get<PortfolioPerformance>(`/portfolio/${portfolioId}/performance`);
  return data;
}

// ── Milestones ─────────────────────────────────────────────────────────────

export interface Milestone {
  id: string;
  label: string;
  description: string;
  achieved: boolean;
  achieved_at: string | null;
  icon_emoji: string;
}

export async function getMilestones(): Promise<Milestone[]> {
  const { data } = await client.get<{ milestones: Milestone[] }>("/portfolio/milestones");
  return Array.isArray(data?.milestones) ? data.milestones : [];
}

// ── Streak ─────────────────────────────────────────────────────────────────

export interface StreakData {
  current_streak_weeks: number;
  longest_streak_weeks: number;
  last_activity_date: string | null;
}

export async function getStreak(): Promise<StreakData> {
  const { data } = await client.get<StreakData>("/portfolio/streak");
  return data;
}

// ── Risk Parity ────────────────────────────────────────────────────────────

export interface RiskParityAllocation {
  sleeve: string;
  label: string;
  ticker: string;
  color: string;
  raw_pct: number;
  normalized_pct: number;
  dollar_amount: number;
}

export interface RiskParityResult {
  regime: string;
  capital: number;
  allocations: RiskParityAllocation[];
  regime_explanation: string;
}

export async function getRiskParity(capital: number, regime: string): Promise<RiskParityResult> {
  const { data } = await client.post<RiskParityResult>("/portfolio/risk-parity", { capital, regime });
  return data;
}
