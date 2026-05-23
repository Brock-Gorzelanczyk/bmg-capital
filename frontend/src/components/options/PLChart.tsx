import { useMemo } from "react";
import { computePL } from "@/types/options";
import type { OptionsLeg } from "@/types/options";

interface Props {
  legs: OptionsLeg[];
  underlyingPrice: number;
}

const WIDTH = 600;
const HEIGHT = 200;
const PAD = { top: 16, right: 16, bottom: 28, left: 52 };

export default function PLChart({ legs, underlyingPrice }: Props) {
  const { points, minPL, maxPL, breakEvens, priceRange } = useMemo(() => {
    if (legs.length === 0) return { points: [], minPL: 0, maxPL: 0, breakEvens: [], priceRange: [0, 0] };

    const strikes = legs.map((l) => l.contract.strike);
    const lo = Math.min(...strikes) * 0.8;
    const hi = Math.max(...strikes) * 1.2;
    const step = (hi - lo) / 200;
    const prices = Array.from({ length: 201 }, (_, i) => lo + i * step);
    const pls = computePL(legs, prices);

    const minPL = Math.min(...pls);
    const maxPL = Math.max(...pls);

    // Find breakeven crossings
    const breakEvens: number[] = [];
    for (let i = 1; i < pls.length; i++) {
      if ((pls[i - 1] < 0 && pls[i] >= 0) || (pls[i - 1] >= 0 && pls[i] < 0)) {
        const t = -pls[i - 1] / (pls[i] - pls[i - 1]);
        breakEvens.push(prices[i - 1] + t * step);
      }
    }

    const points = prices.map((price, i) => ({ price, pl: pls[i] }));
    return { points, minPL, maxPL, breakEvens, priceRange: [lo, hi] as [number, number] };
  }, [legs]);

  if (legs.length === 0) {
    return (
      <div className="h-[200px] flex items-center justify-center text-[#475569] text-sm">
        Add legs to see P&amp;L chart
      </div>
    );
  }

  const chartW = WIDTH - PAD.left - PAD.right;
  const chartH = HEIGHT - PAD.top - PAD.bottom;
  const [lo, hi] = priceRange;

  const toX = (price: number) => PAD.left + ((price - lo) / (hi - lo)) * chartW;
  const plRange = Math.max(Math.abs(minPL), Math.abs(maxPL)) * 1.1 || 100;
  const toY = (pl: number) => PAD.top + chartH / 2 - (pl / plRange) * (chartH / 2);

  // Build SVG path — split into profit (green) and loss (red) segments
  const pathProfit: string[] = [];
  const pathLoss: string[] = [];

  for (let i = 0; i < points.length; i++) {
    const x = toX(points[i].price);
    const y = toY(points[i].pl);
    const cmd = i === 0 ? "M" : "L";
    if (points[i].pl >= 0) {
      pathProfit.push(`${cmd}${x},${y}`);
      if (i > 0 && points[i - 1].pl < 0) {
        // crossing from loss to profit — add connection
        pathProfit.unshift(`M${toX(points[i - 1].price)},${toY(0)}`);
      }
    } else {
      pathLoss.push(`${cmd}${x},${y}`);
      if (i > 0 && points[i - 1].pl >= 0) {
        pathLoss.unshift(`M${toX(points[i - 1].price)},${toY(0)}`);
      }
    }
  }

  const zeroY = toY(0);
  const underlyingX = toX(underlyingPrice);

  // Y-axis labels
  const yLabels = [plRange, plRange / 2, 0, -plRange / 2, -plRange].map((v) => ({
    val: v,
    y: toY(v),
    label: v === 0 ? "$0" : (v > 0 ? "+" : "") + (v >= 1000 || v <= -1000 ? `$${(v / 1000).toFixed(1)}k` : `$${Math.round(v)}`),
  }));

  // X-axis labels: lo, mid, hi
  const xLabels = [lo, (lo + hi) / 2, hi].map((v) => ({
    val: v,
    x: toX(v),
    label: `$${v >= 1000 ? (v / 1000).toFixed(1) + "k" : Math.round(v)}`,
  }));

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full h-auto"
      style={{ maxHeight: 220 }}
    >
      {/* Grid */}
      <line x1={PAD.left} y1={zeroY} x2={WIDTH - PAD.right} y2={zeroY} stroke="#3f3f46" strokeWidth={1} />
      <line x1={underlyingX} y1={PAD.top} x2={underlyingX} y2={HEIGHT - PAD.bottom} stroke="#a16207" strokeWidth={1} strokeDasharray="4,3" />

      {/* P&L paths */}
      {pathProfit.length > 0 && (
        <path d={pathProfit.join(" ")} fill="none" stroke="#34d399" strokeWidth={2} strokeLinejoin="round" />
      )}
      {pathLoss.length > 0 && (
        <path d={pathLoss.join(" ")} fill="none" stroke="#f43f5e" strokeWidth={2} strokeLinejoin="round" />
      )}

      {/* Breakeven markers */}
      {breakEvens.map((be, i) => (
        <g key={i}>
          <circle cx={toX(be)} cy={zeroY} r={3} fill="#fbbf24" />
          <text x={toX(be)} y={zeroY - 6} textAnchor="middle" fontSize={9} fill="#fbbf24">
            ${Math.round(be)}
          </text>
        </g>
      ))}

      {/* Underlying price label */}
      <text x={underlyingX} y={HEIGHT - PAD.bottom + 14} textAnchor="middle" fontSize={9} fill="#a16207">
        ${underlyingPrice.toFixed(2)}
      </text>

      {/* Y-axis labels */}
      {yLabels.map(({ y, label }) => (
        <text key={label} x={PAD.left - 4} y={y + 3} textAnchor="end" fontSize={9} fill="#71717a">
          {label}
        </text>
      ))}

      {/* X-axis labels */}
      {xLabels.map(({ x, label }) => (
        <text key={label} x={x} y={HEIGHT - PAD.bottom + 10} textAnchor="middle" fontSize={9} fill="#52525b">
          {label}
        </text>
      ))}
    </svg>
  );
}
