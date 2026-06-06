import cron from "node-cron";
import { postDailyDigest }       from "./daily-digest.js";
import { postWeeklyLeaderboard } from "./weekly-leaderboard.js";
import { postMonthlyRecap }      from "./monthly-recap.js";

let started = false;

export function startDiscordSchedulers(): void {
  if (started) return;
  started = true;

  // Mon-Fri 4:30 PM ET
  cron.schedule("30 16 * * 1-5", () => void postDailyDigest(), {
    timezone: "America/New_York",
  });

  // Sundays 6:00 PM ET
  cron.schedule("0 18 * * 0", () => void postWeeklyLeaderboard(), {
    timezone: "America/New_York",
  });

  // 1st of each month, 9:00 AM ET
  cron.schedule("0 9 1 * *", () => void postMonthlyRecap(), {
    timezone: "America/New_York",
  });

  console.log("[discord] schedulers started (daily-digest, weekly-leaderboard, monthly-recap)");
}
