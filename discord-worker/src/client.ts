import { Client, GatewayIntentBits, Partials } from "discord.js";

let cachedClient: Client | null = null;
let readyPromise: Promise<Client> | null = null;

export async function getDiscordClient(): Promise<Client> {
  if (cachedClient?.isReady()) return cachedClient;
  if (readyPromise) return readyPromise;

  const token = process.env.DISCORD_BOT_TOKEN;
  if (!token) throw new Error("DISCORD_BOT_TOKEN is not set");

  const client = new Client({
    intents: [GatewayIntentBits.Guilds],
    partials: [Partials.Channel],
  });

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
