"""
setup_quant_and_audit_channels.py

One-shot setup for two missing Discord channels:
- #quant-signals (in SIGNALS category if it exists, else top level)
- #audit-trail (in FUND TEAM category, locked read-only)

Prints both channel IDs as Railway env var lines ready to paste.

USAGE:
    DISCORD_BOT_TOKEN=<your_bot_token> python3 setup_quant_and_audit_channels.py

REQUIREMENTS:
- discord.py installed (already done from earlier setup scripts)
- Bot has Manage Channels + Manage Roles permissions

SAFE BY DESIGN:
- Idempotent. Re-running finds existing channels and just reprints IDs.
- Won't make duplicates.
- Touches only the 2 new channels.
"""

import asyncio
import os
import sys

import discord

SERVER_NAME = "BMG Capital"

QUANT_CHANNEL_NAME = "quant-signals"
QUANT_CHANNEL_TOPIC = (
    "Quant bot signal feed — every signal from Quant Aggressive, "
    "Quant Scalper, Quant Mean Rev. High volume channel."
)
QUANT_CATEGORY_NAME = "SIGNALS"  # falls back to top-level if not found

AUDIT_CHANNEL_NAME = "audit-trail"
AUDIT_CHANNEL_TOPIC = (
    "Append-only audit log of every manual intervention: bot pauses, "
    "resumes, capital changes, config edits. Locked read-only."
)
AUDIT_CATEGORY_NAME = "FUND TEAM"

BROCK_USER_ID = None  # auto-detects guild owner

token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    print("ERROR: DISCORD_BOT_TOKEN env var not set", file=sys.stderr)
    print("Usage: DISCORD_BOT_TOKEN=<token> python3 setup_quant_and_audit_channels.py",
          file=sys.stderr)
    sys.exit(1)


class ChannelSetup(discord.Client):
    async def on_ready(self):
        print(f"Connected as {self.user}")
        guild = discord.utils.get(self.guilds, name=SERVER_NAME)
        if guild is None:
            print(f"ERROR: '{SERVER_NAME}' not found. Bot is in: "
                  f"{[g.name for g in self.guilds]}", file=sys.stderr)
            await self.close()
            return

        print(f"Guild: {guild.name} (id={guild.id})")
        owner_id = BROCK_USER_ID or guild.owner_id

        # ---- QUANT SIGNALS CHANNEL ----
        quant_category = discord.utils.get(guild.categories, name=QUANT_CATEGORY_NAME)
        if quant_category:
            print(f"Found category: {QUANT_CATEGORY_NAME}")
        else:
            print(f"NOTE: '{QUANT_CATEGORY_NAME}' category not found. "
                  f"Creating #{QUANT_CHANNEL_NAME} at top level.")

        quant_ch = discord.utils.get(guild.text_channels, name=QUANT_CHANNEL_NAME)
        if quant_ch:
            print(f"#{QUANT_CHANNEL_NAME} already exists (id={quant_ch.id})")
            if quant_category and quant_ch.category_id != quant_category.id:
                await quant_ch.edit(category=quant_category)
                print(f"  Moved #{QUANT_CHANNEL_NAME} into {QUANT_CATEGORY_NAME}")
        else:
            quant_ch = await guild.create_text_channel(
                name=QUANT_CHANNEL_NAME,
                category=quant_category,  # None means top-level, fine
                topic=QUANT_CHANNEL_TOPIC,
                reason="Quant bot signal feed setup",
            )
            print(f"CREATED #{QUANT_CHANNEL_NAME} (id={quant_ch.id})")

        # ---- AUDIT TRAIL CHANNEL ----
        audit_category = discord.utils.get(guild.categories, name=AUDIT_CATEGORY_NAME)
        if audit_category is None:
            print(f"ERROR: category '{AUDIT_CATEGORY_NAME}' not found. "
                  f"Run setup_fund_team_category.py first.", file=sys.stderr)
            await self.close()
            return
        print(f"Found category: {AUDIT_CATEGORY_NAME}")

        audit_ch = discord.utils.get(guild.text_channels, name=AUDIT_CHANNEL_NAME)
        if audit_ch:
            print(f"#{AUDIT_CHANNEL_NAME} already exists (id={audit_ch.id})")
            if audit_ch.category_id != audit_category.id:
                await audit_ch.edit(category=audit_category)
                print(f"  Moved #{AUDIT_CHANNEL_NAME} into {AUDIT_CATEGORY_NAME}")
        else:
            audit_ch = await guild.create_text_channel(
                name=AUDIT_CHANNEL_NAME,
                category=audit_category,
                topic=AUDIT_CHANNEL_TOPIC,
                reason="Compliance audit log setup",
            )
            print(f"CREATED #{AUDIT_CHANNEL_NAME} (id={audit_ch.id})")

        # ---- LOCK #audit-trail read-only ----
        everyone = guild.default_role
        bot_role = guild.me.top_role

        await audit_ch.set_permissions(
            everyone,
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=False,
            reason="Lock audit-trail read-only",
        )
        await audit_ch.set_permissions(
            bot_role,
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            add_reactions=True,
            manage_messages=True,
            reason="Bot needs append to audit-trail",
        )
        owner_member = guild.get_member(owner_id)
        if owner_member:
            await audit_ch.set_permissions(
                owner_member,
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                reason="CIO can write to audit-trail manually",
            )
            print(f"Permissions set. CIO ({owner_member.name}) can write.")

        # ---- PRINT ENV VAR LINES ----
        print("")
        print("=" * 78)
        print("RAILWAY ENV VARS — paste BOTH into BMG service Variables tab:")
        print("=" * 78)
        print(f"DISCORD_CH_QUANT_SIGNALS={quant_ch.id}")
        print(f"DISCORD_CH_AUDIT_TRAIL={audit_ch.id}")
        print("=" * 78)
        print("")
        print("After adding both, Railway auto-restarts in ~30 seconds.")
        print("Then Quant bot Discord posting gap should close and audit_trail")
        print("entries will appear in #audit-trail.")

        await self.close()


async def main():
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    client = ChannelSetup(intents=intents)
    await client.start(token)


if __name__ == "__main__":
    asyncio.run(main())
