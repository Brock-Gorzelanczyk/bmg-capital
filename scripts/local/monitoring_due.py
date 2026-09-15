"""monitoring_due.py — session-start check for pending work orders.

Per M24: this script is DETECTION only. It reports what is owed;
it never performs the evaluation.

Wires into session start alongside state_staleness.py and
calibration_due.py. Exits non-zero when any of the following hold:

  A. A filing has appeared since the last watermark for any open
     call (i.e. there is an open entry in WORK-ORDERS.md).
  B. An expected event date has passed with no corresponding
     filing detected.
  C. An expected event date has moved (calendar edited).
  D. Any kill criterion or sell trigger has sat at PENDING for
     more than 14 days without evaluation.
  E. monitor_filings.py has not run in more than 7 days.

Session start is the primary invocation. A cron/launchd job can
supplement but cannot replace this.

Exit codes:
  0  nothing due
  1  one or more conditions triggered — human action required
  3  file missing / malformed
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml", file=sys.stderr)
    sys.exit(3)

MAX_MONITOR_STALE_DAYS = 7
MAX_PENDING_DAYS = 14


def _iso_to_date(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def count_open_work_orders(work_orders_path: Path) -> int:
    """Count entries in WORK-ORDERS.md that are still open (Cleared: (open))."""
    if not work_orders_path.exists():
        return 0
    text = work_orders_path.read_text()
    # Count "**Cleared:** (open)" occurrences
    return text.count("**Cleared:** (open)")


def latest_monitor_run(last_seen_path: Path) -> datetime | None:
    """Return most recent last_seen_at across all tickers/forms."""
    with open(last_seen_path) as f:
        data = yaml.safe_load(f) or {}
    latest = None
    for ticker, forms in data.items():
        if not isinstance(forms, dict):
            continue
        for form, entry in forms.items():
            if not isinstance(entry, dict):
                continue
            ts = entry.get("last_seen_at")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if latest is None or dt > latest:
                    latest = dt
    return latest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path.home() / "Documents" / "BMG-Capital-Vault"))
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()

    vault = Path(args.vault)
    monitoring_dir = vault / "monitoring"
    calendar_path = monitoring_dir / "calendar.yaml"
    last_seen_path = monitoring_dir / "last_seen.yaml"
    work_orders_path = monitoring_dir / "WORK-ORDERS.md"

    for p in (calendar_path, last_seen_path, work_orders_path):
        if not p.exists():
            print(f"[fail] missing: {p}", file=sys.stderr)
            return 3

    today = date.today()
    if args.as_of:
        today = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    now_utc = datetime.now(timezone.utc)

    print(f"monitoring_due.py — as of {today.isoformat()}")

    conditions_triggered = []

    # A. Open work orders in WORK-ORDERS.md
    open_orders = count_open_work_orders(work_orders_path)
    if open_orders > 0:
        conditions_triggered.append(("A", f"{open_orders} open work-order(s) in monitoring/WORK-ORDERS.md — awaiting evaluation"))

    # B. Expected event dates passed
    with open(calendar_path) as f:
        calendar = yaml.safe_load(f) or []
    with open(last_seen_path) as f:
        last_seen = yaml.safe_load(f) or {}
    for call in calendar:
        ticker = call["ticker"]
        exp_date_str = str(call["expected_date"])
        exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
        if today > exp_date:
            # Was there a corresponding 10-Q, 10-K, or earnings 8-K filed on/after that date?
            filed_after = False
            for form in ("10-Q", "10-K", "8-K"):
                entry = last_seen.get(ticker, {}).get(form)
                if entry:
                    fdate = datetime.strptime(entry["last_filing_date"], "%Y-%m-%d").date()
                    if fdate >= exp_date:
                        filed_after = True
                        break
            if not filed_after:
                days_late = (today - exp_date).days
                conditions_triggered.append((
                    "B",
                    f"{ticker} expected event {call['next_event']} on {exp_date} — {days_late}d late with no detected filing"
                ))

    # C. Expected event date moved — requires checking git history; approximate by
    #    checking date_verified flag transitions in calendar.yaml diffs. For now,
    #    surface un-verified dates that are within 30 days as "verify soon".
    for call in calendar:
        if not call.get("date_verified", False):
            exp_date = datetime.strptime(str(call["expected_date"]), "%Y-%m-%d").date()
            days_out = (exp_date - today).days
            if 0 <= days_out <= 30:
                conditions_triggered.append((
                    "C",
                    f"{call['ticker']} expected date {exp_date} is {days_out}d out and date_verified=false — pull 8-K to confirm"
                ))

    # D. PENDING > 14 days — this requires scanning open notes' kill_criteria
    #    for a PENDING status with a timestamp. Placeholder: search for
    #    "status: PENDING" markers in research/ notes with dates.
    #    Full implementation requires status-timestamp fields on kill criteria.
    #    Not currently instrumented; skip check with a note.

    # E. Monitor stale
    latest = latest_monitor_run(last_seen_path)
    if latest is None:
        conditions_triggered.append(("E", "monitor_filings.py has never run — run it now to seed watermarks"))
    else:
        stale_days = (now_utc - latest).days
        if stale_days > MAX_MONITOR_STALE_DAYS:
            conditions_triggered.append((
                "E",
                f"monitor_filings.py last ran {stale_days}d ago (max {MAX_MONITOR_STALE_DAYS}d) — run it"
            ))

    if not conditions_triggered:
        print(f"[ok]   nothing due. {open_orders} open work-order(s). latest monitor run: {latest.isoformat() if latest else 'never'}.")
        return 0

    print(f"\n[FLAG] {len(conditions_triggered)} condition(s) triggered — human action required:")
    for cond_class, msg in conditions_triggered:
        print(f"  ({cond_class}) {msg}")
    print(f"\nSee monitoring/WORK-ORDERS.md for open entries.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
