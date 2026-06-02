import client from "./client";
import type { Drawing } from "@/types/chart";

export const getDrawings = (
  symbol: string,
  timeframe: string
): Promise<{ drawings: Drawing[] }> =>
  client
    .get("/chart-drawings", { params: { symbol, timeframe } })
    .then((r) => r.data);

export const saveDrawings = (
  symbol: string,
  timeframe: string,
  drawings: Drawing[]
): Promise<{ ok: boolean }> =>
  client
    .put("/chart-drawings", { symbol, timeframe, drawings })
    .then((r) => r.data);
