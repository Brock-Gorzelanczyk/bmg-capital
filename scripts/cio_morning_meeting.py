#!/usr/bin/env python3
"""CIO Morning Meeting runner.

Manual invocation:
    python scripts/cio_morning_meeting.py [--budget 1.50] [--dry-run] [--runner-label LABEL]

Routes ALL LLM inference through backend's call_llm relay (SHIP 4).
Zero direct SDK usage. Zero shell calls to the LLM binary.

Exit codes:
    0 — meeting completed successfully
    1 — meeting ran but status != 'completed' (failed_budget, failed_timeout, etc.)
    2 — relay probe failed (no inference available)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser(description="CIO Morning Meeting runner")
    ap.add_argument("--budget", type=float, default=1.50, help="Per-meeting LLM budget cap (USD)")
    ap.add_argument("--dry-run", action="store_true", help="Run without writing to DB or posting to Discord")
    ap.add_argument(
        "--runner-label",
        default=f"mac:{os.getenv('USER', 'unknown')}",
        help="Label identifying who/what triggered the meeting",
    )
    args = ap.parse_args()

    # Probe the relay first — fail-fast with clear message.
    from app.services.llm_client import call_llm
    try:
        probe = call_llm(
            model="claude-haiku-4-5-20251001",
            prompt="reply with the single word: ok",
            system_prompt="probe",
            max_tokens=8,
            agent_name="cio_probe",
        )
        print(f"OK: relay responsive (probe text: {probe[:40]!r})")
    except RuntimeError as e:
        print(f"FAIL: relay probe failed: {e}", file=sys.stderr)
        return 2

    from app.db.session import SessionLocal
    from app.agents.cio_orchestrator import kick_off_cio_meeting

    db = SessionLocal()
    try:
        result = kick_off_cio_meeting(
            db,
            runner_label=args.runner_label,
            budget_cap_usd=args.budget,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["status"] == "completed" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
