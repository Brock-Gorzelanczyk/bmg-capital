"""cli.py — operate the research track record.

Subcommands:
  enter    add a new research call + kill criteria
  fire     mark a MANUAL kill criterion as FIRED and record obedience
  close    close a call with thesis attribution
  list     list all calls with statuses (short form of report.py)

Anti-pattern reminder: NEVER add significance-testing outputs to these
commands. Report counts and honest descriptions. Nothing else.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import get_conn  # noqa: E402


def cmd_enter(args) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO research_calls
        (ticker, note_id, direction, published_at, price_at_pub, price_target,
         horizon_months, thesis, benchmark, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """,
        (args.ticker.upper(), args.note, args.direction.upper(), args.date,
         args.price, args.target, args.horizon, args.thesis, args.benchmark.upper()),
    )
    call_id = cur.lastrowid
    conn.commit()
    print(f"created call #{call_id} — {args.ticker.upper()} {args.direction} "
          f"@ ${args.price} → ${args.target} over {args.horizon}mo")
    print("now add kill criteria via `cli.py fire-armed <call_id>` or edit")
    print("the DB directly. For pure-price criteria use metric=price_le/price_ge/drop_pct_ge.")
    return 0


def cmd_add_criterion(args) -> int:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO kill_criteria (call_id, description, metric, threshold, action, status)
        VALUES (?, ?, ?, ?, ?, 'ARMED')
        """,
        (args.call_id, args.description, args.metric, args.threshold, args.action.upper()),
    )
    conn.commit()
    print(f"added ARMED kill criterion to call #{args.call_id}: {args.description}")
    return 0


def cmd_fire(args) -> int:
    conn = get_conn()
    exists = conn.execute(
        "SELECT status FROM kill_criteria WHERE criterion_id=?", (args.criterion_id,)
    ).fetchone()
    if not exists:
        print(f"[fail] criterion #{args.criterion_id} not found")
        return 1
    if exists[0] != "ARMED":
        print(f"[fail] criterion #{args.criterion_id} is {exists[0]}, not ARMED")
        return 1
    obeyed_val = 1 if args.obeyed else 0
    conn.execute(
        "UPDATE kill_criteria SET status='FIRED', fired_at=datetime('now'), obeyed=? "
        "WHERE criterion_id=?",
        (obeyed_val, args.criterion_id),
    )
    conn.commit()
    print(f"criterion #{args.criterion_id} FIRED, obeyed={'YES' if args.obeyed else 'NO'}")
    if not args.obeyed:
        print("NOTE: disobedience recorded. This is the highest-signal number in the system.")
    return 0


def cmd_close(args) -> int:
    if args.attribution not in ("THESIS_CORRECT", "RIGHT_WRONG_REASON", "WRONG", "UNRESOLVED"):
        print(f"[fail] --attribution must be THESIS_CORRECT | RIGHT_WRONG_REASON | WRONG | UNRESOLVED")
        return 1
    conn = get_conn()
    exists = conn.execute(
        "SELECT status FROM research_calls WHERE call_id=?", (args.call_id,)
    ).fetchone()
    if not exists:
        print(f"[fail] call #{args.call_id} not found")
        return 1
    if exists[0] != "OPEN":
        print(f"[fail] call #{args.call_id} is {exists[0]}, not OPEN")
        return 1
    status_map = {
        "target": "CLOSED_TARGET",
        "kill": "CLOSED_KILL",
        "horizon": "CLOSED_HORIZON",
        "manual": "CLOSED_MANUAL",
    }
    if args.status not in status_map:
        print(f"[fail] --status must be one of {list(status_map)}")
        return 1
    conn.execute(
        """
        UPDATE research_calls SET status=?, closed_at=?, closed_price=?,
        closed_reason=?, thesis_attribution=? WHERE call_id=?
        """,
        (status_map[args.status], args.date, args.price, args.reason,
         args.attribution, args.call_id),
    )
    conn.commit()
    print(f"closed call #{args.call_id} as {status_map[args.status]} @ ${args.price}")
    print(f"attribution: {args.attribution}")
    if args.attribution == "RIGHT_WRONG_REASON":
        print("NOTE: RIGHT_WRONG_REASON = luck, not skill. Recorded as such.")
    return 0


def cmd_list(args) -> int:
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.call_id, c.ticker, c.direction, c.status, c.published_at,
               c.price_at_pub, c.price_target, c.horizon_months,
               c.thesis_attribution
        FROM research_calls c
        ORDER BY c.call_id
    """).fetchall()
    if not rows:
        print("no calls")
        return 0
    print(f"{'#ID':<4} {'TICK':<6} {'DIR':<4} {'STATUS':<16} {'PUB':<11} "
          f"{'PX':<8} {'PT':<8} {'HZ':<3} {'ATTRIBUTION':<20}")
    for r in rows:
        cid, tk, dr, st, pub, px, pt, hz, at = r
        print(f"#{cid:<3} {tk:<6} {dr:<4} {st:<16} {pub:<11} "
              f"${px:<7.2f} ${pt or 0:<7.2f} {hz:<3} {at or '(none)':<20}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_enter = sub.add_parser("enter", help="add a new research call")
    p_enter.add_argument("--ticker", required=True)
    p_enter.add_argument("--note", required=True, help="path/id of source note")
    p_enter.add_argument("--direction", required=True, choices=["BUY", "SELL", "HOLD"])
    p_enter.add_argument("--date", required=True, help="published_at YYYY-MM-DD")
    p_enter.add_argument("--price", type=float, required=True)
    p_enter.add_argument("--target", type=float, required=True)
    p_enter.add_argument("--horizon", type=int, required=True, help="months")
    p_enter.add_argument("--thesis", required=True)
    p_enter.add_argument("--benchmark", default="IWM")
    p_enter.set_defaults(func=cmd_enter)

    p_ac = sub.add_parser("add-criterion", help="add a kill criterion to a call")
    p_ac.add_argument("--call-id", type=int, required=True)
    p_ac.add_argument("--description", required=True)
    p_ac.add_argument("--metric", default="MANUAL",
                      help="MANUAL | price_le | price_ge | drop_pct_ge")
    p_ac.add_argument("--threshold", default=None)
    p_ac.add_argument("--action", required=True, choices=["TRIM_HALF", "EXIT", "REASSESS"])
    p_ac.set_defaults(func=cmd_add_criterion)

    p_fire = sub.add_parser("fire", help="mark a kill criterion as FIRED + record obedience")
    p_fire.add_argument("criterion_id", type=int)
    p_fire.add_argument("--obeyed", action="store_true",
                        help="pass this if you obeyed the criterion; omit if you did not")
    p_fire.set_defaults(func=cmd_fire)

    p_close = sub.add_parser("close", help="close a call with thesis attribution")
    p_close.add_argument("--call-id", type=int, required=True)
    p_close.add_argument("--status", required=True,
                         help="target | kill | horizon | manual")
    p_close.add_argument("--date", required=True, help="closed_at YYYY-MM-DD")
    p_close.add_argument("--price", type=float, required=True)
    p_close.add_argument("--reason", required=True)
    p_close.add_argument("--attribution", required=True,
                         help="THESIS_CORRECT | RIGHT_WRONG_REASON | WRONG | UNRESOLVED")
    p_close.set_defaults(func=cmd_close)

    p_list = sub.add_parser("list", help="short list of all calls")
    p_list.set_defaults(func=cmd_list)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
