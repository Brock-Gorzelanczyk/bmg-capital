"""
Smoke-test: post a mock Crypto Quant Aggressive signal to #quant-signals.

Usage:
    railway run python scripts/test_quant_signals.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx

TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("BMG_QUANT_SIGNALS_CHANNEL_ID", "") or os.environ.get("DISCORD_CH_QUANT_SIGNALS", "")

if not TOKEN or not CHANNEL_ID:
    print("ERROR: DISCORD_BOT_TOKEN and BMG_QUANT_SIGNALS_CHANNEL_ID must be set")
    sys.exit(1)

embed = {
    "title": "⚡ Crypto Quant Aggressive · BTC/USD",
    "description": (
        "**Signal:** crypto_quant_vwap_fade\n"
        "**Entry:** $67,420.00  |  **Stop:** $66,384.27  |  **Target:** $69,442.60\n"
        "**Confidence:** 61.3%  |  **Size:** $500.00\n"
        "**Reason:** Price rejected VWAP from below on 3× average volume; momentum diverging bullish\n"
        "—\n"
        "*Paper trading. Not investment advice. Not a registered investment adviser.*"
    ),
    "color": 0xa78bfa,
    "footer": {"text": "TEST — #quant-signals channel verification"},
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
    print("✓ Test signal posted to #quant-signals successfully")
else:
    print(f"✗ Failed: {resp.text}")
    sys.exit(1)
