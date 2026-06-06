"""
Set admin accounts to permanent premium tier in the DB.
This ensures ALL tier checks (effective_tier() calls) return premium for admins,
not just the /tiers/me endpoint.

Run via: railway run python backend/scripts/set_admin_premium.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import SessionLocal
from app.db.models.users import User
from app.db.models.tier import UserTier

ADMIN_EMAILS = {"32bgorzelanczyk@gmail.com", "demo@bmgcapital.com"}

def main():
    db = SessionLocal()
    try:
        admins = db.query(User).filter(User.email.in_(ADMIN_EMAILS)).all()
        if not admins:
            print("No admin users found.")
            return

        for user in admins:
            row = db.query(UserTier).filter_by(user_id=user.id).first()
            if row:
                row.tier = "premium"
                row.status = "active"
                row.trial_ends_at = None
                row.current_period_end = None
                row.cancel_at_period_end = False
                row.aum_override = "premium"
                print(f"Updated {user.email} → premium/active")
            else:
                db.add(UserTier(
                    user_id=user.id,
                    tier="premium",
                    status="active",
                    billing_interval="annual",
                    aum_override="premium",
                ))
                print(f"Created {user.email} → premium/active")

        db.commit()
        print("Done — all admin accounts are now permanent premium.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
