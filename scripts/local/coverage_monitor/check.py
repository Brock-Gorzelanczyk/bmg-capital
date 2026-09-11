"""check.py — coverage monitor for the BMG v2 research portfolio.

For every covered ticker (derived from vault research/*.md notes with v2
frontmatter), reports:
  - CIK resolved via SEC's company_tickers.json (cached)
  - Days since the note's most recent git commit (thesis update age)
  - Next earnings date (yfinance) and days remaining
  - Recent SEC filings (data.sec.gov/submissions/CIK{padded}.json)
  - Filings that appeared since the last check run and predate the thesis
    update — those are ALERTS ("company filed, your thesis has not been
    updated in N days")

Output:
  - stdout: readable report + alerts prominently at top
  - {vault}/coverage-status.md: same content, for reading in Obsidian
  - data/state.json: last-check timestamp + set of accession numbers we've
    already surfaced, so we don't re-alert on the same filing

Run daily via launchd/cron. Zero marginal cost — EDGAR + yfinance only.

SEC EDGAR rate limit: ≤10 req/sec. User-Agent required per SEC access policy.

The tool prioritizes:
  1. Filings we haven't seen before (highest signal — new material)
  2. Companies with earnings due within 21 days (near-term catalysts)
  3. Thesis staleness > 60 days on any active call (analyst hygiene)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("[fail] pip install requests")
    sys.exit(1)
try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml")
    sys.exit(1)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
VAULT = Path.home() / "Documents" / "BMG-Capital-Vault"
NOTES_DIR = VAULT / "research"

UA = {
    "User-Agent": "BMG Capital Research brock@bmg-capital.com",
    "Accept-Encoding": "gzip, deflate",
}
# Priority filing types worth alerting on
KEY_FORMS = {"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A",
             "S-1", "S-3", "424B", "DEF 14A", "SC 13D", "SC 13G",
             "4"}  # form 4 = insider transaction


@dataclass
class Ticker:
    symbol: str
    note_path: Path
    thesis: str
    published_at: str = ""
    last_update_at: str = ""  # last git commit on the note file
    last_update_days: int | None = None
    cik: str = ""
    cik_padded: str = ""
    next_earnings: str | None = None
    next_earnings_days: int | None = None
    recent_filings: list[dict] = field(default_factory=list)
    new_filings: list[dict] = field(default_factory=list)  # since last check
    alerts: list[str] = field(default_factory=list)


def load_covered_tickers() -> list[Ticker]:
    """Read vault research/ for v2 calls."""
    out = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
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
        # Only track OPEN calls
        if fm.get("status", "OPEN").upper() != "OPEN":
            continue
        t = Ticker(
            symbol=fm["ticker"].upper(),
            note_path=path,
            thesis=fm.get("thesis", "").strip(),
        )
        pub = fm.get("published_at")
        t.published_at = pub if isinstance(pub, str) else (pub.isoformat() if pub else "")
        out.append(t)
    return out


def fill_git_metadata(t: Ticker) -> None:
    """Get the most recent commit timestamp for the note file."""
    try:
        rel = t.note_path.relative_to(VAULT)
        cmd = ["git", "-C", str(VAULT), "log", "-1", "--format=%aI", "--", str(rel)]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            dt = datetime.fromisoformat(out.replace("Z", "+00:00"))
            t.last_update_at = dt.date().isoformat()
            t.last_update_days = (date.today() - dt.date()).days
    except Exception:
        t.last_update_at = "(uncommitted)"
        t.last_update_days = None


def load_ticker_cik_map() -> dict[str, tuple[str, str]]:
    """Resolve ticker->CIK using SEC's company_tickers.json, cached locally."""
    cache = DATA / "company_tickers.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 86400 * 7:
        payload = json.loads(cache.read_text())
    else:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=UA, timeout=30)
        r.raise_for_status()
        payload = r.json()
        cache.write_text(json.dumps(payload))
    out = {}
    for entry in payload.values():
        tk = entry.get("ticker", "").upper()
        cik = entry.get("cik_str")
        title = entry.get("title", "")
        if tk and cik:
            out[tk] = (str(cik), title)
    return out


def fetch_filings(cik_padded: str, limit: int = 20) -> list[dict]:
    """Get recent filings from data.sec.gov submissions API."""
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code != 200:
        return []
    payload = r.json()
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    out = []
    for i in range(min(len(forms), limit * 3)):
        if forms[i] not in KEY_FORMS:
            continue
        out.append({
            "form": forms[i],
            "accession": accessions[i],
            "filed": filing_dates[i],
            "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
        })
        if len(out) >= limit:
            break
    return out


def fetch_next_earnings(ticker: str) -> str | None:
    """Get next earnings date via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
        # cal is a dict or DataFrame depending on yfinance version
        if hasattr(cal, "get"):
            eds = cal.get("Earnings Date") or cal.get("earnings_date")
            if eds:
                if isinstance(eds, list) and eds:
                    ed = eds[0]
                else:
                    ed = eds
                if hasattr(ed, "isoformat"):
                    return ed.isoformat() if isinstance(ed, date) else ed.date().isoformat()
                return str(ed)[:10]
        return None
    except Exception:
        return None


def load_state() -> dict:
    p = DATA / "state.json"
    if not p.exists():
        return {"last_check": None, "seen_accessions": {}}
    return json.loads(p.read_text())


def save_state(state: dict) -> None:
    (DATA / "state.json").write_text(json.dumps(state, indent=2))


def build_report(tickers: list[Ticker]) -> tuple[str, list[str]]:
    """Return (report_markdown, alert_lines)."""
    today = date.today().isoformat()
    alerts = []
    for t in tickers:
        # Alert: new filings since last check
        for f in t.new_filings:
            alerts.append(f"NEW FILING: {t.symbol} filed {f['form']} on {f['filed']} — "
                          f"thesis last updated {t.last_update_days} days ago ({t.last_update_at})")
        # Alert: earnings within 21 days
        if t.next_earnings_days is not None and 0 <= t.next_earnings_days <= 21:
            alerts.append(f"NEAR EARNINGS: {t.symbol} reports {t.next_earnings} "
                          f"({t.next_earnings_days} days from today) — thesis last updated {t.last_update_days} days ago")
        # Alert: stale thesis while call is open
        if t.last_update_days is not None and t.last_update_days > 60:
            alerts.append(f"STALE THESIS: {t.symbol} — thesis last updated {t.last_update_days} days ago ({t.last_update_at})")

    lines = []
    lines.append(f"# Coverage Status — {today}")
    lines.append("")
    if alerts:
        lines.append(f"## ⚠️ ALERTS ({len(alerts)})")
        lines.append("")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append("")
    else:
        lines.append("## No alerts.")
        lines.append("")

    lines.append(f"## Covered tickers ({len(tickers)})")
    lines.append("")
    for t in tickers:
        lines.append(f"### {t.symbol} — CIK {t.cik_padded or '(unresolved)'}")
        lines.append(f"- Note: `{t.note_path.relative_to(VAULT)}`")
        lines.append(f"- Thesis: {t.thesis[:120]}{'…' if len(t.thesis) > 120 else ''}")
        lines.append(f"- Published: {t.published_at}")
        lines.append(f"- Thesis last updated: {t.last_update_at} ({t.last_update_days} days ago)")
        if t.next_earnings:
            edays = t.next_earnings_days
            lines.append(f"- Next earnings: {t.next_earnings} ({edays} days from today)")
        else:
            lines.append(f"- Next earnings: unknown (yfinance calendar returned nothing)")
        lines.append(f"- Recent SEC filings (last {len(t.recent_filings)}):")
        for f in t.recent_filings[:5]:
            new_marker = " **NEW**" if f in t.new_filings else ""
            lines.append(f"    - {f['filed']}: {f['form']}{new_marker}")
        lines.append("")

    return "\n".join(lines), alerts


def main() -> int:
    DATA.mkdir(exist_ok=True)
    tickers = load_covered_tickers()
    if not tickers:
        print("[coverage] no OPEN v2 calls found in vault. Nothing to monitor.")
        return 0

    print(f"[coverage] monitoring {len(tickers)} ticker(s)")
    state = load_state()

    cik_map = load_ticker_cik_map()

    for t in tickers:
        fill_git_metadata(t)
        info = cik_map.get(t.symbol)
        if not info:
            print(f"  {t.symbol}: CIK not found in SEC ticker map — skip")
            continue
        t.cik, name = info
        t.cik_padded = f"{int(t.cik):010d}"
        print(f"  {t.symbol}: CIK {t.cik_padded} ({name})")

        # Filings
        t.recent_filings = fetch_filings(t.cik_padded, limit=10)
        time.sleep(0.12)  # rate limit
        seen = set(state["seen_accessions"].get(t.symbol, []))
        t.new_filings = [f for f in t.recent_filings if f["accession"] not in seen]
        # Update seen
        state["seen_accessions"][t.symbol] = list(
            seen | {f["accession"] for f in t.recent_filings}
        )

        # Earnings date
        t.next_earnings = fetch_next_earnings(t.symbol)
        if t.next_earnings:
            try:
                ed = date.fromisoformat(t.next_earnings)
                t.next_earnings_days = (ed - date.today()).days
            except ValueError:
                pass
        time.sleep(0.1)

    report_md, alerts = build_report(tickers)
    report_path = VAULT / "coverage-status.md"
    report_path.write_text(report_md)

    state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # stdout
    print()
    print("=" * 60)
    print(report_md)
    print("=" * 60)
    print(f"\nWrote report to {report_path}")
    if alerts:
        print(f"\n{len(alerts)} alert(s). Review + act.")
        return 2 if any(a.startswith("NEW FILING") for a in alerts) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
