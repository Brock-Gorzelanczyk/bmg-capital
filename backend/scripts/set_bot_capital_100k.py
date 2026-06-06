"""
One-off script: set every bot allocation for every user to $100,000 starting capital.
Total: 8 bots × $100k = $800k per user.
Also updates StrategyPortfolio.starting_capital_cents to match.

Run via: railway run python backend/scripts/set_bot_capital_100k.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import SessionLocal
from app.db.models.bots import BotAllocation, BotProfile, StrategyPortfolio

BOT_CAPITAL_CENTS = 10_000_000  # $100,000

PORTFOLIO_CAPITALS = {
    "stocks":  30_000_000,  # 3 bots × $100k
    "crypto":  30_000_000,
    "options": 20_000_000,  # 2 bots × $100k
}

def main():
    db = SessionLocal()
    try:
        # Update all bot allocations
        allocs = db.query(BotAllocation).all()
        updated_allocs = 0
        for alloc in allocs:
            alloc.starting_capital_cents = BOT_CAPITAL_CENTS
            alloc.capital_cents_within_portfolio = BOT_CAPITAL_CENTS
            updated_allocs += 1

        # Update all strategy portfolios
        portfolios = db.query(StrategyPortfolio).all()
        updated_ports = 0
        for port in portfolios:
            target = PORTFOLIO_CAPITALS.get(port.asset_class)
            if target:
                port.starting_capital_cents = target
                updated_ports += 1

        db.commit()
        print(f"Updated {updated_allocs} bot allocations → $100,000 each")
        print(f"Updated {updated_ports} strategy portfolios")
        print("Done.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
