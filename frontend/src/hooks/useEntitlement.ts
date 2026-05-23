import { useQuery } from "@tanstack/react-query";
import { getMyTier } from "@/api/tiers";
import type { TierFeatures } from "@/api/tiers";

const FREE_FEATURES: TierFeatures = {
  paper_trading: true,
  basic_screener: true,
  learn: true,
  watchlist_limit: 10,
  alerts_limit: 3,
  strategy_backtest: false,
  options_lab: false,
  social: true,
  ai_explain: false,
  advanced_charts: false,
};

export function useEntitlement() {
  const { data } = useQuery({
    queryKey: ["tier-me"],
    queryFn: getMyTier,
    staleTime: 1000 * 60 * 5,
  });

  const tier = data?.tier ?? "free";
  const features = data?.features ?? FREE_FEATURES;

  function can(feature: keyof TierFeatures): boolean {
    const v = features[feature];
    if (typeof v === "boolean") return v;
    return (v as number) !== 0;
  }

  return { tier, features, can };
}
