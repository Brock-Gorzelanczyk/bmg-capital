"""Fund-halt diagnostic — print current NAV, rolling peak, drawdown %, halt status.

Usage:
    cd backend && .venv/bin/python ../scripts/check_fund_halt.py [user_id]

Defaults to user_id=1. Reads FUND_HALT_PAUSE_PCT / FUND_HALT_UNWIND_PCT env
overrides if set.

Exit code:
    0 — query ran (regardless of halt state)
    1 — DB or import failure
"""
from __future__ import annotations

import os
import sys

# Make backend/ importable whether the script is run from repo root or from
# inside backend/. Mirrors how scripts/test_queen_post.py expects callers
# to set up their environment.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, "..", "backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _fmt_dollars(cents: int) -> str:
    return "${:,.2f}".format((cents or 0) / 100.0)


def main() -> int:
    try:
        user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except ValueError:
        print("usage: check_fund_halt.py [user_id]")
        return 1

    try:
        from app.db.session import SessionLocal  # type: ignore
        from strategy_lab.core.fund_halt import compute_drawdown, check_fund_halt
    except Exception as exc:
        print("import failed: {}".format(exc))
        return 1

    db = SessionLocal()
    try:
        diag = compute_drawdown(db, user_id)
        allowed, reason = check_fund_halt(db, user_id)
    finally:
        try:
            db.close()
        except Exception:
            pass

    print("=" * 64)
    print("Fund-Halt Diagnostic — user_id={}".format(user_id))
    print("=" * 64)
    print("Current NAV       : {}".format(_fmt_dollars(diag["current_pv_cents"])))
    print("Rolling 90d peak  : {}".format(_fmt_dollars(diag["peak_pv_cents"])))
    print("Drawdown          : {:+.4f}%".format(diag["drawdown_pct"]))
    print("Pause threshold   : {:.2f}%".format(diag["pause_threshold_pct"]))
    print("Unwind threshold  : {:.2f}%".format(diag["unwind_threshold_pct"]))
    print("Halted (pause)    : {}".format(diag["halted"]))
    print("Would unwind      : {}".format(diag["would_unwind"]))
    if not allowed:
        print("Halt reason       : {}".format(reason))
    else:
        print("Status            : ALLOWED — new entries can proceed")
    print(
        "Summary: nav={} peak={} dd={:+.4f}% halted={}".format(
            _fmt_dollars(diag["current_pv_cents"]),
            _fmt_dollars(diag["peak_pv_cents"]),
            diag["drawdown_pct"],
            diag["halted"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
