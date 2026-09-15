"""monitor_filings.py — detect new SEC filings for open calls.

Per M24: this script DETECTS new primary-source material and FLAGS
which pre-registered items are owed an evaluation. It does not read
filing contents, does not evaluate triggers, does not update any
status other than PENDING (which asserts data exists, not what the
data says).

Reads:
  monitoring/calendar.yaml  — open calls + CIKs to watch
  monitoring/last_seen.yaml — watermark per ticker per form type

Writes:
  monitoring/last_seen.yaml — updated watermark after processing
  monitoring/WORK-ORDERS.md — appended entries for new filings

Never fetches document contents. Records only:
  - accession number
  - form type
  - filing date
  - EDGAR archive URL

Watched form types (per M24 procedure):
  10-Q, 10-K       quarterly and annual primary source
  8-K              material events, guidance, earnings releases
  4                insider transactions
  DEF 14A          proxy — share-pledging disclosure
  S-3, 424B        shelf registrations and prospectus supplements
  424B5            prospectus supplement (used for ATM issuances)

EDGAR requires a descriptive User-Agent carrying a contact address
and rate-limits to 10 requests per second. Set both.

On first run against an empty last_seen entry: SEED the watermark
to the most recent filing per form type without flagging (avoids
a huge one-time dump). Subsequent runs flag only new-since-watermark.

Exit codes:
  0  success (may have appended flags)
  2  network / EDGAR error
  3  file missing or malformed
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml", file=sys.stderr)
    sys.exit(3)

try:
    import requests
except ImportError:
    print("[fail] pip install requests", file=sys.stderr)
    sys.exit(3)

USER_AGENT = "BMG Capital Research 32bgorzelanczyk@gmail.com"
RATE_LIMIT_SLEEP = 0.11  # ~9 req/s, safely under EDGAR's 10/s limit

WATCHED_FORMS = ["10-Q", "10-K", "8-K", "4", "DEF 14A", "S-3", "424B5", "424B2", "424B3"]


def fetch_recent_filings(cik: str, form_type: str, count: int = 20, retries: int = 2) -> list[dict]:
    """Query EDGAR for the most recent N filings of a given form type.
    Returns empty list on any network/HTTP error rather than raising —
    detection is best-effort per M24, and a failed query re-runs on
    next invocation."""
    cik_padded = cik.zfill(10)
    url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik_padded}"
        f"&type={form_type.replace(' ', '+')}"
        f"&dateb=&owner=include&count={count}&output=atom"
    )
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            time.sleep(RATE_LIMIT_SLEEP)
            if r.status_code == 200:
                break
            time.sleep(1.0)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == retries:
                print(f"  [warn] EDGAR timeout on {cik_padded} {form_type} after {retries+1} attempts — will retry next run", file=sys.stderr)
                return []
            time.sleep(2.0)
    else:
        return []
    if r.status_code != 200:
        return []
    # Parse atom feed for entries — simple regex extraction, no XML lib dep
    import re
    filings = []
    for entry_match in re.finditer(r"<entry>(.*?)</entry>", r.text, re.DOTALL):
        entry = entry_match.group(1)
        acc = re.search(r"<accession-number>([^<]+)</accession-number>", entry)
        date_ = re.search(r"<filing-date>([^<]+)</filing-date>", entry)
        form = re.search(r"<filing-type>([^<]+)</filing-type>", entry)
        href = re.search(r"<filing-href>([^<]+)</filing-href>", entry)
        if acc and date_ and form:
            filings.append({
                "accession": acc.group(1),
                "filing_date": date_.group(1),
                "form": form.group(1).strip(),
                "url": href.group(1) if href else "",
            })
    return filings


def _owed_to_for_form(form: str) -> list[str]:
    owed_to = []
    if form in ("10-Q", "10-K"):
        owed_to.append("every kill criterion and sell trigger for this ticker → auto-flip to PENDING")
    if form == "8-K":
        owed_to.append("check for earnings-date confirmation, guidance change, or material-event trigger")
    if form == "4":
        owed_to.append("insider-action check (open-question watch where answerable_by tag matches)")
    if form == "DEF 14A":
        owed_to.append("proxy disclosures (open-question watch: share-pledging, related-party, etc.)")
    if form in ("S-3", "424B5", "424B2", "424B3"):
        owed_to.append("dilution leg — new shelf or ATM affects sell trigger economics")
    return owed_to


def append_work_order(work_orders_path: Path, ticker: str, note: str, filing: dict, form: str,
                       flag_class: str = "NEW_FILING", extra_detail: str = "") -> None:
    """Append a work-order entry to WORK-ORDERS.md.

    flag_class values:
      NEW_FILING       — a filing has appeared since the last watermark
      REVIEW_BACKLOG   — seed-time entry per M24 §5 (initial-state visibility)
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    owed_to = _owed_to_for_form(form)
    detail = f"{flag_class} — {form} filing: accession {filing['accession']}, filing_date {filing['filing_date']}"
    if extra_detail:
        detail = detail + " (" + extra_detail + ")"

    entry = f"""### {now} — {ticker} — {flag_class}

- **Ticker:** {ticker}
- **Note:** {note}
- **Flag class:** {flag_class}
- **Detail:** {detail}
- **Source:** {filing['url']}
- **Owed to:** {'; '.join(owed_to) if owed_to else 'general primary-source watch'}
- **Detected by:** monitor_filings.py
- **Cleared:** (open)

"""
    with open(work_orders_path, "a") as f:
        f.write(entry)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path.home() / "Documents" / "BMG-Capital-Vault"))
    ap.add_argument("--seed-only", action="store_true",
                    help="Seed watermarks without flagging (for initial run)")
    args = ap.parse_args()

    vault = Path(args.vault)
    calendar_path = vault / "monitoring" / "calendar.yaml"
    last_seen_path = vault / "monitoring" / "last_seen.yaml"
    work_orders_path = vault / "monitoring" / "WORK-ORDERS.md"

    for p in (calendar_path, last_seen_path, work_orders_path):
        if not p.exists():
            print(f"[fail] missing: {p}", file=sys.stderr)
            return 3

    with open(calendar_path) as f:
        calendar = yaml.safe_load(f)
    with open(last_seen_path) as f:
        last_seen = yaml.safe_load(f) or {}

    if not isinstance(calendar, list):
        print("[fail] calendar.yaml must be a list of call entries", file=sys.stderr)
        return 3

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = datetime.now(timezone.utc).date()
    new_flag_count = 0
    seeded_count = 0
    backlog_count = 0

    print(f"monitor_filings.py — {now_iso}")
    print(f"watching {len(calendar)} tickers × {len(WATCHED_FORMS)} form types = {len(calendar) * len(WATCHED_FORMS)} queries")
    print()

    from datetime import date as _date_cls

    for call in calendar:
        ticker = call["ticker"]
        cik = str(call["cik"])
        note = f"{call['note']:03d}-{ticker}" if isinstance(call['note'], int) else f"{call['note']}-{ticker}"
        answerable_by_forms = set(call.get("answerable_by_forms") or [])
        if ticker not in last_seen:
            last_seen[ticker] = {}

        for form in WATCHED_FORMS:
            filings = fetch_recent_filings(cik, form, count=5)
            if not filings:
                continue
            newest = filings[0]  # atom feed returns newest first
            prev = last_seen[ticker].get(form)

            if prev is None:
                # First time seeing this ticker+form — SEED the watermark
                last_seen[ticker][form] = {
                    "last_accession": newest["accession"],
                    "last_filing_date": newest["filing_date"],
                    "last_seen_at": now_iso,
                    "url": newest["url"],
                }
                seeded_count += 1
                print(f"[seed] {ticker} {form}: watermark set to {newest['accession']} ({newest['filing_date']})")

                # M24 §5 — initial-state visibility.
                # On seed, ALSO emit a REVIEW_BACKLOG entry if:
                #  (a) filing_date within 30 days of today, OR
                #  (b) form is in the ticker's answerable_by_forms list (any age).
                filing_dt = _date_cls.fromisoformat(newest["filing_date"])
                age_days = (today - filing_dt).days
                reasons = []
                if age_days <= 30:
                    reasons.append(f"filed {age_days}d ago (≤30d window)")
                if form in answerable_by_forms:
                    reasons.append(f"form tagged answerable_by on open question for {ticker}")
                if reasons and not args.seed_only:
                    append_work_order(
                        work_orders_path, ticker, note, newest, form,
                        flag_class="REVIEW_BACKLOG",
                        extra_detail="; ".join(reasons),
                    )
                    backlog_count += 1
                    print(f"[BACKLOG] {ticker} {form}: watermark filing {newest['accession']} ({newest['filing_date']}) → {'; '.join(reasons)}")
            elif newest["accession"] != prev["last_accession"] and newest["filing_date"] > prev["last_filing_date"]:
                # New filing since last watermark — flag it
                if not args.seed_only:
                    append_work_order(work_orders_path, ticker, note, newest, form, flag_class="NEW_FILING")
                    new_flag_count += 1
                    print(f"[FLAG] {ticker} {form}: NEW filing {newest['accession']} ({newest['filing_date']})")
                # Update watermark either way
                last_seen[ticker][form] = {
                    "last_accession": newest["accession"],
                    "last_filing_date": newest["filing_date"],
                    "last_seen_at": now_iso,
                    "url": newest["url"],
                }
            else:
                # No change since watermark
                last_seen[ticker][form]["last_seen_at"] = now_iso

    # Write updated watermarks
    with open(last_seen_path, "w") as f:
        yaml.safe_dump(last_seen, f, default_flow_style=False, sort_keys=False)

    print()
    print(f"seeded: {seeded_count}   review-backlog: {backlog_count}   new-flags: {new_flag_count}")
    if backlog_count > 0:
        print(f"REVIEW_BACKLOG entries added to monitoring/WORK-ORDERS.md — {backlog_count} filing(s)")
        print("that were absorbed as watermarks but are (a) recent or (b) tagged answerable_by")
        print("per open questions require human review before the cold-start is trusted.")
    elif seeded_count > 0 and new_flag_count == 0:
        print("(seed-only run — no work orders raised on this pass)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
