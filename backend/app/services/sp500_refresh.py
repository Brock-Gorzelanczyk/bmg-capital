"""Nightly S&P 500 constituent refresh from iShares IVV holdings CSV.

Pulls the current constituent list from iShares' public holdings feed and
writes it to `strategy_lab/universes/sp500_dynamic.py`. The universes
registry prefers the dynamic file when present and falls back to the
hardcoded snapshot in `sp500.py`.

Zero API cost. Zero auth. Public URL. Runs nightly at 02:15 America/Chicago
(before Portfolio-Rank's 03:00 rebalance cron so the momentum + quality
bots see fresh universe on first-Monday rebalance days).

If the CSV fetch fails for any reason (iShares changed the URL,
network hiccup, malformed rows), the writer aborts and leaves the last
known-good dynamic file in place. Portfolio-Rank runs continue against
whatever universe is on disk.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# iShares IVV holdings CSV. Publicly served, no auth needed.
# Structure: header rows (fund info), then a "Ticker,Name,Sector,..." header
# followed by ~500 rows. Anything with a blank Ticker is a currency/cash line.
_IVV_URL = (
    "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/"
    "1495092304805.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund"
)

_DYNAMIC_FILE = Path(__file__).parent.parent.parent / "strategy_lab" / "universes" / "sp500_dynamic.py"


def _fetch_csv() -> Optional[str]:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as c:
            r = c.get(_IVV_URL, headers={
                "User-Agent": "Mozilla/5.0 (BMG Capital SP500 refresh)",
                "Accept": "text/csv,application/csv,*/*",
            })
            if r.status_code != 200:
                logger.warning("[sp500_refresh] iShares returned %d", r.status_code)
                return None
            return r.text
    except Exception as exc:
        logger.warning("[sp500_refresh] iShares fetch failed: %s", exc)
        return None


def _parse_tickers(csv_text: str) -> list[str]:
    """Extract tickers from the iShares CSV.

    iShares dumps ~9 header rows before the actual holdings header. We find
    the line beginning with "Ticker," and take every subsequent non-empty
    ticker column value. Filters obvious non-equity rows (cash proxies).
    """
    lines = csv_text.splitlines()
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("Ticker,") or ln.startswith('"Ticker",'):
            header_idx = i
            break
    if header_idx is None:
        logger.warning("[sp500_refresh] could not find header row in CSV")
        return []

    tickers: list[str] = []
    for ln in lines[header_idx + 1:]:
        if not ln.strip():
            continue
        # Split on comma but preserve quoted fields. Simple heuristic works
        # here because ticker is column 0 and never contains a comma.
        first = ln.split(",", 1)[0].strip().strip('"')
        # Cash / futures / FX lines look like "USD", "-", or contain digits.
        if not first or first in {"-", "USD", "CASH"}:
            continue
        if not re.match(r"^[A-Z][A-Z0-9\.\-]{0,9}$", first):
            continue
        tickers.append(first)
    return tickers


def _write_dynamic_file(tickers: list[str]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    body = (
        '"""Auto-generated S&P 500 constituents from iShares IVV holdings.\n\n'
        f"Fetched: {now_iso}\n"
        f"Count:   {len(tickers)}\n\n"
        'Do NOT edit by hand. Regenerated nightly by\n'
        'app.services.sp500_refresh.refresh_and_write().\n"""\n\n'
        '_SP500_DYNAMIC: list[str] = [\n'
    )
    # Chunk into rows of 8 for readability.
    for i in range(0, len(tickers), 8):
        chunk = tickers[i:i + 8]
        body += "    " + ", ".join(f'"{t}"' for t in chunk) + ",\n"
    body += "]\n\n\n"
    body += "def sp500_dynamic() -> list[str]:\n"
    body += "    return list(_SP500_DYNAMIC)\n"
    _DYNAMIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DYNAMIC_FILE.write_text(body)


def refresh_and_write() -> dict:
    """Fetch iShares IVV CSV, parse, write dynamic file. Never raises."""
    csv_text = _fetch_csv()
    if not csv_text:
        return {"ok": False, "reason": "fetch_failed", "count": 0}
    tickers = _parse_tickers(csv_text)
    if len(tickers) < 400:
        # Suspicious — S&P 500 should have close to 500 names. Refuse to
        # overwrite the last-good snapshot.
        logger.warning(
            "[sp500_refresh] refusing to write file with only %d tickers "
            "(iShares CSV likely malformed)", len(tickers),
        )
        return {"ok": False, "reason": "too_few_tickers", "count": len(tickers)}
    try:
        _write_dynamic_file(tickers)
    except Exception as exc:
        logger.warning("[sp500_refresh] file write failed: %s", exc)
        return {"ok": False, "reason": f"write_failed: {exc}", "count": len(tickers)}
    logger.warning("[sp500_refresh] wrote %d tickers to %s", len(tickers), _DYNAMIC_FILE)
    return {"ok": True, "count": len(tickers), "path": str(_DYNAMIC_FILE)}


def setup_sp500_scheduler(scheduler) -> None:
    """Register the nightly refresh cron at 02:15 America/Chicago."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[sp500_refresh] apscheduler unavailable, cron not wired: %s", exc)
        return

    def _job() -> None:
        result = refresh_and_write()
        logger.warning("[sp500_refresh] nightly refresh result: %s", result)

    scheduler.add_job(
        _job,
        CronTrigger(hour=2, minute=15, timezone="America/Chicago"),
        id="sp500_refresh_nightly",
        replace_existing=True,
    )
    logger.warning("[sp500_refresh] nightly cron registered: 02:15 America/Chicago")
