import { EmbedBuilder, TextChannel } from "discord.js";
import { and, gte, lte, sql, eq } from "drizzle-orm";
import { getDiscordClient } from "./client.js";
import { db, botSignals, botDailyPnL, botPositions } from "./db.js";

const COMPLIANCE_FOOTER =
  "Paper trading. Not investment advice. Not a registered investment adviser.";
const COLOR_BMG = 0x2ec4a1;

export async function postDailyDigest(): Promise<void> {
  try {
    const today = new Date();
    const dayStart = new Date(today); dayStart.setHours(0, 0, 0, 0);
    const dayEnd   = new Date(today); dayEnd.setHours(23, 59, 59, 999);
    const todayStr = today.toISOString().slice(0, 10);

    const [signalRow] = await db
      .select({ count: sql<number>`count(*)::int` })
      .from(botSignals)
      .where(and(gte(botSignals.ts, dayStart), lte(botSignals.ts, dayEnd)));
    const signalsToday = signalRow?.count ?? 0;

    const [pnlRow] = await db
      .select({
        realized:   sql<number>`coalesce(sum(realized_cents), 0)::int`,
        unrealized: sql<number>`coalesce(sum(unrealized_cents), 0)::int`,
      })
      .from(botDailyPnL)
      .where(eq(botDailyPnL.date, todayStr));
    const totalPnl = ((pnlRow?.realized ?? 0) + (pnlRow?.unrealized ?? 0)) / 100;

    const [posRow] = await db
      .select({ count: sql<number>`count(*)::int` })
      .from(botPositions)
      .where(sql`closed_at IS NULL`);
    const openPositions = posRow?.count ?? 0;

    const pnlEmoji = totalPnl >= 0 ? "📈" : "📉";
    const pnlStr   = totalPnl >= 0
      ? `+$${totalPnl.toFixed(2)}`
      : `-$${Math.abs(totalPnl).toFixed(2)}`;

    const embed = new EmbedBuilder()
      .setColor(COLOR_BMG)
      .setTitle(`${pnlEmoji} BMG Capital — Daily Digest`)
      .setDescription("Market close. Here's what the bots did today across all 3 paper portfolios.")
      .addFields(
        { name: "Signals fired",   value: String(signalsToday),  inline: true },
        { name: "Open positions",  value: String(openPositions), inline: true },
        { name: "Today P&L",       value: pnlStr,                inline: true },
      )
      .setFooter({ text: COMPLIANCE_FOOTER })
      .setTimestamp(new Date());

    const channelId = process.env.DISCORD_CH_DAILY_DIGEST;
    if (!channelId) return;

    const client  = await getDiscordClient();
    const channel = await client.channels.fetch(channelId);
    if (channel?.isTextBased()) await (channel as TextChannel).send({ embeds: [embed] });

    console.log("[discord] daily digest posted");
  } catch (err) {
    console.error("[discord] daily digest failed", err);
  }
}
