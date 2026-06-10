"""
Diagnostic: verbose scan for the 5 silent bots.
Run via: railway run python scripts/diagnose_silent_bots.py
"""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////data/bmg_capital.db")
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
Session = sessionmaker(bind=engine)

BOT_NAMES = [
    "stock_day",
    "stock_swing",
    "stock_lt",
    "options_directional",
    "options_income",
]

def confidence_histogram(results: list) -> dict:
    buckets = {"zero": 0, "0.01-0.20": 0, "0.20-0.40": 0, "0.40-0.45": 0, "0.45+": 0}
    for r in results:
        c = r.get("confidence", 0)
        if c == 0:
            buckets["zero"] += 1
        elif c <= 0.20:
            buckets["0.01-0.20"] += 1
        elif c <= 0.40:
            buckets["0.20-0.40"] += 1
        elif c < 0.45:
            buckets["0.40-0.45"] += 1
        else:
            buckets["0.45+"] += 1
    return buckets

def check_bot_db_state(db, bot_name: str) -> dict:
    row = db.execute(
        text("SELECT id, enabled, paused FROM bot_profiles WHERE name = :n"),
        {"n": bot_name}
    ).first()
    if not row:
        return {"exists": False}
    bp_id = row[0]
    allocs = db.execute(
        text("SELECT id, user_id, enabled, paper_mode FROM bot_allocations WHERE profile_id = :pid"),
        {"pid": bp_id}
    ).fetchall()
    open_pos = db.execute(
        text("""
            SELECT COUNT(*) FROM bot_positions bp2
            JOIN bot_allocations ba ON ba.id = bp2.allocation_id
            WHERE ba.profile_id = :pid AND bp2.closed_at IS NULL
        """),
        {"pid": bp_id}
    ).scalar()
    return {
        "exists": True,
        "enabled": bool(row[1]),
        "paused": bool(row[2]),
        "allocations": [
            {"id": a[0], "user_id": a[1], "enabled": bool(a[2]), "paper_mode": bool(a[3])}
            for a in allocs
        ],
        "open_positions": open_pos or 0,
    }

def run():
    from strategy_lab.scan_and_execute import scan_and_execute

    db = Session()
    try:
        for bot_name in BOT_NAMES:
            print(f"\n{'='*60}")
            print(f"BOT: {bot_name}")
            print("="*60)

            state = check_bot_db_state(db, bot_name)
            print(f"  DB state: {json.dumps(state, indent=2)}")

            if not state["exists"]:
                print("  SKIP: bot_profile not found in DB")
                continue
            if not state["enabled"]:
                print("  SKIP: bot disabled in DB")
                continue
            if state["paused"]:
                print("  NOTE: bot is paused — scan_and_execute(user_id=1) will ignore paused state")

            # user_id=1 so we hit the admin's allocations even if scheduler would be blocked
            result = scan_and_execute(
                bot_name,
                db,
                persist=False,
                execute=False,
                user_id=1,
            )

            print(f"  symbols_scanned:     {result.get('symbols_scanned', '?')}")
            print(f"  symbols_with_bars:   {result.get('symbols_with_bars', '?')}")
            print(f"  strategies_executed: {result.get('strategies_executed', '?')}")
            print(f"  signals_generated:   {result.get('signals_generated', '?')}")

            if result.get("bar_fetch_error"):
                print(f"  BAR FETCH ERROR: {result['bar_fetch_error']}")

            missing = result.get("symbols_missing_bars", [])
            if missing:
                print(f"  symbols_missing_bars ({len(missing)}): {missing[:10]}")

            results = result.get("results", [])
            hist = confidence_histogram(results)
            print(f"  confidence histogram: {hist}")

            # Show top signals
            top = sorted(results, key=lambda r: -r.get("confidence", 0))[:10]
            if top:
                print(f"  top signals:")
                for r in top:
                    print(f"    {r.get('symbol'):8s} {r.get('side'):5s} conf={r.get('confidence', 0):.4f} strat={r.get('strategy','?')}")
            else:
                print("  top signals: NONE")

            # Signals near threshold
            near = [r for r in results if 0.40 <= r.get("confidence", 0) < 0.45]
            if near:
                print(f"  near-threshold (0.40-0.45): {len(near)} signals")
                for r in near[:5]:
                    print(f"    {r.get('symbol'):8s} {r.get('side'):5s} conf={r.get('confidence', 0):.4f}")

            errors = result.get("errors", [])
            if errors:
                print(f"  errors ({len(errors)}):")
                seen_errs = {}
                for e in errors:
                    key = e.get("strategy", "?") + "|" + str(e.get("error", ""))[:80]
                    seen_errs[key] = seen_errs.get(key, 0) + 1
                for k, cnt in seen_errs.items():
                    print(f"    x{cnt}: {k}")

            if result.get("error"):
                print(f"  SCAN ERROR: {result['error']}")

    finally:
        db.close()

if __name__ == "__main__":
    run()
