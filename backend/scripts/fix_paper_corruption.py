#!/usr/bin/env python3
"""Fix corrupt paper trading data — delete phantom positions and reset accounts."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.db.session import SessionLocal
from app.db.models.paper import PaperAccount, PaperPosition, PaperOrder, PaperTransaction

def run():
    db = SessionLocal()
    try:
        # 1. Delete positions where qty is absurd (> 1M for any asset)
        deleted = db.query(PaperPosition).filter(
            PaperPosition.qty > 1_000_000
        ).delete(synchronize_session=False)
        print(f"Deleted {deleted} phantom positions (qty > 1M)")

        # 2. Delete positions where avg_cost / fill_price is 0 (corrupt)
        deleted2 = 0
        for p in db.query(PaperPosition).all():
            fill = getattr(p, 'fill_price', None) or getattr(p, 'avg_cost', None) or 0
            if fill == 0:
                db.delete(p)
                deleted2 += 1
        print(f"Deleted {deleted2} positions with zero cost basis")

        # 3. Delete positions where implied notional > $500,000 (qty * avg_cost > 500k)
        deleted3 = 0
        for p in db.query(PaperPosition).all():
            notional = (p.qty or 0) * (p.avg_cost or 0)
            if notional > 500_000:
                print(f"  Removing oversized position: {p.symbol} qty={p.qty} avg_cost={p.avg_cost} notional=${notional:,.0f}")
                db.delete(p)
                deleted3 += 1
        print(f"Deleted {deleted3} positions with notional > $500k")

        # 4. Reset paper account cash to starting balance for accounts that ended up corrupt
        for acct in db.query(PaperAccount).all():
            total_position_value = sum(
                (getattr(p, 'qty', 0) or 0) * (getattr(p, 'avg_cost', 0) or 0)
                for p in db.query(PaperPosition).filter(PaperPosition.user_id == acct.user_id).all()
            )
            starting = getattr(acct, 'starting_balance', 100_000.0) or 100_000.0
            if total_position_value + (acct.cash or 0) > 1_000_000:
                acct.cash = starting
                print(f"Reset account user_id={acct.user_id} cash to {starting}")

        db.commit()
        print("Done.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
