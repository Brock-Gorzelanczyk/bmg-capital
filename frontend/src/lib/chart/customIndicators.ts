/**
 * BMG-specific custom TradingView indicators.
 * These appear under "Indicators → BMG" in the TV chart.
 */

export function getBmgCustomIndicators(PineJS: any): object[] {
  return [
    bmgSignalMarkers(PineJS),
    bmgBotPositions(PineJS),
    bmgWatchlistScoring(PineJS),
    bmgRegimeBackground(PineJS),
  ];
}

function bmgSignalMarkers(_PineJS: any): object {
  return {
    name: "BMG Signal Markers",
    metainfo: {
      _metainfoVersion: 51,
      id: "BMGSignalMarkers@tv-basicstudies-1",
      scriptIdPart: "",
      name: "BMG Signal Markers",
      description: "BMG Bot Buy/Sell Signal Markers",
      shortDescription: "BMG Signals",
      isCustomIndicator: true,
      is_price_study: true,
      linkedToSeries: true,
      format: { type: "price", precision: 2 },
      plots: [
        { id: "buy_arrow", type: "chars" },
        { id: "sell_arrow", type: "chars" },
      ],
      defaults: {
        plots: {
          buy_arrow: { color: "#10B981", textColor: "#10B981", transparency: 0, visible: true },
          sell_arrow: { color: "#EF4444", textColor: "#EF4444", transparency: 0, visible: true },
        },
        inputs: { show_all_bots: true, min_confidence: 50 },
      },
      inputs: [
        { id: "show_all_bots", name: "Show all bots", defval: true, type: "bool" },
        { id: "min_confidence", name: "Min confidence %", defval: 50, type: "integer", min: 0, max: 100 },
      ],
    },
    constructor: function (this: any) {
      this.main = function (ctx: any) {
        ctx.setMinimumAdditionalDepth(0);
        return [{ value: NaN }, { value: NaN }];
      };
    },
  };
}

function bmgBotPositions(_PineJS: any): object {
  return {
    name: "BMG Bot Positions",
    metainfo: {
      _metainfoVersion: 51,
      id: "BMGBotPositions@tv-basicstudies-1",
      scriptIdPart: "",
      name: "BMG Bot Positions",
      description: "Highlight time ranges when bots held this symbol",
      shortDescription: "BMG Positions",
      isCustomIndicator: true,
      is_price_study: true,
      linkedToSeries: true,
      format: { type: "price", precision: 2 },
      plots: [{ id: "position_bg", type: "bg_colorer" }],
      defaults: {
        plots: { position_bg: { color: "#9333EA", transparency: 85 } },
        inputs: {},
      },
      inputs: [],
    },
    constructor: function (this: any) {
      this.main = function (ctx: any) {
        ctx.setMinimumAdditionalDepth(0);
        return [{ value: NaN }];
      };
    },
  };
}

function bmgWatchlistScoring(_PineJS: any): object {
  return {
    name: "BMG Watchlist Score",
    metainfo: {
      _metainfoVersion: 51,
      id: "BMGWatchlistScore@tv-basicstudies-1",
      scriptIdPart: "",
      name: "BMG Watchlist Score",
      description: "Bot watchlist conviction score (0-100) for this symbol",
      shortDescription: "BMG Score",
      isCustomIndicator: true,
      is_price_study: false,
      linkedToSeries: true,
      format: { type: "price", precision: 0 },
      plots: [
        { id: "score", type: "line" },
        { id: "threshold", type: "line" },
      ],
      defaults: {
        plots: {
          score: { color: "#9333EA", linewidth: 2 },
          threshold: { color: "#F97316", linewidth: 1, linestyle: 1 },
        },
        inputs: { threshold: 55 },
      },
      inputs: [
        { id: "threshold", name: "Signal threshold", defval: 55, type: "integer", min: 0, max: 100 },
      ],
    },
    constructor: function (this: any) {
      this.main = function (ctx: any, inputs: any) {
        ctx.setMinimumAdditionalDepth(0);
        const thr = inputs(0) as number;
        return [{ value: NaN }, { value: thr }];
      };
    },
  };
}

function bmgRegimeBackground(_PineJS: any): object {
  return {
    name: "BMG Market Regime",
    metainfo: {
      _metainfoVersion: 51,
      id: "BMGMarketRegime@tv-basicstudies-1",
      scriptIdPart: "",
      name: "BMG Market Regime",
      description: "Color background by BMG market regime: green=trend, yellow=chop, red=panic",
      shortDescription: "BMG Regime",
      isCustomIndicator: true,
      is_price_study: true,
      linkedToSeries: true,
      format: { type: "price", precision: 2 },
      plots: [{ id: "regime_bg", type: "bg_colorer" }],
      defaults: {
        plots: { regime_bg: { color: "#10B981", transparency: 92 } },
        inputs: {},
      },
      inputs: [],
    },
    constructor: function (this: any) {
      this.main = function (ctx: any) {
        ctx.setMinimumAdditionalDepth(0);
        return [{ value: NaN }];
      };
    },
  };
}
