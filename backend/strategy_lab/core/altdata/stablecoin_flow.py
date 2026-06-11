"""
Stablecoin Flow & Dominance Signal.

Tracks stablecoin market dominance as a crypto risk-on/risk-off indicator.
High stablecoin dominance (>15%) indicates capital sitting on the sidelines
(risk-off). Low dominance (<10%) indicates capital deployed into crypto (risk-on).

Also tracks USDC supply changes as a leading indicator of institutional
on-ramps: rapid minting is bullish, rapid burning is bearish.

Data sources:
  - DeFiLlama /stablecoins (total market cap breakdown)
  - DeFiLlama stablecoin charts (USDC supply time-series)
  - CoinGecko /global (total crypto market cap for dominance calculation)

Cache TTLs: dominance 1 hour, USDC supply 4 hours.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Caches ────────────────────────────────────────────────────────────────────

_dom_cache: dict = {"result": None, "fetched_at": 0.0, "ttl": 3600}
_usdc_cache: dict = {"result": None, "fetched_at": 0.0, "ttl": 14400}

_NEUTRAL_DOMINANCE: dict = {
    "dominance_pct": 12.0,
    "regime": "neutral",
    "size_multiplier": 1.0,
    "7d_change_pct": 0.0,
}

_NEUTRAL_USDC: dict = {
    "supply_change_usd": 0.0,
    "change_pct": 0.0,
    "signal": "neutral",
}


# ── Stablecoin dominance ──────────────────────────────────────────────────────

def _fetch_defi_llama_stablecoins() -> Optional[float]:
    """
    Fetch total stablecoin market cap from DeFiLlama.
    Returns total USD value of all stablecoins.
    """
    try:
        resp = requests.get(
            "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            timeout=12,
        )
        if resp.status_code != 200:
            logger.warning("[stablecoin_flow] DeFiLlama stablecoins returned %d", resp.status_code)
            return None
        data = resp.json()
        pegs = data.get("peggedAssets", [])
        total = 0.0
        for asset in pegs:
            circulating = asset.get("circulating", {})
            usd = circulating.get("peggedUSD", 0.0)
            if usd:
                try:
                    total += float(usd)
                except (TypeError, ValueError):
                    pass
        return total if total > 0 else None
    except Exception as exc:
        logger.warning("[stablecoin_flow] DeFiLlama stablecoins fetch failed: %s", exc)
        return None


def _fetch_total_crypto_market_cap() -> Optional[float]:
    """Fetch total crypto market cap from CoinGecko /global."""
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("[stablecoin_flow] CoinGecko /global returned %d", resp.status_code)
            return None
        data = resp.json()
        mcap = data.get("data", {}).get("total_market_cap", {}).get("usd")
        return float(mcap) if mcap else None
    except Exception as exc:
        logger.warning("[stablecoin_flow] CoinGecko market cap fetch failed: %s", exc)
        return None


def _regime_from_dominance(pct: float) -> tuple[str, float]:
    """Returns (regime_label, size_multiplier)."""
    if pct > 15.0:
        return "risk_off", 0.8
    if pct >= 10.0:
        return "neutral", 1.0
    return "risk_on", 1.1


def get_stablecoin_dominance() -> dict:
    """
    Compute stablecoin dominance as % of total crypto market cap.

    Returns
    -------
    dict with keys:
        dominance_pct   : float (stablecoin % of total crypto market cap)
        regime          : "risk_off" | "neutral" | "risk_on"
        size_multiplier : float 0.8-1.1
        7d_change_pct   : float (dominance change over last 7 days; 0.0 if unavailable)
    On failure: neutral defaults.
    """
    now_ts = time.monotonic()

    if _dom_cache["result"] is not None and (now_ts - _dom_cache["fetched_at"]) < _dom_cache["ttl"]:
        return _dom_cache["result"]

    try:
        stable_mcap = _fetch_defi_llama_stablecoins()
        total_mcap = _fetch_total_crypto_market_cap()

        if stable_mcap is None or total_mcap is None or total_mcap <= 0:
            logger.warning("[stablecoin_flow] Could not compute dominance; using neutral")
            result = dict(_NEUTRAL_DOMINANCE)
        else:
            dominance_pct = round((stable_mcap / total_mcap) * 100.0, 2)
            regime, multiplier = _regime_from_dominance(dominance_pct)
            result = {
                "dominance_pct": dominance_pct,
                "regime": regime,
                "size_multiplier": multiplier,
                "7d_change_pct": 0.0,  # Would require time-series history; stub for now
            }
            logger.info(
                "[stablecoin_flow] dominance=%.1f%% regime=%s mult=%.2f",
                dominance_pct, regime, multiplier,
            )

        _dom_cache["result"] = result
        _dom_cache["fetched_at"] = now_ts
        return result

    except Exception as exc:
        logger.warning("[stablecoin_flow] get_stablecoin_dominance failed: %s", exc)
        return dict(_NEUTRAL_DOMINANCE)


# ── USDC supply change ────────────────────────────────────────────────────────

_USDC_LLAMA_ID = "USDC"  # DeFiLlama stablecoin name for USDC


def _fetch_usdc_supply_history(days: int = 14) -> list[float]:
    """
    Fetch USDC circulating supply time-series from DeFiLlama.
    Returns list of daily USD supply values, oldest first.
    """
    try:
        # DeFiLlama stablecoin chart endpoint
        resp = requests.get(
            "https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1",
            timeout=12,
        )
        if resp.status_code != 200:
            logger.warning("[stablecoin_flow] DeFiLlama USDC chart returned %d", resp.status_code)
            return []
        data = resp.json()
        # Response is a list of {date, totalCirculating: {peggedUSD: ...}, ...}
        if not isinstance(data, list):
            return []
        # Get last (days+2) entries to compute change
        entries = data[-(days + 2):]
        supply_values = []
        for entry in entries:
            circ = entry.get("totalCirculating", {})
            usd = circ.get("peggedUSD", 0.0)
            try:
                supply_values.append(float(usd))
            except (TypeError, ValueError):
                pass
        return supply_values
    except Exception as exc:
        logger.warning("[stablecoin_flow] USDC supply history fetch failed: %s", exc)
        return []


def get_usdc_supply_change(days: int = 7) -> dict:
    """
    Compute USDC supply change over the last `days` trading days.

    Parameters
    ----------
    days : lookback window (default 7)

    Returns
    -------
    dict with keys:
        supply_change_usd : float (positive = minting, negative = burning)
        change_pct        : float
        signal            : "bullish_mint" | "neutral" | "bearish_burn"
    On failure: neutral defaults.
    """
    now_ts = time.monotonic()

    if _usdc_cache["result"] is not None and (now_ts - _usdc_cache["fetched_at"]) < _usdc_cache["ttl"]:
        return _usdc_cache["result"]

    try:
        supply_history = _fetch_usdc_supply_history(days=days)

        if len(supply_history) < 2:
            logger.warning("[stablecoin_flow] Insufficient USDC supply data; using neutral")
            result = dict(_NEUTRAL_USDC)
        else:
            supply_old = supply_history[0]
            supply_new = supply_history[-1]
            supply_change_usd = supply_new - supply_old
            change_pct = (
                round((supply_change_usd / supply_old) * 100.0, 3) if supply_old > 0 else 0.0
            )

            if change_pct > 2.0:
                signal = "bullish_mint"
            elif change_pct < -2.0:
                signal = "bearish_burn"
            else:
                signal = "neutral"

            result = {
                "supply_change_usd": round(supply_change_usd, 0),
                "change_pct": change_pct,
                "signal": signal,
            }
            logger.info(
                "[stablecoin_flow] USDC supply change=%.2f%% signal=%s",
                change_pct, signal,
            )

        _usdc_cache["result"] = result
        _usdc_cache["fetched_at"] = now_ts
        return result

    except Exception as exc:
        logger.warning("[stablecoin_flow] get_usdc_supply_change failed: %s", exc)
        return dict(_NEUTRAL_USDC)
