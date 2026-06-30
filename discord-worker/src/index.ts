import "./instrument";

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
import { getDiscordClient } from "./client.js";
import { attachAgentListener } from "./agent-listener.js";

const POLL_INTERVAL_MS = 10_000; // 10 seconds

// Columns that must exist on each bridge table, with their Postgres types.
// Any column missing at boot gets ALTER TABLE ADD COLUMN IF NOT EXISTS.
const REQUIRED_COLUMNS: Record<string, Record<string, string>> = {
  bot_signals: {
    id:                 "SERIAL PRIMARY KEY",
    allocation_id:      "INTEGER NOT NULL",
    ts:                 "TIMESTAMP NOT NULL DEFAULT NOW()",
    symbol:             "VARCHAR NOT NULL",
    side:               "VARCHAR NOT NULL",
    confidence:         "REAL NOT NULL",
    size_hint:          "REAL",
    reason:             "TEXT",
    strategy:           "VARCHAR",
    entry_price:        "REAL",
    stop_price:         "REAL",
    target_price:       "REAL",
    discord_posted_at:  "TIMESTAMP",
    discord_message_id: "TEXT",
    claimed_at:         "TIMESTAMP",
    executed_at:        "TIMESTAMP",
    is_test:            "BOOLEAN DEFAULT FALSE",
  },
  bot_allocations: {
    id:                     "SERIAL PRIMARY KEY",
    user_id:                "INTEGER NOT NULL",
    profile_id:             "INTEGER NOT NULL",
    starting_capital_cents: "BIGINT",
  },
  bot_profiles: {
    id:   "SERIAL PRIMARY KEY",
    name: "VARCHAR NOT NULL",
  },
};

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

  // ── Comprehensive schema sync: ALTER TABLE for any missing column ─────────────
  for (const [table, columns] of Object.entries(REQUIRED_COLUMNS)) {
    const existing = await db.execute(sql`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = ${table}
    `) as { column_name: string }[];
    const have = new Set(existing.map((r: { column_name: string }) => r.column_name));
    const missing = Object.keys(columns).filter(c => !have.has(c));
    if (missing.length === 0) {
      console.warn(`[migration] ${table} schema OK`);
    } else {
      console.warn(`[migration] ${table} missing: ${missing.join(",")}`);
      for (const col of missing) {
        const colType = columns[col];
        // ALTER TABLE doesn't support IF NOT EXISTS on column type specs with defaults,
        // so we wrap in a DO $$ block to swallow duplicate-column errors safely.
        await db.execute(sql.raw(`
          DO $$ BEGIN
            ALTER TABLE ${table} ADD COLUMN ${col} ${colType};
          EXCEPTION WHEN duplicate_column THEN NULL;
          END $$;
        `));
        console.warn(`[migration] added ${table}.${col} (${colType})`);
      }
    }
  }
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
  // Migrations tracking table for one-shot ops.
  await db.execute(sql`
    CREATE TABLE IF NOT EXISTS discord_worker_migrations (
      name       VARCHAR PRIMARY KEY,
      applied_at TIMESTAMP DEFAULT NOW()
    )
  `);

  // ── One-time: backfill stop/target on signals missing them ──────────────────
  await db.execute(sql`
    UPDATE bot_signals
    SET
      stop_price   = COALESCE(stop_price,   entry_price * 0.93),
      target_price = COALESCE(target_price, entry_price * 1.10)
    WHERE side = 'buy'
      AND entry_price IS NOT NULL
      AND (stop_price IS NULL OR target_price IS NULL)
  `);
  await db.execute(sql`
    UPDATE bot_signals
    SET
      stop_price   = COALESCE(stop_price,   entry_price * 1.07),
      target_price = COALESCE(target_price, entry_price * 0.90)
    WHERE side IN ('sell', 'short')
      AND entry_price IS NOT NULL
      AND (stop_price IS NULL OR target_price IS NULL)
  `);

  // ── EMERGENCY: purge the repost loop ────────────────────────────────────────
  // All signals existing before this fix was deployed have already been spammed.
  // Mark them as posted so the loop stops immediately on next boot.
  // Tracked in discord_worker_migrations so it never runs again after this deploy.
  const purgeRan = await db.execute(sql`
    SELECT 1 FROM discord_worker_migrations WHERE name = 'purge_repost_loop_2026_06_09'
  `);
  if (!purgeRan.length) {
    const purged = await db.execute(sql`
      UPDATE bot_signals
      SET discord_posted_at = NOW()
      WHERE discord_posted_at IS NULL
    `);
    await db.execute(sql`
      INSERT INTO discord_worker_migrations (name) VALUES ('purge_repost_loop_2026_06_09')
    `);
    console.log(`[discord] EMERGENCY PURGE: marked ${(purged as any).count ?? "?"} pending signals as posted`);
  }

  console.log("[discord] migrations complete");
}

// Guard: prevent setInterval from stacking concurrent pollAndPost invocations.
// Without this, slow Discord API responses cause 10s poll ticks to overlap, each
// picking up the same unposted signals before any of them commits discord_posted_at.
let _isPolling = false;

async function pollAndPost(): Promise<void> {
  if (_isPolling) {
    console.log("[discord] poll skipped — previous run still in progress");
    return;
  }
  _isPolling = true;
  try {
    await _doPoll();
  } finally {
    _isPolling = false;
  }
}

async function _doPoll(): Promise<void> {
  try {
    // Find unposted signals — join allocation → profile to get bot name.
    // 48-hour window prevents stale signals from spamming on restart.
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
        bs.is_test,
        bp.name AS bot_profile,
        ba.starting_capital_cents
      FROM bot_signals bs
      JOIN bot_allocations ba ON ba.id = bs.allocation_id
      JOIN bot_profiles bp    ON bp.id = ba.profile_id
      WHERE bs.discord_posted_at IS NULL
        AND bs.executed_at IS NOT NULL
        AND bs.confidence >= 0.65
        AND (bs.claimed_at IS NULL OR bs.claimed_at < NOW() - INTERVAL '2 minutes')
        AND bs.ts > NOW() - INTERVAL '48 hours'
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
      is_test: boolean | null;
      bot_profile: string;
      starting_capital_cents: number | null;
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
        isTest:         row.is_test ?? false,
        startingCapitalCents: row.starting_capital_cents ?? undefined,
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
  // Boot diagnostics — log all channel env vars so Railway logs confirm config.
  console.warn(
    `[worker-boot] channel IDs: ALL_SIGNALS=${process.env.DISCORD_CH_ALL_SIGNALS ?? "MISSING"} ` +
    `STOCKS=${process.env.DISCORD_CH_STOCKS_SIGNALS ?? "MISSING"} ` +
    `CRYPTO=${process.env.DISCORD_CH_CRYPTO_SIGNALS ?? "MISSING"} ` +
    `OPTIONS=${process.env.DISCORD_CH_OPTIONS_SIGNALS ?? "MISSING"} ` +
    `QUANT=${process.env.BMG_QUANT_SIGNALS_CHANNEL_ID ?? process.env.DISCORD_CH_QUANT_SIGNALS ?? "MISSING"}`
  );

  // Eagerly initialize Discord client so the bot shows Online immediately.
  const discordClient = await getDiscordClient();
  // Ensure tables exist (idempotent — safe to run on every boot).
  await runMigrations();

  // Two-way agent chat — only active when Privileged MessageContent intent is
  // enabled in the Discord Developer Portal AND ENABLE_MESSAGE_CONTENT_INTENT=true.
  if (process.env.ENABLE_MESSAGE_CONTENT_INTENT === "true") {
    attachAgentListener(discordClient);
  } else {
    console.warn("[discord] agent listener DISABLED — set ENABLE_MESSAGE_CONTENT_INTENT=true after enabling Message Content Intent in Discord Developer Portal");
  }

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
