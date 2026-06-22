import { useMemo, useRef, useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ForceGraph2D from "react-force-graph-2d";
import { Brain, RefreshCw, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/Skeleton";
import {
  getBrainGraph,
  type BrainNode,
  type BrainNodeType,
  type BrainEdge,
} from "@/api/brain";

// ── Constants ───────────────────────────────────────────────────────────────
const NODE_TYPES: BrainNodeType[] = [
  "session",
  "trade",
  "signal",
  "strategy",
  "symbol",
  "lesson",
];
const TIME_RANGES = [7, 30, 90] as const;
const LAYOUTS = ["force", "sequential", "radial"] as const;
type Layout = (typeof LAYOUTS)[number];

// ── Helpers ─────────────────────────────────────────────────────────────────
function timeAgo(iso?: string): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  if (!isFinite(diffMs) || diffMs < 0) return "—";
  const s = Math.floor(diffMs / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function metaTimestamp(n: BrainNode): number {
  // Pull a time-like value from meta for sequential sort.
  const m = n.meta ?? {};
  const candidates = [m.ts, m.timestamp, m.created_at, m.opened_at, m.date];
  for (const c of candidates) {
    if (!c) continue;
    const t = new Date(c).getTime();
    if (isFinite(t)) return t;
  }
  // Fallback: session ids like "session_2026-06-22_NY_AM" — try to extract date
  const match = n.id.match(/\d{4}-\d{2}-\d{2}/);
  if (match) {
    const t = new Date(match[0]).getTime();
    if (isFinite(t)) return t;
  }
  return 0;
}

// ── Page ────────────────────────────────────────────────────────────────────
// Cap rendered nodes to keep ForceGraph2D smooth. Backend can return 30K+ on
// a 30-day window; the canvas chokes far before then. When over cap, we
// truncate after sorting by (incidence desc, size desc) so the most-connected
// hubs survive.
const RENDER_NODE_CAP = 3000;

export default function BrainGraphPage() {
  // All filter state syncs to URL search params so a particular view is
  // bookmarkable / shareable. Defaults match the no-param case (omit from URL).
  const [searchParams, setSearchParams] = useSearchParams();

  const parsedDays = parseInt(searchParams.get("days") ?? "7", 10);
  const parsedMin = parseInt(searchParams.get("min") ?? "0", 10);
  const parsedLayout = searchParams.get("layout") as Layout | null;
  const parsedTypes = (() => {
    const t = searchParams.get("types");
    if (!t) return new Set(NODE_TYPES);
    const allowed = new Set<BrainNodeType>(NODE_TYPES);
    const out = new Set<BrainNodeType>();
    for (const x of t.split(",")) {
      const lower = x.toLowerCase() as BrainNodeType;
      if (allowed.has(lower)) out.add(lower);
    }
    return out.size > 0 ? out : new Set(NODE_TYPES);
  })();

  const [days, setDaysState] = useState<number>(
    [7, 30, 90].includes(parsedDays) ? parsedDays : 7,
  );
  const [activeTypes, setActiveTypesState] = useState<Set<BrainNodeType>>(parsedTypes);
  const [minConnections, setMinConnectionsState] = useState<number>(
    Number.isFinite(parsedMin) ? Math.max(0, Math.min(5, parsedMin)) : 0,
  );
  const [layout, setLayoutState] = useState<Layout>(
    (LAYOUTS as readonly string[]).includes(parsedLayout ?? "") ? (parsedLayout as Layout) : "force",
  );
  const [selectedNode, setSelectedNode] = useState<BrainNode | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [searchError, setSearchError] = useState<string | null>(null);
  const fgRef = useRef<any>(null);

  // URL-syncing setters — wrap useState updates with searchParams writes.
  const setDays = (next: number) => {
    setDaysState(next);
    const sp = new URLSearchParams(searchParams);
    if (next === 7) sp.delete("days"); else sp.set("days", String(next));
    setSearchParams(sp, { replace: true });
  };
  const setActiveTypes = (next: Set<BrainNodeType>) => {
    setActiveTypesState(next);
    const sp = new URLSearchParams(searchParams);
    if (next.size === NODE_TYPES.length) sp.delete("types");
    else sp.set("types", Array.from(next).sort().join(","));
    setSearchParams(sp, { replace: true });
  };
  const setMinConnections = (next: number) => {
    setMinConnectionsState(next);
    const sp = new URLSearchParams(searchParams);
    if (next === 0) sp.delete("min"); else sp.set("min", String(next));
    setSearchParams(sp, { replace: true });
  };
  const setLayout = (next: Layout) => {
    setLayoutState(next);
    const sp = new URLSearchParams(searchParams);
    if (next === "force") sp.delete("layout"); else sp.set("layout", next);
    setSearchParams(sp, { replace: true });
  };

  const { data, isLoading, isFetching, refetch, isError } = useQuery({
    queryKey: ["brain-graph", days],
    queryFn: () => getBrainGraph(days),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  /** Find a node by id (exact) or by label (case-insensitive substring),
   *  center the graph on it, zoom in, and open the side panel. */
  const handleSearch = (raw: string) => {
    setSearchError(null);
    const q = raw.trim();
    if (!q || !data) return;
    const lower = q.toLowerCase();
    const node =
      data.nodes.find((n) => n.id === q) ??
      data.nodes.find((n) => n.id.toLowerCase() === lower) ??
      data.nodes.find((n) => (n.label ?? "").toLowerCase().includes(lower));
    if (!node) {
      setSearchError("No node matches");
      return;
    }
    setSelectedNode(node);
    // The actual canvas position is set by the d3 simulation. Try to center.
    try {
      const live: any = data.nodes.find((n: any) => n.id === node.id);
      const x = live?.x;
      const y = live?.y;
      if (typeof x === "number" && typeof y === "number") {
        fgRef.current?.centerAt?.(x, y, 800);
        fgRef.current?.zoom?.(4, 800);
      }
    } catch {
      /* no-op — side panel still opens regardless */
    }
  };

  // Edge-incidence counts (computed once per data load) ────────────────────
  const incidenceMap = useMemo(() => {
    const m = new Map<string, number>();
    if (!data) return m;
    for (const e of data.edges) {
      m.set(e.source, (m.get(e.source) ?? 0) + 1);
      m.set(e.target, (m.get(e.target) ?? 0) + 1);
    }
    return m;
  }, [data]);

  // Filtered graph data ────────────────────────────────────────────────────
  // `truncated` is true when the visible-node count exceeded RENDER_NODE_CAP
  // and we sampled down to the top hubs to keep the canvas responsive.
  const { graphData, truncated, totalVisible } = useMemo(() => {
    if (!data) return { graphData: { nodes: [], links: [] }, truncated: false, totalVisible: 0 };
    // Type filter is case-insensitive — defensive against backend type-case
    // drift (we hit this exact bug during the Phase 4 audit).
    const wanted = new Set(Array.from(activeTypes).map((t) => String(t).toLowerCase()));
    let visibleNodes = data.nodes.filter((n) => {
      const t = String(n.type ?? "").toLowerCase();
      return wanted.has(t) && (incidenceMap.get(n.id) ?? 0) >= minConnections;
    });
    const totalVisibleCount = visibleNodes.length;
    let didTruncate = false;
    if (visibleNodes.length > RENDER_NODE_CAP) {
      didTruncate = true;
      visibleNodes = [...visibleNodes].sort((a, b) => {
        const ca = incidenceMap.get(a.id) ?? 0;
        const cb = incidenceMap.get(b.id) ?? 0;
        if (cb !== ca) return cb - ca;
        return (b.size ?? 0) - (a.size ?? 0);
      }).slice(0, RENDER_NODE_CAP);
    }
    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    const visibleEdges = data.edges.filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
    );

    // Sequential layout — sort nodes by time-like meta field.
    // Radial layout — bring most-connected node to the front so dagMode='radialout' anchors it.
    let nodesOut: BrainNode[] = visibleNodes;
    if (layout === "sequential") {
      nodesOut = [...visibleNodes].sort(
        (a, b) => metaTimestamp(a) - metaTimestamp(b),
      );
    } else if (layout === "radial") {
      let centerId: string | null = null;
      let best = -1;
      for (const n of visibleNodes) {
        const c = incidenceMap.get(n.id) ?? 0;
        if (c > best) {
          best = c;
          centerId = n.id;
        }
      }
      if (centerId) {
        nodesOut = [
          ...visibleNodes.filter((n) => n.id === centerId),
          ...visibleNodes.filter((n) => n.id !== centerId),
        ];
      }
    }

    return {
      graphData: {
        nodes: nodesOut.map((n) => ({ ...n })),
        links: visibleEdges.map((e) => ({ ...e })),
      },
      truncated: didTruncate,
      totalVisible: totalVisibleCount,
    };
  }, [data, activeTypes, minConnections, layout, incidenceMap]);

  // Re-cook simulation when layout switches.
  useEffect(() => {
    if (!fgRef.current) return;
    try {
      fgRef.current.d3ReheatSimulation?.();
    } catch {
      /* no-op */
    }
  }, [layout, graphData]);

  // Connected node ids for selected node ───────────────────────────────────
  const connectedToSelected = useMemo(() => {
    if (!selectedNode || !data) return [] as { id: string; type: string }[];
    const ids = new Set<string>();
    for (const e of data.edges) {
      if (e.source === selectedNode.id) ids.add(e.target);
      else if (e.target === selectedNode.id) ids.add(e.source);
    }
    const map = new Map(data.nodes.map((n) => [n.id, n.type] as const));
    return Array.from(ids).map((id) => ({ id, type: map.get(id) ?? "?" }));
  }, [selectedNode, data]);

  // ── Render ─────────────────────────────────────────────────────────────
  const dagMode =
    layout === "sequential" ? "lr" : layout === "radial" ? "radialout" : undefined;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5 animate-page-in">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5">
            // STRATEGY LAB · BRAIN
          </p>
          <h1 className="text-2xl font-bold text-t-hi flex items-center gap-2">
            <Brain size={22} className="text-violet-400" /> Knowledge Graph
          </h1>
          <p className="text-t-muted text-sm mt-1">
            Force-directed view of the last {days} days of trading activity —
            sessions, trades, signals, strategies, symbols, and lessons.
          </p>
        </div>
      </div>

      {/* Stats bar + refresh */}
      <div className="border border-t-dim bg-t-bg1 rounded-xl px-4 py-2.5 text-[10px] font-mono flex items-center gap-4 flex-wrap text-t-muted">
        <span>
          NODES{" "}
          <span className="text-t-hi font-bold">
            {data?.stats.node_count ?? 0}
          </span>
        </span>
        <span>
          EDGES{" "}
          <span className="text-t-hi font-bold">
            {data?.stats.edge_count ?? 0}
          </span>
        </span>
        <span>
          GENERATED{" "}
          <span className="text-violet-400 font-bold">
            {timeAgo(data?.stats.generated_at)}
          </span>
        </span>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="ml-auto flex items-center gap-1.5 bg-t-bg1 border border-t-dim hover:border-t-mid text-t-mid2 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw size={12} className={cn(isFetching && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* Filters row */}
      <div className="border border-t-dim bg-t-bg1 rounded-xl px-4 py-3 flex items-center justify-between gap-4 flex-wrap">
        {/* Left: time range */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-t-muted font-bold">
            RANGE
          </span>
          {TIME_RANGES.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "text-[10px] font-bold uppercase tracking-widest px-2.5 py-1.5 rounded border transition-colors",
                days === d
                  ? "bg-t-bg2 border-t-mid text-t-hi"
                  : "border-t-dim text-t-muted hover:text-t-hi",
              )}
            >
              {d}d
            </button>
          ))}
        </div>

        {/* Middle: node-type toggles */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] uppercase tracking-widest text-t-muted font-bold">
            TYPES
          </span>
          {NODE_TYPES.map((t) => {
            const on = activeTypes.has(t);
            return (
              <button
                key={t}
                onClick={() => {
                  const next = new Set(activeTypes);
                  if (on) next.delete(t);
                  else next.add(t);
                  setActiveTypes(next);
                }}
                className={cn(
                  "text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded border transition-colors",
                  on
                    ? "bg-t-bg2 border-t-mid text-t-hi"
                    : "border-t-dim text-t-muted hover:text-t-hi opacity-60",
                )}
              >
                {t}
              </button>
            );
          })}
        </div>

        {/* Right: min connections + layout */}
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-t-muted font-bold">
            MIN CONN
            <input
              type="range"
              min={0}
              max={5}
              step={1}
              value={minConnections}
              onChange={(e) => setMinConnections(Number(e.target.value))}
              className="accent-violet-400"
            />
            <span className="text-t-hi font-mono-t">{minConnections}</span>
          </label>

          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest text-t-muted font-bold">
              LAYOUT
            </span>
            {LAYOUTS.map((l) => (
              <label
                key={l}
                className={cn(
                  "text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded border cursor-pointer transition-colors",
                  layout === l
                    ? "bg-t-bg2 border-t-mid text-t-hi"
                    : "border-t-dim text-t-muted hover:text-t-hi",
                )}
              >
                <input
                  type="radio"
                  name="layout"
                  value={l}
                  checked={layout === l}
                  onChange={() => setLayout(l)}
                  className="sr-only"
                />
                {l}
              </label>
            ))}
          </div>

          {/* Node search — paste a node id or partial label, Enter to jump */}
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-t-muted" />
              <input
                type="text"
                placeholder="search node…"
                value={searchInput}
                onChange={(e) => { setSearchInput(e.target.value); setSearchError(null); }}
                onKeyDown={(e) => { if (e.key === "Enter") handleSearch(searchInput); }}
                className={cn(
                  "bg-t-bg2 border text-t-hi text-[11px] rounded pl-6 pr-2 py-1 w-40 outline-none",
                  searchError ? "border-t-red focus:border-t-red" : "border-t-dim focus:border-t-mid",
                )}
                aria-label="Search nodes by id or label"
              />
            </div>
            {searchError && (
              <span className="text-[10px] text-t-red">{searchError}</span>
            )}
          </div>
        </div>
      </div>

      {/* Main area: canvas + side panel */}
      <div className="relative grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4">
        {/* Canvas card */}
        <div className="border border-t-dim bg-t-bg1 rounded-xl overflow-hidden relative">
          {isLoading ? (
            <div className="p-4 space-y-3" style={{ height: "70vh" }}>
              <div className="flex items-center justify-between">
                <Skeleton h="12px" w="180px" />
                <Skeleton h="12px" w="100px" />
              </div>
              <Skeleton h="calc(100% - 32px)" className="rounded-2xl" />
            </div>
          ) : isError || data?.stats.error ? (
            <div
              className="flex flex-col items-center justify-center gap-3 text-center px-6"
              style={{ height: "70vh" }}
            >
              <p className="text-t-red text-sm font-semibold">
                {data?.stats.error ?? "Failed to load brain graph."}
              </p>
              <button
                onClick={() => refetch()}
                className="text-xs font-semibold border border-t-dim hover:border-t-mid text-t-mid2 px-3 py-1.5 rounded-lg"
              >
                Retry
              </button>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center text-t-muted text-sm gap-2 text-center px-6"
              style={{ height: "70vh" }}
            >
              <p>No graph data matches the current filters.</p>
              {data && data.nodes.length > 0 && (
                <p className="text-[10px] text-t-mid">
                  API returned {data.nodes.length.toLocaleString()} nodes —
                  check the type-toggle pills and min-connections slider above.
                </p>
              )}
            </div>
          ) : (
            <div style={{ height: "70vh" }}>
              {truncated && (
                <div className="px-3 py-2 mb-2 text-[10px] bg-amber-900/20 border border-amber-700/30 rounded text-amber-300">
                  Rendering top {RENDER_NODE_CAP.toLocaleString()} of{" "}
                  {totalVisible.toLocaleString()} visible nodes (by edge count) to
                  keep the canvas responsive. Narrow the time range or raise
                  min-connections to see fewer.
                </div>
              )}
              <ForceGraph2D
                ref={fgRef}
                graphData={graphData as any}
                nodeRelSize={4}
                nodeVal={(n: any) => (n as BrainNode).size}
                nodeColor={(n: any) => (n as BrainNode).color}
                nodeLabel={(n: any) => (n as BrainNode).label}
                linkColor={(l: any) => {
                  const t = (l as BrainEdge).type;
                  if (t === "contains") return "rgba(148,163,184,0.35)";
                  if (t === "from_signal") return "rgba(167,139,250,0.55)";
                  if (t === "uses_strategy") return "rgba(34,197,94,0.55)";
                  if (t === "on_symbol") return "rgba(56,189,248,0.55)";
                  return "rgba(148,163,184,0.4)";
                }}
                linkWidth={0.6}
                cooldownTicks={150}
                dagMode={dagMode as any}
                dagLevelDistance={layout === "sequential" ? 80 : undefined}
                onNodeClick={(n: any) => setSelectedNode(n as BrainNode)}
                onBackgroundClick={() => setSelectedNode(null)}
                backgroundColor="rgba(0,0,0,0)"
              />
            </div>
          )}
        </div>

        {/* Side panel */}
        {selectedNode && (
          <div className="border border-t-dim bg-t-bg1 rounded-xl p-4 space-y-3 lg:sticky lg:top-4 h-fit">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-widest text-t-muted font-bold">
                  {selectedNode.type}
                </div>
                <div className="text-sm font-bold text-t-hi truncate">
                  {selectedNode.label}
                </div>
                <div className="text-[10px] text-t-muted font-mono mt-0.5 break-all">
                  {selectedNode.id}
                </div>
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-t-muted hover:text-t-hi rounded p-1"
                aria-label="Close"
              >
                <X size={14} />
              </button>
            </div>

            {/* Meta */}
            <div className="border-t border-t-dim pt-3 space-y-1">
              <div className="text-[10px] uppercase tracking-widest text-t-muted font-bold mb-1">
                META
              </div>
              {Object.keys(selectedNode.meta ?? {}).length === 0 ? (
                <div className="text-[10px] text-t-muted italic">empty</div>
              ) : (
                <div className="space-y-1 text-[10px] font-mono">
                  {Object.entries(selectedNode.meta).map(([k, v]) => (
                    <div key={k} className="flex items-baseline gap-2">
                      <span className="text-t-muted shrink-0">{k}</span>
                      <span className="text-t-hi truncate break-all">
                        {typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Connected nodes */}
            <div className="border-t border-t-dim pt-3 space-y-1">
              <div className="text-[10px] uppercase tracking-widest text-t-muted font-bold mb-1">
                CONNECTED ({connectedToSelected.length})
              </div>
              {connectedToSelected.length === 0 ? (
                <div className="text-[10px] text-t-muted italic">none</div>
              ) : (
                <ul className="space-y-1 text-[10px] font-mono max-h-64 overflow-y-auto">
                  {connectedToSelected.map((c) => (
                    <li key={c.id} className="flex items-baseline gap-2">
                      <span className="text-violet-400 shrink-0">
                        [{c.type}]
                      </span>
                      <span className="text-t-hi truncate break-all">
                        {c.id}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Bottom status line */}
      <div className="text-[10px] font-mono text-t-muted border-t border-t-dim pt-3">
        {new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })}{" "}
        <span className="text-violet-400">[brainGraph]</span>{" "}
        {graphData.nodes.length} nodes / {graphData.links.length} edges shown —
        layout: {layout}, range: {days}d.
      </div>
    </div>
  );
}
