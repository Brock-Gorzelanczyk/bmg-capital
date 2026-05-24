export type ChartType = "candle" | "bar" | "line" | "area" | "heikinashi";
export type DrawingTool = "cursor" | "hline" | "trendline" | "rect" | "fib" | "text" | "eraser";

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
  type: "hline" | "trendline" | "rect" | "fib" | "text";
  price?: number;
  p1?: { time: number; price: number };
  p2?: { time: number; price: number };
  color: string;
  label?: string;
}
