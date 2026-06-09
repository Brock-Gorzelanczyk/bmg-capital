"""
Crypto Quant Aggressive — S6: Orderflow Imbalance

Measures cumulative volume-weighted delta (buy pressure vs. sell pressure) across
recent bars. When buyers or sellers dominate the tape by a significant margin the
imbalance is likely to continue for at least one more bar.

Bar delta proxy: (close - open) / max(high - low, ε) × volume  →  signed "money flow"
Cumulative delta over the lookback divided by total volume = imbalance ratio ∈ [-1, 1]

Entry:
  imbalance_ratio >  THRESHOLD → long  (buyers crushing sellers)
  imbalance_ratio < -THRESHOLD → short (sellers crushing buyers)

Exit: profile stop/take-profit (hold_max_hours=8 time-stop).
Bars: 5m (after crypto_quant_aggressive scan_timeframe tuning).
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_orderflow_imbalance"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

IMBALANCE_LOOKBACK = 24   # bars (24 × 5m = 2 hours of flow)
IMBALANCE_THRESHOLD = 0.30  # 30% of volume on one side
MIN_VOLUME_BARS = 16


def _cumulative_delta(bars: list[dict], lookback: int) -> tuple[float, float]:
    """Compute cumulative signed delta and total volume over lookback bars."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    cum_delta = 0.0
    cum_vol = 0.0
    for b in window:
        body = b["c"] - b["o"]
        range_ = max(b["h"] - b["l"], b["c"] * 1e-6)
        bar_vol = b["v"]
        signed_flow = (body / range_) * bar_vol
        cum_delta += signed_flow
        cum_vol += bar_vol
    return cum_delta, cum_vol


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    signals: list[Signal] = []
    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", UNIVERSE) if isinstance(universe, dict) else UNIVERSE

    import datetime as _dt
    is_weekend = _dt.datetime.utcnow().weekday() >= 5
    conf_bump = float(profile_config.get("risk_overlay", {}).get("weekend_confidence_boost", 0.05)) if is_weekend else 0.0

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < MIN_VOLUME_BARS:
            continue

        cum_delta, cum_vol = _cumulative_delta(symbol_bars, IMBALANCE_LOOKBACK)
        if cum_vol <= 0:
            continue

        imbalance = cum_delta / cum_vol  # ∈ [-1, 1]
        current_close = symbol_bars[-1]["c"]
        if current_close <= 0:
            continue

        abs_imb = abs(imbalance)
        if abs_imb < IMBALANCE_THRESHOLD:
            continue

        side = "buy" if imbalance > 0 else "sell"
        excess = abs_imb - IMBALANCE_THRESHOLD
        raw_conf = min(0.9, 0.50 + excess * 1.8)
        confidence = min(0.9, raw_conf + conf_bump)

        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=round(confidence, 3),
            size_hint=min(1.0, confidence),
            reason=(
                f"ORDERFLOW_IMBALANCE {side.upper()}: 2h cumulative delta ratio "
                f"{imbalance:+.3f} (threshold ±{IMBALANCE_THRESHOLD}), "
                f"buyers {'dominating' if side == 'buy' else 'absent'} at "
                f"${current_close:,.4f}"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Orderflow Imbalance"

    if len(symbol_bars) < MIN_VOLUME_BARS:
        return {
            "name": display_name, "key": STRATEGY_NAME,
            "fired": False, "side": None, "score": 0.0,
            "summary": f"Insufficient bars ({len(symbol_bars)}, need {MIN_VOLUME_BARS})",
            "conditions": [],
        }

    cum_delta, cum_vol = _cumulative_delta(symbol_bars, IMBALANCE_LOOKBACK)
    if cum_vol <= 0:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "No volume data", "conditions": []}

    imbalance = cum_delta / cum_vol
    abs_imb = abs(imbalance)
    imb_ok = abs_imb >= IMBALANCE_THRESHOLD
    side = "buy" if imbalance > 0 else "sell"

    cond = {
        "name": f"2h cumulative volume-delta imbalance ratio",
        "current_value": round(imbalance, 4),
        "operator": ">= threshold" if imbalance > 0 else "<= -threshold",
        "required_value": IMBALANCE_THRESHOLD,
        "unit": "",
        "passed": imb_ok,
        "to_pass": (
            f"Imbalance met ({imbalance:+.3f})"
            if imb_ok else
            f"Needs ±{IMBALANCE_THRESHOLD} — currently {imbalance:+.3f} "
            f"({(IMBALANCE_THRESHOLD - abs_imb) / IMBALANCE_THRESHOLD * 100:.0f}% short)"
        ),
    }

    fired = imb_ok
    score = round(min(0.9, 0.50 + max(0, abs_imb - IMBALANCE_THRESHOLD) * 1.8), 4) if fired else 0.0
    summary = (
        f"{'Long' if side == 'buy' else 'Short'} imbalance triggered — {imbalance:+.3f} ratio"
        if fired else
        f"Flow balanced ({imbalance:+.3f}), needs ±{IMBALANCE_THRESHOLD}"
    )

    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": side if fired else None, "score": score,
        "summary": summary, "conditions": [cond],
    }
