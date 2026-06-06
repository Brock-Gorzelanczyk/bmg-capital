"""
MVRV Z-Score Accumulation — long BTC/ETH when MVRV-Z < 0 (historic buy zone).
Source: Glassnode. 30-day hold horizon.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "mvrv_zscore_accumulation"
UNIVERSE = ["BTC", "ETH"]
ACCUMULATION_THRESHOLD = 0.0
DISTRIBUTION_THRESHOLD = 4.0


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from app.db.session import SessionLocal
    from app.services.onchain_ingest import get_latest_metric

    signals = []
    db = SessionLocal()
    try:
        for symbol in UNIVERSE:
            mvrv_z = get_latest_metric(db, symbol, "mvrv_z", "glassnode")
            if mvrv_z is None:
                continue
            trading_symbol = f"{symbol}/USD"
            if mvrv_z < ACCUMULATION_THRESHOLD:
                confidence = min(0.95, 0.6 + abs(mvrv_z) * 0.1)
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="buy",
                    confidence=round(confidence, 3),
                    size_hint=0.10,
                    reason=f"MVRV-Z = {mvrv_z:.2f} (historical accumulation zone < 0). Strong long-term buy signal.",
                    strategy=STRATEGY_NAME,
                ))
            elif mvrv_z > DISTRIBUTION_THRESHOLD:
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="sell",
                    confidence=min(0.90, 0.6 + (mvrv_z - DISTRIBUTION_THRESHOLD) * 0.05),
                    size_hint=0.10,
                    reason=f"MVRV-Z = {mvrv_z:.2f} > {DISTRIBUTION_THRESHOLD}. Distribution zone — reduce exposure.",
                    strategy=STRATEGY_NAME,
                ))
    finally:
        db.close()
    return signals
