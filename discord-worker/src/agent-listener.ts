/**
 * Agent Message Listener — two-way Discord ↔ BMG Capital agent chat.
 *
 * When Brock (or anyone with permission) posts a message in a FUND TEAM channel,
 * the corresponding agent responds within ~10 seconds.
 *
 * Channel → agent mapping uses env-var channel IDs (same IDs used for posting).
 * Rate limit: 1 response per channel per 10 seconds (in-memory).
 *
 * Requires Discord bot to have "Message Content Intent" enabled in the
 * Discord Developer Portal → Bot → Privileged Gateway Intents.
 */

import { Client, Message, TextChannel, EmbedBuilder } from "discord.js";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

// Channel ID → agent name mapping (env-var driven so IDs can change without redeploy)
function buildChannelAgentMap(): Map<string, string> {
  const m = new Map<string, string>();
  const add = (envVar: string, agent: string) => {
    const id = process.env[envVar]?.trim();
    if (id) m.set(id, agent);
  };
  add("DISCORD_CH_QUEEN_BRIEFINGS",  "brick");
  add("DISCORD_CH_QUEEN_PROPOSALS",  "brick");
  add("DISCORD_CH_RISK_ALERTS",      "dick");
  add("DISCORD_CH_MACRO_VIEW",       "rick");
  add("DISCORD_CH_RESEARCH_LOG",     "nick");
  add("DISCORD_CH_BMG_MONITORING",   "vick");
  add("DISCORD_CH_OPS_STATUS",       "wick");
  add("DISCORD_CH_FUND_TEAM_CHAT",   "brick");  // default to Brick, handle @mentions inside
  return m;
}

// Agent display names for embed author field
const AGENT_PERSONA: Record<string, string> = {
  brick: "👑 Brick (Portfolio Manager)",
  dick:  "⚠️ Dick (CRO)",
  vick:  "📊 Vick (Data Quality)",
  wick:  "🔧 Wick (Ops)",
  rick:  "🔭 Rick (Macro Strategist)",
  nick:  "🔬 Nick (Researcher)",
};

const AGENT_COLOR: Record<string, number> = {
  brick: 0xF59E0B,  // amber
  dick:  0xEF4444,  // red
  vick:  0x3B82F6,  // blue
  wick:  0x6B7280,  // gray
  rick:  0x8B5CF6,  // purple
  nick:  0x10B981,  // green
};

// Rate limiting: channelId → timestamp of last response
const _lastResponse = new Map<string, number>();
const RATE_LIMIT_MS = 10_000;  // 10 seconds

function isRateLimited(channelId: string): boolean {
  const last = _lastResponse.get(channelId) ?? 0;
  return Date.now() - last < RATE_LIMIT_MS;
}

function markResponded(channelId: string): void {
  _lastResponse.set(channelId, Date.now());
}

// Detect @mention override for fund-team-chat routing
function detectMentionedAgent(content: string): string | null {
  const lower = content.toLowerCase();
  if (lower.includes("@dick") || lower.includes("@cro"))  return "dick";
  if (lower.includes("@vick"))                             return "vick";
  if (lower.includes("@wick") || lower.includes("@ops"))  return "wick";
  if (lower.includes("@rick") || lower.includes("@macro")) return "rick";
  if (lower.includes("@nick") || lower.includes("@research")) return "nick";
  if (lower.includes("@brick") || lower.includes("@queen")) return "brick";
  return null;
}

async function callAgentRespond(
  agent: string,
  message: string,
  authorName: string,
  authorId: string,
  channelId: string,
): Promise<string | null> {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/agents/${agent}/respond`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, author_name: authorName, author_id: authorId, channel_id: channelId }),
      signal: AbortSignal.timeout(30_000),
    });
    if (!resp.ok) {
      console.warn(`[agent-listener] backend returned ${resp.status} for ${agent}`);
      return null;
    }
    const data = await resp.json() as { reply: string | null };
    return data.reply ?? null;
  } catch (err) {
    console.warn("[agent-listener] backend call failed:", err);
    return null;
  }
}

async function postAgentReply(
  channel: TextChannel,
  agent: string,
  replyText: string,
  originalMessage: Message,
): Promise<void> {
  const embed = new EmbedBuilder()
    .setAuthor({ name: AGENT_PERSONA[agent] ?? agent })
    .setDescription(replyText.slice(0, 4096))
    .setColor(AGENT_COLOR[agent] ?? 0x6B7280)
    .setTimestamp()
    .setFooter({ text: "BMG Capital | Paper trading. Not investment advice." });

  try {
    await channel.send({ embeds: [embed], reply: { messageReference: originalMessage.id, failIfNotExists: false } });
  } catch {
    await channel.send({ embeds: [embed] });
  }
}

export function attachAgentListener(client: Client): void {
  const channelAgentMap = buildChannelAgentMap();

  if (channelAgentMap.size === 0) {
    console.warn("[agent-listener] No DISCORD_CH_* env vars set — agent listener inactive");
    return;
  }

  console.log(`[agent-listener] Listening on ${channelAgentMap.size} channels`);

  client.on("messageCreate", async (message: Message) => {
    // Ignore bots (prevents infinite loops)
    if (message.author.bot) return;

    // Only respond in mapped channels
    const baseAgent = channelAgentMap.get(message.channelId);
    if (!baseAgent) return;

    // Rate limit per channel
    if (isRateLimited(message.channelId)) return;

    // Determine which agent responds (allow @mentions to override)
    const agent = detectMentionedAgent(message.content) ?? baseAgent;

    const channel = message.channel as TextChannel;
    markResponded(message.channelId);

    // Show typing indicator
    try { await channel.sendTyping(); } catch { /* ignore */ }

    const reply = await callAgentRespond(
      agent,
      message.content,
      message.author.username,
      message.author.id,
      message.channelId,
    );

    if (!reply) {
      console.warn(`[agent-listener] No reply from ${agent} for message in ${message.channelId}`);
      return;
    }

    await postAgentReply(channel, agent, reply, message);
  });
}
