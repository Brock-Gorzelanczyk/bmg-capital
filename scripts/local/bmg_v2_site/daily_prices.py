"""daily_prices.py — pull latest close + publication-day close for every call.

Reads the vault's research/ folder for notes with v2 frontmatter (ticker,
direction, published_price). For each unique (ticker, benchmark) pair,
fetches the latest close + the historical close on the call's published_at
date. Writes data/prices.json with fetched_at timestamp.

Data source: Alpaca market data v2 API (paper-trading account). Free tier
covers the IEX feed which is sufficient for daily EOD numbers.

Env vars required:
  ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY

Fallback: yfinance if Alpaca is unavailable.
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

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml"); sys.exit(1)


def load_call_tickers() -> list[tuple[str, str, str]]:
    """Return list of (ticker, benchmark, published_at_iso) tuples from vault."""
    out = []
    for path in sorted((VAULT / "research").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m: continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        if not all(k in fm for k in ("ticker", "direction", "published_price")):
            continue
        pub_at = fm.get("published_at")
        if not pub_at:
            # use file mtime as fallback
            pub_at = date.fromtimestamp(path.stat().st_mtime).isoformat()
        out.append((
            fm["ticker"].upper(),
            (fm.get("benchmark") or "IWM").upper(),
            pub_at if isinstance(pub_at, str) else pub_at.isoformat(),
        ))
    return out


def _unwrap(v):
    """Unwrap a possibly-Series scalar and skip NaN."""
    import math
    if hasattr(v, "iloc"):
        v = v.iloc[0]
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return v


def fetch_via_yfinance(ticker: str, hist_date: str | None = None) -> dict:
    """Return {last: float, historical: {date_iso: close}} for a ticker."""
    import yfinance as yf
    result = {"last": None, "historical": {}}
    try:
        t = yf.Ticker(ticker)
        # Pull 10 days so we have enough valid rows even if today's row is NaN
        hist = t.history(period="10d", auto_adjust=True)
        if not hist.empty:
            # walk backwards to first non-NaN close
            for i in range(len(hist) - 1, -1, -1):
                close = _unwrap(hist["Close"].iloc[i])
                if close is not None:
                    result["last"] = close
                    break
        # historical date
        if hist_date:
            hd = date.fromisoformat(hist_date)
            df = t.history(start=hist_date, end=(hd + timedelta(days=8)).isoformat(),
                           auto_adjust=True)
            for idx, row in df.iterrows():
                d = idx.strftime("%Y-%m-%d")
                if d >= hist_date:
                    close_val = _unwrap(row["Close"])
                    if close_val is not None:
                        result["historical"][hist_date] = close_val
                        break
    except Exception as e:
        print(f"  yfinance {ticker}: {e}")
    return result


def main() -> int:
    DATA.mkdir(exist_ok=True)
    tickers = load_call_tickers()
    if not tickers:
        print("[daily-prices] no v2 calls found in vault")
        return 0

    # aggregate all tickers we need to price
    need = {}  # ticker -> set of historical dates needed
    for tk, bench, pub in tickers:
        need.setdefault(tk, set())  # last only
        need.setdefault(bench, set()).add(pub)

    print(f"[daily-prices] pricing {len(need)} tickers...")
    result_prices = {}
    for tk in sorted(need.keys()):
        hist_dates = need[tk]
        combined = {"last": None, "historical": {}}
        # Latest close
        latest = fetch_via_yfinance(tk)
        combined["last"] = latest["last"]
        # Historical dates
        for d in sorted(hist_dates):
            hd = fetch_via_yfinance(tk, d)
            combined["historical"].update(hd["historical"])
        result_prices[tk] = combined
        latest_str = f"${combined['last']:.2f}" if combined["last"] else "—"
        print(f"  {tk}: last={latest_str}, hist_dates={sorted(hist_dates)}")

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "prices": result_prices,
    }
    (DATA / "prices.json").write_text(json.dumps(payload, indent=2))
    print(f"[daily-prices] wrote {DATA / 'prices.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
