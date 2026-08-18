/**
 * VaultArchivedStub — single shared placeholder for demoted Vault routes.
 *
 * Brock 2026-08-18: 26 individual trailer pages is real build time for zero
 * functional benefit. ONE shared static component gets the same outcome —
 * no data fetching, no heavy children, no crash surface — at a fraction of
 * the cost.
 *
 * HARD REQUIREMENT (also from Brock): this component makes ZERO network
 * calls. No useQuery, no useEffect-with-fetch, no store subscriptions that
 * trigger fetches. The real page components stay in the codebase but are
 * NOT imported for these routes — otherwise their data hooks still mount.
 *
 * Original crash class: strategy-journal endpoints fanned out 40 parallel
 * queries on mount and OOM-killed the container twice. Static stub =
 * that class doesn't exist.
 *
 * To restore a page: change its route in App.tsx from <VaultArchivedStub />
 * back to <RealPageComponent />. One-line change.
 */
import { Link, useLocation } from "react-router-dom";

export default function VaultArchivedStub({ pageName }: { pageName?: string }) {
  const location = useLocation();
  const displayName = pageName || _humanizeRoute(location.pathname);

  return (
    <div
      className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-6"
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        color: "#7a8a7a",
        background: "transparent",
      }}
    >
      <div className="max-w-md w-full">
        <div
          className="rounded-lg border p-8"
          style={{
            borderColor: "rgba(74,222,128,0.15)",
            background: "rgba(10,16,10,0.4)",
          }}
        >
          <div
            className="text-[10px] uppercase tracking-widest mb-3"
            style={{ color: "#4ade80", opacity: 0.7 }}
          >
            // ARCHIVED
          </div>
          <h1
            className="text-2xl mb-4"
            style={{ color: "#e5e7eb", fontWeight: 500 }}
          >
            {displayName}
          </h1>
          <p
            className="text-sm leading-relaxed mb-6"
            style={{ color: "#8a9a8a" }}
          >
            This page is archived. Enable it when you're ready.
          </p>
          <p
            className="text-xs leading-relaxed mb-6"
            style={{ color: "#5a6a5a" }}
          >
            The component still exists in the codebase. Restoring is a
            routing change, not a rebuild.
          </p>
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="text-sm px-4 py-2 rounded transition-colors"
              style={{
                color: "#4ade80",
                border: "1px solid rgba(74,222,128,0.3)",
                background: "rgba(74,222,128,0.05)",
                textDecoration: "none",
              }}
            >
              ← Dashboard
            </Link>
            <Link
              to="/strategy"
              className="text-sm px-4 py-2 rounded transition-colors"
              style={{
                color: "#7a8a7a",
                border: "1px solid rgba(74,222,128,0.15)",
                background: "transparent",
                textDecoration: "none",
              }}
            >
              Strategy Lab
            </Link>
          </div>
        </div>
        <div
          className="mt-4 text-[10px] tracking-widest text-center"
          style={{ color: "#4a5a4a" }}
        >
          route: {location.pathname}
        </div>
      </div>
    </div>
  );
}

function _humanizeRoute(path: string): string {
  const last = (path || "").replace(/\/+$/, "").split("/").pop() || "page";
  return last
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
