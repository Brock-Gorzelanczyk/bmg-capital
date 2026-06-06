"""
Task 3 smoke test — manually fire daily digest, weekly leaderboard, and monthly recap.
No DB required — passes test data directly to the discord_public helpers.

Run:
    railway run --environment production .venv/bin/python3 scripts/test_discord_crons.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

token = os.environ.get("DISCORD_BOT_TOKEN", "")
if not token:
    print("ERROR: DISCORD_BOT_TOKEN must be set")
    sys.exit(1)

from app.services.discord_public import post_daily_digest, post_weekly_leaderboard, post_monthly_recap

# --- Daily digest ---
print("Posting daily digest ...")
post_daily_digest({
    "total_signals": 14,
    "by_bot": {
        "stock_swing":  5,
        "crypto_swing": 4,
        "crypto_day":   3,
        "options_income": 2,
    },
    "top_symbols": ["AAPL", "ETH/USD", "BTC/USD", "NVDA", "SPY"],
    "realized_pnl_cents": 84700,  # $847.00
})
print("  done")

# --- Weekly leaderboard ---
print("Posting weekly leaderboard ...")
post_weekly_leaderboard([
    {"profile": "stock_swing",       "return_30d_pct":  4.21},
    {"profile": "crypto_swing",      "return_30d_pct":  3.88},
    {"profile": "options_income",    "return_30d_pct":  2.14},
    {"profile": "crypto_day",        "return_30d_pct":  1.57},
    {"profile": "stock_day",         "return_30d_pct":  0.93},
    {"profile": "stock_lt",          "return_30d_pct": -0.31},
    {"profile": "options_directional","return_30d_pct":-1.02},
])
print("  done")

# --- Monthly recap ---
print("Posting monthly recap ...")
post_monthly_recap({
    "month_name": "May 2025",
    "signals":    312,
    "trades":     0,
    "pnl_cents":  1_240_000,  # $12,400
})
print("  done")

print("\nAll three embeds fired — verify in Discord.")
