import { useQuery } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useExplainStore } from "@/store/explainStore";
import { getGlossaryTerms } from "@/api/explain";
import { FEATURES } from "@/config/features";

// Local lightweight definitions for instant tooltip (no API call needed)
const QUICK_DEFS: Record<string, string> = {
  "p/e ratio": "Price ÷ EPS. How much investors pay per $1 of annual earnings.",
  "eps": "Net income ÷ shares outstanding. The standard unit of profitability.",
  "ebitda": "Earnings before interest, taxes, depreciation & amortization.",
  "free cash flow": "Operating cash flow minus capital expenditures.",
  "market cap": "Stock price × shares outstanding. Total market value.",
  "beta": "Sensitivity to market moves. 1.5 = moves 50% more than the S&P 500.",
  "rsi": "Momentum oscillator 0–100. Above 70 = potentially overbought.",
  "macd": "Trend-following momentum indicator using two EMAs.",
  "sharpe ratio": "Return per unit of risk. Above 1.0 is considered good.",
  "max drawdown": "Largest peak-to-trough loss. A 50% drop needs 100% to recover.",
  "implied volatility": "Market's forecast of future price movement. High IV = expensive options.",
  "delta": "Option price change per $1 move in the stock.",
  "theta": "Daily value lost from time decay.",
  "short selling": "Borrow and sell shares, hoping to buy back cheaper.",
  "support": "Price level where buying tends to halt a decline.",
  "resistance": "Price level where selling tends to halt a rally.",
  "dividend yield": "Annual dividend ÷ stock price. Income per dollar invested.",
  "roe": "Net income ÷ equity. How efficiently management uses shareholder capital.",
  "gross margin": "Gross profit ÷ revenue. Core product profitability.",
  "book value": "Net assets per share (assets minus liabilities).",
  "enterprise value": "Market cap + debt − cash. True acquisition cost.",
  "inflation": "General rise in prices. Erodes purchasing power.",
  "yield curve": "Treasury rates across maturities. Inverted = recession predictor.",
  "stop loss": "Auto-sell order that triggers at your specified price to limit losses.",
  "limit order": "Order to buy or sell only at your specified price or better.",
  "market order": "Buy or sell immediately at the best available price.",
  "float": "Shares actually available to trade (excluding insider-locked shares).",
  "volume": "Shares traded in a period. High volume confirms price moves.",
};

// Terms we auto-detect and underline in body text
const DETECTABLE = Object.keys(QUICK_DEFS);

interface AnnotatedChunk {
  text: string;
  term?: string;
}

function tokenize(text: string): AnnotatedChunk[] {
  if (!FEATURES.EXPLAIN_THIS) return [{ text }];

  const sorted = [...DETECTABLE].sort((a, b) => b.length - a.length);
  const pattern = sorted.map((t) => t.replace(/[/()]/g, "\\$&")).join("|");
  const re = new RegExp(`(${pattern})`, "gi");
  const parts = text.split(re);
  return parts.map((part) => {
    const lower = part.toLowerCase();
    const match = DETECTABLE.find((t) => t === lower);
    return match ? { text: part, term: match } : { text: part };
  });
}

interface Props {
  children: string;
  className?: string;
}

export default function GlossaryTooltip({ children, className }: Props) {
  if (!FEATURES.EXPLAIN_THIS) return <span className={className}>{children}</span>;

  const explain = useExplainStore((s) => s.explain);
  const chunks = tokenize(children);
  const hasAny = chunks.some((c) => c.term);

  if (!hasAny) return <span className={className}>{children}</span>;

  return (
    <Tooltip.Provider delayDuration={300}>
      <span className={className}>
        {chunks.map((chunk, i) =>
          chunk.term ? (
            <Tooltip.Root key={i}>
              <Tooltip.Trigger asChild>
                <span
                  className="underline decoration-dotted decoration-zinc-600 cursor-help hover:decoration-zinc-400 transition-colors"
                  onClick={(e) => { e.stopPropagation(); explain(chunk.term!); }}
                >
                  {chunk.text}
                </span>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content
                  className="z-50 max-w-xs bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-300 shadow-xl"
                  sideOffset={5}
                >
                  <p className="font-semibold text-[var(--text-primary)] capitalize mb-1">{chunk.term}</p>
                  <p>{QUICK_DEFS[chunk.term]}</p>
                  <p className="text-zinc-600 mt-1">Click for full explanation →</p>
                  <Tooltip.Arrow className="fill-zinc-700" />
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          ) : (
            <span key={i}>{chunk.text}</span>
          )
        )}
      </span>
    </Tooltip.Provider>
  );
}
