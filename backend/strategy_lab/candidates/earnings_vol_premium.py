"""
CANDIDATE — not scheduled. Iron condor 7 days before earnings,
filtered by IV rank + implied move richness.
Reference: Augustin, Brenner, Subrahmanyam (2014) on earnings IV mean reversion.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "name": "Earnings Vol Premium",
    "asset_class": "equity",
    "style": "short_volatility",
    "data_source": "yfinance+tradier_optional",
    "expected_sharpe": "1.0-1.6 filtered (0.4 blind)",
    "academic_refs": ["Augustin et al. (2014)"],
    "promotion_minimum_paper_trades": 30,
    "promotion_minimum_days_observed": 60,
}

STRATEGY_NAME = "earnings_vol_premium"
DAYS_AHEAD_WINDOW = 7
MIN_IMPLIED_MOVE_PCT = 0.05
MIN_IV_RANK = 0.70
MIN_STOCK_PRICE = 20.0
WING_MULTIPLIER = 1.5


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    import yfinance as yf

    signals = []
    today = datetime.now().date()
    window_end = today + timedelta(days=DAYS_AHEAD_WINDOW)

    for symbol, bar_list in bars.items():
        try:
            ticker = yf.Ticker(symbol)
            earnings_dates = ticker.earnings_dates
            if earnings_dates is None or len(earnings_dates) == 0:
                continue
            upcoming = [d for d in earnings_dates.index if today <= d.date() <= window_end]
            if not upcoming:
                continue
            earnings_date = upcoming[0].date()

            closes = [float(b.get("c", 0) or 0) for b in bar_list if b.get("c")]
            if not closes or closes[-1] < MIN_STOCK_PRICE:
                continue
            spot = closes[-1]

            expiry, iv_rank, implied_move = _estimate_options(ticker, spot, earnings_date)
            if expiry is None or iv_rank < MIN_IV_RANK or implied_move < MIN_IMPLIED_MOVE_PCT:
                continue

            short_call = round(spot * (1 + implied_move), 1)
            short_put = round(spot * (1 - implied_move), 1)
            long_call = round(spot * (1 + implied_move * WING_MULTIPLIER), 1)
            long_put = round(spot * (1 - implied_move * WING_MULTIPLIER), 1)

            metadata = json.dumps({
                "setup": "earnings_iron_condor",
                "earnings_date": str(earnings_date),
                "expiry": str(expiry),
                "short_call_strike": short_call,
                "long_call_strike": long_call,
                "short_put_strike": short_put,
                "long_put_strike": long_put,
                "implied_move_pct": round(implied_move, 4),
                "iv_rank": round(iv_rank, 3),
                "spot": spot,
            })
            confidence = min(0.85, 0.60 + (iv_rank - MIN_IV_RANK) * 0.5
                             + max(0.0, implied_move - 0.05) * 2.0)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=confidence,
                size_hint=0.025, reason=metadata, strategy=STRATEGY_NAME,
            ))
        except Exception as exc:
            logger.debug("earnings_vol %s: %s", symbol, exc)
            continue
    return signals


def _estimate_options(ticker, spot: float, earnings_date) -> tuple:
    from datetime import date
    try:
        expirations = ticker.options
        if not expirations:
            return None, None, None
        targets = [e for e in expirations if date.fromisoformat(e) > earnings_date]
        if not targets:
            return None, None, None
        expiry = targets[0]
        opt = ticker.option_chain(expiry)
        atm_call = opt.calls.iloc[(opt.calls["strike"] - spot).abs().argsort()[:1]]
        atm_put = opt.puts.iloc[(opt.puts["strike"] - spot).abs().argsort()[:1]]
        if atm_call.empty or atm_put.empty:
            return None, None, None
        call_ask = float(atm_call["ask"].values[0])
        put_ask = float(atm_put["ask"].values[0])
        if call_ask <= 0 or put_ask <= 0:
            return None, None, None
        implied_move = (call_ask + put_ask) / spot
        atm_iv = float(atm_call["impliedVolatility"].values[0])
        iv_rank = min(1.0, atm_iv / 0.6)
        return expiry, iv_rank, implied_move
    except Exception:
        return None, None, None
