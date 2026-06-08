import { EmbedBuilder, TextChannel } from "discord.js";
import { eq } from "drizzle-orm";
import { getDiscordClient } from "./client.js";
import { db, botSignals } from "./db.js";

function fmtPrice(price: number): string {
  const abs = Math.abs(price);
  let maxDec: number;
  if (abs >= 1000) maxDec = 2;
  else if (abs >= 1) maxDec = 4;
  else if (abs >= 0.01) maxDec = 5;
  else if (abs >= 0.0001) maxDec = 6;
  else maxDec = 8;
  return price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: maxDec });
}

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
  isTest?: boolean;
};

const BOT_DISPLAY: Record<string, string> = {
  stock_swing:          "Stock Swing",
  stock_day:            "Stock Day",
  stock_lt:             "Stock Long-Term",
  crypto_swing:         "Crypto Swing",
  crypto_day:           "Crypto Day",
  crypto_lt:            "Crypto Long-Term",
  crypto_onchain:            "Crypto On-Chain",
  crypto_quant_aggressive:   "Crypto Quant Aggressive",
  options_income:            "Options Income",
  options_directional:  "Options Directional",
};

const STOCKS_BOTS  = new Set(["stock_swing", "stock_day", "stock_lt"]);
const CRYPTO_BOTS  = new Set(["crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain"]);
const OPTIONS_BOTS = new Set(["options_income", "options_directional"]);
const QUANT_BOTS   = new Set(["crypto_quant_aggressive"]);

function channelIdsForBot(botProfile: string): string[] {
  const ids: string[] = [];
  if (process.env.DISCORD_CH_ALL_SIGNALS) ids.push(process.env.DISCORD_CH_ALL_SIGNALS);
  if (STOCKS_BOTS.has(botProfile) && process.env.DISCORD_CH_STOCKS_SIGNALS)
    ids.push(process.env.DISCORD_CH_STOCKS_SIGNALS);
  if (CRYPTO_BOTS.has(botProfile) && process.env.DISCORD_CH_CRYPTO_SIGNALS)
    ids.push(process.env.DISCORD_CH_CRYPTO_SIGNALS);
  if (OPTIONS_BOTS.has(botProfile) && process.env.DISCORD_CH_OPTIONS_SIGNALS)
    ids.push(process.env.DISCORD_CH_OPTIONS_SIGNALS);
  if (QUANT_BOTS.has(botProfile)) {
    const quantCh = process.env.BMG_QUANT_SIGNALS_CHANNEL_ID ?? process.env.DISCORD_CH_QUANT_SIGNALS;
    if (quantCh) ids.push(quantCh);
  }
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

    const entry = signal.entryPrice ?? null;
    const isBuy = signal.side === "buy" || signal.side === "cover";

    // Resolve stop — use DB value or compute 7% default from entry
    let stop = signal.stopLoss ?? null;
    if (stop == null && entry != null) {
      stop = isBuy ? entry * 0.93 : entry * 1.07;
    }

    // Resolve target — use DB value or compute 10% default from entry
    let target = signal.takeProfit ?? null;
    if (target == null && entry != null) {
      target = isBuy ? entry * 1.10 : entry * 0.90;
    }

    const stopPct   = stop   != null && entry != null ? (stop   - entry) / entry * 100 : null;
    const targetPct = target != null && entry != null ? (target - entry) / entry * 100 : null;
    const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

    const testPrefix = signal.isTest ? "[TEST] " : "";
    const embed = new EmbedBuilder()
      .setColor(color)
      .setAuthor({ name: `${displayName} bot` })
      .setTitle(`${testPrefix}${sideEmoji(signal.side)} ${signal.side.toUpperCase()} ${signal.symbol}`)
      .setDescription(signal.reason)
      .addFields(
        { name: "Strategy",    value: signal.strategy,                                                                                   inline: true },
        { name: "Confidence",  value: `${(signal.confidence * 100).toFixed(1)}%`,                                                        inline: true },
        { name: "Size",        value: signal.positionSizePct != null ? `${signal.positionSizePct.toFixed(1)}% of portfolio` : "—",        inline: true },
        { name: "Entry",       value: entry  != null ? `$${fmtPrice(entry)}`                                                         : "—", inline: true },
        { name: "Stop",        value: stop   != null ? `$${fmtPrice(stop)}${stopPct   != null ? ` (${fmtPct(stopPct)})`   : ""}` : "—", inline: true },
        { name: "Take Profit", value: target != null ? `$${fmtPrice(target)}${targetPct != null ? ` (${fmtPct(targetPct)})` : ""}` : "—", inline: true },
      )
      .setFooter({ text: COMPLIANCE_FOOTER })
      .setTimestamp(new Date());

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
