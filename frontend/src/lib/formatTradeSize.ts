export function formatQty(qty: number, symbol: string): string {
  const base = symbol.includes("/") ? symbol.split("/")[0] : symbol;
  const abs = Math.abs(qty);
  if (abs >= 100_000) return `${qty.toFixed(0)} ${base}`;
  if (abs >= 100)     return `${qty.toFixed(2)} ${base}`;
  if (abs >= 1)       return `${qty.toFixed(4)} ${base}`;
  return `${qty.toFixed(8)} ${base}`;
}

export function formatUSD(amount: number): string {
  const abs = Math.abs(amount);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return amount < 0 ? `-$${formatted}` : `$${formatted}`;
}

export function formatTradeSize(qty: number, symbol: string, costBasis: number): string {
  return `${formatQty(qty, symbol)} (${formatUSD(costBasis)})`;
}
