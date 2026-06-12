"""
Standalone Queen test post — no DB, no app required.

Usage:
    DISCORD_BOT_TOKEN=<token> DISCORD_CH_DEV_LOG=1512906481651945512 python3 scripts/test_queen_post.py

Posts a realistic Queen brief embed to #dev-log using today's date.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

CHANNEL_ID = os.getenv("DISCORD_CH_DEV_LOG", "1512906481651945512")
TOKEN       = os.getenv("DISCORD_BOT_TOKEN", "")

if not TOKEN:
    print("ERROR: set DISCORD_BOT_TOKEN env var")
    print("  Run:  DISCORD_BOT_TOKEN=<your_token> python3 scripts/test_queen_post.py")
    sys.exit(1)

now = datetime.now(timezone.utc)

embed = {
    "author":    {"name": "BMG Capital — Queen Agent"},
    "title":     f"Daily Intelligence Brief — {now.strftime('%A, %B %-d, %Y')} [TEST]",
    "color":     0x16A34A,
    "fields": [
        {"name": "✅ System Status",    "value": "GREEN (test run)",                                           "inline": True},
        {"name": "Market Regime",        "value": "📈 **bull_trending** | VIX 16.2 | Trend bullish | BTC Dom 52.1%", "inline": False},
        {"name": "Bot Execution",        "value": "12 healthy | 0 stale | 1 disabled",                         "inline": False},
        {"name": "Signals Today",        "value": "142 today | avg 128/day (111% of avg) — **OK**",            "inline": False},
        {"name": "Alpaca (stocks sleeve)", "value": "**OK** | equity $514.3k | BP $412.0k",                    "inline": False},
        {"name": "Signal IC Health",     "value": "Strong: crypto_quant_aggressive | All others within range", "inline": False},
        {"name": "WFA Pipeline",         "value": "0 ready | 2 total in pipeline",                             "inline": False},
        {"name": "Research Directives",  "value": (
            "• Regime bull_trending — prioritize stock_swing, stock_lt\n"
            "• VIX=16.2 normal — premium selling window open; check IVR > 30\n"
            "• BTC dominance=52.1% — altcoins underperforming; stick to BTC/ETH\n"
            "• STRONG IC: crypto_quant_aggressive IC=0.071 — consider increasing allocation weight"
        ), "inline": False},
    ],
    "footer":    {"text": "Paper trading · Not investment advice · TEST POST — Queen Agent v1"},
    "timestamp": now.isoformat(),
}

url  = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
body = json.dumps({"embeds": [embed]}).encode()
req  = urllib.request.Request(
    url,
    data=body,
    headers={
        "Authorization": f"Bot {TOKEN}",
        "Content-Type":  "application/json",
        "User-Agent":    "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        print(f"Posted successfully — message ID: {data.get('id')}")
        print(f"Channel: {CHANNEL_ID}")
except urllib.error.HTTPError as e:
    body_text = e.read().decode()
    print(f"Discord API error {e.code}: {body_text}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
