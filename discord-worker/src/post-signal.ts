import { EmbedBuilder, TextChannel } from "discord.js";
import { eq, sql } from "drizzle-orm";
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

// Sidebar color = asset class category. Buy/sell direction stays in the title emoji.
const COLOR_BY_CATEGORY: Record<string, number> = {
  crypto:   0x9333EA,  // purple
  stocks:   0x10B981,  // green
  equities: 0x10B981,  // alias — stock_* bots report asset_class "equities"
  options:  0xF97316,  // orange
  quant:    0x2D2D2D,  // soft black
};
const COLOR_FALLBACK = 0x6B7280; // gray

function colorForBot(botProfile: string): number {
  if (STOCKS_BOTS.has(botProfile))  return COLOR_BY_CATEGORY.stocks;
  if (CRYPTO_BOTS.has(botProfile))  return COLOR_BY_CATEGORY.crypto;
  if (OPTIONS_BOTS.has(botProfile)) return COLOR_BY_CATEGORY.options;
  if (QUANT_BOTS.has(botProfile))   return COLOR_BY_CATEGORY.quant;
  return COLOR_FALLBACK;
}

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
  startingCapitalCents?: number;
};

const BOT_DISPLAY: Record<string, string> = {
  stock_swing:                  "Stock Swing",
  stock_day:                    "Stock Day",
  stock_lt:                     "Stock Long-Term",
  crypto_swing:                 "Crypto Swing",
  crypto_day:                   "Crypto Day",
  crypto_lt:                    "Crypto Long-Term",
  crypto_onchain:               "Crypto On-Chain",
  crypto_quant_aggressive:      "Crypto Quant Aggressive",
  crypto_quant_scalper:         "Crypto Quant Scalper",
  crypto_quant_mean_reversion:  "Crypto Quant Mean Reversion",
  options_income:               "Options Income",
  options_directional:          "Options Directional",
};

const STOCKS_BOTS  = new Set(["stock_swing", "stock_day", "stock_lt"]);
const CRYPTO_BOTS  = new Set(["crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain"]);
const OPTIONS_BOTS = new Set(["options_income", "options_directional"]);
const QUANT_BOTS   = new Set([
  "crypto_quant_aggressive",
  "crypto_quant_scalper",
  "crypto_quant_mean_reversion",
]);

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

// In-process rate limiter: max 5 messages per 5 seconds per channel (Discord burst limit).
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

// Per-minute per-channel hard cap: drop signals that would exceed 5/min.
const _perMinuteSends: Map<string, number[]> = new Map();
function perMinuteCheck(channelId: string): boolean {
  const now = Date.now();
  const window = 60_000;
  const max = 5;
  const sends = (_perMinuteSends.get(channelId) ?? []).filter(t => now - t < window);
  if (sends.length >= max) return false; // drop
  sends.push(now);
  _perMinuteSends.set(channelId, sends);
  return true;
}

// Content dedup: skip if same (bot, symbol, strategy) was posted within 5 minutes.
const _recentKeys: Map<string, number> = new Map();
const DEDUP_WINDOW_MS = 5 * 60 * 1000;
function isDuplicate(signal: SignalInput): boolean {
  const key = `${signal.botProfile}|${signal.symbol}|${signal.strategy}`;
  const last = _recentKeys.get(key);
  if (last && Date.now() - last < DEDUP_WINDOW_MS) return true;
  _recentKeys.set(key, Date.now());
  return false;
}

export async function postSignalToDiscord(signal: SignalInput): Promise<void> {
  // ── Step 1: Atomic claim ─────────────────────────────────────────────────────
  // UPDATE with WHERE claimed_at IS NULL (and discord_posted_at IS NULL) is
  // atomic in PostgreSQL — exactly one concurrent worker will get RETURNING rows.
  // Also reclaims signals whose previous worker crashed (claimed_at > 2 min ago).
  let claimed: unknown[];
  try {
    claimed = await db.execute(sql`
      UPDATE bot_signals
      SET claimed_at = NOW()
      WHERE id = ${signal.signalId}
        AND discord_posted_at IS NULL
        AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '2 minutes')
      RETURNING id
    `);
  } catch (claimErr) {
    console.error(`[discord] claim failed for signal ${signal.signalId}:`, claimErr);
    return;
  }
  if (!claimed.length) {
    // Another worker claimed it or it was already posted.
    return;
  }

  // ── Step 2: Build + send embed ───────────────────────────────────────────────
  try {
    // Content dedup: identical (bot, symbol, strategy) within 5 min → mark posted, skip send.
    if (isDuplicate(signal)) {
      console.log(`[discord] dedup skip signal ${signal.signalId} (${signal.symbol} ${signal.side})`);
      await db.update(botSignals)
        .set({ discordPostedAt: new Date(), claimedAt: null })
        .where(eq(botSignals.id, signal.signalId));
      return;
    }

    const client = await getDiscordClient();
    const color = colorForBot(signal.botProfile);
    const displayName = BOT_DISPLAY[signal.botProfile] ?? signal.botProfile;

    const entry = signal.entryPrice ?? null;
    const isBuy = signal.side === "buy" || signal.side === "cover";
    const direction = isBuy ? "LONG" : "SHORT";

    let stop = signal.stopLoss ?? null;
    if (stop == null && entry != null) stop = isBuy ? entry * 0.93 : entry * 1.07;

    let target = signal.takeProfit ?? null;
    if (target == null && entry != null) target = isBuy ? entry * 1.10 : entry * 0.90;

    const stopPct   = stop   != null && entry != null ? (stop   - entry) / entry * 100 : null;
    const targetPct = target != null && entry != null ? (target - entry) / entry * 100 : null;
    const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

    // Quantity and notional from allocation starting capital + size hint
    const portfolioValue = signal.startingCapitalCents != null ? signal.startingCapitalCents / 100 : 0;
    const sizeFraction   = signal.positionSizePct != null ? signal.positionSizePct / 100 : 0;
    const notional       = portfolioValue > 0 && sizeFraction > 0 ? portfolioValue * sizeFraction : null;
    const qty            = notional != null && entry != null && entry > 0 ? notional / entry : null;
    const baseAsset      = signal.symbol.split("/")[0];

    const fmtQty = (q: number): string => {
      if (q >= 1000) return q.toFixed(0);
      if (q >= 100)  return q.toFixed(2);
      if (q >= 1)    return q.toFixed(4);
      return q.toFixed(8);
    };
    const fmtUSD = (amount: number): string =>
      amount >= 1000
        ? "$" + amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : "$" + amount.toFixed(2);

    const qtyStr      = qty     != null ? `${fmtQty(qty)} ${baseAsset}`   : "—";
    const notionalStr = notional != null ? fmtUSD(notional)                 : "—";
    const allocStr    = signal.positionSizePct != null ? `${signal.positionSizePct.toFixed(1)}% of portfolio` : "—";
    const costLabel   = isBuy ? "Cost Basis" : "Notional";

    const testPrefix = signal.isTest ? "[TEST] " : "";
    const embed = new EmbedBuilder()
      .setColor(color)
      .setAuthor({ name: `${displayName} bot` })
      .setTitle(`${testPrefix}${sideEmoji(signal.side)} ${direction} ${signal.symbol}`)
      .setDescription(signal.reason)
      .addFields(
        { name: "Strategy",    value: signal.strategy,                                       inline: true },
        { name: "Direction",   value: direction,                                             inline: true },
        { name: "Confidence",  value: `${(signal.confidence * 100).toFixed(1)}%`,           inline: true },
        { name: "Quantity",    value: qtyStr,                                                inline: true },
        { name: costLabel,     value: notionalStr,                                           inline: true },
        { name: "Allocation",  value: allocStr,                                              inline: true },
        { name: "Entry",       value: entry  != null ? `$${fmtPrice(entry)}`              : "—", inline: true },
        { name: "Stop",        value: stop   != null ? `$${fmtPrice(stop)}${stopPct   != null ? ` (${fmtPct(stopPct)})`   : ""}` : "—", inline: true },
        { name: "Take Profit", value: target != null ? `$${fmtPrice(target)}${targetPct != null ? ` (${fmtPct(targetPct)})` : ""}` : "—", inline: true },
      )
      .setFooter({ text: COMPLIANCE_FOOTER })
      .setTimestamp(new Date());

    const channelIds = channelIdsForBot(signal.botProfile);
    let sentCount = 0;
    for (const channelId of channelIds) {
      if (!perMinuteCheck(channelId)) {
        console.warn(`[discord] rate-limited channel ${channelId} — dropping signal ${signal.signalId}`);
        continue;
      }
      await rateLimit(channelId);
      const channel = await client.channels.fetch(channelId);
      if (channel?.isTextBased()) {
        await (channel as TextChannel).send({ embeds: [embed] });
        sentCount++;
      }
    }

    // ── Step 3: Mark as posted (success path) ──────────────────────────────────
    await db.update(botSignals)
      .set({ discordPostedAt: new Date(), claimedAt: null })
      .where(eq(botSignals.id, signal.signalId));

    console.log(`[discord] posted signal ${signal.signalId} (${signal.symbol} ${signal.side}) to ${sentCount} channel(s)`);

  } catch (err) {
    // Discord send or DB update failed — release the claim so the signal can retry.
    console.error(`[discord] failed to post signal ${signal.signalId}:`, err);
    try {
      await db.update(botSignals)
        .set({ claimedAt: null })
        .where(eq(botSignals.id, signal.signalId));
    } catch (releaseErr) {
      console.error(`[discord] failed to release claim for signal ${signal.signalId}:`, releaseErr);
    }
  }
}
