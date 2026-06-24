import { useQuery } from "@tanstack/react-query";
import { BracketFrame, SectionLabel } from "@/components/design";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

interface LiveSlice {
  key: string;
  label: string;
  dollars: number;
  pct: number;
  color: string;
  position_count: number;
}

interface AllocationLiveResponse {
  as_of: string;
  total_portfolio_value: number;
  deployed_value: number;
  cash_value: number;
  slices: LiveSlice[];
}

async function fetchAllocationLive(): Promise<AllocationLiveResponse> {
  const { data } = await client.get<AllocationLiveResponse>("/portfolio/allocation-live");
  return data;
}

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtUsd(dollars: number): string {
  if (dollars >= 1_000_000) return `$${(dollars / 1_000_000).toFixed(2)}M`;
  if (dollars >= 10_000)    return `$${(dollars / 1_000).toFixed(1)}k`;
  return dollars.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function fmtFullUsd(dollars: number): string {
  return dollars.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

const SLEEVE_LABELS: Record<string, string> = {
  stocks:  "Stocks",
  crypto:  "Crypto",
  options: "Options",
  quant:   "Quant",
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function DeploymentSummary() {
  const { data, isLoading } = useQuery({
    queryKey: ["allocation-live"],
    queryFn: fetchAllocationLive,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (isLoading || !data) {
    return (
      <BracketFrame className="rounded-2xl p-5 mb-8 bg-t-bg1 border border-t-dim">
        <SectionLabel as="p" className="mb-3">Capital Deployment</SectionLabel>
        <div className="h-24 animate-pulse">
          <div className="h-8 w-48 bg-t-bg2 rounded mb-3" />
          <div className="h-3 w-full bg-t-bg2 rounded mb-2" />
          <div className="h-3 w-3/4 bg-t-bg2 rounded" />
        </div>
      </BracketFrame>
    );
  }

  const total    = data.total_portfolio_value;
  const deployed = data.deployed_value;
  const cash     = data.cash_value;

  const deployedPct = total > 0 ? (deployed / total) * 100 : 0;
  const cashPct     = total > 0 ? (cash / total) * 100     : 0;

  // Per-sleeve deployment % vs total allocation (excludes the cash slice).
  const sleeveSlices = (data.slices ?? []).filter((s) => s.key !== "cash");

  return (
    <BracketFrame className="rounded-2xl p-5 mb-8 bg-t-bg1 border border-t-dim">
      <div className="flex items-center justify-between mb-4">
        <SectionLabel as="p">Capital Deployment</SectionLabel>
        <span className="text-[10px] text-t-gdim font-mono-t tabular-nums">
          live · refreshes every 30s
        </span>
      </div>

      {/* Headline: allocated */}
      <div className="mb-4">
        <p className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t mb-1">
          Allocated
        </p>
        <p className="text-3xl font-bold text-t-hi tabular-nums font-mono-t">
          {fmtFullUsd(total)}
        </p>
      </div>

      {/* Deployed / cash secondaries */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t mb-1">
            Deployed
          </p>
          <p className="text-lg font-semibold text-t-green tabular-nums font-mono-t">
            {fmtFullUsd(deployed)}
            <span className="text-xs text-t-muted font-normal ml-1.5">
              ({deployedPct.toFixed(1)}%)
            </span>
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t mb-1">
            Cash buffer
          </p>
          <p className="text-lg font-semibold text-t-mid2 tabular-nums font-mono-t">
            {fmtFullUsd(cash)}
            <span className="text-xs text-t-muted font-normal ml-1.5">
              ({cashPct.toFixed(1)}%)
            </span>
          </p>
        </div>
      </div>

      {/* Progress bar: deployed vs cash, butting together inside one rounded rect */}
      <div
        className="relative h-3 rounded-full overflow-hidden border border-t-dim bg-t-bg2 mb-3"
        role="img"
        aria-label={`${deployedPct.toFixed(0)} percent deployed, ${cashPct.toFixed(0)} percent cash`}
      >
        <div className="absolute inset-y-0 left-0 flex">
          <div
            className="bg-t-green"
            style={{ width: `${deployedPct}%`, transition: "width 400ms ease" }}
          />
          <div
            className="bg-t-mid/40"
            style={{ width: `${cashPct}%`, transition: "width 400ms ease" }}
          />
        </div>
      </div>

      {/* Per-sleeve mini-rows */}
      {sleeveSlices.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 pt-3 border-t border-t-dim/50">
          {sleeveSlices.map((s) => {
            const sleeveDeployedPct = total > 0 ? (s.dollars / total) * 100 : 0;
            const label = SLEEVE_LABELS[s.key] ?? s.label ?? s.key;
            return (
              <div key={s.key} className="flex items-center gap-2 text-[11px] font-mono-t">
                <span
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: s.color }}
                />
                <span className="text-t-mid2">{label} deployed</span>
                <span className={cn("font-semibold tabular-nums text-t-hi")}>
                  {sleeveDeployedPct.toFixed(1)}%
                </span>
                <span className="text-t-gdim tabular-nums">
                  ({fmtUsd(s.dollars)})
                </span>
              </div>
            );
          })}
        </div>
      )}
    </BracketFrame>
  );
}
