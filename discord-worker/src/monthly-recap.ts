import { EmbedBuilder, TextChannel } from "discord.js";
import { sql } from "drizzle-orm";
import { getDiscordClient } from "./client.js";
import { db } from "./db.js";

const COMPLIANCE_FOOTER =
  "Paper trading. Not investment advice. Not a registered investment adviser.";
const COLOR_BMG = 0x2ec4a1;

export async function postMonthlyRecap(): Promise<void> {
  try {
    const now        = new Date();
    const monthStart = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const monthEnd   = new Date(now.getFullYear(), now.getMonth(), 0);
    const startStr   = monthStart.toISOString().slice(0, 10);
    const endStr     = monthEnd.toISOString().slice(0, 10);
    const monthName  = monthStart.toLocaleString("en-US", { month: "long" });

    const [row] = await db.execute(sql`
      SELECT
        (
          SELECT COUNT(*)::int FROM bot_signals
          WHERE ts >= ${monthStart.toISOString()} AND ts <= ${monthEnd.toISOString()}
        ) AS signals,
        (
          SELECT COALESCE(SUM(realized_cents + unrealized_cents), 0)::int
          FROM bot_daily_pnl
          WHERE date >= ${startStr} AND date <= ${endStr}
        ) AS pnl_cents,
        (
          SELECT COUNT(*)::int FROM bot_trades
          WHERE ts >= ${monthStart.toISOString()} AND ts <= ${monthEnd.toISOString()}
        ) AS trades
    `) as [{ signals: number; pnl_cents: number; trades: number }];

    const pnl    = (row?.pnl_cents ?? 0) / 100;
    const pnlStr = pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`;

    const embed = new EmbedBuilder()
      .setColor(COLOR_BMG)
      .setTitle(`📊 ${monthName} ${monthStart.getFullYear()} — Monthly Recap`)
      .setDescription("Here's the month in numbers across the paper-trading bots.")
      .addFields(
        { name: "Signals fired",    value: String(row?.signals ?? 0), inline: true },
        { name: "Trades executed",  value: String(row?.trades ?? 0),  inline: true },
        { name: "Net P&L",          value: pnlStr,                    inline: true },
      )
      .setFooter({ text: COMPLIANCE_FOOTER })
      .setTimestamp(new Date());

    const channelId = process.env.DISCORD_CH_MONTHLY_RECAP;
    if (!channelId) return;

    const client  = await getDiscordClient();
    const channel = await client.channels.fetch(channelId);
    if (channel?.isTextBased()) await (channel as TextChannel).send({ embeds: [embed] });

    console.log("[discord] monthly recap posted");
  } catch (err) {
    console.error("[discord] monthly recap failed", err);
  }
}
