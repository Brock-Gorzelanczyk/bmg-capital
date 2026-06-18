import { Client, GatewayIntentBits, Partials } from "discord.js";

let cachedClient: Client | null = null;
let readyPromise: Promise<Client> | null = null;

export async function getDiscordClient(): Promise<Client> {
  if (cachedClient?.isReady()) return cachedClient;
  if (readyPromise) return readyPromise;

  const token = process.env.DISCORD_BOT_TOKEN;
  if (!token) throw new Error("DISCORD_BOT_TOKEN is not set");

  // MessageContent is a Privileged Gateway Intent — must be enabled in the
  // Discord Developer Portal before the bot may request it.  Gate it behind
  // an env var so the worker boots cleanly even if the portal flag isn't set.
  const intents: GatewayIntentBits[] = [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
  ];
  if (process.env.ENABLE_MESSAGE_CONTENT_INTENT === "true") {
    intents.push(GatewayIntentBits.MessageContent);
  }

  const client = new Client({ intents, partials: [Partials.Channel] });

  readyPromise = new Promise((resolve, reject) => {
    client.once("ready", () => {
      console.log(`[discord] logged in as ${client.user?.tag}`);
      cachedClient = client;
      resolve(client);
    });
    client.once("error", reject);
    client.login(token).catch(reject);
  });

  return readyPromise;
}
