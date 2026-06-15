import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { SectionLabel, BracketFrame } from "@/components/design";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Finding {
  id: number;
  agent_id: string;
  memory_type: string;
  key: string;
  value: unknown;
  preview: string;
  updated_at: string;
}

interface FindingsResponse {
  findings: Finding[];
  total: number;
  memory_types: string[];
  agents: string[];
}

// ── API ───────────────────────────────────────────────────────────────────────

async function fetchFindings(params: {
  agent: string;
  memory_type: string;
  days: number;
  q: string;
}): Promise<FindingsResponse> {
  const token = localStorage.getItem("bmg_token") ?? "";
  const sp = new URLSearchParams({
    agent: params.agent,
    days: String(params.days),
    limit: "150",
  });
  if (params.memory_type) sp.set("memory_type", params.memory_type);
  if (params.q) sp.set("q", params.q);

  const res = await fetch(`/api/research-feed/findings?${sp}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function translateFinding(content: string): Promise<string> {
  const token = localStorage.getItem("bmg_token") ?? "";
  const res = await fetch("/api/copilot/rewrite-level", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content, level: "beginner", context: "Agent research finding" }),
  });
  if (!res.ok) return content;
  const data = await res.json();
  return data.rewritten ?? content;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function formatValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

const TYPE_COLORS: Record<string, string> = {
  regime:         "text-t-cyan   border-t-cyan/30   bg-t-cyan/10",
  signal:         "text-t-green  border-t-green/30  bg-t-green/10",
  bot_health:     "text-t-amber  border-t-amber/30  bg-t-amber/10",
  candidate:      "text-purple-400 border-purple-400/30 bg-purple-400/10",
  macro:          "text-blue-400   border-blue-400/30   bg-blue-400/10",
  risk:           "text-t-red    border-t-red/30    bg-t-red/10",
  observation:    "text-t-muted  border-t-dim       bg-t-bg1",
};

function TypeBadge({ type }: { type: string }) {
  const cls = TYPE_COLORS[type] ?? "text-t-muted border-t-dim bg-t-bg1";
  return (
    <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded border font-mono-t uppercase tracking-wider whitespace-nowrap", cls)}>
      {type.replace(/_/g, " ")}
    </span>
  );
}

function PillButton({
  active, onClick, children,
}: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-lg font-mono-t text-[11px] uppercase tracking-widest transition-all duration-150",
        active
          ? "bg-t-bg2 text-t-hi"
          : "bg-t-bg1 border border-t-dim text-t-muted hover:text-t-mid2 hover:border-t-mid"
      )}
    >
      {children}
    </button>
  );
}

const DAYS_OPTIONS = [
  { label: "7D",  value: 7 },
  { label: "30D", value: 30 },
  { label: "90D", value: 90 },
  { label: "All", value: 0 },
];

// ── Finding Card ──────────────────────────────────────────────────────────────

function FindingCard({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false);
  const [plainEnglish, setPlainEnglish] = useState<string | null>(null);
  const [translating, setTranslating] = useState(false);

  const rawText = formatValue(finding.value);

  async function handleTranslate() {
    if (plainEnglish) {
      setPlainEnglish(null);
      return;
    }
    setTranslating(true);
    try {
      const result = await translateFinding(rawText.slice(0, 1500));
      setPlainEnglish(result);
    } finally {
      setTranslating(false);
    }
  }

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-xl overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-t-bg2/40 transition-colors"
      >
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <TypeBadge type={finding.memory_type} />
            <span className="font-mono-t text-xs text-t-gdim">{finding.agent_id}</span>
          </div>
          <p className="text-t-hi text-sm font-semibold truncate">{finding.key}</p>
          <p className="text-t-muted text-xs leading-snug line-clamp-2">{finding.preview}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[10px] text-t-gdim font-mono-t">{timeAgo(finding.updated_at)}</p>
          <p className="text-[9px] text-t-gdim font-mono-t mt-0.5">
            {expanded ? "▲" : "▼"}
          </p>
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-t-dim px-4 py-3 space-y-3">
          <div className="flex items-center gap-2">
            <p className="text-[10px] text-t-gdim font-mono-t">// RAW VALUE</p>
            <button
              onClick={handleTranslate}
              disabled={translating}
              className={cn(
                "ml-auto text-[10px] font-mono-t px-2.5 py-1 rounded border transition-colors",
                plainEnglish
                  ? "border-t-green/40 text-t-green bg-t-green/10"
                  : "border-t-dim text-t-muted hover:text-t-hi hover:border-t-mid"
              )}
            >
              {translating ? "translating…" : plainEnglish ? "↺ Show raw" : "⚡ Plain English"}
            </button>
          </div>

          {plainEnglish ? (
            <div className="bg-t-bg2 border border-t-green/20 rounded-lg px-3 py-2.5">
              <p className="text-[10px] text-t-green font-mono-t mb-1.5">// PLAIN ENGLISH</p>
              <p className="text-sm text-t-hi leading-relaxed">{plainEnglish}</p>
            </div>
          ) : (
            <pre className="text-xs text-t-mid2 font-mono-t whitespace-pre-wrap break-words bg-t-bg2 rounded-lg px-3 py-2.5 max-h-64 overflow-y-auto">
              {rawText}
            </pre>
          )}

          <p className="text-[10px] text-t-gdim font-mono-t">
            Updated {new Date(finding.updated_at).toLocaleString()} · ID #{finding.id}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ResearchFeedPage() {
  const [agent, setAgent]     = useState("researcher");
  const [memType, setMemType] = useState("");
  const [days, setDays]       = useState(30);
  const [q, setQ]             = useState("");
  const [search, setSearch]   = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["research-feed-findings", agent, memType, days, search],
    queryFn: () => fetchFindings({ agent, memory_type: memType, days, q: search }),
    staleTime: 60_000,
    retry: 0,
  });

  const findings = data?.findings ?? [];
  const memTypes = data?.memory_types ?? [];
  const agents = data?.agents ?? ["researcher"];

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8 space-y-6">

        {/* Header */}
        <div>
          <SectionLabel as="h1" className="text-base mb-1">
            // RESEARCH FEED
          </SectionLabel>
          <p className="text-sm text-t-muted">
            Persistent memory from the Researcher agent — regime notes, bot observations, candidate flags.
          </p>
        </div>

        {/* Filters */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {/* Agent */}
            <span className="text-xs text-t-gdim font-mono-t uppercase tracking-widest">Agent</span>
            <PillButton active={agent === "researcher"} onClick={() => setAgent("researcher")}>Researcher</PillButton>
            {agents.filter(a => a !== "researcher").map(a => (
              <PillButton key={a} active={agent === a} onClick={() => setAgent(a)}>{a}</PillButton>
            ))}
            <PillButton active={agent === "all"} onClick={() => setAgent("all")}>All</PillButton>

            <div className="w-px h-6 bg-t-dim hidden sm:block" />

            {/* Days */}
            <span className="text-xs text-t-gdim font-mono-t uppercase tracking-widest">Window</span>
            {DAYS_OPTIONS.map(d => (
              <PillButton key={d.value} active={days === d.value} onClick={() => setDays(d.value)}>
                {d.label}
              </PillButton>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Memory type */}
            <span className="text-xs text-t-gdim font-mono-t uppercase tracking-widest">Type</span>
            <PillButton active={memType === ""} onClick={() => setMemType("")}>All</PillButton>
            {memTypes.map(t => (
              <PillButton key={t} active={memType === t} onClick={() => setMemType(t)}>
                {t.replace(/_/g, " ")}
              </PillButton>
            ))}

            {/* Search */}
            <input
              type="text"
              placeholder="Search findings…"
              value={q}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") setSearch(q); }}
              className="ml-auto px-3 py-1.5 bg-t-bg1 border border-t-dim rounded-lg text-sm text-t-hi placeholder-t-gdim font-mono-t focus:outline-none focus:border-t-mid w-48"
            />
            {q !== search && (
              <button
                onClick={() => setSearch(q)}
                className="px-3 py-1.5 bg-t-bg2 text-t-hi text-xs font-mono-t rounded-lg border border-t-mid"
              >
                Search
              </button>
            )}
          </div>
        </div>

        {/* Results count */}
        {!isLoading && !isError && (
          <p className="text-xs text-t-gdim font-mono-t">
            {findings.length} finding{findings.length !== 1 ? "s" : ""}
            {search && ` matching "${search}"`}
          </p>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-20 rounded-xl bg-t-bg1 border border-t-dim animate-pulse" />
            ))}
          </div>
        )}

        {/* Error */}
        {isError && (
          <BracketFrame className="bg-t-bg1 rounded-2xl px-5 py-10 text-center" bracketSize={12}>
            <SectionLabel as="p" className="mb-2 text-t-gdim">// Research Feed</SectionLabel>
            <p className="text-t-hi font-semibold mb-1">Could not load findings</p>
            <p className="text-t-muted text-sm">
              The agent_memory table may be empty. Findings populate after the Researcher agent runs (7 AM ET daily).
            </p>
          </BracketFrame>
        )}

        {/* Empty */}
        {!isLoading && !isError && findings.length === 0 && (
          <BracketFrame className="bg-t-bg1 rounded-2xl px-5 py-10 text-center" bracketSize={12}>
            <SectionLabel as="p" className="mb-2 text-t-gdim">// No Findings</SectionLabel>
            <p className="text-t-hi font-semibold mb-1">No findings match your filters</p>
            <p className="text-t-muted text-sm">
              Try widening the window or clearing the memory type filter.
            </p>
          </BracketFrame>
        )}

        {/* Cards */}
        {!isLoading && !isError && findings.length > 0 && (
          <div className="space-y-2">
            {findings.map(f => (
              <FindingCard key={f.id} finding={f} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
