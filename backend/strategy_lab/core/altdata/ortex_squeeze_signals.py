"""
ORTEX Short Squeeze Signals — Weekend 8, Module 22.

Identifies squeeze setups using short interest data:
  - Cost-to-borrow (CTB) spike: > 50% annualized
  - Utilization: > 90% (no shares available to borrow)
  - Short interest as % of float: > 20%
  - Price catalyst: volume > 2× ADV on up day

All four conditions met → high-probability squeeze setup.
Pass to stock_swing + options_directional strategies.

Data: Ortex retail tier (~$80/mo) or FINRA short interest reports (free, biweekly lag).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

CTB_THRESHOLD = 50.0          # % annualized cost to borrow
UTIL_THRESHOLD = 90.0         # % utilization
SI_FLOAT_THRESHOLD = 20.0     # % short interest as % of float
VOLUME_CATALYST_MULT = 2.0    # volume multiplier vs ADV


@dataclass
class ShortData:
    symbol: str
    short_interest_shares: float
    float_shares: float
    short_pct_float: float
    utilization_pct: float
    cost_to_borrow_pct: float   # annualized %
    days_to_cover: float
    updated_at: datetime
    source: str


@dataclass
class SqueezeSetup:
    symbol: str
    ctb_pct: float
    utilization_pct: float
    short_pct_float: float
    has_catalyst: bool
    squeeze_score: int          # 0-4 (one point per condition)
    signal_strength: str        # "extreme" | "high" | "moderate"
    message: str


def _fetch_ortex(symbol: str) -> Optional[ShortData]:
    """
    Fetch short data from Ortex API.
    Requires ORTEX_API_KEY environment variable.
    """
    try:
        import requests
        api_key = os.getenv("ORTEX_API_KEY", "")
        if not api_key:
            return None

        # Ortex API endpoint (actual URL requires subscription)
        url = f"https://api.ortex.com/v1/shorts/live/{symbol}"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return None

        r = resp.json()
        return ShortData(
            symbol=symbol,
            short_interest_shares=float(r.get("short_interest", 0)),
            float_shares=float(r.get("float_shares", 1)),
            short_pct_float=float(r.get("short_pct_float", 0)),
            utilization_pct=float(r.get("utilization", 0)),
            cost_to_borrow_pct=float(r.get("fee_rate", 0)),
            days_to_cover=float(r.get("days_to_cover", 0)),
            updated_at=datetime.now(timezone.utc),
            source="ortex",
        )
    except Exception as exc:
        logger.debug("[ortex] error for %s: %s", symbol, exc)
        return None


def _fetch_finra_biweekly(symbol: str) -> Optional[ShortData]:
    """
    Fetch biweekly FINRA short interest report (free, 2-week lag).
    Not useful for day-of signals but good for trend monitoring.
    """
    try:
        import requests
        # FINRA doesn't provide a clean REST API; typically scraped from
        # https://www.finra.org/investors/learn-to-invest/advanced-investing/short-selling/
        # This is a stub — production uses a FINRA parser or vendor data
        logger.debug("[ortex] FINRA scrape not implemented — returning None for %s", symbol)
        return None
    except Exception as exc:
        logger.debug("[ortex] FINRA error for %s: %s", symbol, exc)
        return None


def detect_squeeze(
    symbol: str,
    current_volume: Optional[float] = None,
    adv: Optional[float] = None,
    day_return_pct: Optional[float] = None,
) -> Optional[SqueezeSetup]:
    """
    Detect squeeze setup for a symbol.

    Parameters
    ----------
    symbol : ticker
    current_volume : today's volume so far
    adv : average daily volume (20-day)
    day_return_pct : today's price change %

    Returns
    -------
    SqueezeSetup if conditions met, else None
    """
    data = _fetch_ortex(symbol)
    if data is None:
        data = _fetch_finra_biweekly(symbol)
    if data is None:
        return None

    score = 0
    conditions = []

    if data.cost_to_borrow_pct >= CTB_THRESHOLD:
        score += 1
        conditions.append(f"CTB={data.cost_to_borrow_pct:.0f}% (threshold: {CTB_THRESHOLD}%)")

    if data.utilization_pct >= UTIL_THRESHOLD:
        score += 1
        conditions.append(f"Util={data.utilization_pct:.0f}% (threshold: {UTIL_THRESHOLD}%)")

    if data.short_pct_float >= SI_FLOAT_THRESHOLD:
        score += 1
        conditions.append(f"SI/Float={data.short_pct_float:.0f}% (threshold: {SI_FLOAT_THRESHOLD}%)")

    has_catalyst = (
        current_volume is not None
        and adv is not None
        and adv > 0
        and current_volume >= adv * VOLUME_CATALYST_MULT
        and (day_return_pct or 0) > 0
    )
    if has_catalyst:
        score += 1
        conditions.append(
            f"catalyst vol={current_volume:,.0f} > {VOLUME_CATALYST_MULT}×ADV"
        )

    if score < 2:
        return None

    if score == 4:
        strength = "extreme"
    elif score == 3:
        strength = "high"
    else:
        strength = "moderate"

    logger.info(
        "[ortex] squeeze setup: %s score=%d/%d strength=%s",
        symbol, score, 4, strength,
    )

    return SqueezeSetup(
        symbol=symbol,
        ctb_pct=data.cost_to_borrow_pct,
        utilization_pct=data.utilization_pct,
        short_pct_float=data.short_pct_float,
        has_catalyst=has_catalyst,
        squeeze_score=score,
        signal_strength=strength,
        message=f"Squeeze setup [{strength.upper()}]: " + " | ".join(conditions),
    )
