import { EmbedBuilder, TextChannel } from "discord.js";
import { eq } from "drizzle-orm";
import { getDiscordClient } from "./client.js";
import { db, botSignals } from "./db.js";

const COMPLIANCE_FOOTER =
  "Paper trading. Not investment advice. Not a registered investment adviser.";
const COLOR_BUY  = 0x2ec4a1;
const COLOR_SELL = 0xe5484d;

export type SignalInput = {
  signalId: number;
  botProfile: string;
  symbol: string;
  side: "buy" | "sell" | "short" | "cover";
  confidence: number;
  strategy: string;
  reason: string;
  entryPrice?: number;
  stopLoss?: number;
  takeProfit?: number;
  positionSizePct?: number;
};

const BOT_DISPLAY: Record<string, string> = {
  stock_swing:          "Stock Swing",
  stock_day:            "Stock Day",
  stock_lt:             "Stock Long-Term",
  crypto_swing:         "Crypto Swing",
  crypto_day:           "Crypto Day",
  crypto_lt:            "Crypto Long-Term",
  crypto_onchain:       "Crypto On-Chain",
  options_income:       "Options Income",
  options_directional:  "Options Directional",
};

const STOCKS_BOTS  = new Set(["stock_swing", "stock_day", "stock_lt"]);
const CRYPTO_BOTS  = new Set(["crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain"]);
const OPTIONS_BOTS = new Set(["options_income", "options_directional"]);

function channelIdsForBot(botProfile: string): string[] {
  const ids: string[] = [];
  if (process.env.DISCORD_CH_ALL_SIGNALS) ids.push(process.env.DISCORD_CH_ALL_SIGNALS);
  if (STOCKS_BOTS.has(botProfile) && process.env.DISCORD_CH_STOCKS_SIGNALS)
    ids.push(process.env.DISCORD_CH_STOCKS_SIGNALS);
  if (CRYPTO_BOTS.has(botProfile) && process.env.DISCORD_CH_CRYPTO_SIGNALS)
    ids.push(process.env.DISCORD_CH_CRYPTO_SIGNALS);
  if (OPTIONS_BOTS.has(botProfile) && process.env.DISCORD_CH_OPTIONS_SIGNALS)
    ids.push(process.env.DISCORD_CH_OPTIONS_SIGNALS);
  return [...new Set(ids)];
}

function sideEmoji(side: string): string {
  if (side === "buy")    return "🟢";
  if (side === "sell" || side === "short") return "🔴";
  if (side === "cover")  return "🟡";
  return "⚪";
}

// Simple in-process rate limiter: 5 messages per 5 seconds per channel.
const _lastSends: Map<string, number[]> = new Map();
async function rateLimit(channelId: string): Promise<void> {
  const now = Date.now();
  const window = 5_000;
  const max = 5;
  const sends = (_lastSends.get(channelId) ?? []).filter(t => now - t < window);
  if (sends.length >= max) {
    const wait = window - (now - sends[0]);
    await new Promise(r => setTimeout(r, wait));
  }
  sends.push(Date.now());
  _lastSends.set(channelId, sends);
}

export async function postSignalToDiscord(signal: SignalInput): Promise<void> {
  try {
    // Deduplication: skip if already posted.
    const existing = await db.query.botSignals.findFirst({
      where: eq(botSignals.id, signal.signalId),
      columns: { discordPostedAt: true },
    });
    if (existing?.discordPostedAt) return;

    const client = await getDiscordClient();
    const color = signal.side === "buy" ? COLOR_BUY : COLOR_SELL;
    const displayName = BOT_DISPLAY[signal.botProfile] ?? signal.botProfile;

    const embed = new EmbedBuilder()
      .setColor(color)
      .setAuthor({ name: `${displayName} bot` })
      .setTitle(`${sideEmoji(signal.side)} ${signal.side.toUpperCase()} ${signal.symbol}`)
      .setDescription(signal.reason)
      .addFields(
        { name: "Strategy",   value: signal.strategy,                              inline: true },
        { name: "Confidence", value: `${(signal.confidence * 100).toFixed(0)}%`,  inline: true },
      );

    if (signal.entryPrice     != null) embed.addFields({ name: "Entry",  value: `$${signal.entryPrice.toFixed(2)}`,  inline: true });
    if (signal.stopLoss       != null) embed.addFields({ name: "Stop",   value: `$${signal.stopLoss.toFixed(2)}`,    inline: true });
    if (signal.takeProfit     != null) embed.addFields({ name: "Target", value: `$${signal.takeProfit.toFixed(2)}`,  inline: true });
    if (signal.positionSizePct != null) embed.addFields({ name: "Size",  value: `${signal.positionSizePct.toFixed(1)}% of portfolio`, inline: true });

    embed.setFooter({ text: COMPLIANCE_FOOTER }).setTimestamp(new Date());

    const channelIds = channelIdsForBot(signal.botProfile);
    for (const channelId of channelIds) {
      await rateLimit(channelId);
      const channel = await client.channels.fetch(channelId);
      if (channel?.isTextBased()) {
        await (channel as TextChannel).send({ embeds: [embed] });
      }
    }

    await db
      .update(botSignals)
      .set({ discordPostedAt: new Date() })
      .where(eq(botSignals.id, signal.signalId));

    console.log(`[discord] posted signal ${signal.signalId} (${signal.symbol} ${signal.side})`);
  } catch (err) {
    // Never crash the signal loop — catch and log only.
    console.error("[discord] failed to post signal", err);
  }
}
