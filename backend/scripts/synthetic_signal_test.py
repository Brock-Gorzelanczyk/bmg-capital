"""
EOD synthetic signal test.

Injects a test signal directly into the execution pipeline for a given bot,
bypassing the strategy scan. Verifies: BotSignal created → BotTrade created
→ Discord posted → DB row has correct fields.

USAGE:
    railway ssh "cd /app && python3 scripts/synthetic_signal_test.py options_income SPY sell_put"
    railway ssh "cd /app && python3 scripts/synthetic_signal_test.py stock_day AAPL long"

The injected signal has is_test=True so it's excluded from signals_24h counts
but goes through the full execution + Discord path.
"""
import sys
import os
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

bot_name  = sys.argv[1] if len(sys.argv) > 1 else "options_income"
symbol    = sys.argv[2] if len(sys.argv) > 2 else "SPY"
side      = sys.argv[3] if len(sys.argv) > 3 else "sell_put"

print(f"=== SYNTHETIC SIGNAL TEST: bot={bot_name} symbol={symbol} side={side} ===")

from app.db.session import SessionLocal
from app.db.models.bots import BotProfile, BotAllocation, BotSignal
from strategy_lab.seeds import load_profile

db = SessionLocal()
try:
    # 1. Find the bot profile
    bp = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
    if not bp:
        print(f"FAILED: no BotProfile for {bot_name}")
        sys.exit(1)
    if not bp.enabled:
        print(f"FAILED: BotProfile {bot_name} is disabled (profile_enabled=False)")
        sys.exit(1)

    # 2. Find first enabled paper allocation
    alloc = db.query(BotAllocation).filter(
        BotAllocation.profile_id == bp.id,
        BotAllocation.enabled.is_(True),
        BotAllocation.paper_mode.is_(True),
    ).first()
    if not alloc:
        print(f"FAILED: no enabled paper allocation for {bot_name}")
        sys.exit(1)
    print(f"  Using alloc_id={alloc.id} (user_id={alloc.user_id})")

    # 3. Build a minimal signal object
    from types import SimpleNamespace
    profile = load_profile(bot_name) or {}
    asset_class = profile.get("asset_class", bp.asset_class or "stock")

    sig = SimpleNamespace(
        symbol=symbol,
        side=side,
        confidence=0.85,
        price=None,
        size_pct=profile.get("position_size_pct", 5.0),
        stop=None,
        target=None,
        strategy="synthetic_eod_test",
        reason={"test": "eod_synthetic", "injected": True},
        asset_class=asset_class,
        is_test=True,
    )

    # 4. Persist BotSignal
    now = datetime.now(timezone.utc)
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        price = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
    except Exception:
        price = 0.0

    bs = BotSignal(
        allocation_id=alloc.id,
        symbol=symbol,
        side=side,
        confidence=sig.confidence,
        price=price,
        size_pct=sig.size_pct,
        stop=None,
        target=None,
        strategy=sig.strategy,
        reason=json.dumps(sig.reason),
        ts=now,
        is_test=True,
    )
    db.add(bs)
    db.flush()
    print(f"  BotSignal created: id={bs.id} symbol={symbol} side={side} price={price:.2f}")

    # 5. Execute the paper trade (options or stock)
    profile_cfg = load_profile(bot_name) or {}
    final_size_pct = sig.size_pct

    if asset_class == "options":
        from strategy_lab.runner import _execute_options_signal
        _execute_options_signal(
            sig=sig,
            alloc=alloc,
            db=db,
            profile_name=bot_name,
            final_size_pct=final_size_pct,
        )
    else:
        # Stock/crypto paper trade
        from app.db.models.bots import BotTrade, BotPosition
        capital_usd = (alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000) / 100.0
        position_dollars = capital_usd * (final_size_pct / 100.0)
        qty = round(position_dollars / price, 4) if price > 0 else 1.0
        fill_cents = round(price * 100)

        pos = BotPosition(
            allocation_id=alloc.id,
            symbol=symbol,
            qty=qty,
            avg_cost_cents=fill_cents,
            side="long" if side in ("long", "buy") else "short",
            opened_at=now,
            is_paper=True,
        )
        db.add(pos)
        db.flush()

        trade = BotTrade(
            allocation_id=alloc.id,
            symbol=symbol,
            side=side,
            qty=qty,
            fill_price_cents=fill_cents,
            fees_cents=0,
            ts=now,
            position_id=pos.id,
            is_paper=True,
            expected_fill_cents=fill_cents,
            slippage_bps=0.0,
        )
        db.add(trade)
        db.flush()
        print(f"  BotTrade created: id={trade.id} qty={qty:.4f} @ ${price:.2f}")

    db.commit()

    # 6. Verify DB row
    db.refresh(bs)
    print(f"  BotSignal in DB: id={bs.id} is_test={bs.is_test} allocation_id={bs.allocation_id}")

    # 7. Post to Discord
    try:
        from app.services.discord_public import post_signal
        signal_payload = {
            "bot": bot_name,
            "symbol": symbol,
            "side": side,
            "strategy": "synthetic_eod_test",
            "confidence": sig.confidence,
            "price": price,
            "reason": f"[EOD TEST] Synthetic signal — verifying Discord routing for {bot_name}",
            "size_pct": sig.size_pct,
            "stop": None,
            "target": None,
        }
        msg_id = post_signal(signal_payload)
        print(f"  Discord post result: message_id={msg_id}")
        if msg_id:
            print("  Discord: POSTED OK")
        else:
            print("  Discord: post returned None (check DISCORD_CH_* env vars)")
    except Exception as de:
        print(f"  Discord: FAILED — {type(de).__name__}: {de}")

    print()
    print("=== SYNTHETIC TEST RESULT ===")
    print(f"  BotSignal id={bs.id}: CREATED")
    print(f"  asset_class={asset_class}")
    print(f"  Discord: {'OK' if msg_id else 'NO MESSAGE ID'}")
    print("  Check the relevant Discord channel for the test embed.")

except Exception as exc:
    import traceback
    print(f"FAILED: {type(exc).__name__}: {exc}")
    traceback.print_exc()
    db.rollback()
finally:
    db.close()
