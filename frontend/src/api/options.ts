import client from "./client";
import type { OptionsChain } from "@/types/options";

export const getExpirations = (): Promise<string[]> =>
  client.get("/options/expirations").then((r) => r.data);

export const getOptionsChain = (symbol: string, expiration?: string): Promise<OptionsChain> => {
  const params = expiration ? { expiration } : {};
  return client.get(`/options/chain/${encodeURIComponent(symbol)}`, { params }).then((r) => r.data);
};
