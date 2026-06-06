"""
Social Sentiment Extreme Fade — contrarian signal using LunarCrush Galaxy Score.
Long when Galaxy Score > 80 AND price down 5%+ over 7d (fear at highs of attention).
Reduce when Galaxy < 20 AND price up 10%+ over 7d (euphoria).
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "social_sentiment_extreme_fade"
UNIVERSE = ["BTC", "ETH", "SOL", "AVAX", "LINK"]
HIGH_GALAXY_THRESHOLD = 80
LOW_GALAXY_THRESHOLD  = 20


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from app.db.session import SessionLocal
    from app.services.onchain_ingest import get_latest_metric

    signals = []
    db = SessionLocal()
    try:
        for symbol in UNIVERSE:
            galaxy = get_latest_metric(db, symbol, "galaxy_score", "lunarcrush")
            if galaxy is None:
                continue
            trading_symbol = f"{symbol}/USD"
            symbol_bars = bars.get(trading_symbol, [])

            # Need ~35 bars of daily data to compute 7d price change
            if len(symbol_bars) >= 7:
                close_now  = symbol_bars[-1]["c"]
                close_7d   = symbol_bars[-7]["c"] if len(symbol_bars) >= 7 else close_now
                change_7d  = (close_now - close_7d) / close_7d if close_7d else 0
            else:
                change_7d = 0

            if galaxy > HIGH_GALAXY_THRESHOLD and change_7d < -0.05:
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="buy",
                    confidence=min(0.78, 0.55 + (galaxy - HIGH_GALAXY_THRESHOLD) / 100),
                    size_hint=0.07,
                    reason=(f"Galaxy Score {galaxy:.0f} (high attention) while price is down "
                            f"{abs(change_7d)*100:.1f}% in 7d. Fear at high social visibility — contrarian long."),
                    strategy=STRATEGY_NAME,
                ))
            elif galaxy < LOW_GALAXY_THRESHOLD and change_7d > 0.10:
                signals.append(Signal(
                    symbol=trading_symbol,
                    side="sell",
                    confidence=min(0.72, 0.50 + (LOW_GALAXY_THRESHOLD - galaxy) / 100),
                    size_hint=0.05,
                    reason=(f"Galaxy Score {galaxy:.0f} (low social interest) while price is up "
                            f"{change_7d*100:.1f}% in 7d. Stealthy rally losing momentum — reduce."),
                    strategy=STRATEGY_NAME,
                ))
    finally:
        db.close()
    return signals
