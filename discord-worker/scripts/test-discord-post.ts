/**
 * Test script — posts a synthetic NVDA buy signal to Discord.
 * Run: tsx scripts/test-discord-post.ts
 *
 * Requires: DATABASE_URL, DISCORD_BOT_TOKEN, DISCORD_CH_ALL_SIGNALS,
 *           DISCORD_CH_STOCKS_SIGNALS in environment (or .env file).
 */

import { postSignalToDiscord } from "../src/post-signal.js";

const testId = -(Date.now() % 100_000); // Negative ID so it never clashes with real signals

await postSignalToDiscord({
  signalId:       testId,
  botProfile:     "stock_swing",
  symbol:         "NVDA",
  side:           "buy",
  confidence:     0.78,
  strategy:       "Minervini VCP",
  reason:
    "Tight price contraction after 30% advance. Volume drying up on basing pattern. " +
    "Breakout above 142.50 confirms.",
  entryPrice:      142.50,
  stopLoss:        138.75,
  takeProfit:      156.00,
  positionSizePct: 4.5,
});

console.log("[test] done — check #all-signals and #stocks-signals in Discord");
process.exit(0);
