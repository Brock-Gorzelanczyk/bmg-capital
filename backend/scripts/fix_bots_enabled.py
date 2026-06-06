"""
One-shot: re-enable all bots for the admin user whose email was reset by
the 3-portfolio migration. Idempotent — safe to run multiple times.

Usage (from backend/):
    railway run python scripts/fix_bots_enabled.py
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text

EMAIL = os.environ.get("TARGET_EMAIL", "32bgorzelanczyk@gmail.com")

db_url = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(os.path.dirname(__file__), '..', 'bmg_capital.db')}",
)
engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
)

with engine.connect() as conn:
    # ── Step 1: Re-enable all bots ──────────────────────────────────────────
    result = conn.execute(text("""
        UPDATE bot_allocations
        SET enabled = 1,
            paused = 0,
            paused_reason = NULL
        WHERE user_id = (SELECT id FROM users WHERE email = :email)
    """), {"email": EMAIL})
    print(f"Step 1 — Updated {result.rowcount} bot_allocation rows (enabled=1, paused=0).")

    # ── Step 2: Verify bots ─────────────────────────────────────────────────
    rows = conn.execute(text("""
        SELECT ba.name, ba.enabled, ba.paused, ba.portfolio_id,
               ba.starting_capital_cents, ba.current_value_cents
        FROM bot_allocations ba
        WHERE ba.user_id = (SELECT id FROM users WHERE email = :email)
        ORDER BY ba.portfolio_id, ba.name
    """), {"email": EMAIL}).fetchall()

    print(f"\nStep 2 — Bot allocation rows ({len(rows)} found):")
    for r in rows:
        status = "ENABLED" if r[1] else "DISABLED"
        paused = " PAUSED" if r[2] else ""
        capital = f"${r[4]/100:,.0f}" if r[4] else "—"
        print(f"  [{status}{paused}] {r[0]:35s}  portfolio={r[3]}  capital={capital}")

    # ── Step 3: Verify portfolios ───────────────────────────────────────────
    portfolios = conn.execute(text("""
        SELECT name, asset_class, starting_capital_cents, current_value_cents
        FROM strategy_portfolios
        WHERE user_id = (SELECT id FROM users WHERE email = :email)
        ORDER BY asset_class
    """), {"email": EMAIL}).fetchall()

    print(f"\nStep 3 — Strategy portfolios ({len(portfolios)} found):")
    if not portfolios:
        print("  WARNING: 0 portfolios found! Re-run the 3-portfolio migration.")
    for p in portfolios:
        start = f"${p[2]/100:,.0f}" if p[2] else "—"
        curr  = f"${p[3]/100:,.0f}" if p[3] else "—"
        print(f"  {p[0]:30s}  class={p[1]:8s}  start={start}  current={curr}")

    conn.commit()

print("\nDone.")
