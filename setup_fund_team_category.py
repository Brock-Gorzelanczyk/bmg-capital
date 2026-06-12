#!/usr/bin/env python3
"""
Creates the FUND TEAM Discord category and its 6 channels.
Usage: DISCORD_BOT_TOKEN=<token> python3 setup_fund_team_category.py

After running, copy the printed env var block into Railway environment settings.
"""
import os
import sys
import json
import urllib.request
import urllib.error

API = "https://discord.com/api/v10"

CHANNELS = [
    ("queen-briefings",  "Daily Queen briefings and morning session summaries"),
    ("queen-proposals",  "Queen allocation proposals awaiting CIO approval"),
    ("risk-alerts",      "Risk Sentinel alerts and CRO escalations"),
    ("macro-view",       "Macro regime updates and market observations"),
    ("research-log",     "Researcher findings and equity/crypto analysis"),
    ("bmg-monitoring",   "Ops reconciliation, data quality, execution audits"),
]

ENV_KEYS = {
    "queen-briefings":  "DISCORD_CH_QUEEN_BRIEFINGS",
    "queen-proposals":  "DISCORD_CH_QUEEN_PROPOSALS",
    "risk-alerts":      "DISCORD_CH_RISK_ALERTS",
    "macro-view":       "DISCORD_CH_MACRO_VIEW",
    "research-log":     "DISCORD_CH_RESEARCH_LOG",
    "bmg-monitoring":   "DISCORD_CH_BMG_MONITORING",
}


def _req(method: str, path: str, payload=None) -> dict:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN env var not set", file=sys.stderr)
        sys.exit(1)

    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload else None
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "BMGCapital/1.0",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"HTTP {e.code} {method} {path}: {body}", file=sys.stderr)
        sys.exit(1)


def get_guilds() -> list[dict]:
    return _req("GET", "/users/@me/guilds")


def pick_guild(guilds: list[dict]) -> dict:
    if len(guilds) == 1:
        return guilds[0]
    print("\nBot is in multiple servers — pick one:")
    for i, g in enumerate(guilds):
        print(f"  [{i}] {g['name']} (id={g['id']})")
    while True:
        raw = input("Enter number: ").strip()
        if raw.isdigit() and 0 <= int(raw) < len(guilds):
            return guilds[int(raw)]


def create_category(guild_id: str, name: str = "FUND TEAM") -> str:
    ch = _req("POST", f"/guilds/{guild_id}/channels", {
        "name": name,
        "type": 4,  # GUILD_CATEGORY
    })
    print(f"Created category: {ch['name']} (id={ch['id']})")
    return ch["id"]


def create_text_channel(guild_id: str, name: str, topic: str, parent_id: str) -> str:
    ch = _req("POST", f"/guilds/{guild_id}/channels", {
        "name": name,
        "type": 0,       # GUILD_TEXT
        "topic": topic,
        "parent_id": parent_id,
    })
    print(f"  Created #{ch['name']} (id={ch['id']})")
    return ch["id"]


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: Set DISCORD_BOT_TOKEN before running this script.", file=sys.stderr)
        sys.exit(1)

    print("Fetching guilds...")
    guilds = get_guilds()
    if not guilds:
        print("ERROR: Bot is not in any Discord server.", file=sys.stderr)
        sys.exit(1)

    guild = pick_guild(guilds)
    guild_id = guild["id"]
    print(f"\nUsing server: {guild['name']} (id={guild_id})\n")

    category_id = create_category(guild_id)

    print("\nCreating channels:")
    created: dict[str, str] = {}
    for ch_name, topic in CHANNELS:
        ch_id = create_text_channel(guild_id, ch_name, topic, category_id)
        created[ch_name] = ch_id

    print("\n" + "=" * 60)
    print("DONE — add these env vars to Railway:")
    print("=" * 60)
    for ch_name, ch_id in created.items():
        env_key = ENV_KEYS[ch_name]
        print(f"{env_key}={ch_id}")

    print("\nAlso set:")
    print("CIO_DISCORD_USER_ID=<your Discord user ID>")
    print("=" * 60)


if __name__ == "__main__":
    main()
