"""
One-off migration: set each bot allocation to $100k starting capital and
link all allocations to their StrategyPortfolio (portfolio_id).

8 bots × $100k = $800k total per user.

  Stocks  (stock_swing, stock_day, stock_lt)      → $300k portfolio
  Crypto  (crypto_swing, crypto_day, crypto_lt)    → $300k portfolio
  Options (options_income, options_directional)     → $200k portfolio

Run via: railway run python backend/scripts/set_bot_capital_100k.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import SessionLocal
from app.db.models.bots import BotAllocation, BotProfile, StrategyPortfolio

BOT_CAPITAL_CENTS = 10_000_000  # $100,000 per bot

PORTFOLIO_CAPITALS = {
    "stocks":  30_000_000,
    "crypto":  30_000_000,
    "options": 20_000_000,
}

# Which bots belong to which portfolio asset_class
BOT_TO_ASSET_CLASS = {
    "stock_swing": "stocks",
    "stock_day":   "stocks",
    "stock_lt":    "stocks",
    "crypto_swing": "crypto",
    "crypto_day":   "crypto",
    "crypto_lt":    "crypto",
    "options_income":       "options",
    "options_directional":  "options",
}

def main():
    db = SessionLocal()
    try:
        profiles = {p.name: p for p in db.query(BotProfile).all()}
        portfolios_by_user_class = {}
        for port in db.query(StrategyPortfolio).all():
            portfolios_by_user_class[(port.user_id, port.asset_class)] = port

        # Update portfolio starting capitals
        updated_ports = 0
        for port in db.query(StrategyPortfolio).all():
            target = PORTFOLIO_CAPITALS.get(port.asset_class)
            if target and port.starting_capital_cents != target:
                port.starting_capital_cents = target
                updated_ports += 1

        # Update each allocation: capital + link to portfolio
        allocs = db.query(BotAllocation).all()
        updated_capital = 0
        linked = 0

        for alloc in allocs:
            profile = profiles.get(None)
            # find profile by id
            for p in profiles.values():
                if p.id == alloc.profile_id:
                    profile = p
                    break

            if profile is None:
                continue

            # Set capital
            alloc.starting_capital_cents = BOT_CAPITAL_CENTS
            alloc.capital_cents_within_portfolio = BOT_CAPITAL_CENTS
            updated_capital += 1

            # Link to portfolio if not already linked
            if alloc.portfolio_id is None:
                asset_class = BOT_TO_ASSET_CLASS.get(profile.name)
                if asset_class:
                    port = portfolios_by_user_class.get((alloc.user_id, asset_class))
                    if port:
                        alloc.portfolio_id = port.id
                        linked += 1

        db.commit()
        print(f"Updated {updated_ports} portfolio starting capitals")
        print(f"Updated {updated_capital} bot allocations → $100,000 each")
        print(f"Linked {linked} allocations to their portfolios")
        print("Done — refresh Strategy Lab to see $800k total.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
