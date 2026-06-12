import { useQuery } from "@tanstack/react-query";
import { getPortfolioSnapshot, type PortfolioSnapshot, EMPTY_SNAPSHOT } from "@/api/portfolioSnapshot";

export const SNAPSHOT_KEY = ["portfolio-snapshot"] as const;

export function usePortfolioSnapshot() {
  const { data, isLoading, error } = useQuery({
    queryKey: SNAPSHOT_KEY,
    queryFn: getPortfolioSnapshot,
    staleTime: 30_000,
    retry: 1,
  });
  return {
    snap: data ?? EMPTY_SNAPSHOT,
    isLoading,
    error,
  };
}
