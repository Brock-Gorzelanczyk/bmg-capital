export type ChartType = "candle" | "bar" | "line" | "area" | "heikinashi";
export type DrawingTool = "cursor" | "hline" | "trendline" | "rect" | "fib" | "text" | "eraser" | "vline" | "channel" | "longpos" | "shortpos" | "arrow";

export interface HoveredBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Drawing {
  id: string;
  type: "hline" | "trendline" | "rect" | "fib" | "text" | "vline" | "channel" | "longpos" | "shortpos" | "arrow";
  price?: number;
  p1?: { time: number; price: number };
  p2?: { time: number; price: number };
  p3?: { time: number; price: number };
  color: string;
  label?: string;
  style?: {
    color?: string;
    lineWidth?: number;
    lineStyle?: "solid" | "dashed" | "dotted";
    fillColor?: string;
    fillOpacity?: number;
    extendLeft?: boolean;
    extendRight?: boolean;
  };
  metadata?: {
    label?: string;
    locked?: boolean;
  };
}
