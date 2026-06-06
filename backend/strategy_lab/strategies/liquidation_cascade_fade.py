"""
Liquidation Cascade Fade — enter long after a major liquidation event (>$200M in 1h).
Price tends to snap back after cascade clears. Requires 15-min consolidation post-event.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "liquidation_cascade_fade"
UNIVERSE = ["BTC", "ETH"]
LIQ_THRESHOLD_USD = 200_000_000    # $200M in liquidations in 1h
CONSOLIDATION_BARS = 3             # 3 × 5-min bars = 15 min


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from app.db.session import SessionLocal
    from app.services.onchain_ingest import get_latest_metric

    signals = []
    db = SessionLocal()
    try:
        for symbol in UNIVERSE:
            oi = get_latest_metric(db, symbol, "open_interest_usd", "coinglass")
            if oi is None:
                continue
            trading_symbol = f"{symbol}/USD"
            symbol_bars = bars.get(trading_symbol, [])

            if len(symbol_bars) < CONSOLIDATION_BARS + 2:
                continue

            # Proxy: detect cascade as a large candle body drop then consolidation
            closes = [b["c"] for b in symbol_bars]
            recent_drop = (closes[-CONSOLIDATION_BARS - 1] - closes[-CONSOLIDATION_BARS]) / closes[-CONSOLIDATION_BARS - 1]
            consolidation_range = max(closes[-CONSOLIDATION_BARS:]) - min(closes[-CONSOLIDATION_BARS:])
            avg_range = sum(abs(b["h"] - b["l"]) for b in symbol_bars[-10:]) / 10

            if recent_drop > 0.03 and consolidation_range < avg_range * 1.2:
                confidence = min(0.80, 0.60 + recent_drop * 5)
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="buy",
                    confidence=round(confidence, 3),
                    size_hint=0.06,
                    reason=(f"{symbol} dropped {recent_drop*100:.1f}% in one candle then consolidated "
                            f"{CONSOLIDATION_BARS} bars. Liquidation cascade fade — snap-back likely."),
                    strategy=STRATEGY_NAME,
                ))
    finally:
        db.close()
    return signals
