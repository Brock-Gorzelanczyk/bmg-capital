"""Regime state machine — Faber + Cooper-Gutierrez-Hameed + Moreira-Muir.

See vault: [[2026-08-27-regime-horizon-selection]]

Three gates computed daily from SPY daily bars:

  1. FABER 10mo SMA (Faber 2007 SSRN 962461)
     - If SPY close > 10mo SMA (~210 daily bars): equity gate OPEN
     - If SPY < 10mo SMA: equity gate CLOSED → cash

  2. COOPER-GUTIERREZ-HAMEED 36mo state (Cooper/Gutierrez/Hameed JF 2004)
     - If SPY 36mo return > 0: UP state → momentum works (+0.93%/mo)
     - If SPY 36mo return < 0: DOWN state → momentum fails (-0.37%/mo)
     - 1.3%/mo swing on same signal based only on 36-month market sign

  3. MOREIRA-MUIR vol scalar (Moreira & Muir JF 2017)
     - scalar = min(1.0, target_vol / realized_20d_vol)
     - Scales exposure inversely to trailing 20-day realized vol
     - target_vol default 15% annualized (typical equity target)

Consumers:
  from app.services.regime_state import get_regime_state
  st = get_regime_state()
  if not st.faber_open: skip_new_entries()
  size *= st.vol_scalar
  if not st.cgh_up: halve_momentum_sizing()

Cached daily — refreshed at 4:05 PM ET after market close, or lazily
on first call each trading day.
"""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Configuration defaults (overridable via env)
TARGET_VOL_ANNUAL = float(os.environ.get("REGIME_TARGET_VOL_ANNUAL", "0.15"))  # 15%


@dataclass
class RegimeState:
    """Snapshot of the market regime, refreshed daily."""
    as_of: str                    # ISO date the snapshot represents
    spy_close: float              # SPY close used
    sma_200: float                # 10mo SMA (~210 daily bars)
    faber_open: bool              # SPY > 10mo SMA
    ret_36mo_pct: float           # trailing 36mo total return
    cgh_up: bool                  # 36mo return > 0
    realized_vol_20d_annual: float  # trailing 20d realized vol, annualized
    vol_scalar: float             # min(1, target / realized)
    target_vol: float             # target vol used
    computed_at: str              # when this snapshot was computed
    error: Optional[str] = None   # if compute failed, describe

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "spy_close": self.spy_close,
            "sma_200": self.sma_200,
            "faber_open": self.faber_open,
            "ret_36mo_pct": self.ret_36mo_pct,
            "cgh_up": self.cgh_up,
            "realized_vol_20d_annual": self.realized_vol_20d_annual,
            "vol_scalar": self.vol_scalar,
            "target_vol": self.target_vol,
            "computed_at": self.computed_at,
            "error": self.error,
        }


# In-memory cache — one entry per trading day
_CACHE: Dict[str, RegimeState] = {}


def _alpaca_headers() -> Dict[str, str]:
    kid = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        raise RuntimeError("no_alpaca_creds")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec}


def _fetch_spy_bars(days_needed: int = 800) -> List[Dict[str, Any]]:
    """Fetch SPY daily bars from Alpaca. days_needed covers 36mo + buffer."""
    # 800 daily bars ≈ 38 months of trading days
    url = (
        f"https://data.alpaca.markets/v2/stocks/SPY/bars"
        f"?timeframe=1Day&limit={days_needed}&adjustment=all"
    )
    req = urllib.request.Request(url, headers=_alpaca_headers())
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("bars", [])


def _compute_regime(bars: List[Dict[str, Any]]) -> RegimeState:
    """Compute regime state from a list of Alpaca daily bars."""
    if not bars or len(bars) < 210:
        raise RuntimeError(f"insufficient_bars_for_faber_sma: got {len(bars)}")

    closes = [float(b["c"]) for b in bars]
    latest = bars[-1]
    latest_close = closes[-1]
    latest_ts = latest.get("t", "")

    # Faber 10mo SMA — 210 daily bars (10 months × ~21 trading days)
    sma_200 = sum(closes[-210:]) / 210

    # CGH 36mo state — need at least 756 bars (36mo × 21 trading days)
    if len(closes) < 756:
        # Fall back to shortest available window — flag as partial
        cgh_lookback = min(len(closes) - 1, 756)
    else:
        cgh_lookback = 756
    ret_36mo = (latest_close / closes[-cgh_lookback - 1] - 1.0) * 100.0

    # Moreira-Muir 20d realized vol — annualized
    if len(closes) < 21:
        rv_annual = 0.20  # fallback assumption
    else:
        returns = [
            math.log(closes[i] / closes[i - 1])
            for i in range(len(closes) - 20, len(closes))
        ]
        # Population std of daily log returns * sqrt(252)
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        rv_annual = math.sqrt(var_r) * math.sqrt(252)

    vol_scalar = min(1.0, TARGET_VOL_ANNUAL / rv_annual) if rv_annual > 0 else 1.0

    return RegimeState(
        as_of=str(latest_ts)[:10] or datetime.now(timezone.utc).date().isoformat(),
        spy_close=latest_close,
        sma_200=sma_200,
        faber_open=latest_close > sma_200,
        ret_36mo_pct=ret_36mo,
        cgh_up=ret_36mo > 0,
        realized_vol_20d_annual=rv_annual,
        vol_scalar=vol_scalar,
        target_vol=TARGET_VOL_ANNUAL,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def get_regime_state(force_refresh: bool = False) -> RegimeState:
    """Return current regime state, computing / caching as needed.

    Caches per trading-day (UTC-based key). Force refresh with force_refresh=True.
    Falls back to a permissive default if Alpaca fetch fails (faber_open=True,
    cgh_up=True, vol_scalar=1.0) so downstream bots don't halt entirely on
    a transient data outage — but the error field is populated so operators see it.
    """
    today_key = datetime.now(timezone.utc).date().isoformat()
    if not force_refresh and today_key in _CACHE:
        return _CACHE[today_key]

    try:
        bars = _fetch_spy_bars()
        st = _compute_regime(bars)
        _CACHE[today_key] = st
        # Prune old cache entries (keep last 10)
        if len(_CACHE) > 10:
            for k in sorted(_CACHE.keys())[:-10]:
                _CACHE.pop(k, None)
        logger.info(
            "[regime_state] refreshed: faber_open=%s cgh_up=%s vol_scalar=%.3f ret36=%.2f%% rv20=%.3f",
            st.faber_open, st.cgh_up, st.vol_scalar, st.ret_36mo_pct, st.realized_vol_20d_annual,
        )
        return st
    except Exception as exc:
        logger.error("[regime_state] compute failed: %s — using permissive fallback", exc)
        return RegimeState(
            as_of=today_key,
            spy_close=0.0,
            sma_200=0.0,
            faber_open=True,   # permissive: default to "gate open" on data outage
            ret_36mo_pct=0.0,
            cgh_up=True,
            realized_vol_20d_annual=0.20,
            vol_scalar=1.0,
            target_vol=TARGET_VOL_ANNUAL,
            computed_at=datetime.now(timezone.utc).isoformat(),
            error=f"{type(exc).__name__}: {exc}",
        )


def refresh_regime_tick() -> Dict[str, Any]:
    """APScheduler entry point — fires daily at 4:05 PM ET (after market close)."""
    st = get_regime_state(force_refresh=True)
    return st.to_dict()


def setup_regime_state_scheduler(scheduler) -> None:
    """Register the daily refresh cron."""
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    ET = pytz.timezone("America/New_York")
    scheduler.add_job(
        refresh_regime_tick,
        trigger=CronTrigger(
            hour=16, minute=5, day_of_week="mon-fri", timezone=ET,
        ),
        id="regime_state_refresh",
        name="regime_state_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("[regime_state] scheduler registered (daily 4:05 PM ET)")
