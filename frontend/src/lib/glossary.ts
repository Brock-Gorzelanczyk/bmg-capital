/**
 * Glossary — shared definitions for jargon that appears on multiple admin
 * pages. Keep entries to one short sentence. Anything longer belongs in
 * the docs, not a tooltip.
 *
 * Add new keys here; the <HelpIcon term="..." /> component resolves them.
 */
export const GLOSSARY: Record<string, string> = {
  // Discipline filter (Phase 1)
  composite_score:
    "0-100 weighted blend of: 35% raw confidence, 20% regime fit, 15% volume agreement, 15% multi-timeframe alignment, 15% recent strategy win rate.",
  composite_threshold:
    "Minimum composite_score a signal needs to pass the score gate. Default 60. Raise to throttle volume, lower to let more signals through.",
  confluence:
    "How many of 5 factors are aligned: trend agreement, volume confirmation, time-of-day, volatility regime, cross-asset agreement. Need 3 of 5 to pass.",
  regime_gate:
    "First gate: does the strategy's regime_preference match the current market regime (bull / bear / chop / low_vol / crisis)?",
  regime_preference:
    "What market type a strategy expects to work in. 'any' means it fires in all regimes.",
  filter_reason:
    "Which discipline gate rejected the signal: regime_mismatch, score_below_threshold, insufficient_confluence, or multiple.",

  // Hypothesis tracking (Phase 2)
  hypothesis_status:
    "TESTING (new — auto-collects data), LIVE (proven — actively trades), RETIRED (manually disabled).",
  win_rate:
    "Percent of closed trades that ended profitable. Computed from BotPosition entry vs sell-trade fill price.",
  expected_r:
    "Expectancy proxy: (win_rate × avg_win - (1-win_rate) × avg_loss) / avg_loss. Roughly 'R units per trade you can expect long-run'.",
  r_multiple:
    "Ratio of average win to average loss. >1.0 means your winners are bigger than your losers.",
  factor_exposures:
    "How heavily a strategy leans on each factor: MOM (momentum), TRD (trend), VOL (volume), FLW (flow), MR (mean reversion), TIME (time-of-day), HYP (hypothesis confidence).",

  // Tuning (this sprint)
  reject_rate:
    "Percent of analyzed signals that were filtered out by the discipline gates. >95% on 20+ signals is usually a sign the strategy or its thresholds need tuning.",
  promotion_rule:
    "TESTING → LIVE eligibility: N ≥ 10 trades AND win_rate ≥ 55% AND expected_r ≥ +0.10R.",
  red_flag:
    "Strategy with ≥50 signals analyzed but 0 executed — gate config is likely too tight.",
  volume_bomb:
    "Strategy generating > 500 signals/day. Raise composite_threshold to throttle.",

  // Strategies (Phase 3)
  atr:
    "Average True Range. 14-period default. Measures typical volatility — used to express stops, targets, and pullback tolerances as a multiple of recent range.",
  vwap:
    "Volume-Weighted Average Price. Anchored to session open by default. Acts as a magnet for mean-reversion trades.",
  ofi:
    "Order Flow Imbalance. (buy_volume - sell_volume) / (buy_volume + sell_volume) per bar. Range -1 to +1. Extremes flag institutional pressure.",
  adx:
    "Average Directional Index. >25 = strong trend, <20 = chop. Used by MTF Momentum Surge as the trend-strength filter.",
  pdh_pdl:
    "Previous Day High / Previous Day Low. Most-watched intraday levels — strategies fire breakouts at them or fade approaches that don't break.",
  mtf_alignment:
    "Multi-timeframe trend agreement. 1.0 = 5m, 15m, and 1h all point the same direction. <0.5 = timeframes disagree.",

  // Brain graph (Phase 4)
  brain_node:
    "One entity in the knowledge graph: session, strategy, symbol, signal, trade, or lesson. Color encodes type, size encodes magnitude.",
  brain_edge:
    "Relationship between two nodes: SESSION→TRADE (contains), TRADE→SIGNAL (from_signal), SIGNAL→STRATEGY (uses_strategy), TRADE→SYMBOL (on_symbol).",
  min_connections:
    "Hide nodes with fewer than N incident edges. Useful for cleaning up the singletons when the graph is dense.",
};

/** Lookup a term's definition. Returns the term itself if not in glossary. */
export function defineTerm(term: string): string {
  return GLOSSARY[term] ?? term;
}
