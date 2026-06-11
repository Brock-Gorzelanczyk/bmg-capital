import client from "./client";

export interface ScoutCatalogEntry {
  strategy_id: string;
  display_name: string;
  category: string;
  description: string;
  confidence_threshold: number;
}

export interface EvaluateResult {
  strategy_id: string;
  display_name: string;
  category: string;
  setup_quality: number;
  confidence: number;
  side: string;
  threshold: number;
  armed: boolean;
  entry: number | null;
  stop: number | null;
  target: number | null;
  reason: string;
  indicators: Record<string, unknown>;
}

export interface ScanResult {
  ticker: string;
  bar_count: number;
  results: EvaluateResult[];
  conflict_warning: string | null;
  message: string | null;
}

export interface ScoutSetup {
  id: number;
  ticker: string;
  strategy_id: string;
  display_name: string;
  category: string;
  status: string;
  created_at: string;
  last_scanned_at: string | null;
  last_confidence: number | null;
  fired_at: string | null;
}

export interface ScoutSignal {
  id: number;
  setup_id: number;
  ticker: string;
  strategy_id: string;
  display_name: string;
  side: string;
  confidence: number;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  reason: string | null;
  created_at: string;
}

export const getCatalog = () =>
  client.get<{ strategies: ScoutCatalogEntry[] }>("/scout/catalog").then((r) => r.data);

export const evaluate = (strategy_id: string, ticker: string) =>
  client
    .post<EvaluateResult>("/scout/evaluate", { strategy_id, ticker })
    .then((r) => r.data);

export const scanTicker = (ticker: string) =>
  client.post<ScanResult>("/scout/scan-ticker", { ticker }).then((r) => r.data);

export const getSetups = () =>
  client.get<{ setups: ScoutSetup[] }>("/scout/setups").then((r) => r.data);

export const createSetup = (ticker: string, strategy_id: string) =>
  client.post<{ id: number; already_exists: boolean }>("/scout/setups", { ticker, strategy_id }).then((r) => r.data);

export const deleteSetup = (id: number) =>
  client.delete(`/scout/setups/${id}`).then((r) => r.data);

export const getSignals = () =>
  client.get<{ signals: ScoutSignal[] }>("/scout/signals").then((r) => r.data);
