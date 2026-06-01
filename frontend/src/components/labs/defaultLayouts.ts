// Default dockview layout JSON for the "Default" workspace
// This is passed to dockview's fromJSON to restore a preset arrangement.
// Layout: left 60% = PositionBlotter | right 40% = EquityCurve
//         bottom full width 35% = PnLCalendar

export const DEFAULT_LAYOUT = {
  grid: {
    root: {
      type: "branch",
      data: [
        {
          type: "branch",
          data: [
            {
              type: "leaf",
              data: {
                views: ["position-blotter"],
                activeView: "position-blotter",
                id: "group-blotter",
              },
              size: 60,
            },
            {
              type: "leaf",
              data: {
                views: ["equity-curve"],
                activeView: "equity-curve",
                id: "group-equity",
              },
              size: 40,
            },
          ],
          size: 65,
        },
        {
          type: "leaf",
          data: {
            views: ["pnl-calendar"],
            activeView: "pnl-calendar",
            id: "group-calendar",
          },
          size: 35,
        },
      ],
    },
    height: 600,
    width: 1200,
    orientation: 1, // vertical split at top level
  },
  panels: {
    "position-blotter": {
      id: "position-blotter",
      contentComponent: "position-blotter",
      title: "Position Blotter",
    },
    "equity-curve": {
      id: "equity-curve",
      contentComponent: "equity-curve",
      title: "Equity Curve",
    },
    "pnl-calendar": {
      id: "pnl-calendar",
      contentComponent: "pnl-calendar",
      title: "P&L Calendar",
    },
  },
  activeGroup: "group-blotter",
};

// "Analysis" workspace: watchlist + daily recap side by side + equity curve below
export const ANALYSIS_LAYOUT = {
  grid: {
    root: {
      type: "branch",
      data: [
        {
          type: "branch",
          data: [
            {
              type: "leaf",
              data: {
                views: ["watchlist"],
                activeView: "watchlist",
                id: "group-watchlist",
              },
              size: 40,
            },
            {
              type: "leaf",
              data: {
                views: ["daily-recap"],
                activeView: "daily-recap",
                id: "group-recap",
              },
              size: 60,
            },
          ],
          size: 55,
        },
        {
          type: "leaf",
          data: {
            views: ["equity-curve-2"],
            activeView: "equity-curve-2",
            id: "group-equity-2",
          },
          size: 45,
        },
      ],
    },
    height: 600,
    width: 1200,
    orientation: 1,
  },
  panels: {
    watchlist: {
      id: "watchlist",
      contentComponent: "watchlist",
      title: "Watchlist",
    },
    "daily-recap": {
      id: "daily-recap",
      contentComponent: "daily-recap",
      title: "Daily Recap",
    },
    "equity-curve-2": {
      id: "equity-curve-2",
      contentComponent: "equity-curve",
      title: "Equity Curve",
    },
  },
  activeGroup: "group-watchlist",
};
