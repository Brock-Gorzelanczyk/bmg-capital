#!/usr/bin/env python3
"""
One-shot: creates FUND TEAM category + 6 channels on the BMG Capital Discord server,
locks #queen-proposals, moves #dev-log in, and auto-writes env vars to Railway.
"""
import os, sys, json, subprocess, urllib.request, urllib.error

TOKEN     = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID  = os.environ.get("DISCORD_GUILD_ID", "1512902284043096175").strip()
API       = "https://discord.com/api/v10"

if not TOKEN:
    sys.exit("ERROR: DISCORD_BOT_TOKEN not set")

CHANNELS = [
    ("queen-briefings", "PM daily briefings (7am / 12pm / 4:30pm / 9pm ET)"),
    ("queen-proposals", "Tier B proposals — react ✅ approve / ❌ reject / 🕐 defer 24h"),
    ("risk-alerts",     "Chief Risk Officer real-time alerts"),
    ("macro-view",      "Macro Strategist daily + regime transitions"),
    ("research-log",    "Equity + Quant Research findings"),
    ("bmg-monitoring",  "Data Quality + Execution Auditor + Operations"),
]

ENV_KEYS = {
    "queen-briefings": "DISCORD_CH_QUEEN_BRIEFINGS",
    "queen-proposals": "DISCORD_CH_QUEEN_PROPOSALS",
    "risk-alerts":     "DISCORD_CH_RISK_ALERTS",
    "macro-view":      "DISCORD_CH_MACRO_VIEW",
    "research-log":    "DISCORD_CH_RESEARCH_LOG",
    "bmg-monitoring":  "DISCORD_CH_BMG_MONITORING",
}

# Discord permission bit flags
PERM_VIEW            = 1 << 10
PERM_SEND            = 1 << 11
PERM_READ_HISTORY    = 1 << 16
PERM_ADD_REACTIONS   = 1 << 6
PERM_MANAGE_MESSAGES = 1 << 13


def req(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        f"{API}{path}", data=data,
        headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json", "User-Agent": "DiscordBot (https://github.com, 1.0.0)"},
        method=method,
    )
    try:
        with urllib.request.urlopen(r) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"  !! HTTP {e.code} {method} {path}: {body}")
        raise


def get_guild():
    return req("GET", f"/guilds/{GUILD_ID}?with_counts=false")


def get_channels():
    return req("GET", f"/guilds/{GUILD_ID}/channels")


def find_or_create_category(channels, name="FUND TEAM"):
    existing = next((c for c in channels if c["type"] == 4 and c["name"].upper() == name.upper()), None)
    if existing:
        print(f"  Category already exists: {existing['name']} ({existing['id']})")
        return existing["id"]
    cat = req("POST", f"/guilds/{GUILD_ID}/channels", {"name": name, "type": 4, "position": 0})
    print(f"  Created category: {cat['name']} ({cat['id']})")
    return cat["id"]


def find_or_create_text_channel(channels, name, topic, parent_id, position):
    existing = next((c for c in channels if c["type"] == 0 and c["name"] == name), None)
    if existing:
        # Ensure it's under the right category
        if existing.get("parent_id") != parent_id:
            req("PATCH", f"/channels/{existing['id']}", {"parent_id": parent_id, "position": position})
            print(f"  Moved existing #{name} → FUND TEAM ({existing['id']})")
        else:
            print(f"  Channel already exists: #{name} ({existing['id']})")
        return existing["id"]
    ch = req("POST", f"/guilds/{GUILD_ID}/channels", {
        "name": name, "type": 0, "topic": topic,
        "parent_id": parent_id, "position": position,
    })
    print(f"  Created #{ch['name']} ({ch['id']})")
    return ch["id"]


def move_dev_log(channels, parent_id, position):
    dev_log = next((c for c in channels if c["type"] == 0 and c["name"] == "dev-log"), None)
    if not dev_log:
        print("  #dev-log not found, skipping")
        return
    if dev_log.get("parent_id") == parent_id:
        print(f"  #dev-log already in FUND TEAM ({dev_log['id']})")
        return
    req("PATCH", f"/channels/{dev_log['id']}", {"parent_id": parent_id, "position": position})
    print(f"  Moved #dev-log → FUND TEAM ({dev_log['id']})")


def lock_proposals_channel(channel_id, guild, bot_user_id):
    """
    @everyone: view + read_history only (deny send + add_reactions)
    Bot role: full send + react + manage_messages
    Guild owner: full send + add_reactions
    """
    everyone_role_id = GUILD_ID  # @everyone role ID == guild ID in Discord

    # Find the bot's role (integration role — same name as bot app)
    guild_roles = req("GET", f"/guilds/{GUILD_ID}/roles")
    bot_role = next(
        (r for r in guild_roles if r.get("managed") and r.get("name") != "@everyone"),
        None,
    )

    # @everyone: allow view + read_history, deny send + add_reactions
    req("PUT", f"/channels/{channel_id}/permissions/{everyone_role_id}", {
        "type": 0,  # role
        "allow": str(PERM_VIEW | PERM_READ_HISTORY),
        "deny":  str(PERM_SEND | PERM_ADD_REACTIONS),
    })
    print(f"  @everyone overwrite set on #queen-proposals")

    # Bot role overwrite
    if bot_role:
        req("PUT", f"/channels/{channel_id}/permissions/{bot_role['id']}", {
            "type": 0,
            "allow": str(PERM_SEND | PERM_ADD_REACTIONS | PERM_MANAGE_MESSAGES | PERM_VIEW | PERM_READ_HISTORY),
            "deny":  "0",
        })
        print(f"  Bot role ({bot_role['name']}) overwrite set on #queen-proposals")

    # Guild owner (Brock) — member overwrite
    owner_id = guild.get("owner_id")
    if owner_id:
        req("PUT", f"/channels/{channel_id}/permissions/{owner_id}", {
            "type": 1,  # member
            "allow": str(PERM_VIEW | PERM_READ_HISTORY | PERM_SEND | PERM_ADD_REACTIONS),
            "deny":  "0",
        })
        print(f"  Owner ({owner_id}) overwrite set on #queen-proposals")

    return owner_id


def railway_set(key, value):
    result = subprocess.run(
        ["railway", "variables", "set", f"{key}={value}", "--service", "disciplined-intuition"],
        capture_output=True, text=True,
        cwd="/Users/brockgorzelanczyk/my-new-project",
    )
    if result.returncode != 0:
        print(f"  !! railway set {key} failed: {result.stderr.strip()}")
        return False
    return True


def get_bot_user_id():
    me = req("GET", "/users/@me")
    return me.get("id")


def main():
    print("\n[1/8] Fetching guild info...")
    guild = get_guild()
    print(f"  Guild: {guild['name']} ({guild['id']}), owner: {guild['owner_id']}")

    print("\n[2/8] Fetching existing channels...")
    channels = get_channels()
    print(f"  Found {len(channels)} existing channels")

    print("\n[3/8] Creating FUND TEAM category...")
    cat_id = find_or_create_category(channels)

    print("\n[4/8] Creating 6 text channels...")
    created_ids = {}
    for i, (name, topic) in enumerate(CHANNELS):
        ch_id = find_or_create_text_channel(channels, name, topic, cat_id, position=i)
        created_ids[name] = ch_id

    print("\n[5/8] Moving #dev-log into FUND TEAM...")
    move_dev_log(channels, cat_id, position=7)

    print("\n[6/8] Locking #queen-proposals...")
    bot_user_id = get_bot_user_id()
    owner_id = lock_proposals_channel(created_ids["queen-proposals"], guild, bot_user_id)

    env_vars = {
        ENV_KEYS[name]: ch_id for name, ch_id in created_ids.items()
    }
    env_vars["QUEEN_BRIEF_CHANNEL_ID"] = created_ids["queen-briefings"]
    env_vars["CIO_DISCORD_USER_ID"]    = guild["owner_id"]

    print("\n[7/8] Writing env vars to Railway...")
    for key, value in env_vars.items():
        ok = railway_set(key, value)
        status = "✓" if ok else "✗"
        print(f"  {status} {key}={value}")

    print("\n[8/8] Verifying Railway picked up CIO_DISCORD_USER_ID...")
    result = subprocess.run(
        ["railway", "variables", "--service", "disciplined-intuition"],
        capture_output=True, text=True,
        cwd="/Users/brockgorzelanczyk/my-new-project",
    )
    cio_set = "CIO_DISCORD_USER_ID" in result.stdout
    print(f"  CIO_DISCORD_USER_ID in Railway vars: {'YES ✓' if cio_set else 'NOT FOUND ✗'}")

    print("\n" + "=" * 60)
    print("ENV VAR BLOCK — also written to Railway above:")
    print("=" * 60)
    for key, value in env_vars.items():
        print(f"{key}={value}")
    print("=" * 60)
    print("\nDone. Railway will restart and pick up the new vars automatically.")


if __name__ == "__main__":
    main()
