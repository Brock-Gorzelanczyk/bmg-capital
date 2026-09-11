"""daily_prices.py — pull latest close + publication-day close for every call.

Reads the vault's research/ folder for notes with v2 frontmatter. For each
unique (ticker, benchmark) pair, fetches the latest close + the historical
close on the call's published_at date. Writes data/prices.json with
fetched_at timestamp.

Data source: **Alpaca Market Data v2 API** (IEX feed on free tier).
  - GET https://data.alpaca.markets/v2/stocks/bars — historical daily bars
  - GET https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest — latest
  - Auth: APCA-API-KEY-ID + APCA-API-SECRET-KEY headers

Auth: read from environment. Set in a local .env or your shell:
    export APCA_API_KEY_ID=PK...
    export APCA_API_SECRET_KEY=...

or copy `.env.example` to `.env` and populate. The build script reads
`.env` if present (via python-dotenv if installed, or a lightweight parser
if not).

yfinance migration note (2026-09-10): this file previously used
yfinance.Ticker().history() which is an unofficial scraper subject to
breakage without notice. Migrated to Alpaca which is a stable licensed
feed. See README's "yfinance blast radius" section for the remaining
places yfinance is still used (none in this file after this change).

Failure modes:
  - Missing API keys → clear error, exit non-zero
  - Symbol not in IEX feed → skip with warning, still write partial JSON
  - Historical date is a market holiday → walk forward until we find a
    valid trading-day close
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
VAULT = Path.home() / "Documents" / "BMG-Capital-Vault"
DOTENV = ROOT / ".env"
ALPACA_DATA_HOST = "https://data.alpaca.markets"

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml")
    sys.exit(1)
try:
    import requests
except ImportError:
    print("[fail] pip install requests")
    sys.exit(1)


def load_dotenv() -> None:
    """Populate os.environ from .env if present. Bare minimum parser."""
    if not DOTENV.exists():
        return
    for line in DOTENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def alpaca_headers() -> dict:
    # Accept both the official Alpaca SDK names (APCA_API_KEY_ID / APCA_API_SECRET_KEY)
    # and the shorter aliases used elsewhere in this repo (ALPACA_API_KEY / ALPACA_SECRET_KEY).
    key = (os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise RuntimeError(
            "Alpaca creds missing. Set APCA_API_KEY_ID + APCA_API_SECRET_KEY "
            "(or the aliases ALPACA_API_KEY + ALPACA_SECRET_KEY used by backend/.env) "
            "in the environment or in scripts/local/bmg_v2_site/.env "
            "(see .env.example). Get keys at https://app.alpaca.markets "
            "(paper account keys work for market data)."
        )
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


def fetch_latest_close(symbol: str, headers: dict) -> float | None:
    """Fetch the latest daily bar close via Alpaca."""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=10)).isoformat()
    url = f"{ALPACA_DATA_HOST}/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Day", "start": start, "end": end, "limit": 10, "feed": "iex"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        return None
    bars = r.json().get("bars", [])
    if not bars:
        return None
    # Walk backwards from the most recent bar until we find a valid close
    for b in reversed(bars):
        c = b.get("c")
        if c is not None:
            return float(c)
    return None


def fetch_close_on_or_after(symbol: str, target_date: str, headers: dict) -> float | None:
    """Get close on target_date, or on the next available trading day."""
    d = date.fromisoformat(target_date)
    end = (d + timedelta(days=8)).isoformat()
    url = f"{ALPACA_DATA_HOST}/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Day", "start": target_date, "end": end, "limit": 10, "feed": "iex"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        return None
    bars = r.json().get("bars", [])
    for b in bars:
        ts = b.get("t", "")[:10]
        if ts >= target_date and b.get("c") is not None:
            return float(b["c"])
    return None


def load_call_tickers() -> list[tuple[str, str, str]]:
    """(ticker, benchmark, published_at_iso) tuples for every v2 call."""
    out = []
    for path in sorted((VAULT / "research").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m: continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict): continue
        if not all(k in fm for k in ("ticker", "direction", "published_price")):
            continue
        pub = fm.get("published_at")
        if not pub:
            pub = date.fromtimestamp(path.stat().st_mtime).isoformat()
        out.append((
            fm["ticker"].upper(),
            (fm.get("benchmark") or "IWM").upper(),
            pub if isinstance(pub, str) else pub.isoformat(),
        ))
    return out


def main() -> int:
    load_dotenv()
    DATA.mkdir(exist_ok=True)
    try:
        headers = alpaca_headers()
    except RuntimeError as e:
        print(f"[fail] {e}")
        return 1

    tickers = load_call_tickers()
    if not tickers:
        print("[daily-prices] no v2 calls found in vault")
        return 0

    need_hist: dict[str, set[str]] = {}
    for tk, bench, pub in tickers:
        need_hist.setdefault(tk, set())
        need_hist.setdefault(bench, set()).add(pub)

    print(f"[daily-prices] pricing {len(need_hist)} tickers via Alpaca")
    result_prices = {}
    for tk in sorted(need_hist.keys()):
        last = fetch_latest_close(tk, headers)
        hist = {}
        for d in sorted(need_hist[tk]):
            c = fetch_close_on_or_after(tk, d, headers)
            if c is not None:
                hist[d] = c
        result_prices[tk] = {"last": last, "historical": hist}
        last_s = f"${last:.2f}" if last is not None else "—"
        print(f"  {tk}: last={last_s}, hist_dates={sorted(hist.keys()) or '[]'}")

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Alpaca Market Data v2 (IEX feed)",
        "prices": result_prices,
    }
    (DATA / "prices.json").write_text(json.dumps(payload, indent=2))
    print(f"[daily-prices] wrote {DATA / 'prices.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
