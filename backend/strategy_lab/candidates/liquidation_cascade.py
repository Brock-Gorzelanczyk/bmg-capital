"""
CANDIDATE — not scheduled. Graduate manually after paper trading.
Strategy: Liquidation Cascade Predictor (Ride + Fade Modes)

Alpha source: Perpetual futures liquidation clusters create predictable
price momentum (cascade ride) and mechanical overshoots that revert
(cascade fade). Coinglass heatmap data identifies cluster locations.

Timeframe: 5-minute bars (compatible with crypto_quant_aggressive profile)
Hold time: Ride = 5-30 minutes | Fade = 10-60 minutes

Academic foundation: Forced liquidation mechanics in leveraged markets.
Practitioners: documented in Coinglass research blog 2021-2024.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "liquidation_cascade"

UNIVERSE = ["BTC", "ETH", "SOL"]
MODE = "both"  # "ride" | "fade" | "both"

RIDE_CLUSTER_PROXIMITY_PCT = 0.008
RIDE_MIN_CLUSTER_DENSITY = 1.5
RIDE_STOP_PCT = 0.010
RIDE_TARGET_PCT = 0.025
RIDE_CONFIDENCE = 0.62

FADE_MIN_MOVE_PCT = 0.025
FADE_LIQUIDATION_DECEL = True
FADE_STOP_PCT = 0.015
FADE_TARGET_PCT = 0.018
FADE_CONFIDENCE = 0.58
FADE_MAX_HOLD_MINUTES = 45

MIN_OI_THRESHOLD_BTC = 8_000_000_000

HIGH_VOLATILITY_SUSPEND = True

# Module-level caches
_HEATMAP_CACHE: dict = {}   # {symbol: {"data": dict, "fetched_at": float}}
_OI_CACHE: dict = {}        # {symbol: {"data": dict, "fetched_at": float}}
_LIQ_CACHE: dict = {}       # {symbol: {"data": dict, "fetched_at": float}}
_OPEN_CASCADE_POSITIONS: dict = {}  # {symbol: {"entry_time": float, "side": str}}

_HEATMAP_TTL = 600   # 10 minutes
_OI_TTL = 300        # 5 minutes


# ── Data helpers ──────────────────────────────────────────────────────────────

def _fetch_coinglass_liquidation_heatmap(symbol: str) -> dict | None:
    """
    Fetch liquidation heatmap / open interest concentration from Coinglass.
    Uses COINGLASS_API_KEY env var and coinglassSecret header —
    same pattern as crypto_cycle_detector._fetch_funding_rate_coinglass.

    Parses available data into:
        {"price_levels": [{"price": float, "long_liq_usd": float,
                           "short_liq_usd": float, "total_liq_usd": float,
                           "density_vs_avg": float}]}

    Falls back to open interest by price level as proxy when heatmap
    endpoint is not available. Caches 10 minutes. Returns None on failure.
    """
    now = time.monotonic()
    cached = _HEATMAP_CACHE.get(symbol)
    if cached and (now - cached["fetched_at"]) < _HEATMAP_TTL:
        return cached["data"]

    try:
        api_key = os.getenv("COINGLASS_API_KEY", "")
        if not api_key:
            _HEATMAP_CACHE[symbol] = {"data": None, "fetched_at": now}
            return None

        # Try liquidation heatmap endpoint first
        url = "https://open-api.coinglass.com/public/v2/liquidation_heatmap"
        headers = {"coinglassSecret": api_key}
        params = {"symbol": symbol, "timeframe": "1h"}
        resp = requests.get(url, headers=headers, params=params, timeout=8)

        if resp.status_code == 200:
            raw = resp.json()
            levels_raw = raw.get("data", {}).get("priceLevels", raw.get("data", []))
            if levels_raw:
                levels = _parse_heatmap_levels(levels_raw)
                result = {"price_levels": levels}
                _HEATMAP_CACHE[symbol] = {"data": result, "fetched_at": now}
                return result

        # Fallback: open interest by price level as proxy
        url_oi = "https://open-api.coinglass.com/public/v2/openInterest/liquidation_ex"
        resp2 = requests.get(url_oi, headers=headers, params={"symbol": symbol}, timeout=8)
        if resp2.status_code == 200:
            raw2 = resp2.json()
            levels_raw2 = raw2.get("data", [])
            if levels_raw2:
                levels = _parse_heatmap_levels(levels_raw2)
                result = {"price_levels": levels}
                _HEATMAP_CACHE[symbol] = {"data": result, "fetched_at": now}
                return result

        _HEATMAP_CACHE[symbol] = {"data": None, "fetched_at": now}
        return None

    except Exception as exc:
        logger.debug("[liquidation_cascade] heatmap fetch error for %s: %s", symbol, exc)
        _HEATMAP_CACHE[symbol] = {"data": None, "fetched_at": now}
        return None


def _parse_heatmap_levels(levels_raw: list) -> list[dict]:
    """
    Normalise raw Coinglass heatmap rows into a uniform list.
    Computes density_vs_avg = level_total / mean_total across all levels.
    """
    parsed: list[dict] = []
    for row in levels_raw:
        try:
            price = float(row.get("price", row.get("liqPrice", 0)))
            long_liq = float(row.get("longLiqUsd", row.get("buyLiqUsd", 0)))
            short_liq = float(row.get("shortLiqUsd", row.get("sellLiqUsd", 0)))
            total_liq = long_liq + short_liq or float(row.get("totalLiqUsd", 0))
            if price > 0:
                parsed.append({
                    "price": price,
                    "long_liq_usd": long_liq,
                    "short_liq_usd": short_liq,
                    "total_liq_usd": total_liq,
                    "density_vs_avg": 0.0,  # filled below
                })
        except Exception:
            continue

    if not parsed:
        return parsed

    avg_total = sum(lv["total_liq_usd"] for lv in parsed) / len(parsed)
    if avg_total > 0:
        for lv in parsed:
            lv["density_vs_avg"] = round(lv["total_liq_usd"] / avg_total, 4)

    return parsed


def _fetch_binance_liquidations_realtime(symbol: str) -> dict:
    """
    Fetch last 10 minutes of forced orders (liquidations) from Binance futures.
    Returns:
        {
            "total_liq_usd_10min": float,
            "liq_volume_trend": str,   # "accelerating" | "decelerating" | "stable"
            "dominant_side": str,      # "long" | "short" | "mixed"
            "largest_single_liq_usd": float,
        }
    On failure returns safe defaults so callers never need to guard for None.
    """
    _safe = {
        "total_liq_usd_10min": 0.0,
        "liq_volume_trend": "stable",
        "dominant_side": "mixed",
        "largest_single_liq_usd": 0.0,
    }
    try:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - 10 * 60 * 1000  # 10 minutes ago

        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/forceOrders",
            params={"symbol": f"{symbol}USDT", "limit": 50, "startTime": start_ms},
            timeout=8,
        )
        if resp.status_code != 200:
            logger.debug("[liquidation_cascade] forceOrders %d for %s", resp.status_code, symbol)
            return _safe

        orders = resp.json()
        if not orders or not isinstance(orders, list):
            return _safe

        total_usd = 0.0
        largest_usd = 0.0
        long_usd = 0.0
        short_usd = 0.0
        half = len(orders) // 2 or 1
        first_half_usd = 0.0
        second_half_usd = 0.0

        for i, o in enumerate(orders):
            try:
                qty = float(o.get("origQty", 0))
                price = float(o.get("price", 0))
                usd_val = qty * price
                total_usd += usd_val
                largest_usd = max(largest_usd, usd_val)
                side = o.get("side", "").upper()
                if side == "SELL":
                    long_usd += usd_val   # SELL order closes a long (long liquidated)
                else:
                    short_usd += usd_val  # BUY order closes a short
                if i < half:
                    first_half_usd += usd_val
                else:
                    second_half_usd += usd_val
            except Exception:
                continue

        if first_half_usd > 0 and second_half_usd > 0:
            ratio = second_half_usd / first_half_usd
            if ratio >= 1.2:
                trend = "accelerating"
            elif ratio < 0.8:
                trend = "decelerating"
            else:
                trend = "stable"
        else:
            trend = "stable"

        dominant = "long" if long_usd > short_usd * 1.2 else (
            "short" if short_usd > long_usd * 1.2 else "mixed"
        )

        return {
            "total_liq_usd_10min": total_usd,
            "liq_volume_trend": trend,
            "dominant_side": dominant,
            "largest_single_liq_usd": largest_usd,
        }

    except Exception as exc:
        logger.debug("[liquidation_cascade] realtime liq error for %s: %s", symbol, exc)
        return _safe


def _fetch_open_interest(symbol: str) -> dict:
    """
    Fetch current open interest from Binance futures.
    Returns {"oi_usd": float, "above_threshold": bool}.
    For BTC: above_threshold = oi_usd > MIN_OI_THRESHOLD_BTC.
    Other symbols: always above_threshold=True (no symbol-specific threshold).
    Caches 5 minutes. Fails open (above_threshold=True) on any error.
    """
    _fail_open = {"oi_usd": 0, "above_threshold": True}
    now = time.monotonic()
    cached = _OI_CACHE.get(symbol)
    if cached and (now - cached["fetched_at"]) < _OI_TTL:
        return cached["data"]

    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": f"{symbol}USDT"},
            timeout=8,
        )
        if resp.status_code != 200:
            logger.debug("[liquidation_cascade] OI %d for %s", resp.status_code, symbol)
            _OI_CACHE[symbol] = {"data": _fail_open, "fetched_at": now}
            return _fail_open

        data = resp.json()
        oi_qty = float(data.get("openInterest", 0))
        # openInterest is in base asset (e.g. BTC); approximate USD by fetching last price
        # Use markPrice endpoint as proxy for current price
        mark_resp = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": f"{symbol}USDT"},
            timeout=5,
        )
        if mark_resp.status_code == 200:
            mark_price = float(mark_resp.json().get("markPrice", 0))
        else:
            mark_price = 0.0

        oi_usd = oi_qty * mark_price if mark_price > 0 else 0.0

        if symbol == "BTC":
            above_threshold = oi_usd > MIN_OI_THRESHOLD_BTC
        else:
            above_threshold = True

        result = {"oi_usd": oi_usd, "above_threshold": above_threshold}
        _OI_CACHE[symbol] = {"data": result, "fetched_at": now}
        return result

    except Exception as exc:
        logger.debug("[liquidation_cascade] OI fetch error for %s: %s", symbol, exc)
        _OI_CACHE[symbol] = {"data": _fail_open, "fetched_at": now}
        return _fail_open


# ── Main signal generator ─────────────────────────────────────────────────────

def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """
    Scan UNIVERSE for liquidation cascade setups and emit ride/fade signals.
    See module docstring for hold times and paper-trading guidance.
    """
    signals_by_symbol: dict[str, Signal] = {}
    now = time.time()
    now_dt = datetime.now(timezone.utc)

    # ── STEP 0: Regime gates ──────────────────────────────────────────────────
    if regime.get("vix_regime") == "panic":
        logger.debug("[liquidation_cascade] vix_regime=panic — skipping")
        return []

    current_cycle_phase: str | None = None
    try:
        from strategy_lab.core.crypto_signal_aggregator import get_crypto_regime_snapshot
        current_cycle_phase = get_crypto_regime_snapshot().get("cycle_phase")
        if current_cycle_phase == "bear":
            logger.debug("[liquidation_cascade] cycle_phase=bear — skipping")
            return []
    except ImportError:
        pass

    # ── STEP 1: Check time stops on open positions ────────────────────────────
    expired_syms = [
        sym for sym, pos in list(_OPEN_CASCADE_POSITIONS.items())
        if pos["entry_time"] + FADE_MAX_HOLD_MINUTES * 60 < now
    ]
    for sym in expired_syms:
        pos = _OPEN_CASCADE_POSITIONS.pop(sym, None)
        if pos:
            close_side = "sell" if pos["side"] == "buy" else "buy"
            signals_by_symbol[f"{sym}_close"] = Signal(
                symbol=f"{sym}-USD",
                side=close_side,
                confidence=0.75,
                size_hint=0.30,
                reason=f"cascade_time_stop_{sym}_max_{FADE_MAX_HOLD_MINUTES}min_elapsed",
                strategy=STRATEGY_NAME,
            )
            logger.info("[liquidation_cascade] time stop triggered for %s", sym)

    # ── STEP 2: Iterate over universe ─────────────────────────────────────────
    for symbol in UNIVERSE:
        oi_data = _fetch_open_interest(symbol)
        if not oi_data["above_threshold"]:
            logger.debug("[liquidation_cascade] %s OI below threshold — skip", symbol)
            continue

        current_bars = bars.get(f"{symbol}-USD", bars.get(f"{symbol}/USDT", []))
        if len(current_bars) < 10:
            continue

        current_price = float(current_bars[-1]["c"])
        if current_price <= 0:
            continue

        ride_signal: Signal | None = None
        fade_signal: Signal | None = None

        # ── STEP 3: RIDE MODE ─────────────────────────────────────────────────
        if MODE in ("ride", "both"):
            heatmap = _fetch_coinglass_liquidation_heatmap(symbol)
            liq_rt = _fetch_binance_liquidations_realtime(symbol)

            if heatmap and heatmap.get("price_levels"):
                # Find the nearest dense cluster
                best_cluster: dict | None = None
                best_dist = float("inf")

                for level in heatmap["price_levels"]:
                    if level["density_vs_avg"] < RIDE_MIN_CLUSTER_DENSITY:
                        continue
                    dist = abs(current_price - level["price"]) / current_price
                    if dist < best_dist:
                        best_dist = dist
                        best_cluster = level

                if best_cluster and best_dist <= RIDE_CLUSTER_PROXIMITY_PCT:
                    cluster_price = best_cluster["price"]
                    direction = "sell" if cluster_price < current_price else "buy"

                    # Momentum confirmation
                    bar_momentum = (
                        float(current_bars[-1]["c"]) - float(current_bars[-3]["c"])
                    ) / float(current_bars[-3]["c"])

                    momentum_ok = True
                    if direction == "sell" and bar_momentum >= 0:
                        momentum_ok = False
                    elif direction == "buy" and bar_momentum <= 0:
                        momentum_ok = False

                    if momentum_ok:
                        conf = RIDE_CONFIDENCE
                        if liq_rt["liq_volume_trend"] == "accelerating":
                            conf = min(0.85, conf + 0.05)

                        ride_signal = Signal(
                            symbol=f"{symbol}-USD",
                            side=direction,
                            confidence=round(conf, 3),
                            size_hint=0.35,
                            reason=(
                                f"cascade_ride_{direction}_{symbol}_cluster_dist_{best_dist:.3f}"
                                f"_liq_{liq_rt['total_liq_usd_10min']:,.0f}"
                            ),
                            strategy=STRATEGY_NAME,
                        )

        # ── STEP 4: FADE MODE ─────────────────────────────────────────────────
        if MODE in ("fade", "both"):
            if len(current_bars) >= 6:
                last_6 = current_bars[-6:]
                recent_high = max(float(b["h"]) for b in last_6)
                recent_low = min(float(b["l"]) for b in last_6)
                recent_range_pct = (recent_high - recent_low) / recent_low if recent_low > 0 else 0.0

                if recent_range_pct >= FADE_MIN_MOVE_PCT:
                    cascade_open = float(current_bars[-6]["o"])
                    cascade_direction = "down" if current_price < cascade_open else "up"
                    cascade_magnitude = abs(current_price - cascade_open) / cascade_open

                    # Reuse liq_rt from ride or fetch fresh
                    try:
                        liq_rt_fade = liq_rt  # type: ignore[name-defined]
                    except NameError:
                        liq_rt_fade = _fetch_binance_liquidations_realtime(symbol)

                    if (
                        liq_rt_fade["liq_volume_trend"] == "decelerating"
                        and liq_rt_fade["total_liq_usd_10min"] > 500_000
                    ):
                        fade_side = "buy" if cascade_direction == "down" else "sell"
                        conf = min(0.75, FADE_CONFIDENCE + (cascade_magnitude * 2))

                        fade_signal = Signal(
                            symbol=f"{symbol}-USD",
                            side=fade_side,
                            confidence=round(conf, 3),
                            size_hint=0.30,
                            reason=(
                                f"cascade_fade_{fade_side}_{symbol}_cascade_{cascade_magnitude:.1%}"
                                f"_liq_decel_{liq_rt_fade['liq_volume_trend']}"
                            ),
                            strategy=STRATEGY_NAME,
                        )

        # ── STEP 5: Dedup — keep higher confidence if both fired ──────────────
        chosen: Signal | None = None
        if ride_signal and fade_signal:
            chosen = ride_signal if ride_signal.confidence >= fade_signal.confidence else fade_signal
        elif ride_signal:
            chosen = ride_signal
        elif fade_signal:
            chosen = fade_signal

        if chosen:
            signals_by_symbol[symbol] = chosen

    # ── STEP 6: Track new signals in OPEN_CASCADE_POSITIONS ──────────────────
    final_signals: list[Signal] = list(signals_by_symbol.values())
    for sym, sig in signals_by_symbol.items():
        if "_close" not in sym:
            _OPEN_CASCADE_POSITIONS[sym] = {
                "entry_time": now,
                "side": sig.side,
            }

    return final_signals
