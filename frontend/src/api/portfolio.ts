import client from "./client";
import type { Portfolio, Position } from "@/types/portfolio";

export async function getPortfolios(): Promise<Portfolio[]> {
  const { data } = await client.get<{ portfolios: Portfolio[] }>("/portfolio");
  return data.portfolios;
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
