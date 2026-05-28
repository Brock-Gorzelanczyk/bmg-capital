import { cn } from "@/lib/utils";
import type { OptionContract, OptionsLeg } from "@/types/options";

interface Props {
  calls: OptionContract[];
  puts: OptionContract[];
  underlyingPrice: number;
  legs: OptionsLeg[];
  onAddLeg: (contract: OptionContract, side: "buy" | "sell") => void;
}

function fmt(n: number, digits = 2) {
  return n.toFixed(digits);
}

function pct(n: number) {
  return (n * 100).toFixed(1) + "%";
}

function ContractCell({
  contract,
  side,
  onAdd,
  highlight,
}: {
  contract: OptionContract;
  side: "buy" | "sell";
  onAdd: () => void;
  highlight: boolean;
}) {
  return (
    <button
      onClick={onAdd}
      title={`${side === "buy" ? "Buy" : "Sell"} ${contract.optionType} @ $${contract.strike}`}
      className={cn(
        "w-full text-left px-2 py-1 rounded transition-colors text-xs",
        highlight ? "bg-[#334155]" : "hover:bg-[var(--bg-elevated-2)]"
      )}
    >
      <span className={cn("font-mono", side === "buy" ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
        {side === "buy" ? "B" : "S"}
      </span>{" "}
      <span className="text-[var(--text-secondary)]">${fmt(contract.bid)}</span>
      <span className="text-[var(--text-tertiary)]"> / </span>
      <span className="text-[var(--text-secondary)]">${fmt(contract.ask)}</span>
    </button>
  );
}

export default function OptionsChain({ calls, puts, underlyingPrice, legs, onAddLeg }: Props) {
  const legSymbols = new Set(legs.map((l) => l.contract.symbol));

  // Align calls and puts by strike
  const allStrikes = Array.from(
    new Set([...calls.map((c) => c.strike), ...puts.map((p) => p.strike)])
  ).sort((a, b) => a - b);

  const callByStrike = new Map(calls.map((c) => [c.strike, c]));
  const putByStrike = new Map(puts.map((p) => [p.strike, p]));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-[var(--border-emphasis)]">
            <th className="text-left px-2 py-2 text-[var(--text-tertiary)] font-medium w-[120px]">Call Bid/Ask</th>
            <th className="text-center px-2 py-2 text-[var(--text-tertiary)] font-medium w-14">Δ</th>
            <th className="text-center px-2 py-2 text-[var(--text-tertiary)] font-medium w-14">IV</th>
            <th className="text-center px-2 py-2 text-[var(--text-tertiary)] font-bold w-20 bg-[var(--bg-elevated)]">Strike</th>
            <th className="text-center px-2 py-2 text-[var(--text-tertiary)] font-medium w-14">IV</th>
            <th className="text-center px-2 py-2 text-[var(--text-tertiary)] font-medium w-14">Δ</th>
            <th className="text-right px-2 py-2 text-[var(--text-tertiary)] font-medium w-[120px]">Put Bid/Ask</th>
          </tr>
        </thead>
        <tbody>
          {allStrikes.map((strike) => {
            const call = callByStrike.get(strike);
            const put = putByStrike.get(strike);
            const atm = Math.abs(strike - underlyingPrice) < (allStrikes[1] - allStrikes[0]) * 0.75;

            return (
              <tr
                key={strike}
                className={cn(
                  "border-b border-[var(--border-subtle)]/50 transition-colors",
                  atm && "bg-[var(--bg-elevated-2)]/30"
                )}
              >
                {/* Call columns */}
                {call ? (
                  <>
                    <td className="px-1 py-0.5">
                      <div className="flex gap-1">
                        <ContractCell
                          contract={call}
                          side="buy"
                          onAdd={() => onAddLeg(call, "buy")}
                          highlight={legSymbols.has(call.symbol)}
                        />
                        <ContractCell
                          contract={call}
                          side="sell"
                          onAdd={() => onAddLeg(call, "sell")}
                          highlight={legSymbols.has(call.symbol)}
                        />
                      </div>
                    </td>
                    <td className="text-center px-2 py-0.5 font-mono text-[var(--text-secondary)]">
                      {fmt(call.delta, 2)}
                    </td>
                    <td className="text-center px-2 py-0.5 font-mono text-[var(--text-tertiary)]">
                      {pct(call.impliedVolatility)}
                    </td>
                  </>
                ) : (
                  <td colSpan={3} />
                )}

                {/* Strike column */}
                <td
                  className={cn(
                    "text-center px-2 py-0.5 font-mono font-bold bg-[var(--bg-elevated)]",
                    atm ? "text-amber-400" : "text-[var(--text-secondary)]"
                  )}
                >
                  ${strike % 1 === 0 ? strike : fmt(strike)}
                  {atm && <span className="ml-1 text-[9px] text-amber-600">ATM</span>}
                </td>

                {/* Put columns */}
                {put ? (
                  <>
                    <td className="text-center px-2 py-0.5 font-mono text-[var(--text-tertiary)]">
                      {pct(put.impliedVolatility)}
                    </td>
                    <td className="text-center px-2 py-0.5 font-mono text-[var(--text-secondary)]">
                      {fmt(put.delta, 2)}
                    </td>
                    <td className="px-1 py-0.5">
                      <div className="flex gap-1 justify-end">
                        <ContractCell
                          contract={put}
                          side="buy"
                          onAdd={() => onAddLeg(put, "buy")}
                          highlight={legSymbols.has(put.symbol)}
                        />
                        <ContractCell
                          contract={put}
                          side="sell"
                          onAdd={() => onAddLeg(put, "sell")}
                          highlight={legSymbols.has(put.symbol)}
                        />
                      </div>
                    </td>
                  </>
                ) : (
                  <td colSpan={3} />
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
