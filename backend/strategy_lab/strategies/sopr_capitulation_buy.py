"""
SOPR Capitulation Buy — long BTC when STH-SOPR crosses 1.0 from below.
Short-term holders just stopped panic-selling → bounce signal.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "sopr_capitulation_buy"


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from app.db.session import SessionLocal
    from app.services.onchain_ingest import get_latest_metric
    from app.db.models.onchain import OnChainMetric

    signals = []
    db = SessionLocal()
    try:
        sopr = get_latest_metric(db, "BTC", "sopr_sth", "glassnode")
        if sopr is None:
            return signals

        # Get previous reading to detect cross
        rows = (
            db.query(OnChainMetric)
            .filter_by(symbol="BTC", metric="sopr_sth", source="glassnode")
            .order_by(OnChainMetric.ts.desc())
            .limit(3)
            .all()
        )
        prev_sopr = rows[1].value if len(rows) >= 2 else None

        if sopr >= 1.0 and prev_sopr is not None and prev_sopr < 1.0:
            signals.append(Signal(
                symbol="BTC/USD",
                side="buy",
                confidence=0.78,
                size_hint=0.08,
                reason=f"STH-SOPR crossed 1.0 from below ({prev_sopr:.3f} → {sopr:.3f}). Panic selling ended — bounce likely.",
                strategy=STRATEGY_NAME,
            ))
        elif sopr > 1.03:
            signals.append(Signal(
                symbol="BTC/USD",
                side="sell",
                confidence=0.65,
                size_hint=0.05,
                reason=f"STH-SOPR = {sopr:.3f} > 1.03. Short-term holders in profit — consider taking gains.",
                strategy=STRATEGY_NAME,
            ))
    finally:
        db.close()
    return signals
