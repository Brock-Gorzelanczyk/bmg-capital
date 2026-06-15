import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { FUND_ROLES, ROLE_BY_ID } from "@/data/fundRoles";
import type { FundRole, AgentStatus } from "@/data/fundRoles";

// ── Types ──────────────────────────────────────────────────────────────────────

type BudgetStatus = {
  cap_usd: number;
  spent_today_usd: number;
  remaining_usd: number;
  pct_used: number;
  cap_hit: boolean;
  reset_at: string;
};

type LiveAgentData = {
  id: string;
  status: AgentStatus | "not_built";
  last_activity: string | null;
  expected_deploy_phase?: number;
  today: Record<string, number>;
  recent_activity: Array<{ ts: string; action: string; result: string }>;
};

type AgentsStatusResponse = {
  agents: LiveAgentData[];
  as_of: string;
};

// ── API ────────────────────────────────────────────────────────────────────────

async function fetchBudgetStatus(): Promise<BudgetStatus> {
  const res = await fetch("/api/budget/status");
  if (!res.ok) throw new Error("Budget status unavailable");
  return res.json();
}

async function fetchAgentStatus(): Promise<AgentsStatusResponse> {
  const token = localStorage.getItem("bmg_token") ?? "";
  const res = await fetch("/api/agents/status", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Failed to fetch agent status (${res.status})`);
  return res.json();
}

// ── Budget Chip ────────────────────────────────────────────────────────────────

function timeUntilMidnightUTC(resetAt: string): string {
  const diff = new Date(resetAt).getTime() - Date.now();
  if (diff <= 0) return "soon";
  const totalMinutes = Math.floor(diff / 60_000);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function BudgetChip() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["budget-status"],
    queryFn: fetchBudgetStatus,
    refetchInterval: 60_000,
    retry: false,
  });

  if (isLoading || isError || !data) return null;

  const { cap_usd, spent_today_usd, pct_used, cap_hit, reset_at } = data;

  const barColor = cap_hit
    ? "bg-zinc-600"
    : pct_used > 80
    ? "bg-red-500"
    : pct_used > 50
    ? "bg-[var(--amber)]"
    : "bg-[var(--green)]";

  const labelColor = cap_hit
    ? "text-red-400"
    : pct_used > 80
    ? "text-red-400"
    : pct_used > 50
    ? "text-[var(--amber)]"
    : "text-[var(--green)]";

  return (
    <div
      className="border border-[var(--border-dim)] px-2.5 py-1.5 min-w-[140px]"
      style={{ fontFamily: "var(--font-mono-t)" }}
    >
      <p className="text-[9px] font-bold tracking-widest text-[var(--text-dim)] uppercase mb-1">
        DAILY API BUDGET
      </p>
      <p className={cn("text-[10px] font-medium mb-1", labelColor)}>
        ${spent_today_usd.toFixed(2)} / ${cap_usd.toFixed(2)}
      </p>
      {/* Progress bar */}
      <div className="w-full h-1 bg-[var(--bg-2)] border border-[var(--border-dim)] mb-1">
        <div
          className={cn("h-full transition-all duration-500", barColor)}
          style={{ width: `${Math.min(pct_used, 100)}%` }}
        />
      </div>
      <div className="flex items-center justify-between">
        <span className={cn("text-[9px]", labelColor)}>{Math.round(pct_used)}%</span>
        {cap_hit ? (
          <span className="text-[9px] text-red-400">LLM PAUSED · resets midnight UTC</span>
        ) : (
          <span className="text-[9px] text-[var(--text-dim)]">
            resets in {timeUntilMidnightUTC(reset_at)}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const STATUS_DOT: Record<string, string> = {
  active:    "● text-[var(--green)]",
  degraded:  "◐ text-[var(--amber)]",
  offline:   "○ text-[var(--text-dim)]",
  not_built: "○ text-[var(--text-dim)]",
};

const STATUS_LABEL: Record<string, string> = {
  active:    "ACTIVE",
  degraded:  "DEGRADED",
  offline:   "OFFLINE",
  not_built: "NOT BUILT",
};

const STATUS_LABEL_COLOR: Record<string, string> = {
  active:    "text-[var(--green)]",
  degraded:  "text-[var(--amber)]",
  offline:   "text-[var(--text-dim)]",
  not_built: "text-zinc-600",
};

// ── Role Box ──────────────────────────────────────────────────────────────────

function RoleBox({
  role,
  liveStatus,
  lastActivity,
  isSelected,
  onClick,
}: {
  role: FundRole;
  liveStatus: string;
  lastActivity: string | null;
  isSelected: boolean;
  onClick: () => void;
}) {
  const [dotClass, dotChar] = STATUS_DOT[liveStatus]?.split(" ") ?? ["○", "text-[var(--text-dim)]"];

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-[160px] text-left p-3 border transition-colors duration-150 cursor-pointer",
        "bg-[var(--bg-2)] hover:border-[var(--text-hi)]",
        isSelected
          ? "border-[var(--green)] border-2 shadow-[0_0_8px_rgba(74,222,128,0.15)]"
          : "border-[var(--border-subtle)]"
      )}
      style={{ fontFamily: "var(--font-mono-t)" }}
    >
      {/* Title */}
      <p className="text-[9px] font-bold tracking-widest text-[var(--text-hi)] leading-tight mb-1 uppercase">
        {role.title}
      </p>
      {/* Agent name */}
      <p className="text-[10px] text-[var(--text-dim)] mb-2">{role.agentName}</p>

      {role.isHuman ? (
        <p className="text-[9px] text-[var(--text-dim)] italic">human · CIO seat</p>
      ) : (
        <>
          {/* Status */}
          <div className="flex items-center gap-1 mb-0.5">
            <span className={cn("text-[10px]", dotChar)}>{dotClass}</span>
            <span className={cn("text-[9px] font-bold tracking-wider", STATUS_LABEL_COLOR[liveStatus])}>
              {STATUS_LABEL[liveStatus]}
            </span>
          </div>
          {/* Last seen / deploy phase */}
          {liveStatus === "not_built" ? (
            <p className="text-[9px] text-zinc-600">Deploy {role.expectedDeployPhase}</p>
          ) : (
            <p className="text-[9px] text-[var(--text-dim)]">Last: {timeAgo(lastActivity)}</p>
          )}
        </>
      )}
    </button>
  );
}

// ── Org chart connector utils ─────────────────────────────────────────────────

const BOX_W = 160;
const BOX_H = 84;
const HALF_W = BOX_W / 2;

// Node positions: cx = horizontal center, cy = vertical top edge
const NODES: Record<string, { cx: number; cy: number }> = {
  cio:                { cx: 460, cy:   0 },
  portfolio_manager:  { cx: 230, cy: 130 },
  chief_risk_officer: { cx: 690, cy: 130 },
  equity_researcher:  { cx:  80, cy: 260 },
  quant_researcher:   { cx: 240, cy: 260 },
  macro_strategist:   { cx: 400, cy: 260 },
  data_quality_watcher: { cx: 580, cy: 260 },
  execution_auditor:  { cx: 740, cy: 260 },
  operations:         { cx: 120, cy: 390 },
  sentinel_devops:    { cx: 740, cy: 390 },
};

const SVG_W = 930;
const SVG_H = 390 + BOX_H + 10;
const BRANCH_H = 20; // vertical drop before branching

function lineD(x1: number, y1: number, x2: number, y2: number): string {
  const my = y1 + BRANCH_H;
  return `M ${x1} ${y1} L ${x1} ${my} L ${x2} ${my} L ${x2} ${y2}`;
}

// All connection lines [from-id, to-id, style?]
type LineSpec = [string, string, "solid" | "dashed" | "amber-dashed"];
const LINES: LineSpec[] = [
  ["cio", "portfolio_manager", "solid"],
  ["cio", "chief_risk_officer", "solid"],
  ["portfolio_manager", "equity_researcher", "solid"],
  ["portfolio_manager", "quant_researcher", "solid"],
  ["portfolio_manager", "macro_strategist", "solid"],
  ["portfolio_manager", "operations", "solid"],
  ["chief_risk_officer", "data_quality_watcher", "solid"],
  ["chief_risk_officer", "execution_auditor", "solid"],
  ["chief_risk_officer", "sentinel_devops", "solid"],
  // Veto line — CRO left edge to PM right edge, horizontal at box mid-height
  ["chief_risk_officer", "portfolio_manager", "amber-dashed"],
];

// ── Macro Run Button ──────────────────────────────────────────────────────────

function MacroRunButton() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ regime?: string; confidence?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const token = localStorage.getItem("bmg_token") ?? "";
      const res = await fetch("/api/agents/macro-strategist/run-classification", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult({
        regime: data.result?.regime,
        confidence: data.result?.confidence != null
          ? `${(data.result.confidence * 100).toFixed(0)}%`
          : undefined,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex items-center gap-3 flex-wrap" style={{ fontFamily: "var(--font-mono-t)" }}>
      <button
        onClick={handleRun}
        disabled={running}
        className="text-[10px] font-bold tracking-wider border px-3 py-1.5 transition-colors
          border-[var(--green)] text-[var(--green)] hover:bg-[var(--green)]/10 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {running ? "CLASSIFYING…" : "▶ RUN CLASSIFICATION"}
      </button>
      {result && (
        <span className="text-[10px] text-[var(--green)]">
          ✓ {result.regime}{result.confidence ? ` · ${result.confidence}` : ""}
        </span>
      )}
      {error && (
        <span className="text-[10px] text-red-400">✗ {error}</span>
      )}
    </div>
  );
}

// ── Quant Run Button ──────────────────────────────────────────────────────────

function QuantRunButton() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ transitions?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const token = localStorage.getItem("bmg_token") ?? "";
      const res = await fetch("/api/agents/quant-researcher/run-pipeline", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult({ transitions: data.result?.transitions?.length ?? 0 });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex items-center gap-3 flex-wrap" style={{ fontFamily: "var(--font-mono-t)" }}>
      <button
        onClick={handleRun}
        disabled={running}
        className="text-[10px] font-bold tracking-wider border px-3 py-1.5 transition-colors
          border-[var(--green)] text-[var(--green)] hover:bg-[var(--green)]/10 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {running ? "SCANNING…" : "▶ RUN PIPELINE SCAN"}
      </button>
      {result !== null && (
        <span className="text-[10px] text-[var(--green)]">
          ✓ {result.transitions} transition{result.transitions !== 1 ? "s" : ""} this cycle
        </span>
      )}
      {error && (
        <span className="text-[10px] text-red-400">✗ {error}</span>
      )}
    </div>
  );
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="text-[9px] tracking-widest font-bold text-[var(--text-dim)] uppercase mb-2"
      style={{ fontFamily: "var(--font-mono-t)" }}
    >
      // {children}
    </p>
  );
}

function DetailPanel({
  role,
  liveData,
}: {
  role: FundRole;
  liveData: LiveAgentData | undefined;
}) {
  const status = liveData?.status ?? role.status;

  return (
    <div
      className="border border-[var(--border-subtle)] bg-[var(--bg-2)]"
      style={{ fontFamily: "var(--font-mono-t)" }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-sm font-bold text-[var(--text-hi)] tracking-wider">{role.title}</h2>
          <p className="text-[11px] text-[var(--text-dim)] mt-0.5">{role.agentName}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("text-xs font-bold tracking-wider", STATUS_LABEL_COLOR[status])}>
            {STATUS_DOT[status]?.split(" ")[0]} {STATUS_LABEL[status]}
          </span>
          {status === "not_built" && liveData?.expected_deploy_phase && (
            <span className="text-[9px] text-zinc-600 border border-zinc-800 px-2 py-0.5">
              Deploy {liveData.expected_deploy_phase}
            </span>
          )}
          {status === "active" && liveData?.last_activity && (
            <span className="text-[9px] text-[var(--text-dim)]">
              Last: {timeAgo(liveData.last_activity)}
            </span>
          )}
        </div>
      </div>

      <div className="p-5 space-y-5">
        {/* Description */}
        <div>
          <SectionHeader>Seat Description</SectionHeader>
          <p className="text-[11px] text-[var(--text-mid)] leading-relaxed">{role.description}</p>
        </div>

        <div className="border-t border-[var(--border-subtle)]" />

        {/* Authority */}
        <div>
          <SectionHeader>Authority</SectionHeader>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "Tier A — Autonomous", items: role.authority.tierA, color: "text-[var(--green)]" },
              { label: "Tier B — Propose → Approve", items: role.authority.tierB, color: "text-[var(--amber)]" },
              { label: "Tier C — Never Automated", items: role.authority.tierC, color: "text-red-400" },
            ].map(({ label, items, color }) => (
              <div key={label}>
                <p className={cn("text-[9px] font-bold mb-1.5", color)}>{label}</p>
                {items.length === 0 ? (
                  <p className="text-[10px] text-zinc-600">—</p>
                ) : (
                  <ul className="space-y-1">
                    {items.map((item, i) => (
                      <li key={i} className="text-[10px] text-[var(--text-dim)] leading-snug">
                        · {item}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="border-t border-[var(--border-subtle)]" />

        {/* Reports to + inputs + outputs */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <SectionHeader>Reports To</SectionHeader>
            <p className="text-[11px] text-[var(--text-mid)]">{role.reportsTo}</p>
          </div>
          <div>
            <SectionHeader>Receives Input From</SectionHeader>
            <ul className="space-y-0.5">
              {role.inputsFrom.map((src, i) => (
                <li key={i} className="text-[10px] text-[var(--text-dim)] leading-snug">· {src}</li>
              ))}
            </ul>
          </div>
          <div>
            <SectionHeader>Sends Output To</SectionHeader>
            <ul className="space-y-0.5">
              {role.outputsTo.map((dst, i) => (
                <li key={i} className="text-[10px] text-[var(--text-dim)] leading-snug">· {dst}</li>
              ))}
            </ul>
          </div>
        </div>

        {/* Live status row (only for active/degraded agents) */}
        {status !== "not_built" && liveData && (
          <>
            <div className="border-t border-[var(--border-subtle)]" />
            <div className="grid grid-cols-2 gap-4">
              <div>
                <SectionHeader>Live Status</SectionHeader>
                <div className="space-y-1">
                  {Object.entries(liveData.today ?? {}).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2">
                      <span className="text-[10px] text-[var(--text-dim)] capitalize">
                        {k.replace(/_/g, " ")}:
                      </span>
                      <span className="text-[10px] text-[var(--text-hi)] font-medium">{String(v)}</span>
                    </div>
                  ))}
                  {Object.keys(liveData.today ?? {}).length === 0 && (
                    <p className="text-[10px] text-zinc-600">No activity data</p>
                  )}
                </div>
              </div>
              <div>
                <SectionHeader>Recent Activity</SectionHeader>
                {!liveData.recent_activity?.length ? (
                  <p className="text-[10px] text-zinc-600">No recent messages</p>
                ) : (
                  <ul className="space-y-1">
                    {liveData.recent_activity.slice(0, 5).map((a, i) => (
                      <li key={i} className="text-[10px] text-[var(--text-dim)]">
                        <span className="text-zinc-600">{timeAgo(a.ts)}</span>
                        {" · "}
                        <span>{a.action}</span>
                        {a.result && (
                          <span className="text-zinc-600"> — {a.result}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </>
        )}

        {/* Agent-specific action buttons */}
        {(role.id === "macro_strategist" || role.id === "quant_researcher") && (
          <>
            <div className="border-t border-[var(--border-subtle)]" />
            <div>
              <SectionHeader>Actions</SectionHeader>
              {role.id === "macro_strategist" && <MacroRunButton />}
              {role.id === "quant_researcher" && <QuantRunButton />}
            </div>
          </>
        )}

        {/* Discord channels */}
        {role.discordChannels.length > 0 && (
          <>
            <div className="border-t border-[var(--border-subtle)]" />
            <div>
              <SectionHeader>View In Discord</SectionHeader>
              <div className="flex flex-wrap gap-2">
                {role.discordChannels.map((ch) => (
                  <div
                    key={ch.name}
                    className="flex items-center gap-1.5 text-[10px] text-[var(--text-dim)] border border-[var(--border-dim)] px-2.5 py-1"
                  >
                    <ExternalLink size={9} className="text-zinc-600" />
                    <span className="font-medium">{ch.name}</span>
                    <span className="text-zinc-600">— {ch.purpose}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Attention Panel ───────────────────────────────────────────────────────────

type AttentionItem = {
  id: string;
  severity: "red" | "yellow" | "gray";
  title: string;
  subtitle: string;
  action: string;
  link: string;
  ts: string;
};

type AttentionResponse = {
  items: AttentionItem[];
  count: number;
};

async function fetchAttentionItems(): Promise<AttentionResponse> {
  const token = localStorage.getItem("bmg_token") ?? "";
  const res = await fetch("/api/fund/attention", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Failed to fetch attention items (${res.status})`);
  return res.json();
}

const SEV_DOT: Record<string, [string, string]> = {
  red:    ["●", "text-red-400"],
  yellow: ["◆", "text-amber-400"],
  gray:   ["·", "text-zinc-500"],
};

const SEV_BORDER: Record<string, string> = {
  red:    "border-l-red-500/60",
  yellow: "border-l-amber-500/40",
  gray:   "border-l-zinc-700",
};

function AttentionPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["fund-attention"],
    queryFn: fetchAttentionItems,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: false,
  });

  if (isLoading || !data?.items.length) return null;

  return (
    <div
      className="border border-[var(--border-subtle)] bg-[var(--bg-1)]"
      style={{ fontFamily: "var(--font-mono-t)" }}
    >
      <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <p className="text-[9px] font-bold tracking-widest text-[var(--text-dim)] uppercase">
          // NEEDS YOUR ATTENTION
        </p>
        <span className="text-[10px] text-[var(--text-dim)]">
          {data.count} item{data.count !== 1 ? "s" : ""}
        </span>
      </div>
      <ul className="divide-y divide-[var(--border-dim)]">
        {data.items.map((item) => {
          const [dotChar, dotColor] = SEV_DOT[item.severity] ?? ["·", "text-zinc-500"];
          return (
            <li
              key={item.id}
              className={cn(
                "flex items-start gap-3 px-4 py-3 border-l-2",
                SEV_BORDER[item.severity] ?? "border-l-zinc-700"
              )}
            >
              <span className={cn("text-[11px] mt-0.5 shrink-0", dotColor)}>{dotChar}</span>
              <div className="min-w-0 flex-1">
                <p className="text-[11px] text-[var(--text-hi)] font-medium leading-snug truncate">{item.title}</p>
                <p className="text-[10px] text-[var(--text-dim)] leading-snug mt-0.5">{item.subtitle}</p>
              </div>
              <Link
                to={item.link}
                className="shrink-0 text-[9px] text-[var(--text-dim)] border border-[var(--border-dim)] px-2 py-1 hover:border-[var(--text-hi)] hover:text-[var(--text-hi)] transition-colors"
              >
                View →
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── Org Chart SVG ─────────────────────────────────────────────────────────────

function OrgChartSVG({
  liveMap,
  selectedId,
  onSelect,
}: {
  liveMap: Record<string, { status: string; last_activity: string | null }>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="relative w-full overflow-x-auto">
      <div style={{ minWidth: SVG_W + 20, position: "relative", height: SVG_H + 20 }}>
        {/* SVG connector lines */}
        <svg
          width={SVG_W}
          height={SVG_H}
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          style={{ position: "absolute", top: 10, left: 10, pointerEvents: "none", overflow: "visible" }}
        >
          {LINES.map(([fromId, toId, style]) => {
            const from = NODES[fromId];
            const to = NODES[toId];
            if (!from || !to) return null;

            if (style === "amber-dashed") {
              // Horizontal veto line between right edge of PM and left edge of CRO
              const pmNode = NODES["portfolio_manager"];
              const croNode = NODES["chief_risk_officer"];
              const y = pmNode.cy + BOX_H / 2;
              const x1 = pmNode.cx + HALF_W;
              const x2 = croNode.cx - HALF_W;
              return (
                <g key={`${fromId}-${toId}`}>
                  <line
                    x1={x1} y1={y} x2={x2} y2={y}
                    stroke="var(--amber)"
                    strokeWidth="1"
                    strokeDasharray="4 4"
                    opacity="0.6"
                  />
                  <text
                    x={(x1 + x2) / 2}
                    y={y - 5}
                    textAnchor="middle"
                    fill="var(--amber)"
                    fontSize="9"
                    opacity="0.7"
                    style={{ fontFamily: "var(--font-mono-t)" }}
                  >
                    veto
                  </text>
                </g>
              );
            }

            // Standard right-angle connector: parent bottom → child top
            const x1 = from.cx + HALF_W;
            const y1 = from.cy + BOX_H;
            const x2 = to.cx + HALF_W;
            const y2 = to.cy;
            return (
              <path
                key={`${fromId}-${toId}`}
                d={lineD(x1, y1, x2, y2)}
                fill="none"
                stroke="var(--border-subtle)"
                strokeWidth="1"
              />
            );
          })}
        </svg>

        {/* Role boxes */}
        {FUND_ROLES.map((role) => {
          const node = NODES[role.id];
          if (!node) return null;
          const live = liveMap[role.id];
          const status = live?.status ?? role.status;
          return (
            <div
              key={role.id}
              style={{
                position: "absolute",
                left: node.cx + 10,
                top: node.cy + 10,
                width: BOX_W,
              }}
            >
              <RoleBox
                role={role}
                liveStatus={status}
                lastActivity={live?.last_activity ?? null}
                isSelected={selectedId === role.id}
                onClick={() => onSelect(role.id)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function FundPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["agents-status"],
    queryFn: fetchAgentStatus,
    staleTime: 30_000,
    refetchInterval: 30_000,
    retry: false,
  });

  const liveMap: Record<string, { status: string; last_activity: string | null }> =
    Object.fromEntries(
      (data?.agents ?? []).map((a) => [
        a.id,
        { status: a.status, last_activity: a.last_activity ?? null },
      ])
    );

  const activeCount = Object.values(liveMap).filter(
    (a) => a.status === "active" || a.status === "degraded"
  ).length;
  const totalAgents = FUND_ROLES.filter((r) => !r.isHuman).length;

  const selectedRole = selectedId ? ROLE_BY_ID[selectedId] : null;
  const selectedLiveData = selectedId
    ? data?.agents.find((a) => a.id === selectedId)
    : undefined;

  return (
    <div className="min-h-screen p-6 space-y-6" style={{ background: "var(--bg-0)" }}>
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1
            className="text-base font-bold text-[var(--text-hi)] tracking-widest"
            style={{ fontFamily: "var(--font-mono-t)" }}
          >
            // FUND TEAM
          </h1>
          <p className="text-[11px] text-[var(--text-dim)] mt-0.5" style={{ fontFamily: "var(--font-mono-t)" }}>
            Live org chart — click any role for details
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isLoading ? (
            <span className="text-[10px] text-zinc-600" style={{ fontFamily: "var(--font-mono-t)" }}>
              loading…
            </span>
          ) : isError ? (
            <span className="text-[10px] text-zinc-600" style={{ fontFamily: "var(--font-mono-t)" }}>
              status unavailable
            </span>
          ) : (
            <span
              className="text-[10px] border border-[var(--border-dim)] px-2.5 py-1 text-[var(--text-dim)]"
              style={{ fontFamily: "var(--font-mono-t)" }}
            >
              {activeCount} of {totalAgents} active
            </span>
          )}
          <BudgetChip />
        </div>
      </div>

      {/* Attention panel */}
      <AttentionPanel />

      {/* Org chart */}
      <div className="border border-[var(--border-subtle)] bg-[var(--bg-1)] p-4">
        <OrgChartSVG
          liveMap={liveMap}
          selectedId={selectedId}
          onSelect={(id) => setSelectedId((prev) => (prev === id ? null : id))}
        />
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4" style={{ fontFamily: "var(--font-mono-t)" }}>
        {[
          { dot: "●", label: "ACTIVE", color: "text-[var(--green)]" },
          { dot: "◐", label: "DEGRADED", color: "text-[var(--amber)]" },
          { dot: "○", label: "OFFLINE / NOT BUILT", color: "text-[var(--text-dim)]" },
        ].map(({ dot, label, color }) => (
          <div key={label} className="flex items-center gap-1.5">
            <span className={cn("text-[11px]", color)}>{dot}</span>
            <span className="text-[9px] text-[var(--text-dim)] tracking-wider">{label}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5">
          <svg width="24" height="8" className="shrink-0">
            <line x1="0" y1="4" x2="24" y2="4" stroke="var(--amber)" strokeWidth="1" strokeDasharray="4 4" opacity="0.7" />
          </svg>
          <span className="text-[9px] text-[var(--text-dim)] tracking-wider">VETO AUTHORITY</span>
        </div>
      </div>

      {/* Detail panel */}
      {selectedRole && (
        <DetailPanel role={selectedRole} liveData={selectedLiveData} />
      )}

      {/* Empty state when nothing selected */}
      {!selectedRole && (
        <div
          className="flex items-center justify-center py-10 border border-dashed border-[var(--border-dim)]"
          style={{ fontFamily: "var(--font-mono-t)" }}
        >
          <p className="text-[11px] text-zinc-600">Select a role above to view seat details</p>
        </div>
      )}

      {/* Footer */}
      <p className="text-[9px] text-zinc-700 pb-2" style={{ fontFamily: "var(--font-mono-t)" }}>
        Agent fleet status polls every 30s · All agents operate on paper capital only · Not investment advice
      </p>
    </div>
  );
}
