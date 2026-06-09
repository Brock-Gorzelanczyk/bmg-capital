/**
 * PostgreSQL connection + minimal Drizzle schema for the tables this worker needs.
 * Uses the same DATABASE_URL as the Python backend (Neon on Railway).
 */
import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";
import {
  pgTable,
  serial,
  integer,
  varchar,
  text,
  real,
  timestamp,
  boolean,
  date,
} from "drizzle-orm/pg-core";

if (!process.env.DATABASE_URL) {
  throw new Error("DATABASE_URL is required");
}

const client = postgres(process.env.DATABASE_URL, { max: 5 });

// ── Minimal schema (only columns this worker reads/writes) ───────────────────

export const botSignals = pgTable("bot_signals", {
  id:              serial("id").primaryKey(),
  allocationId:   integer("allocation_id").notNull(),
  ts:             timestamp("ts").notNull(),
  symbol:         varchar("symbol").notNull(),
  side:           varchar("side").notNull(),
  confidence:     real("confidence").notNull(),
  sizeHint:       real("size_hint"),
  reason:         text("reason"),
  strategy:       varchar("strategy"),
  entryPrice:     real("entry_price"),
  stopPrice:      real("stop_price"),
  targetPrice:    real("target_price"),
  discordPostedAt: timestamp("discord_posted_at"),
  discordMessageId: varchar("discord_message_id"),
  claimedAt:      timestamp("claimed_at"),
  isTest:          boolean("is_test").default(false),
  executedAt:      timestamp("executed_at"),
});

export const botAllocations = pgTable("bot_allocations", {
  id:        serial("id").primaryKey(),
  userId:    integer("user_id").notNull(),
  profileId: integer("profile_id").notNull(),
});

export const botProfiles = pgTable("bot_profiles", {
  id:   serial("id").primaryKey(),
  name: varchar("name").notNull(),
});

export const botDailyPnL = pgTable("bot_daily_pnl", {
  id:                    serial("id").primaryKey(),
  allocationId:         integer("allocation_id").notNull(),
  date:                 date("date").notNull(),
  realizedCents:        integer("realized_cents").notNull().default(0),
  unrealizedCents:      integer("unrealized_cents").notNull().default(0),
  portfolioValueEodCents: integer("portfolio_value_eod_cents"),
});

export const botPositions = pgTable("bot_positions", {
  id:           serial("id").primaryKey(),
  allocationId: integer("allocation_id").notNull(),
  symbol:       varchar("symbol").notNull(),
  closedAt:     timestamp("closed_at"),
  isActive:     boolean("is_active").default(true),
});

const schema = { botSignals, botAllocations, botProfiles, botDailyPnL, botPositions };
export const db = drizzle(client, { schema });
