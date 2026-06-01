import type { IDockviewPanelProps } from "dockview";
import type React from "react";
import PositionBlotterWidget from "./widgets/PositionBlotterWidget";
import EquityCurveWidget from "./widgets/EquityCurveWidget";
import PnLCalendarWidget from "./widgets/PnLCalendarWidget";
import WatchlistWidget from "./widgets/WatchlistWidget";
import DailyRecapWidget from "./widgets/DailyRecapWidget";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const WIDGET_REGISTRY: Record<string, React.FunctionComponent<IDockviewPanelProps<any>>> = {
  "position-blotter": PositionBlotterWidget,
  "equity-curve": EquityCurveWidget,
  "pnl-calendar": PnLCalendarWidget,
  watchlist: WatchlistWidget,
  "daily-recap": DailyRecapWidget,
};

export const WIDGET_CATALOG = [
  {
    id: "position-blotter",
    title: "Position Blotter",
    icon: "📋",
    description: "Live paper trading positions",
    category: "Portfolio",
  },
  {
    id: "equity-curve",
    title: "Equity Curve",
    icon: "📈",
    description: "Portfolio performance chart",
    category: "Portfolio",
  },
  {
    id: "pnl-calendar",
    title: "P&L Calendar",
    icon: "📅",
    description: "Daily P&L history calendar",
    category: "Portfolio",
  },
  {
    id: "watchlist",
    title: "Watchlist",
    icon: "👁",
    description: "Track your symbols",
    category: "Research",
  },
  {
    id: "daily-recap",
    title: "Daily Recap",
    icon: "☀️",
    description: "AI morning brief",
    category: "AI",
  },
] as const;
