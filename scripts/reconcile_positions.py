"""Broker vs DB position reconciliation — standalone ops runner.

Usage:
    cd backend && .venv/bin/python ../scripts/reconcile_positions.py [user_id]

Defaults to user_id=1 (Brock). Reads Alpaca paper credentials from env
(ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET or ALPACA_API_KEY / ALPACA_SECRET_KEY).

READ-ONLY. Never mutates broker state. Use the report to decide which DB
rows to close or open broker-side manually.

Exit code:
    0 — report generated and severity == 'ok'
    1 — DB/import failure OR severity == 'error'
    2 — severity == 'warn' (diffs present, < $100 dollar divergence)
    3 — severity == 'alert' (diffs present, >= $100 dollar divergence)
"""
from __future__ import annotations

import json
import os
import sys

# Make backend/ importable whether the script is run from repo root or from
# inside backend/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, "..", "backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _exit_code_for_severity(sev: str) -> int:
    return {
        "ok": 0,
        "warn": 2,
        "alert": 3,
        "error": 1,
    }.get(sev, 1)


def main(argv):
    user_id = 1
    if len(argv) >= 2:
        try:
            user_id = int(argv[1])
        except ValueError:
            print(f"invalid user_id: {argv[1]}", file=sys.stderr)
            return 1

    try:
        from app.db.session import SessionLocal
        from app.ops.broker_reconciliation import (
            reconcile_positions,
            format_report_for_discord,
        )
    except Exception as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        report = reconcile_positions(db, user_id=user_id)
    finally:
        try:
            db.close()
        except Exception:
            pass

    print("─── Broker reconciliation report ───")
    print(format_report_for_discord(report))
    print("─── Full JSON ───")
    print(json.dumps(report, indent=2, default=str))

    return _exit_code_for_severity(report.get("divergence_severity", "error"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
