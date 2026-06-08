import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number | null | undefined, decimals = 2): string {
  if (value == null || !isFinite(value as number)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * Tier-based price formatter — matches TradingView precision for low-priced crypto.
 * Returns a display string without the $ sign.
 *   >= $1000  → 2 decimals  (BTC, ETH)
 *   >= $1     → 4 decimals  (SOL, AAPL)
 *   >= $0.01  → 5 decimals  (DOGE, ADA)
 *   >= $0.0001→ 6 decimals  (SHIB tier)
 *   < $0.0001 → 8 decimals  (micro caps)
 * minimumFractionDigits=2 so trailing zeros are natural, not forced past 2dp.
 */
export function formatPrice(price: number | null | undefined): string {
  if (price == null || !isFinite(price as number)) return "—";
  const abs = Math.abs(price as number);
  let maxDecimals: number;
  if (abs >= 1000) maxDecimals = 2;
  else if (abs >= 1) maxDecimals = 4;
  else if (abs >= 0.01) maxDecimals = 5;
  else if (abs >= 0.0001) maxDecimals = 6;
  else maxDecimals = 8;
  return (price as number).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: maxDecimals,
  });
}

export function formatPercent(value: number, decimals = 2): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

export function formatVolume(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toString();
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const diff = Math.max(0, Date.now() - new Date(dateStr).getTime());
  const days = Math.floor(diff / 86_400_000);
  const hrs  = Math.floor(diff / 3_600_000);
  const mins = Math.floor(diff / 60_000);
  if (days >= 1) return `${days}d ago`;
  if (hrs  >= 1) return `${hrs}h ago`;
  if (mins >= 1) return `${mins}m ago`;
  return "just now";
}

export function formatShareQty(qty: number): string {
  if (qty % 1 === 0) return qty.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return qty.toFixed(4).replace(/\.?0+$/, "");
}
