import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";

interface RegimeStripProps {
  className?: string;
}

function RegimePill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className={cn("flex items-center gap-1.5 px-2.5 py-1 rounded-sm border text-xs font-mono-t", color)}>
      <span className="text-[9px] uppercase tracking-widest opacity-60">{label}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}

export function RegimeStrip({ className }: RegimeStripProps) {
  const { data } = useQuery({
    queryKey: ["regime-strip"],
    queryFn: () =>
      fetch("/api/bots/regime", {
        headers: { Authorization: `Bearer ${localStorage.getItem("bmg_token") ?? ""}` },
      }).then((r) => r.json()).catch(() => null),
    staleTime: 300_000,
    retry: 0,
  });

  const regime = data?.regime ?? data;
  if (!regime) return null;

  const vix = regime.vix ?? regime.vix_level;
  const trend = regime.market_trend ?? regime.trend;
  const btcDom = regime.btc_dominance ?? regime.btc_dom;

  const vixColor =
    !vix ? "border-t-dim text-t-muted" :
    vix < 20  ? "border-t-mid/40 text-t-green bg-t-green/5" :
    vix < 30  ? "border-amber-500/30 text-t-amber bg-amber-500/5" :
               "border-red-500/30 text-t-red bg-red-500/5";

  const trendColor =
    !trend ? "border-t-dim text-t-muted" :
    trend === "bull" ? "border-t-mid/40 text-t-green bg-t-green/5" :
    trend === "bear" ? "border-red-500/30 text-t-red bg-red-500/5" :
                       "border-t-dim text-t-mid2 bg-t-bg2";

  return (
    <div className={cn("flex items-center gap-2 flex-wrap", className)}>
      {vix != null && (
        <RegimePill label="VIX" value={Number(vix).toFixed(1)} color={vixColor} />
      )}
      {trend && (
        <RegimePill label="TREND" value={String(trend).toUpperCase()} color={trendColor} />
      )}
      {btcDom != null && (
        <RegimePill
          label="BTC DOM"
          value={`${Number(btcDom).toFixed(1)}%`}
          color="border-t-dim text-t-mid2 bg-t-bg2"
        />
      )}
    </div>
  );
}
