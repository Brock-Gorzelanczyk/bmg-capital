"""
End-to-end crypto pipeline smoke test.

Calls POST /api/bots/debug/force-trade on the live server and prints
a step-by-step report.

Usage:
  API_URL=https://your-app.railway.app \
  API_TOKEN=<your JWT token> \
  python scripts/force_test_crypto_trade.py

The token is your 920wp_token or BMG_TOKEN from the browser localStorage.
"""
import json
import os
import sys

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

API_URL = os.environ.get("API_URL", "http://localhost:8000")
TOKEN   = os.environ.get("API_TOKEN", "")

if not TOKEN:
    print("ERROR: set API_TOKEN env var to your JWT.")
    sys.exit(1)

url = f"{API_URL.rstrip('/')}/api/bots/debug/force-trade"
print(f"POST {url}\n")

r = httpx.post(
    url,
    headers={"Authorization": f"Bearer {TOKEN}"},
    timeout=30.0,
)

if r.status_code != 200:
    print(f"HTTP {r.status_code}: {r.text}")
    sys.exit(1)

data = r.json()
steps = data.get("steps", {})
labels = {
    "a_allocation": "a. Find allocation",
    "b_btc_price":  "b. Fetch BTC price",
    "c_alpaca":     "c. Alpaca paper trade",
    "d_bot_signal": "d. Insert bot_signal",
    "e_position":   "e. Insert bot_position",
    "f_trade":      "f. Insert bot_trade",
    "g_discord":    "g. Post Discord embed",
}

for key, label in labels.items():
    step = steps.get(key, {})
    ok   = step.get("ok", False)
    icon = "✓" if ok else "✗"
    detail = {k: v for k, v in step.items() if k != "ok"}
    print(f"  {icon} {label}")
    if detail:
        print(f"      {json.dumps(detail, indent=None)}")

print()
print("Summary:", data.get("summary"))
print("Portfolio value:", f"${data.get('portfolio_value_usd', 0):,.2f}")
print()
print(data.get("next", ""))
