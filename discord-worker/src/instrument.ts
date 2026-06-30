import * as Sentry from "@sentry/node";

if (process.env.SENTRY_DSN_DISCORD_WORKER) {
  Sentry.init({
    dsn: process.env.SENTRY_DSN_DISCORD_WORKER,
    environment: process.env.RAILWAY_ENVIRONMENT || "production",
    release: process.env.RAILWAY_GIT_COMMIT_SHA || "unknown",
    tracesSampleRate: 0.05,
  });
}

export default Sentry;
