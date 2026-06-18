#!/usr/bin/env python3
"""Create #price-alerts Discord channel for Workshop price alert notifications.

Usage:
    DISCORD_BOT_TOKEN=<token> DISCORD_GUILD_ID=<guild_id> python3 backend/scripts/setup_workshop_channel.py

The script finds or creates a WORKSHOP category, then creates #price-alerts inside it.
Prints the channel ID — add it to Railway as DISCORD_CH_PRICE_ALERTS.

Requires: pip install httpx (already in requirements)
"""
import os
import sys
import httpx

TOKEN    = os.environ.get("DISCORD_BOT_TOKEN", "")
GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")

if not TOKEN or not GUILD_ID:
    print("ERROR: Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID env vars before running.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bot {TOKEN}",
    "Content-Type": "application/json",
}
BASE = "https://discord.com/api/v10"

# ── Fetch current channels ────────────────────────────────────────────────────
resp = httpx.get(f"{BASE}/guilds/{GUILD_ID}/channels", headers=HEADERS, timeout=10)
if resp.status_code != 200:
    print(f"ERROR fetching channels: {resp.status_code} {resp.text}")
    sys.exit(1)
channels = resp.json()

# ── Find or create WORKSHOP category ─────────────────────────────────────────
category = next(
    (c for c in channels if c["type"] == 4 and c["name"].upper() == "WORKSHOP"),
    None
)
if not category:
    print("Creating WORKSHOP category...")
    r = httpx.post(
        f"{BASE}/guilds/{GUILD_ID}/channels",
        headers=HEADERS,
        json={"name": "WORKSHOP", "type": 4},
        timeout=10,
    )
    if r.status_code not in (200, 201):
        print(f"ERROR creating category: {r.status_code} {r.text}")
        sys.exit(1)
    category = r.json()
    print(f"  Created category: WORKSHOP (ID: {category['id']})")
else:
    print(f"Found category: {category['name']} (ID: {category['id']})")

# ── Find or create #price-alerts ─────────────────────────────────────────────
existing = next(
    (c for c in channels if c.get("parent_id") == category["id"] and c["name"] == "price-alerts"),
    None
)
if existing:
    print(f"Channel already exists: #{existing['name']} (ID: {existing['id']})")
    channel_id = existing["id"]
else:
    print("Creating #price-alerts channel...")
    r = httpx.post(
        f"{BASE}/guilds/{GUILD_ID}/channels",
        headers=HEADERS,
        json={
            "name": "price-alerts",
            "type": 0,
            "parent_id": category["id"],
            "topic": "🔔 Price alerts from Workshop — fires when your annotated levels are crossed.",
        },
        timeout=10,
    )
    if r.status_code not in (200, 201):
        print(f"ERROR creating channel: {r.status_code} {r.text}")
        sys.exit(1)
    ch = r.json()
    channel_id = ch["id"]
    print(f"  Created: #{ch['name']} (ID: {channel_id})")

print()
print("=" * 60)
print("Add to Railway environment variables:")
print(f"  DISCORD_CH_PRICE_ALERTS={channel_id}")
print("=" * 60)
