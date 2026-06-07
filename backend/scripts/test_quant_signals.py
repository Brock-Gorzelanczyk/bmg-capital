"""
Smoke-test: post a mock Crypto Quant Aggressive signal to #quant-signals.

Usage (from project root):
    railway run python backend/scripts/test_quant_signals.py

Usage (from inside backend/):
    railway run python scripts/test_quant_signals.py

Add --dry-run to print the payload without hitting Discord.
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("BMG_QUANT_SIGNALS_CHANNEL_ID", "") or \
             os.environ.get("DISCORD_CH_QUANT_SIGNALS", "")

EMBED = {
    "title": "⚡ Crypto Quant Aggressive · BTC/USD",
    "description": (
        "**Signal:** BB_BREAKOUT (TEST)\n"
        "**Entry:** $67,432.50  |  **Stop:** $66,750.00  |  **Target:** $68,900.00\n"
        "**Confidence:** 0.72  |  **Size:** $5,000\n"
        "**Reason:** Test message — wiring verification only\n"
        "---\n"
        "*Paper trading. Not investment advice. Not a registered investment adviser.*"
    ),
    "color": 0xa78bfa,
    "footer": {"text": "TEST — #quant-signals channel verification"},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print payload without posting")
    args = parser.parse_args()

    if not TOKEN:
        print("✗ ERROR: DISCORD_BOT_TOKEN is not set")
        sys.exit(1)

    if not CHANNEL_ID:
        print("✗ ERROR: BMG_QUANT_SIGNALS_CHANNEL_ID is not set")
        sys.exit(1)

    print(f"✓ Loaded BMG_QUANT_SIGNALS_CHANNEL_ID={CHANNEL_ID}")

    if args.dry_run:
        import json
        print("-- DRY RUN — payload that would be posted:")
        print(json.dumps({"embeds": [EMBED]}, indent=2))
        return

    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    with httpx.Client(timeout=10) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
            json={"embeds": [EMBED]},
        )

    if resp.status_code == 401:
        print(f"✗ HTTP 401 — DISCORD_BOT_TOKEN is wrong or expired")
        sys.exit(1)
    elif resp.status_code == 403:
        print(f"✗ HTTP 403 — bot lacks permission to post in channel {CHANNEL_ID}")
        sys.exit(1)
    elif resp.status_code == 404:
        print(f"✗ HTTP 404 — channel ID {CHANNEL_ID} not found (check BMG_QUANT_SIGNALS_CHANNEL_ID)")
        sys.exit(1)
    elif not resp.is_success:
        print(f"✗ HTTP {resp.status_code} — {resp.text}")
        sys.exit(1)

    print(f"✓ Posted to #quant-signals — HTTP {resp.status_code}")
    print("✓ Test complete.")


if __name__ == "__main__":
    main()
