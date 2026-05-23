export interface OptionContract {
  symbol: string;          // OCC symbol e.g. AAPL240119C00150000
  strike: number;
  expiration: string;      // YYYY-MM-DD
  optionType: "call" | "put";
  bid: number;
  ask: number;
  last: number;
  volume: number;
  openInterest: number;
  impliedVolatility: number;  // 0–1 decimal
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  inTheMoney: boolean;
}

export interface OptionsChain {
  underlying: string;
  underlyingPrice: number;
  expiration: string;
  calls: OptionContract[];
  puts: OptionContract[];
  source: "live" | "synthetic";
}

export type LegSide = "buy" | "sell";

export interface OptionsLeg {
  contract: OptionContract;
  side: LegSide;
  qty: number;
}

export interface SpreadResult {
  legs: OptionsLeg[];
  netPremium: number;     // negative = debit (cost), positive = credit (received)
  maxGain: number | null; // null = unlimited
  maxLoss: number | null; // null = unlimited
  breakEvens: number[];
  strategy: string;       // e.g. "Long Call", "Bull Call Spread", "Iron Condor"
}

/** Compute P&L at expiration for a set of legs across a price range */
export function computePL(legs: OptionsLeg[], prices: number[]): number[] {
  return prices.map((price) => {
    let pnl = 0;
    for (const leg of legs) {
      const { contract, side, qty } = leg;
      const intrinsic =
        contract.optionType === "call"
          ? Math.max(0, price - contract.strike)
          : Math.max(0, contract.strike - price);
      const midPremium = (contract.bid + contract.ask) / 2;
      // Long = pay premium, Short = collect premium
      const legPnl = side === "buy"
        ? (intrinsic - midPremium) * qty * 100
        : (midPremium - intrinsic) * qty * 100;
      pnl += legPnl;
    }
    return Math.round(pnl * 100) / 100;
  });
}

/** Identify spread strategy name from legs */
export function identifyStrategy(legs: OptionsLeg[]): string {
  if (legs.length === 0) return "—";
  if (legs.length === 1) {
    const { side, contract } = legs[0];
    return `${side === "buy" ? "Long" : "Short"} ${contract.optionType === "call" ? "Call" : "Put"}`;
  }
  const calls = legs.filter((l) => l.contract.optionType === "call");
  const puts = legs.filter((l) => l.contract.optionType === "put");
  if (calls.length === 2 && puts.length === 0) {
    const buys = calls.filter((l) => l.side === "buy");
    if (buys.length === 1) return "Bull Call Spread";
    if (buys.length === 0) return "Bear Call Spread";
  }
  if (puts.length === 2 && calls.length === 0) {
    const buys = puts.filter((l) => l.side === "buy");
    if (buys.length === 1) return "Bear Put Spread";
    if (buys.length === 0) return "Bull Put Spread";
  }
  if (calls.length === 2 && puts.length === 2) return "Iron Condor";
  if (calls.length === 1 && puts.length === 1) {
    const allBuys = legs.every((l) => l.side === "buy");
    const allSells = legs.every((l) => l.side === "sell");
    if (allBuys) return "Long Straddle";
    if (allSells) return "Short Straddle";
  }
  return "Custom Spread";
}
