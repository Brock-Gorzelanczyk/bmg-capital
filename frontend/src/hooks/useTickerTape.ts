import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

export interface TickerData {
  symbol: string;
  price: number;
  prevClose: number;
  changePct: number;
  changeAbs: number;
}

interface StockRow {
  symbol: string;
  price: number | null;
  change_1d: number | null;
}

async function fetchTickerTapeData(): Promise<TickerData[]> {
  const r = await client.get<{ stocks: StockRow[] }>("/markets/stocks");
  const stocks = r.data?.stocks ?? [];
  return stocks
    .filter((s): s is StockRow & { price: number; change_1d: number } =>
      s.price != null && s.change_1d != null && !Number.isNaN(s.price)
    )
    .map((s) => {
      const changePct = s.change_1d;
      const changeAbs = s.price * changePct / 100;
      const prevClose = s.price - changeAbs;
      return {
        symbol: s.symbol,
        price: s.price,
        prevClose: Math.max(0, prevClose),
        changePct,
        changeAbs,
      };
    });
}

export function useTickerTape() {
  const { data } = useQuery({
    queryKey: ["ticker-tape-stocks"],
    queryFn: fetchTickerTapeData,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
  return data ?? [];
}
