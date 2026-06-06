"""
Task 2 smoke test — fire a test signal embed to #all-signals and the stock channel.
No DB connection required (passes db=None to post_signal).

Run:
    railway run --environment production .venv/bin/python3 scripts/test_signal_discord.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

# Verify Discord env vars are present before importing anything else
token = os.environ.get("DISCORD_BOT_TOKEN", "")
ch_all = os.environ.get("DISCORD_CH_ALL_SIGNALS", "")
if not token or not ch_all:
    print("ERROR: DISCORD_BOT_TOKEN and DISCORD_CH_ALL_SIGNALS must be set")
    sys.exit(1)

print(f"Token present: {'yes' if token else 'no'}")
print(f"#all-signals channel: {ch_all}")

from app.services.discord_public import post_signal

test_signal = {
    "bot":        "stock_swing",
    "symbol":     "AAPL",
    "side":       "BUY",
    "confidence": 0.78,
    "reason":     "Task 2 smoke test — Discord wiring from audit.py log_signal()",
    "strategy":   "momentum",
    "size_pct":   5.0,
    "price":      None,
    "stop":       None,
    "target":     None,
}

print(f"\nPosting test signal: {test_signal['side']} {test_signal['symbol']} ...")
post_signal(test_signal, db=None, signal_id=None)
print("Done — check #all-signals and #stocks-signals in Discord.")
