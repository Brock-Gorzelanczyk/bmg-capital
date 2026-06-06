import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

export interface TickerData {
  symbol: string;
  price: number;
  prevClose: number;
  changePct: number;
  changeAbs: number;
}

async function fetchSp500Snapshot(): Promise<TickerData[]> {
  const r = await client.get<{ tickers: TickerData[] }>("/api/market/sp500-snapshot");
  return r.data?.tickers ?? [];
}

export function useTickerTape() {
  const { data } = useQuery({
    queryKey: ["sp500-tape"],
    queryFn: fetchSp500Snapshot,
    staleTime: 5 * 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
  return data ?? [];
}
