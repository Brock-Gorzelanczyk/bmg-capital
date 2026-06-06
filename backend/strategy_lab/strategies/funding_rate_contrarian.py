"""
Funding Rate Contrarian — fade overcrowded longs/shorts via perpetual funding rates.
Long when funding < -0.05% (crowded shorts), short-bias when > +0.05% (crowded longs).
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "funding_rate_contrarian"
UNIVERSE = ["BTC", "ETH", "SOL"]
LONG_THRESHOLD  = -0.0005   # -0.05%
SHORT_THRESHOLD =  0.0005   # +0.05%


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from app.db.session import SessionLocal
    from app.services.onchain_ingest import get_latest_metric

    signals = []
    db = SessionLocal()
    try:
        for symbol in UNIVERSE:
            rate = get_latest_metric(db, symbol, "funding_rate", "coinglass")
            if rate is None:
                continue
            trading_symbol = f"{symbol}/USD"
            rate_pct = rate * 100

            if rate < LONG_THRESHOLD:
                confidence = min(0.85, 0.60 + abs(rate - LONG_THRESHOLD) * 500)
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="buy",
                    confidence=round(confidence, 3),
                    size_hint=0.08,
                    reason=(f"Funding rate {rate_pct:.3f}% (negative). Shorts are over-leveraged "
                            "— squeeze risk. Contrarian long."),
                    strategy=STRATEGY_NAME,
                ))
            elif rate > SHORT_THRESHOLD:
                confidence = min(0.80, 0.55 + abs(rate - SHORT_THRESHOLD) * 500)
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="sell",
                    confidence=round(confidence, 3),
                    size_hint=0.05,
                    reason=(f"Funding rate +{rate_pct:.3f}% (elevated). Longs paying premium — "
                            "crowded trade, reduce exposure."),
                    strategy=STRATEGY_NAME,
                ))
    finally:
        db.close()
    return signals
