"""backfill_gatx_001.py — enter GATX v1 pitch as call 001.

Data taken verbatim from interview-prep/02-stock-pitch-GATX.md (v1 one-pager
written for Baird interview on 2026-09-08). Do NOT retro-fit. Enter as
written, honestly counting what v1 stated.

v1 sell signals (3, per Q&A "What would make you sell?"):
  1. LPI decelerates below +5% for two consecutive quarters
  2. Fleet utilization drops below 95%
  3. Management walks back the GABX call option

Note: user's task spec referred to "5 kill criteria from the note" but v1 as
WRITTEN contains only 3 explicit sell signals. Adding two more would be
retro-fitting. If the intent is 5, the additional two need to be sourced from
v1 explicitly and stated by the author. Entered as 3.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import get_conn  # noqa: E402


def main() -> int:
    conn = get_conn()

    # Guard: only insert once. Idempotent.
    exists = conn.execute(
        "SELECT call_id FROM research_calls WHERE ticker='GATX' AND note_id='interview-prep/02-stock-pitch-GATX.md'"
    ).fetchone()
    if exists:
        print(f"[backfill] already present as call {exists[0]}, skipping insert")
        return 0

    # Call 001: GATX
    cur = conn.execute(
        """
        INSERT INTO research_calls
        (ticker, note_id, direction, published_at, price_at_pub, price_target,
         horizon_months, thesis, benchmark, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "GATX",
            "interview-prep/02-stock-pitch-GATX.md",
            "BUY",
            "2026-09-08",  # date of Baird interview when v1 was delivered
            178.00,         # v1 states "Trading at about $178"
            225.00,         # v1 stated PT
            12,             # v1: "12 months" upside
            "GABX/Wells Fargo joint venture unlocks asset-light management economics + LPI-driven pricing power at low-end-of-historical multiple",
            "IWM",          # small-cap benchmark per BMG spec
            "OPEN",
        ),
    )
    call_id = cur.lastrowid

    # Kill criteria — verbatim from v1's Q&A section "What would make you sell?"
    kill_criteria = [
        {
            "description": "LPI (Lease Price Index) decelerates below +5% for two consecutive quarters — pricing cycle turning",
            "metric": "MANUAL",  # quarterly disclosed metric, human evaluates
            "threshold": "5",
            "action": "EXIT",
        },
        {
            "description": "Fleet utilization drops below 95% — supply-demand imbalance ending",
            "metric": "MANUAL",  # quarterly disclosed metric
            "threshold": "95",
            "action": "EXIT",
        },
        {
            "description": "Management walks back the GABX call option — JV economics not working as planned",
            "metric": "MANUAL",  # narrative disclosure
            "threshold": None,
            "action": "REASSESS",
        },
    ]

    for k in kill_criteria:
        conn.execute(
            """
            INSERT INTO kill_criteria (call_id, description, metric, threshold, action, status)
            VALUES (?, ?, ?, ?, ?, 'ARMED')
            """,
            (call_id, k["description"], k["metric"], k["threshold"], k["action"]),
        )

    conn.commit()
    print(f"[backfill] inserted call {call_id} (GATX) with {len(kill_criteria)} kill criteria")
    print("  Note: v1 states 3 kill criteria. Task spec said 5 — v1 as written")
    print("  contains 3. Adding 2 more would be retro-fitting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
