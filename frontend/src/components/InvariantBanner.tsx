/**
 * Global banner surfacing RED / AMBER invariants from Layer 3.
 * Polls /api/admin/invariants every 60s and renders a fixed strip at
 * the top of every page when any check is not green.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import client from "@/api/client";

interface InvariantResult {
  check_id: string;
  level: "green" | "amber" | "red";
  actual: any;
  expected: any;
  delta: number | null;
  detail: string;
  ts: string;
}

interface Snapshot {
  as_of?: string;
  results?: InvariantResult[];
  error?: string;
}

export default function InvariantBanner() {
  const [dismissed, setDismissed] = useState(false);
  const { data } = useQuery<Snapshot>({
    queryKey: ["invariants"],
    queryFn: async () => (await client.get<Snapshot>("/admin/invariants")).data,
    refetchInterval: 60_000,
    retry: false,
    staleTime: 30_000,
  });

  if (dismissed) return null;
  const results = data?.results ?? [];
  const reds = results.filter((r) => r.level === "red");
  const ambers = results.filter((r) => r.level === "amber");
  if (reds.length === 0 && ambers.length === 0) return null;

  const bg = reds.length > 0 ? "#7f1d1d" : "#78350f";
  const label = reds.length > 0
    ? `${reds.length} INVARIANT BREACH${reds.length === 1 ? "" : "ES"}`
    : `${ambers.length} INVARIANT WARNING${ambers.length === 1 ? "" : "S"}`;

  return (
    <div
      style={{
        position: "sticky",
        top: 0,
        zIndex: 9999,
        background: bg,
        color: "#fefefe",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
        padding: "6px 14px",
        borderBottom: "1px solid rgba(255,255,255,0.15)",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <span style={{ fontWeight: 700, letterSpacing: "0.05em" }}>[{label}]</span>
      <div style={{ flex: 1, display: "flex", gap: 12, overflowX: "auto" }}>
        {[...reds, ...ambers].slice(0, 6).map((r) => (
          <span
            key={r.check_id + r.ts}
            title={r.detail}
            style={{
              padding: "2px 8px",
              borderRadius: 3,
              background: r.level === "red" ? "rgba(0,0,0,0.35)" : "rgba(0,0,0,0.2)",
              whiteSpace: "nowrap",
            }}
          >
            <b>{r.check_id}</b> · {r.detail.length > 80 ? r.detail.slice(0, 80) + "…" : r.detail}
          </span>
        ))}
      </div>
      <button
        onClick={() => setDismissed(true)}
        style={{
          background: "transparent",
          border: "1px solid rgba(255,255,255,0.3)",
          color: "#fefefe",
          padding: "2px 10px",
          fontSize: 11,
          cursor: "pointer",
          borderRadius: 3,
        }}
        title="Hide until next page load"
      >
        ×
      </button>
    </div>
  );
}
