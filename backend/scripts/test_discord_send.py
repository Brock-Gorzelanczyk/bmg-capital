"""
Quick smoke-test: post a test embed to #all-signals via the same httpx path
production uses (no discord.py needed).

Usage:
    railway run python scripts/test_discord_send.py
    # or locally (needs DISCORD_BOT_TOKEN + DISCORD_CH_ALL_SIGNALS in env):
    DISCORD_BOT_TOKEN=... DISCORD_CH_ALL_SIGNALS=... python scripts/test_discord_send.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx

TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("DISCORD_CH_ALL_SIGNALS", "")

if not TOKEN or not CHANNEL_ID:
    print("ERROR: set DISCORD_BOT_TOKEN and DISCORD_CH_ALL_SIGNALS env vars")
    sys.exit(1)

embed = {
    "title": "🟢 BMG Signals connected",
    "description": "Test post — REST API path is live.",
    "color": 0x2EC4A1,
    "footer": {"text": "Paper trading. Not investment advice."},
}

url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
with httpx.Client(timeout=10) as client:
    resp = client.post(
        url,
        headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
        json={"embeds": [embed]},
    )

print(f"HTTP {resp.status_code}")
if resp.is_success:
    print("✓ Message posted successfully")
else:
    print(f"✗ Failed: {resp.text}")
    sys.exit(1)
