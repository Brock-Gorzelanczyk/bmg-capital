import { EmbedBuilder, TextChannel } from "discord.js";
import { sql } from "drizzle-orm";
import { getDiscordClient } from "./client.js";
import { db } from "./db.js";

const COMPLIANCE_FOOTER =
  "Paper trading. Not investment advice. Not a registered investment adviser.";
const COLOR_BMG = 0x2ec4a1;

const MEDALS = ["🥇", "🥈", "🥉"];

export async function postWeeklyLeaderboard(): Promise<void> {
  try {
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    const cutoff = sevenDaysAgo.toISOString().slice(0, 10);

    const rows = await db.execute(sql`
      SELECT
        bp.name,
        COALESCE(SUM(bdp.realized_cents + bdp.unrealized_cents), 0)::int AS pnl_cents
      FROM bot_profiles bp
      LEFT JOIN bot_allocations ba ON ba.profile_id = bp.id
      LEFT JOIN bot_daily_pnl bdp
        ON bdp.allocation_id = ba.id
        AND bdp.date >= ${cutoff}
      GROUP BY bp.name
      ORDER BY pnl_cents DESC
      LIMIT 8
    `);

    const lines = (rows as { name: string; pnl_cents: number }[]).map((r, i) => {
      const medal  = MEDALS[i] ?? `${i + 1}.`;
      const pnl    = r.pnl_cents / 100;
      const pnlStr = pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`;
      return `${medal}  **${r.name}** — ${pnlStr}`;
    });

    const embed = new EmbedBuilder()
      .setColor(COLOR_BMG)
      .setTitle("🏆 BMG Capital — Weekly Leaderboard")
      .setDescription(
        "Last 7 days, ranked by paper P&L across all bots.\n\n" + lines.join("\n")
      )
      .setFooter({ text: COMPLIANCE_FOOTER })
      .setTimestamp(new Date());

    const channelId = process.env.DISCORD_CH_WEEKLY_LEADERBOARD;
    if (!channelId) return;

    const client  = await getDiscordClient();
    const channel = await client.channels.fetch(channelId);
    if (channel?.isTextBased()) await (channel as TextChannel).send({ embeds: [embed] });

    console.log("[discord] weekly leaderboard posted");
  } catch (err) {
    console.error("[discord] weekly leaderboard failed", err);
  }
}
