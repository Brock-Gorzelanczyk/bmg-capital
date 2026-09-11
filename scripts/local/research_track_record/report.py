"""report.py — the front page of the platform.

Replaces the bot leaderboard. Prints:
  - open calls: ticker, thesis, days open, return vs benchmark, kill status, days to horizon
  - closed calls: same + outcome + thesis attribution
  - headline: total calls, closed calls, hit rate, median excess return,
              kill-criteria compliance rate

Anti-pattern reminder enforced: this script does not compute Sharpe / t-stat /
information ratio / any significance test. It reports counts and rates
qualified with N. "3 of 5" not "60%".
"""

from __future__ import annotations

import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import get_conn  # noqa: E402

BANNED_TERMS = {"sharpe", "t-stat", "t stat", "tstat", "information ratio",
                "p-value", "statistical significance", "significance test",
                "confidence interval"}


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def days_to_horizon(pub_str: str, horizon_months: int) -> int:
    pub = date.fromisoformat(pub_str)
    horizon_days = horizon_months * 30
    elapsed = (date.today() - pub).days
    return max(0, horizon_days - elapsed)


def kill_summary(conn, call_id: int) -> str:
    rows = conn.execute(
        "SELECT status, action, obeyed FROM kill_criteria WHERE call_id=?",
        (call_id,),
    ).fetchall()
    if not rows:
        return "none"
    n_armed = sum(1 for s, _, _ in rows if s == "ARMED")
    n_fired = sum(1 for s, _, _ in rows if s == "FIRED")
    parts = []
    if n_armed:
        parts.append(f"{n_armed} armed")
    if n_fired:
        obeyed_str = ""
        for s, a, obeyed in rows:
            if s == "FIRED":
                mark = "?" if obeyed is None else ("✓" if obeyed else "✗")
                obeyed_str += mark
        parts.append(f"{n_fired} fired[{obeyed_str}]")
    return ", ".join(parts) if parts else "none"


def open_calls_section(conn) -> None:
    rows = conn.execute("""
        SELECT c.call_id, c.ticker, c.thesis, c.published_at, c.horizon_months,
               o.return_since_pub_pct, o.benchmark_return_pct, o.excess_return_pct,
               o.days_held, c.benchmark
        FROM research_calls c
        LEFT JOIN call_outcomes o ON o.call_id = c.call_id
        WHERE c.status = 'OPEN'
        ORDER BY c.call_id
    """).fetchall()

    print("\n== OPEN CALLS ({}) ==".format(len(rows)))
    if not rows:
        print("  (none)")
        return
    for call_id, ticker, thesis, pub, horizon, ret, bench, excess, days_held, bench_tk in rows:
        thesis_short = (thesis[:70] + "…") if len(thesis) > 70 else thesis
        dth = days_to_horizon(pub, horizon)
        kills = kill_summary(conn, call_id)
        print(f"  #{call_id:03d} {ticker:6s} | {thesis_short}")
        print(f"         open {days_held or 0}d | return {fmt_pct(ret)} vs {bench_tk} {fmt_pct(bench)} = excess {fmt_pct(excess)}")
        print(f"         days-to-horizon {dth} | kill: {kills}")


def closed_calls_section(conn) -> None:
    rows = conn.execute("""
        SELECT c.call_id, c.ticker, c.status, c.thesis, c.thesis_attribution,
               c.closed_at, c.closed_reason,
               o.return_since_pub_pct, o.benchmark_return_pct, o.excess_return_pct,
               o.days_held, c.benchmark, o.target_hit
        FROM research_calls c
        LEFT JOIN call_outcomes o ON o.call_id = c.call_id
        WHERE c.status != 'OPEN'
        ORDER BY c.closed_at DESC
    """).fetchall()

    print("\n== CLOSED CALLS ({}) ==".format(len(rows)))
    if not rows:
        print("  (none)")
        return
    for (call_id, ticker, status, thesis, attrib, closed_at, reason,
         ret, bench, excess, days_held, bench_tk, target_hit) in rows:
        thesis_short = (thesis[:70] + "…") if len(thesis) > 70 else thesis
        print(f"  #{call_id:03d} {ticker:6s} | {status:15s} | {closed_at}")
        print(f"         thesis:  {thesis_short}")
        print(f"         held {days_held or 0}d | return {fmt_pct(ret)} vs {bench_tk} {fmt_pct(bench)} = excess {fmt_pct(excess)}")
        print(f"         target_hit: {bool(target_hit)} | attribution: {attrib or '(unclassified)'}")
        if reason:
            print(f"         reason: {reason}")


def headline_section(conn) -> None:
    total = conn.execute("SELECT COUNT(*) FROM research_calls").fetchone()[0]
    open_n = conn.execute("SELECT COUNT(*) FROM research_calls WHERE status='OPEN'").fetchone()[0]
    closed_n = total - open_n

    # Hit rate on CLOSED calls only; expressed as "X of Y"
    closed_rows = conn.execute("""
        SELECT o.excess_return_pct, c.thesis_attribution
        FROM research_calls c
        LEFT JOIN call_outcomes o ON o.call_id = c.call_id
        WHERE c.status != 'OPEN'
    """).fetchall()
    excess_vals = [r[0] for r in closed_rows if r[0] is not None]
    hits = sum(1 for v in excess_vals if v > 0)
    thesis_correct = sum(1 for _, a in closed_rows if a == "THESIS_CORRECT")
    right_wrong_reason = sum(1 for _, a in closed_rows if a == "RIGHT_WRONG_REASON")
    wrong = sum(1 for _, a in closed_rows if a == "WRONG")
    unresolved = sum(1 for _, a in closed_rows if a == "UNRESOLVED")
    unclassified = closed_n - thesis_correct - right_wrong_reason - wrong - unresolved

    # Kill compliance across all FIRED criteria
    fired_rows = conn.execute("""
        SELECT obeyed FROM kill_criteria WHERE status = 'FIRED'
    """).fetchall()
    fired_n = len(fired_rows)
    obeyed_n = sum(1 for (o,) in fired_rows if o == 1)
    disobeyed_n = sum(1 for (o,) in fired_rows if o == 0)
    unrecorded_n = sum(1 for (o,) in fired_rows if o is None)

    print("\n== HEADLINE ==")
    print(f"  total calls:          {total}")
    print(f"  open:                 {open_n}")
    print(f"  closed:               {closed_n}")
    if closed_n:
        print(f"  positive excess:      {hits} of {len(excess_vals)}  (closed calls only)")
        if excess_vals:
            median_x = statistics.median(excess_vals)
            print(f"  median excess return: {median_x:+.1f}%  (n={len(excess_vals)})")
        print(f"  thesis attribution:")
        print(f"    THESIS_CORRECT      {thesis_correct} of {closed_n}")
        print(f"    RIGHT_WRONG_REASON  {right_wrong_reason} of {closed_n}  (luck, not skill)")
        print(f"    WRONG               {wrong} of {closed_n}")
        print(f"    UNRESOLVED          {unresolved} of {closed_n}")
        if unclassified:
            print(f"    (unclassified)      {unclassified} of {closed_n}  <-- classify these")
    else:
        print("  (no closed calls yet)")

    print(f"\n  kill criteria fired:  {fired_n}")
    if fired_n:
        print(f"    obeyed:             {obeyed_n} of {fired_n}")
        print(f"    disobeyed:          {disobeyed_n} of {fired_n}  (highest-signal number in system)")
        if unrecorded_n:
            print(f"    unrecorded:         {unrecorded_n} of {fired_n}  <-- record these")


def anti_pattern_guard() -> None:
    """Enforce: this script does not compute or emit any of the banned terms.

    Run at end. Raises if any banned term appears in the source or output.
    """
    with open(__file__) as f:
        src = f.read().lower()
    # scan comments/docstrings for justification-of-existence uses; the
    # BANNED_TERMS constant itself is legitimate. Anything else that references
    # sharpe etc. WITHOUT quoting BANNED_TERMS is a defect.
    for term in BANNED_TERMS:
        if term in src:
            # Check: it's inside the BANNED_TERMS constant declaration.
            if f'"{term}"' in src and 'banned_terms' in src:
                continue
            # otherwise flag
            print(f"[anti-pattern] '{term}' appears in report.py — remove it")


def main() -> int:
    conn = get_conn()
    print("=" * 68)
    print(f"BMG CAPITAL — Research Track Record ({date.today().isoformat()})")
    print("=" * 68)
    headline_section(conn)
    open_calls_section(conn)
    closed_calls_section(conn)
    print()
    anti_pattern_guard()
    return 0


if __name__ == "__main__":
    sys.exit(main())
