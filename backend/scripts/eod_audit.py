"""
EOD audit — run via: railway ssh "cd /app/backend && python3 scripts/eod_audit.py"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db.session import SessionLocal
from app.db.models.bots import BotProfile, BotAllocation, BotSignal, BotTrade

db = SessionLocal()

SEP = "=" * 70

print(SEP)
print("SECTION A — ALL BOT PROFILES + ALLOCATIONS")
print(SEP)
for bp in db.query(BotProfile).order_by(BotProfile.name).all():
    allocs = db.query(BotAllocation).filter(BotAllocation.profile_id == bp.id).all()
    if not allocs:
        print(f"\n{bp.name} (asset_class={bp.asset_class}) profile_enabled={bp.enabled}")
        print("  *** NO ALLOCATIONS ***")
        continue
    for a in allocs:
        cap = (a.starting_capital_cents or 0) / 100
        tier = getattr(a, "tier", "?")
        print(
            f"\n{bp.name} (asset_class={bp.asset_class}) profile_enabled={bp.enabled}"
        )
        print(
            f"  alloc_id={a.id} enabled={a.enabled} paper_mode={a.paper_mode} "
            f"cap=${cap:.0f} tier={tier} paused_reason={a.paused_reason}"
        )

print()
print(SEP)
print("SECTION B — SIGNAL VOLUME (24H) PER BOT")
print(SEP)
with db.bind.connect() as c:
    rows = c.execute(
        text("""
        SELECT bp.name, bp.asset_class,
               COUNT(DISTINCT bs.id) as signals_24h,
               COUNT(DISTINCT bt.id) as trades_24h,
               MAX(bs.ts) as last_signal
          FROM bot_profiles bp
          LEFT JOIN bot_allocations ba ON ba.profile_id = bp.id
          LEFT JOIN bot_signals bs ON bs.allocation_id = ba.id
            AND bs.ts > datetime('now','-24 hours')
          LEFT JOIN bot_trades bt ON bt.allocation_id = ba.id
            AND bt.ts > datetime('now','-24 hours')
         GROUP BY bp.id ORDER BY bp.asset_class, bp.name
        """)
    ).fetchall()
    for r in rows:
        print(f"  {r[0]:35s} ({r[1]:8s}) signals_24h={r[2]:5d} trades_24h={r[3]:5d} last_signal={r[4]}")

print()
print(SEP)
print("SECTION C — DISCORD POSTS (24H)")
print(SEP)
with db.bind.connect() as c:
    try:
        rows = c.execute(
            text("""
            SELECT bot_name, COUNT(*) as posts
              FROM discord_posts
             WHERE ts > datetime('now','-24 hours')
             GROUP BY bot_name ORDER BY posts DESC
            """)
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  {r[0]:35s} posted_24h={r[1]}")
        else:
            print("  (no discord_posts in last 24h)")
    except Exception as e:
        print(f"  discord_posts table read failed: {e}")

print()
print(SEP)
print("SECTION D — SCHEDULER JOBS (next_run_time)")
print(SEP)
with db.bind.connect() as c:
    try:
        rows = c.execute(
            text("SELECT id, next_run_time FROM apscheduler_jobs ORDER BY id")
        ).fetchall()
        for r in rows:
            print(f"  {r[0]:45s} next_run={r[1]}")
    except Exception as e:
        print(f"  apscheduler_jobs table read failed: {e}")

print()
print(SEP)
print("SECTION E — DISCORD CHANNEL ENV VARS")
print(SEP)
discord_vars = [
    "DISCORD_CH_ALL_SIGNALS",
    "DISCORD_CH_STOCKS_SIGNALS",
    "DISCORD_CH_CRYPTO_SIGNALS",
    "DISCORD_CH_OPTIONS_SIGNALS",
    "DISCORD_CH_QUANT_SIGNALS",
    "DISCORD_CH_AUDIT_TRAIL",
    "DISCORD_BOT_TOKEN",
]
for var in discord_vars:
    val = os.environ.get(var, "NOT_SET")
    status = "SET" if val != "NOT_SET" else "NOT_SET"
    print(f"  {var:35s} {status}")

db.close()
print()
print("AUDIT COMPLETE")
