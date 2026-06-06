"""
Exchange Outflow Signal — long when sustained BTC outflow from exchanges
for 14+ days (coins moving to cold storage = accumulation).
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "exchange_outflow_signal"
OUTFLOW_THRESHOLD = -5000        # BTC/day sustained outflow
SUSTAINED_DAYS_REQUIRED = 14
REVERSAL_DAYS = 7


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from app.db.session import SessionLocal
    from app.db.models.onchain import OnChainMetric

    signals = []
    db = SessionLocal()
    try:
        rows = (
            db.query(OnChainMetric)
            .filter_by(symbol="BTC", metric="exchange_net_flow", source="glassnode")
            .order_by(OnChainMetric.ts.desc())
            .limit(30)
            .all()
        )
        if len(rows) < SUSTAINED_DAYS_REQUIRED:
            return signals

        recent = [r.value for r in rows[:SUSTAINED_DAYS_REQUIRED]]
        outflow_days = sum(1 for v in recent if v < OUTFLOW_THRESHOLD)
        inflow_days  = sum(1 for v in recent[:REVERSAL_DAYS] if v > 0)

        avg_flow = sum(recent) / len(recent)

        if outflow_days >= SUSTAINED_DAYS_REQUIRED:
            signals.append(Signal(
                symbol="BTC/USD",
                side="buy",
                confidence=min(0.88, 0.65 + outflow_days * 0.01),
                size_hint=0.10,
                reason=(f"BTC exchange net flow: {avg_flow:.0f} BTC/day avg over 14d "
                        f"(outflow on {outflow_days}/{SUSTAINED_DAYS_REQUIRED} days). "
                        "Sustained accumulation off exchanges."),
                strategy=STRATEGY_NAME,
            ))
        elif inflow_days >= REVERSAL_DAYS:
            signals.append(Signal(
                symbol="BTC/USD",
                side="sell",
                confidence=0.62,
                size_hint=0.05,
                reason=f"Exchange inflow flipped positive for {inflow_days} consecutive days — distribution risk.",
                strategy=STRATEGY_NAME,
            ))
    finally:
        db.close()
    return signals
