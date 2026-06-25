import client from "./client";

// ── Portfolio Health ─────────────────────────────────────────────────────────

export interface PortfolioHealth {
  as_of: string;
  status: "ok" | "warn";
  dashboard_pv: number;
  portfolio_pv: number;
  strategy_lab_pv: number;
  max_divergence: number;
  threshold?: number;
  notes?: string;
}

export const getPortfolioHealth = (): Promise<PortfolioHealth> =>
  client.get("/admin/portfolio-health").then(r => r.data);

// ── Concentration ────────────────────────────────────────────────────────────

export interface ConcentrationRow {
  symbol: string;
  notional_dollars: number;
  pct_of_fleet: number;
  open_positions: number;
  flagged: boolean;
}

export interface ConcentrationResponse {
  as_of: string;
  cap_pct: number;
  fleet_total_dollars: number;
  rows: ConcentrationRow[];
}

export const getConcentration = (limit = 20): Promise<ConcentrationResponse> =>
  client.get(`/admin/concentration?limit=${limit}`).then(r => r.data);

// ── Bot Heartbeats ───────────────────────────────────────────────────────────

export interface HeartbeatRow {
  bot_name: string;
  last_signal_at: string | null;
  last_scan_at: string | null;
  cadence_min: number;
  status: "fresh" | "stale";
}

export interface HeartbeatResponse {
  as_of: string;
  rows: HeartbeatRow[];
}

export const getBotHeartbeats = (): Promise<HeartbeatResponse> =>
  client.get("/admin/bot-heartbeats").then(r => r.data);

// ── Allocation Inventory ─────────────────────────────────────────────────────

export type AllocationClassification = "active" | "incubating" | "retired" | "orphan";

export interface InventoryRow {
  bot_name: string;
  classification: AllocationClassification;
  capital_cents: number;
}

export interface InventoryResponse {
  as_of: string;
  rows: InventoryRow[];
}

export const getAllocationInventory = (): Promise<InventoryResponse> =>
  client.get("/admin/allocations/inventory").then(r => r.data);

// ── Stop-Hit Asymmetry ───────────────────────────────────────────────────────

export interface StopAsymmetryRow {
  bot: string;
  total_closes: number;
  stops: number;
  stop_pct: number;
}

export interface StopAsymmetryResponse {
  as_of: string;
  days: number;
  rows: StopAsymmetryRow[];
}

export const getStopAsymmetry = (days = 7): Promise<StopAsymmetryResponse> =>
  client.get(`/admin/closes/stop-asymmetry?days=${days}`).then(r => r.data);

// ── Discipline Gate Rate ─────────────────────────────────────────────────────

export interface GateRateRow {
  strategy: string;
  total: number;
  gated: number;
  gate_pct: number;
}

export interface GateRateResponse {
  as_of: string;
  days: number;
  rows: GateRateRow[];
}

export const getDisciplineGateRate = (days = 7): Promise<GateRateResponse> =>
  client.get(`/admin/discipline/gate-rate?days=${days}`).then(r => r.data);

// ── Cooldown Storm ───────────────────────────────────────────────────────────

export interface CooldownStormRow {
  bot: string;
  symbol: string;
  entries_4h: number;
}

export interface CooldownStormResponse {
  as_of: string;
  rows: CooldownStormRow[];
}

export const getCooldownStorm = (): Promise<CooldownStormResponse> =>
  client.get("/admin/cooldown/storm-check").then(r => r.data);

// ── Legacy Quarantine Audit ──────────────────────────────────────────────────

export interface QuarantineRow {
  id: number;
  symbol: string;
  opened_at: string;
  classification: "REAL" | "FAKE";
  gate_count: number;
}

export interface QuarantineResponse {
  as_of: string;
  rows: QuarantineRow[];
}

export const getLegacyQuarantineAudit = (): Promise<QuarantineResponse> =>
  client.get("/admin/options/legacy-quarantine-audit").then(r => r.data);

// ── Equity Directional Reconcile ─────────────────────────────────────────────

export interface DirectionalReconcileResponse {
  as_of: string;
  allocation_enabled: boolean | null;
  leaderboard_entry: Record<string, unknown> | null;
  per_alloc_snapshot: Record<string, unknown> | null;
  divergent?: boolean;
}

export const getDirectionalReconcile = (): Promise<DirectionalReconcileResponse> =>
  client.get("/admin/bot/options_directional/reconciliation").then(r => r.data);

// ── Vol-targeting Last Dry-Run ───────────────────────────────────────────────

export interface DryRunResponse {
  as_of: string;
  warning?: string;
  excluded_bots: { bot: string; reason: string }[];
  survivor_bots: { bot: string; realized_vol: number; target_weight: number }[];
  per_sleeve_summary: { sleeve: string; gross_weight: number; net_weight: number }[];
  constraint_violations: string[];
  [k: string]: unknown;
}

export const getLastDryRun = (): Promise<DryRunResponse> =>
  client.get("/admin/allocator/last-dry-run").then(r => r.data);

export const runAllocatorDryRun = (): Promise<DryRunResponse> =>
  client.post("/admin/allocator/run-dry-run").then(r => r.data);

// ── Ops Alert Test ───────────────────────────────────────────────────────────

export interface OpsAlertResponse {
  ok: boolean;
  delivered_to?: string;
  severity?: string;
  message?: string;
  [k: string]: unknown;
}

export const testOpsAlert = (severity: "info" | "warn" | "critical"): Promise<OpsAlertResponse> =>
  client.post(`/admin/ops-alert/test?severity=${severity}`).then(r => r.data);

// ── EOD Force-Complete ───────────────────────────────────────────────────────

export interface ForceCompleteResponse {
  ok: boolean;
  reconciled_at?: string;
  message?: string;
}

export const forceEodComplete = (reason: string): Promise<ForceCompleteResponse> =>
  client.post("/admin/reconciliation/force-complete", { reason }).then(r => r.data);

// ── Watchlist Sweep ──────────────────────────────────────────────────────────

export interface WatchlistSweepResponse {
  ok: boolean;
  removed_count: number;
  removed?: string[];
}

export const sweepStaleWatchlist = (): Promise<WatchlistSweepResponse> =>
  client.post("/admin/watchlist/sweep-stale").then(r => r.data);
