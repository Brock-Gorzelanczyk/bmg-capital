/**
 * BMG Capital Discord Worker
 *
 * Polls the database every 10 seconds for bot signals that haven't been
 * posted to Discord yet (discord_posted_at IS NULL), posts them as embeds,
 * and runs the scheduled digest/leaderboard/recap cron jobs.
 *
 * Env vars required:
 *   DATABASE_URL            — PostgreSQL connection string (same as Python backend)
 *   DISCORD_BOT_TOKEN       — Discord bot token
 *   DISCORD_CH_ALL_SIGNALS  — channel ID for every signal
 *   DISCORD_CH_STOCKS_SIGNALS / CRYPTO / OPTIONS
 *   DISCORD_CH_DAILY_DIGEST / WEEKLY_LEADERBOARD / MONTHLY_RECAP
 */

import { sql } from "drizzle-orm";
import { startDiscordSchedulers } from "./scheduler.js";
import { postSignalToDiscord }    from "./post-signal.js";
import { db } from "./db.js";

const POLL_INTERVAL_MS = 10_000; // 10 seconds

async function runMigrations(): Promise<void> {
  console.log("[discord] running startup migrations…");
  await db.execute(sql`
    CREATE TABLE IF NOT EXISTS bot_profiles (
      id   SERIAL PRIMARY KEY,
      name VARCHAR NOT NULL
    )
  `);
  await db.execute(sql`
    CREATE TABLE IF NOT EXISTS bot_allocations (
      id         SERIAL PRIMARY KEY,
      user_id    INTEGER NOT NULL,
      profile_id INTEGER NOT NULL
    )
  `);
  await db.execute(sql`
    CREATE TABLE IF NOT EXISTS bot_signals (
      id                 SERIAL PRIMARY KEY,
      allocation_id      INTEGER NOT NULL,
      ts                 TIMESTAMP NOT NULL DEFAULT NOW(),
      symbol             VARCHAR NOT NULL,
      side               VARCHAR NOT NULL,
      confidence         REAL NOT NULL,
      size_hint          REAL,
      reason             TEXT,
      strategy           VARCHAR,
      entry_price        REAL,
      stop_price         REAL,
      target_price       REAL,
      discord_posted_at  TIMESTAMP
    )
  `);
  await db.execute(sql`
    CREATE TABLE IF NOT EXISTS bot_daily_pnl (
      id                        SERIAL PRIMARY KEY,
      allocation_id             INTEGER NOT NULL,
      date                      DATE NOT NULL,
      realized_cents            INTEGER NOT NULL DEFAULT 0,
      unrealized_cents          INTEGER NOT NULL DEFAULT 0,
      portfolio_value_eod_cents INTEGER
    )
  `);
  await db.execute(sql`
    CREATE TABLE IF NOT EXISTS bot_positions (
      id            SERIAL PRIMARY KEY,
      allocation_id INTEGER NOT NULL,
      symbol        VARCHAR NOT NULL,
      closed_at     TIMESTAMP,
      is_active     BOOLEAN DEFAULT TRUE
    )
  `);
  console.log("[discord] migrations complete");
}

async function pollAndPost(): Promise<void> {
  try {
    // Find unposted signals — join allocation → profile to get bot name.
    const rows = await db.execute(sql`
      SELECT
        bs.id,
        bs.symbol,
        bs.side,
        bs.confidence,
        bs.strategy,
        bs.reason,
        bs.entry_price,
        bs.stop_price,
        bs.target_price,
        bs.size_hint,
        bp.name AS bot_profile
      FROM bot_signals bs
      JOIN bot_allocations ba ON ba.id = bs.allocation_id
      JOIN bot_profiles bp    ON bp.id = ba.profile_id
      WHERE bs.discord_posted_at IS NULL
      ORDER BY bs.ts ASC
      LIMIT 20
    `) as {
      id: number;
      symbol: string;
      side: string;
      confidence: number;
      strategy: string | null;
      reason: string | null;
      entry_price: number | null;
      stop_price: number | null;
      target_price: number | null;
      size_hint: number | null;
      bot_profile: string;
    }[];

    for (const row of rows) {
      await postSignalToDiscord({
        signalId:       row.id,
        botProfile:     row.bot_profile,
        symbol:         row.symbol,
        side:           row.side as "buy" | "sell" | "short" | "cover",
        confidence:     row.confidence,
        strategy:       row.strategy ?? "unknown",
        reason:         row.reason   ?? "",
        entryPrice:     row.entry_price  ?? undefined,
        stopLoss:       row.stop_price   ?? undefined,
        takeProfit:     row.target_price ?? undefined,
        positionSizePct: row.size_hint != null ? row.size_hint * 100 : undefined,
      });
    }
  } catch (err) {
    console.error("[discord] poll error", err);
  }
}

async function main(): Promise<void> {
  console.log("[discord] worker starting…");

  if (!process.env.DISCORD_BOT_TOKEN) {
    console.error("[discord] DISCORD_BOT_TOKEN not set — exiting");
    process.exit(1);
  }

  // Ensure tables exist (idempotent — safe to run on every boot).
  await runMigrations();

  // Start scheduled cron jobs (digest, leaderboard, recap).
  startDiscordSchedulers();

  // Poll loop for unposted signals.
  console.log(`[discord] polling every ${POLL_INTERVAL_MS / 1000}s for unposted signals`);
  setInterval(() => void pollAndPost(), POLL_INTERVAL_MS);

  // Run once immediately on startup to catch any signals from before boot.
  await pollAndPost();
}

main().catch(err => {
  console.error("[discord] fatal error", err);
  process.exit(1);
});
