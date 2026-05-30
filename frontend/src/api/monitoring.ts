import client from "./client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface HealthResult {
  db: "ok" | "error";
  api: "ok" | "error";
  latency_ms: number;
  timestamp: string;
  error?: string;
}

export interface HistoryResult {
  history: HealthResult[];
}

export interface IntegrityCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface IntegrityResult {
  passed: boolean;
  checks: IntegrityCheck[];
  timestamp: string;
}

export interface SentinelFinding {
  priority: "P1" | "P2" | "P3";
  title: string;
  description: string;
  action: string;
}

export interface SentinelResult {
  findings: SentinelFinding[];
  generated_at: string | null;
  message?: string;
}

export interface CheckRegistryItem {
  id: string;
  category: string;
  frequency: string;
  severity_on_fail: "P1" | "P2" | "P3";
  runbook: string;
  expected_pass_rate: number;
  market_hours_only: boolean;
  enabled: boolean;
}

export interface CheckRegistryResult {
  checks: CheckRegistryItem[];
  total: number;
}

export interface MonitoringResultRow {
  id: number;
  check_id: string;
  category: string;
  passed: boolean;
  severity: string;
  detail: string;
  runbook: string;
  duration_ms: number;
  timestamp: string;
}

export interface MonitoringResultsResponse {
  results: MonitoringResultRow[];
  count: number;
  since: string;
}

export interface CategoryStatus {
  status: "green" | "yellow" | "red" | "gray";
  total_checks: number;
  checks_with_data: number;
  failures_p1_p2: number;
  failures_p3: number;
  last_run: string | null;
}

export interface StatusResponse {
  categories: Record<string, CategoryStatus>;
  as_of: string;
}

// ── API functions ─────────────────────────────────────────────────────────────

export const getHealth = (): Promise<HealthResult> =>
  client.get("/api/monitoring/health").then((r) => r.data);

export const getHistory = (): Promise<HistoryResult> =>
  client.get("/api/monitoring/history").then((r) => r.data);

export const getIntegrity = (): Promise<IntegrityResult> =>
  client.get("/api/monitoring/integrity").then((r) => r.data);

export const triggerSentinel = (): Promise<SentinelResult> =>
  client.post("/api/monitoring/sentinel").then((r) => r.data);

export const getSentinelLatest = (): Promise<SentinelResult> =>
  client.get("/api/monitoring/sentinel/latest").then((r) => r.data);

export const getChecks = (): Promise<CheckRegistryResult> =>
  client.get("/api/monitoring/checks").then((r) => r.data);

export const getResults = (params?: {
  check_id?: string;
  category?: string;
  hours?: number;
  passed?: boolean;
}): Promise<MonitoringResultsResponse> =>
  client.get("/api/monitoring/results", { params }).then((r) => r.data);

export const getStatus = (): Promise<StatusResponse> =>
  client.get("/api/monitoring/status").then((r) => r.data);
