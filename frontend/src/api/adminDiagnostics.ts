import client from "./client";

// Backends return server-native shapes (cents-suffixed keys, `report`/
// `inventory`/`top_concentrations` array names). The page consumes a
// normalized shape (dollars + `rows`). Transforms live in each fetcher so
// the page doesn't have to know about the underlying naming.

const cents = (n: number | null | undefined): number => (Number(n ?? 0) / 100);

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

interface RawPortfolioHealth {
  dashboard_pv_cents?: number;
  portfolio_pv_cents?: number;
  strategy_lab_pv_cents?: number;
  max_divergence_cents?: number;
  status?: "ok" | "warn";
  ts?: string;
  notes?: string;
}

export const getPortfolioHealth = (): Promise<PortfolioHealth> =>
  client.get<RawPortfolioHealth>("/admin/portfolio-health").then((r) => {
    const raw = r.data;
    const dashboard_pv = cents(raw.dashboard_pv_cents);
    const portfolio_pv = cents(raw.portfolio_pv_cents);
    const strategy_lab_pv = cents(raw.strategy_lab_pv_cents);
    const divergence_dollars = cents(raw.max_divergence_cents);
    const max_pv = Math.max(dashboard_pv, portfolio_pv, strategy_lab_pv, 1);
    return {
      as_of: raw.ts || new Date().toISOString(),
      status: raw.status ?? "ok",
      dashboard_pv,
      portfolio_pv,
      strategy_lab_pv,
      max_divergence: divergence_dollars / max_pv,
      notes: raw.notes,
    };
  });

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

interface RawConcentration {
  fleet_nav_cents?: number;
  per_name_cap_pct?: number;
  top_concentrations?: Array<{
    symbol: string;
    notional_cents: number;
    notional_pct_of_fleet: number;
    open_positions: number;
    exceeds_cap: boolean;
  }>;
}

export const getConcentration = (limit = 20): Promise<ConcentrationResponse> =>
  client.get<RawConcentration>(`/admin/concentration?limit=${limit}`).then((r) => {
    const raw = r.data;
    return {
      as_of: new Date().toISOString(),
      cap_pct: raw.per_name_cap_pct ?? 3,
      fleet_total_dollars: cents(raw.fleet_nav_cents),
      rows: (raw.top_concentrations ?? []).map((t) => ({
        symbol: t.symbol,
        notional_dollars: cents(t.notional_cents),
        pct_of_fleet: t.notional_pct_of_fleet,
        open_positions: t.open_positions,
        flagged: t.exceeds_cap,
      })),
    };
  });

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

interface RawHeartbeats {
  heartbeats?: Array<{
    bot_name: string;
    last_signal_at: string | null;
    last_scan_at: string | null;
    expected_cadence_minutes: number | null;
    is_stale: boolean;
  }>;
  ts?: string;
}

export const getBotHeartbeats = (): Promise<HeartbeatResponse> =>
  client.get<RawHeartbeats>("/admin/bot-heartbeats").then((r) => ({
    as_of: r.data.ts || new Date().toISOString(),
    rows: (r.data.heartbeats ?? []).map((h) => ({
      bot_name: h.bot_name,
      last_signal_at: h.last_signal_at,
      last_scan_at: h.last_scan_at,
      cadence_min: h.expected_cadence_minutes ?? 0,
      status: h.is_stale ? "stale" : "fresh",
    })),
  }));

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

interface RawInventory {
  inventory?: Array<{
    name: string;
    classification: string;
    starting_capital_cents: number | null;
    capital_cents_within_portfolio: number | null;
  }>;
}

export const getAllocationInventory = (): Promise<InventoryResponse> =>
  client.get<RawInventory>("/admin/allocations/inventory").then((r) => ({
    as_of: new Date().toISOString(),
    rows: (r.data.inventory ?? []).map((i) => ({
      bot_name: i.name,
      classification: (i.classification as AllocationClassification) ?? "orphan",
      capital_cents: (i.capital_cents_within_portfolio ?? i.starting_capital_cents) || 0,
    })),
  }));

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

interface RawStopAsymmetry {
  window_days?: number;
  report?: Array<{
    profile_name: string;
    total_closes: number;
    stops: number;
    stop_pct: number;
  }>;
}

export const getStopAsymmetry = (days = 7): Promise<StopAsymmetryResponse> =>
  client.get<RawStopAsymmetry>(`/admin/closes/stop-asymmetry?days=${days}`).then((r) => ({
    as_of: new Date().toISOString(),
    days: r.data.window_days ?? days,
    rows: (r.data.report ?? []).map((e) => ({
      bot: e.profile_name,
      total_closes: e.total_closes,
      stops: e.stops,
      stop_pct: e.stop_pct,
    })),
  }));

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

interface RawGateRate {
  window_days?: number;
  report?: Array<{
    strategy: string;
    total: number;
    gated: number;
    gate_rate: number;
  }>;
}

export const getDisciplineGateRate = (days = 7): Promise<GateRateResponse> =>
  client.get<RawGateRate>(`/admin/discipline/gate-rate?days=${days}`).then((r) => ({
    as_of: new Date().toISOString(),
    days: r.data.window_days ?? days,
    rows: (r.data.report ?? []).map((e) => ({
      strategy: e.strategy,
      total: e.total,
      gated: e.gated,
      gate_pct: e.gate_rate,
    })),
  }));

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

interface RawCooldownStorm {
  ts?: string;
  storms?: Array<{ bot_name?: string; profile_name?: string; symbol: string; entries_4h: number }>;
  rows?: CooldownStormRow[];
}

export const getCooldownStorm = (): Promise<CooldownStormResponse> =>
  client.get<RawCooldownStorm>("/admin/cooldown/storm-check").then((r) => ({
    as_of: r.data.ts || new Date().toISOString(),
    rows:
      (r.data.rows && r.data.rows.length > 0)
        ? r.data.rows
        : (r.data.storms ?? []).map((s) => ({
            bot: s.bot_name || s.profile_name || "?",
            symbol: s.symbol,
            entries_4h: s.entries_4h,
          })),
  }));

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

interface RawQuarantine {
  classifications?: Array<{
    id: number;
    symbol: string;
    opened_at: string;
    classification: "REAL" | "FAKE";
    gates_passed?: number;
    gate_count?: number;
  }>;
}

export const getLegacyQuarantineAudit = (): Promise<QuarantineResponse> =>
  client.get<RawQuarantine>("/admin/options/legacy-quarantine-audit").then((r) => ({
    as_of: new Date().toISOString(),
    rows: (r.data.classifications ?? []).map((c) => ({
      id: c.id,
      symbol: c.symbol,
      opened_at: c.opened_at,
      classification: c.classification,
      gate_count: c.gates_passed ?? c.gate_count ?? 0,
    })),
  }));

// ── Cross-Sleeve Quarantine (SHIP 14) ────────────────────────────────────────

export interface CrossSleeveQuarantineRow {
  id: number;
  position_id: number;
  bot_id: string;
  user_id: number;
  declared_asset_class: string;
  actual_symbol: string;
  actual_asset_class: string;
  detected_at: string;
  action: string;
}
export interface CrossSleeveQuarantineResponse {
  as_of: string;
  unresolved_count: number;
  rows: CrossSleeveQuarantineRow[];
}
export const getCrossSleeveQuarantine = (): Promise<CrossSleeveQuarantineResponse> =>
  client.get<CrossSleeveQuarantineResponse>("/admin/cross-sleeve-quarantine").then((r) => r.data);

// ── Equity Directional Reconcile ─────────────────────────────────────────────

export interface DirectionalReconcileResponse {
  as_of: string;
  allocation_enabled: boolean | null;
  leaderboard_entry: Record<string, unknown> | null;
  per_alloc_snapshot: Record<string, unknown> | null;
  divergent?: boolean;
}

export const getDirectionalReconcile = (): Promise<DirectionalReconcileResponse> =>
  client.get<Record<string, unknown>>("/admin/bot/options_directional/reconciliation").then((r) => {
    const raw = r.data;
    return {
      as_of:
        (typeof raw.ts === "string" && raw.ts) ||
        new Date().toISOString(),
      allocation_enabled: (raw.allocation_enabled as boolean | null) ?? null,
      leaderboard_entry: (raw.leaderboard_entry as Record<string, unknown> | null) ?? null,
      per_alloc_snapshot: (raw.per_alloc_snapshot as Record<string, unknown> | null) ?? null,
      divergent: (raw.divergent as boolean | undefined) ?? undefined,
    };
  });

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

interface RawDryRun {
  computed_at?: string;
  warning_banner?: string;
  excluded_bots?: Array<{ profile?: string; bot?: string; reason: string }>;
  survivor_bots?: Array<{
    profile?: string;
    bot?: string;
    realized_vol_60d?: number;
    realized_vol?: number;
  }>;
  per_sleeve_summary?: Array<{
    sleeve: string;
    target_sleeve_weight?: number;
    proposed_pct_of_fleet?: number;
    current_pct_of_fleet?: number;
  }>;
  constraint_violations?: string[];
  [k: string]: unknown;
}

export const getLastDryRun = (): Promise<DryRunResponse> =>
  client.get<RawDryRun>("/admin/allocator/last-dry-run").then((r) => normalizeDryRun(r.data));

export const runAllocatorDryRun = (): Promise<DryRunResponse> =>
  client.post<RawDryRun>("/admin/allocator/run-dry-run").then((r) => normalizeDryRun(r.data));

function normalizeDryRun(raw: RawDryRun): DryRunResponse {
  return {
    as_of: raw.computed_at || new Date().toISOString(),
    warning: raw.warning_banner,
    excluded_bots: (raw.excluded_bots ?? []).map((e) => ({
      bot: e.profile || e.bot || "?",
      reason: e.reason,
    })),
    survivor_bots: (raw.survivor_bots ?? []).map((s) => ({
      bot: s.profile || s.bot || "?",
      realized_vol: s.realized_vol_60d ?? s.realized_vol ?? 0,
      target_weight: 0,
    })),
    per_sleeve_summary: (raw.per_sleeve_summary ?? []).map((p) => ({
      sleeve: p.sleeve,
      gross_weight: p.target_sleeve_weight ?? 0,
      net_weight: (p.proposed_pct_of_fleet ?? 0) / 100,
    })),
    constraint_violations: raw.constraint_violations ?? [],
    raw,
  };
}

// ── Ops Alert Test ───────────────────────────────────────────────────────────

export interface OpsAlertResponse {
  ok: boolean;
  delivered_to?: string;
  severity?: string;
  message?: string;
  [k: string]: unknown;
}

export const testOpsAlert = (severity: "info" | "warn" | "critical"): Promise<OpsAlertResponse> =>
  client.post<OpsAlertResponse>(`/admin/ops-alert/test?severity=${severity}`).then((r) => r.data);

// ── EOD Force-Complete ───────────────────────────────────────────────────────

export interface ForceCompleteResponse {
  ok: boolean;
  reconciled_at?: string;
  message?: string;
}

export const forceEodComplete = (reason: string): Promise<ForceCompleteResponse> =>
  client.post<ForceCompleteResponse>("/admin/reconciliation/force-complete", { reason }).then((r) => r.data);

// ── Cash Floor ───────────────────────────────────────────────────────────────

export interface CashFloorPosition {
  symbol: string;
  qty: number;
  avg_cost_cents: number;
  notional_cents: number;
  target_cents: number;
  drift_cents: number;
  drift_shares: number | null;
  live_price_usd: number | null;
}

export interface CashFloorStatus {
  as_of: string;
  fleet_nav_cents: number;
  active_deployment_cents: number;
  cash_floor_target_pct: number;
  cash_floor_target_cents: number;
  actual_cash_pct: number;
  deployable_cents: number;
  target_allocation: {
    spy_target_cents: number;
    qqq_target_cents: number;
    spy_weight_pct: number;
    qqq_weight_pct: number;
  };
  current_positions: CashFloorPosition[];
  total_cash_floor_holding_cents: number;
  cash_floor_pct_of_fleet: number;
  needs_buy: boolean;
  needs_trim: boolean;
  error?: string;
}

export const getCashFloorStatus = (): Promise<CashFloorStatus> =>
  client.get<CashFloorStatus>("/admin/cash-floor/status").then((r) => r.data);

// ── Watchlist Sweep ──────────────────────────────────────────────────────────

export interface WatchlistSweepResponse {
  ok: boolean;
  removed_count: number;
  removed?: string[];
}

interface RawWatchlistSweep {
  ok?: boolean;
  result?: { removed?: number; removed_count?: number };
  removed_count?: number;
}

export const sweepStaleWatchlist = (): Promise<WatchlistSweepResponse> =>
  client.post<RawWatchlistSweep>("/admin/watchlist/sweep-stale").then((r) => ({
    ok: r.data.ok ?? true,
    removed_count: r.data.removed_count ?? r.data.result?.removed_count ?? r.data.result?.removed ?? 0,
  }));
