"""
Crypto Quant Aggressive — S7: Funding Rate Arb

Perpetual futures funding rates signal crowded positioning:
  • Rate > +0.05%  (longs paying shorts) → market is overcrowded long → fade short
  • Rate < -0.05%  (shorts paying longs) → market is overcrowded short → fade long

Uses live funding data from the onchain metrics DB (same source as
funding_rate_contrarian strategy). Falls back to a synthetic OHLCV proxy
when DB data is unavailable: consecutive bullish/bearish bars with volume
acceleration as a proxy for crowded positioning.

Targets only the most liquid coins (BTC, ETH, SOL) where funding data is
reliable and execution slippage is minimal.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_funding_rate_arb"

LIVE_UNIVERSE = ["BTC", "ETH", "SOL"]   # coins with reliable funding data
FUNDING_LONG_THRESHOLD  = -0.0005        # -0.05%: crowded shorts → go long
FUNDING_SHORT_THRESHOLD =  0.0005        # +0.05%: crowded longs  → go short

# OHLCV proxy fallback parameters
PROXY_LOOKBACK = 20           # bars
PROXY_BULL_RATIO_HIGH = 0.80  # 80%+ bullish bars → implied high funding → fade short
PROXY_BULL_RATIO_LOW  = 0.20  # 20%- bullish bars → implied negative funding → fade long
PROXY_MIN_BARS = 12


def _get_live_funding_signals(conf_bump: float) -> list[Signal]:
    signals: list[Signal] = []
    try:
        from app.db.session import SessionLocal
        from app.services.onchain_ingest import get_latest_metric
        db = SessionLocal()
        try:
            for symbol in LIVE_UNIVERSE:
                rate = get_latest_metric(db, symbol, "funding_rate", "coinglass")
                if rate is None:
                    continue
                trading_symbol = f"{symbol}/USD"
                if rate < FUNDING_LONG_THRESHOLD:
                    confidence = min(0.85, 0.58 + abs(rate - FUNDING_LONG_THRESHOLD) * 600)
                    signals.append(Signal(
                        symbol=trading_symbol,
                        side="buy",
                        confidence=round(min(0.85, confidence + conf_bump), 3),
                        size_hint=0.08,
                        reason=(
                            f"FUNDING_ARB long: rate {rate * 100:.3f}% (shorts overcrowded). "
                            "Squeeze risk → buy the squeeze."
                        ),
                        strategy=STRATEGY_NAME,
                    ))
                elif rate > FUNDING_SHORT_THRESHOLD:
                    confidence = min(0.80, 0.55 + abs(rate - FUNDING_SHORT_THRESHOLD) * 600)
                    signals.append(Signal(
                        symbol=trading_symbol,
                        side="sell",
                        confidence=round(min(0.80, confidence + conf_bump), 3),
                        size_hint=0.06,
                        reason=(
                            f"FUNDING_ARB short: rate +{rate * 100:.3f}% (longs overcrowded). "
                            "Carry trade unwind risk → fade the premium."
                        ),
                        strategy=STRATEGY_NAME,
                    ))
        finally:
            db.close()
    except Exception as exc:
        logger.debug("[%s] live funding unavailable: %s", STRATEGY_NAME, exc)
    return signals


def _get_proxy_signals(
    bars: dict[str, list[dict]],
    symbols: list[str],
    conf_bump: float,
) -> list[Signal]:
    """OHLCV proxy: consecutive bull/bear bar ratio as synthetic funding indicator."""
    signals: list[Signal] = []
    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < PROXY_MIN_BARS:
            continue
        window = symbol_bars[-PROXY_LOOKBACK:] if len(symbol_bars) >= PROXY_LOOKBACK else symbol_bars
        bull_bars = sum(1 for b in window if b["c"] >= b["o"])
        bull_ratio = bull_bars / len(window)
        current_close = symbol_bars[-1]["c"]
        if current_close <= 0:
            continue

        if bull_ratio >= PROXY_BULL_RATIO_HIGH:
            # High implied funding → fade short
            confidence = round(min(0.72, 0.52 + (bull_ratio - PROXY_BULL_RATIO_HIGH) * 2.0 + conf_bump), 3)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=min(1.0, confidence),
                reason=(
                    f"FUNDING_ARB proxy short: {bull_ratio:.0%} bullish bars over last {len(window)} bars "
                    f"→ implied crowded longs → fade at ${current_close:,.4f}"
                ),
                strategy=STRATEGY_NAME,
            ))
        elif bull_ratio <= PROXY_BULL_RATIO_LOW:
            # Deeply negative implied funding → go long
            confidence = round(min(0.72, 0.52 + (PROXY_BULL_RATIO_LOW - bull_ratio) * 2.0 + conf_bump), 3)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=min(1.0, confidence),
                reason=(
                    f"FUNDING_ARB proxy long: only {bull_ratio:.0%} bullish bars over last {len(window)} bars "
                    f"→ implied crowded shorts → buy at ${current_close:,.4f}"
                ),
                strategy=STRATEGY_NAME,
            ))
    return signals


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    import datetime as _dt
    is_weekend = _dt.datetime.utcnow().weekday() >= 5
    conf_bump = float(profile_config.get("risk_overlay", {}).get("weekend_confidence_boost", 0.05)) if is_weekend else 0.0

    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", [f"{s}/USD" for s in LIVE_UNIVERSE]) if isinstance(universe, dict) else [f"{s}/USD" for s in LIVE_UNIVERSE]

    # Try live funding data first
    live_signals = _get_live_funding_signals(conf_bump)
    if live_signals:
        return live_signals

    # Fall back to OHLCV proxy for full universe
    return _get_proxy_signals(bars, symbols, conf_bump)


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Funding Rate Arb"
    base = symbol.split("/")[0]

    try:
        from app.db.session import SessionLocal
        from app.services.onchain_ingest import get_latest_metric
        db = SessionLocal()
        try:
            rate = get_latest_metric(db, base, "funding_rate", "coinglass")
        finally:
            db.close()
        if rate is not None:
            fired_long  = rate < FUNDING_LONG_THRESHOLD
            fired_short = rate > FUNDING_SHORT_THRESHOLD
            fired = fired_long or fired_short
            side = "buy" if fired_long else ("sell" if fired_short else None)
            score = 0.0
            if fired_long:
                score = round(min(0.85, 0.58 + abs(rate - FUNDING_LONG_THRESHOLD) * 600), 4)
            elif fired_short:
                score = round(min(0.80, 0.55 + abs(rate - FUNDING_SHORT_THRESHOLD) * 600), 4)
            return {
                "name": display_name, "key": STRATEGY_NAME,
                "fired": fired, "side": side, "score": score,
                "summary": (
                    f"Live funding {rate * 100:.3f}% — "
                    + ("crowded shorts → long" if fired_long else
                       "crowded longs → short" if fired_short else
                       "rate within neutral band")
                ),
                "conditions": [{
                    "name": "Perpetual funding rate",
                    "current_value": round(rate * 100, 4),
                    "operator": f"< {FUNDING_LONG_THRESHOLD * 100:.3f}% or > {FUNDING_SHORT_THRESHOLD * 100:.3f}%",
                    "required_value": f"±{FUNDING_SHORT_THRESHOLD * 100:.3f}%",
                    "unit": "%",
                    "passed": fired,
                    "to_pass": f"Currently {rate * 100:.3f}%",
                }],
            }
    except Exception:
        pass

    # Proxy trace
    if len(symbol_bars) < PROXY_MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "Insufficient bars for proxy", "conditions": []}
    window = symbol_bars[-PROXY_LOOKBACK:] if len(symbol_bars) >= PROXY_LOOKBACK else symbol_bars
    bull_bars = sum(1 for b in window if b["c"] >= b["o"])
    bull_ratio = bull_bars / len(window)
    fired_short = bull_ratio >= PROXY_BULL_RATIO_HIGH
    fired_long  = bull_ratio <= PROXY_BULL_RATIO_LOW
    fired = fired_long or fired_short
    score = 0.0
    if fired_short:
        score = round(min(0.72, 0.52 + (bull_ratio - PROXY_BULL_RATIO_HIGH) * 2.0), 4)
    elif fired_long:
        score = round(min(0.72, 0.52 + (PROXY_BULL_RATIO_LOW - bull_ratio) * 2.0), 4)
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "sell" if fired_short else ("buy" if fired_long else None),
        "score": score,
        "summary": (
            f"Proxy: {bull_ratio:.0%} bullish bars — "
            + ("implied crowded longs → short" if fired_short else
               "implied crowded shorts → long" if fired_long else
               "positioning neutral")
        ),
        "conditions": [{
            "name": f"Bull bar ratio (last {len(window)} bars)",
            "current_value": round(bull_ratio, 3),
            "operator": f">= {PROXY_BULL_RATIO_HIGH} or <= {PROXY_BULL_RATIO_LOW}",
            "required_value": f"{PROXY_BULL_RATIO_LOW}–{PROXY_BULL_RATIO_HIGH}",
            "unit": "",
            "passed": fired,
            "to_pass": f"Currently {bull_ratio:.0%}",
        }],
    }
