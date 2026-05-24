import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMyTier } from "@/api/tiers";
import { useTierStore } from "@/store/tierStore";
import type { Entitlements } from "@/api/tiers";

/**
 * Loads the user's tier from the API, syncs to tierStore, and exposes helpers.
 * Use `can()` for boolean feature gates, `canNum()` for numeric limits.
 */
export function useEntitlement() {
  const store = useTierStore();

  const { data } = useQuery({
    queryKey: ["tier-me"],
    queryFn: getMyTier,
    staleTime: 1000 * 60 * 5,
  });

  useEffect(() => {
    if (data) store.setTierData(data);
  }, [data]);

  return {
    tier: store.tier,
    entitlements: store.entitlements,
    loaded: store.loaded,
    /** True if the boolean feature is enabled for this tier */
    can: (feature: keyof Entitlements): boolean => store.can(feature),
    /** True if the numeric limit is >= required (-1 = unlimited) */
    canNum: (feature: keyof Entitlements, required: number): boolean => store.canNum(feature, required),
    /** Get the raw numeric value of a limit (-1 = unlimited) */
    limit: (feature: keyof Entitlements): number => {
      const val = store.entitlements[feature];
      return typeof val === "number" ? val : 0;
    },
  };
}
