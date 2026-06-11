"""
CANDIDATE — not scheduled. Options premium collection filtered by IV Rank.

Enters cash-secured puts or covered calls only when IVR is elevated (>= 50),
ensuring we collect premium when implied vol is rich relative to its history.
Below IVR 30 the position is skipped entirely; 30–49 is half-size.

Reference: Israelov & Nielsen (2014) "Still Not Cheap: Portfolio Protection in
Calm Markets". Expected edge lives in selling expensive implied vol, not cheap.

Promotion gate:
  - Minimum 30 paper trades observed
  - Minimum 60 days in shadow-paper
  - Annualised premium yield >= 12% before cost drag
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from strategy_lab.core.signals import Signal
from strategy_lab.core.regime.regime_router import advisory_vix_scale

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "name": "Options IV Premium Filter",
    "asset_class": "options",
    "style": "short_volatility",
    "data_source": "yfinance",
    "expected_sharpe": "0.7-1.1 with IVR filter (0.2 blind)",
    "academic_refs": ["Israelov & Nielsen (2014)"],
    "promotion_minimum_paper_trades": 30,
    "promotion_minimum_days_observed": 60,
}

STRATEGY_NAME = "options_iv_premium_filter"

# IVR thresholds
IVR_FULL_SIZE = 50    # >= 50: full size_hint
IVR_HALF_SIZE = 30    # 30-49: half size_hint
                      # < 30: skip entirely

# IV Rank lookback window in calendar days used for rank estimation
IVR_LOOKBACK_DAYS = 252

MIN_STOCK_PRICE = 20.0
MIN_OPTION_PREMIUM_PCT = 0.005   # must yield at least 0.5% premium / notional


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    """Scan bars for options-eligible symbols; gate entries on IV Rank."""
    # VIX safety floor — hard kill switch when VIX > 40; never sell premium in crisis
    _vix: float | None = None
    if regime:
        _vix = regime.get("vix_level") or (
            (regime.get("signals_breakdown") or {}).get("vix", {}).get("level")
        )
    if _vix is not None and advisory_vix_scale(float(_vix)) == 0.0:
        logger.warning(
            "[ivr-filter] VIX=%.1f > 40 — crisis kill switch active, returning []", _vix
        )
        return []

    signals = []

    for symbol, bar_list in bars.items():
        try:
            closes = [float(b.get("c", 0) or 0) for b in bar_list if b.get("c")]
            if not closes or closes[-1] < MIN_STOCK_PRICE:
                continue
            spot = closes[-1]

            ivr, atm_iv, expiry = _compute_ivr(symbol, closes)
            if ivr is None:
                # Fail-closed: no IV data → skip symbol, never fall through to full-size
                logger.warning("[ivr-filter] %s: IV data unavailable — skipping (fail-closed)", symbol)
                continue

            size_multiplier = _ivr_size_multiplier(ivr)
            if size_multiplier == 0.0:
                logger.debug("[ivr-filter] %s: IVR=%.0f < %d — skip", symbol, ivr, IVR_HALF_SIZE)
                continue

            # Prefer put side (cash-secured put) in all regimes; covered call if
            # regime is bear_trending to reduce directional risk.
            regime_label = regime.get("regime", "sideways_choppy") if regime else "sideways_choppy"
            side = "sell_put" if regime_label != "bear_trending" else "sell_call"

            metadata = json.dumps({
                "setup": "ivr_premium_filter",
                "ivr": round(ivr, 1),
                "atm_iv": round(atm_iv, 4) if atm_iv else None,
                "expiry": expiry,
                "spot": round(spot, 2),
                "size_multiplier": size_multiplier,
                "regime": regime_label,
            })

            base_confidence = 0.55 + min(0.30, (ivr - IVR_FULL_SIZE) / 100.0)
            signals.append(Signal(
                symbol=symbol,
                side=side,
                confidence=round(base_confidence, 4),
                size_hint=round(0.04 * size_multiplier, 4),
                reason=metadata,
                strategy=STRATEGY_NAME,
            ))

        except Exception as exc:
            logger.debug("[ivr-filter] %s: %s", symbol, exc)
            continue

    return signals


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ivr_size_multiplier(ivr: float) -> float:
    """Map IV Rank to a [0, 1] size multiplier."""
    if ivr >= IVR_FULL_SIZE:
        return 1.0
    if ivr >= IVR_HALF_SIZE:
        return 0.5
    return 0.0


def _compute_ivr(symbol: str, closes: list[float]) -> tuple[float | None, float | None, str | None]:
    """
    Estimate IV Rank from yfinance ATM implied vol.

    Returns (ivr_pct, atm_iv, nearest_expiry_str) or (None, None, None).

    IVR = (current_iv - 52w_low_iv) / (52w_high_iv - 52w_low_iv) * 100

    Since we only have spot IV (not a full IV history), we use a simplified
    proxy: compare current ATM IV against the realised-vol percentile of the
    underlying's own return series. This is an approximation — production
    promotion should replace it with a proper IV history feed.
    """
    import math
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("[ivr-filter] yfinance not available")
        return None, None, None

    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            return None, None, None

        today = datetime.now().date()
        targets = [e for e in expirations
                   if (datetime.strptime(e, "%Y-%m-%d").date() - today).days >= 14]
        if not targets:
            return None, None, None
        expiry = targets[0]

        chain = ticker.option_chain(expiry)
        spot = closes[-1]
        atm_calls = chain.calls.iloc[(chain.calls["strike"] - spot).abs().argsort()[:1]]
        if atm_calls.empty:
            return None, None, None

        atm_iv = float(atm_calls["impliedVolatility"].values[0])
        if math.isnan(atm_iv) or atm_iv <= 0:
            return None, None, None

        # Proxy IVR: position of atm_iv relative to historical realised vol range
        if len(closes) < 20:
            return None, None, None
        returns = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        if len(returns) < 20:
            return None, None, None

        ann_factor = math.sqrt(252)
        windows = [returns[max(0, i - 20):i] for i in range(20, len(returns) + 1)]
        rv_series = [
            ann_factor * math.sqrt(sum(r ** 2 for r in w) / len(w))
            for w in windows
        ]
        rv_low, rv_high = min(rv_series), max(rv_series)
        if rv_high <= rv_low:
            return None, None, None

        # Rank current ATM IV against the RV range as a proxy for IV richness
        ivr = max(0.0, min(100.0, (atm_iv - rv_low) / (rv_high - rv_low) * 100.0))
        return ivr, atm_iv, expiry

    except Exception as exc:
        logger.debug("[ivr-filter] _compute_ivr %s: %s", symbol, exc)
        return None, None, None
