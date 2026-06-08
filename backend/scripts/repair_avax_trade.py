"""
Repair bad AVAX trade (id=25) that was filled at $37.94 (stale 2024 yfinance data)
when the real AVAX/USD price is ~$6.50.

Two options:
  --delete   : delete BotTrade id=25 and BotPosition linked to it
  --reprice  : update fill_price to current Kraken spot and recalculate stop/target

Usage:
  python scripts/repair_avax_trade.py --delete
  python scripts/repair_avax_trade.py --reprice
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models.bots import BotTrade, BotPosition

BAD_TRADE_ID = 25


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--delete"
    db = SessionLocal()
    try:
        trade = db.get(BotTrade, BAD_TRADE_ID)
        if not trade:
            print(f"Trade id={BAD_TRADE_ID} not found — already repaired?")
            return

        print(f"Found trade id={trade.id}: {trade.symbol}  fill=${trade.fill_price_cents/100:.4f}  qty={trade.qty}  ts={trade.ts}")
        pos = db.get(BotPosition, trade.position_id) if trade.position_id else None
        if pos:
            print(f"  Linked BotPosition id={pos.id}: avg_cost=${pos.avg_cost_cents/100:.4f}  closed_at={pos.closed_at}")

        if mode == "--delete":
            if pos:
                db.delete(pos)
                print(f"  Deleted BotPosition id={pos.id}")
            db.delete(trade)
            print(f"  Deleted BotTrade id={trade.id}")
            db.commit()
            print("Done — bad AVAX trade removed.")

        elif mode == "--reprice":
            from app.services.live_prices import fetch_live_prices
            live = fetch_live_prices(["AVAX/USD"])
            live_price = float(live.get("AVAX/USD", 0) or 0)
            if live_price <= 0:
                print("ERROR: could not fetch live AVAX/USD price — aborting")
                return

            print(f"  Live AVAX/USD price from Kraken: ${live_price:.4f}")
            new_fill_cents = int(live_price * 100)

            # Recalculate stop/target using same defaults as compute_bracket_prices
            stop_pct = 0.05   # 5%
            target_pct = 0.10  # 10%
            new_stop = round(live_price * (1 - stop_pct), 4)
            new_target = round(live_price * (1 + target_pct), 4)

            trade.fill_price_cents = new_fill_cents
            trade.expected_fill_cents = new_fill_cents
            trade.slippage_bps = 0.0

            if pos:
                pos.avg_cost_cents = new_fill_cents
                pos.stop_price_usd = new_stop
                pos.target_price_usd = new_target

            db.commit()
            print(f"Done — repriced AVAX trade to ${live_price:.4f}  stop=${new_stop}  target=${new_target}")

        else:
            print(f"Unknown mode: {mode}. Use --delete or --reprice")

    finally:
        db.close()


if __name__ == "__main__":
    main()
