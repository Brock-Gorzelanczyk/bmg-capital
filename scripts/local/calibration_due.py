"""calibration_due.py — session-start check for overdue evaluations.

Reads calibration/calls.yaml. Exits non-zero if any call is at or past
its evaluation_date without a committed evaluation file, or if any
open call is past a quarterly interim-mark date.

Wire into session start alongside the existing staleness check.

Exit codes:
    0 = nothing due
    1 = one or more calls have overdue evaluations or interim marks
    3 = vault path or calls.yaml not found
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def quarterly_marks_from(open_date: date, today: date) -> list[date]:
    """Return the list of quarterly interim-mark dates between open and today."""
    marks = []
    m = open_date
    while True:
        # Approximate quarter = 91 days
        m = m + timedelta(days=91)
        if m > today:
            break
        marks.append(m)
    return marks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--vault",
        default=str(Path.home() / "Documents" / "BMG-Capital-Vault"),
    )
    ap.add_argument("--as-of", default=None, help="Override today for testing (YYYY-MM-DD)")
    args = ap.parse_args()

    vault = Path(args.vault)
    calls_path = vault / "calibration" / "calls.yaml"
    if not calls_path.exists():
        print(f"[fail] calls.yaml not found: {calls_path}", file=sys.stderr)
        return 3

    with open(calls_path) as f:
        calls = yaml.safe_load(f)

    today = date.today()
    if args.as_of:
        today = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    overdue: list[str] = []
    interim_due: list[str] = []

    for call in calls:
        if call.get("status") not in ("OPEN", None):
            continue
        ticker = call["ticker"]
        eval_dt = datetime.strptime(str(call["evaluation_date"]), "%Y-%m-%d").date()
        open_dt = datetime.strptime(str(call["opened"]), "%Y-%m-%d").date()

        # Evaluation overdue?
        if today >= eval_dt:
            eval_file = vault / "calibration" / "evaluations" / f"{ticker}-{eval_dt.isoformat()}.md"
            if not eval_file.exists():
                overdue.append(f"{ticker} note {call['note']}: evaluation_date {eval_dt} passed {(today - eval_dt).days} days ago; no {eval_file.name} in calibration/evaluations/")

        # Interim marks missed?
        marks = quarterly_marks_from(open_dt, today)
        if marks:
            interim_dir = vault / "calibration" / "interim"
            missed = []
            for m in marks:
                interim_file = interim_dir / f"{ticker}-{m.isoformat()}.md"
                if not interim_file.exists():
                    missed.append(m.isoformat())
            if missed:
                interim_due.append(f"{ticker} note {call['note']}: missing interim marks for {', '.join(missed)}")

    print(f"calibration_due.py — as of {today.isoformat()}")
    print(f"loaded {len(calls)} calls from {calls_path.relative_to(vault)}")

    if not overdue and not interim_due:
        print("[ok]   no calls overdue on evaluation or interim marks.")
        return 0

    if overdue:
        print(f"\n[FAIL] {len(overdue)} evaluation(s) overdue:")
        for msg in overdue:
            print(f"  - {msg}")
    if interim_due:
        print(f"\n[warn] {len(interim_due)} call(s) missing interim marks:")
        for msg in interim_due:
            print(f"  - {msg}")

    return 1 if overdue else 0


if __name__ == "__main__":
    sys.exit(main())
