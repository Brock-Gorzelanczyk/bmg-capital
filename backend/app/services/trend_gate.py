"""Trend gate — Priority 1 + 2 adjustments from confluence backtest analysis 2026-08-30.

Backtest of 20 candidates showed the confluence framework was picking value/
turnaround setups in a growth regime — 12 of 12 current picks underperforming
their sectors by ~10%. The 5 biggest losers (VFC -28%, ONON -25%, PODD -17%,
APTV -16%, MTDR -6.5%) shared two properties:
  1. Trading BELOW their 200-day SMA at arm time (Weinstein Stage 4 territory)
  2. In sectors that were negative/flat over 3-month lookback

This service adds those two gates to the arm endpoint. Signals still get to
FIRE (create_confluence_pick still allowed) but arming requires trend + sector
confirmation. Applies Weinstein Stage 2 + Faber TAA discipline to individual
name selection.

See `vault:research/2026-08-30-confluence-framework-backtest-analysis.md`
for the full backtest evidence + reasoning.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# GICS sector → SPDR ETF map (same as backtest script)
SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology":       "XLK",
    "Healthcare":       "XLV",
    "Financials":       "XLF",
    "Consumer Disc.":   "XLY",
    "Consumer Staples": "XLP",
    "Energy":           "XLE",
    "Industrials":      "XLI",
    "Comm. Services":   "XLC",
    "Real Estate":      "XLRE",
    "Materials":        "XLB",
    "Utilities":        "XLU",
}


def _yahoo_closes(symbol: str, days_back: int = 400) -> Optional[list]:
    """Fetch daily closes for `days_back` calendar days. Zero-cost (Yahoo free).
    Default 400 calendar days = ~275 trading days = enough for 200-SMA + buffer."""
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG trend_gate)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        return [c for c in closes if c is not None]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as e:
        logger.warning("[trend_gate] yahoo fetch failed for %s: %s", symbol, e)
        return None


def check_price_above_200sma(symbol: str) -> Dict[str, Any]:
    """PRIORITY 1: is the stock trading above its 200-day SMA?

    Weinstein Stage 2 filter — the biggest single winnower for long swings.
    Returns dict with pass/fail + supporting numbers.
    """
    closes = _yahoo_closes(symbol, days_back=400)
    if not closes or len(closes) < 200:
        return {
            "gate": "price_above_200sma",
            "pass": None,  # UNTESTABLE — data unavailable
            "reason": f"insufficient bars ({len(closes) if closes else 0} < 200)",
        }
    sma200 = sum(closes[-200:]) / 200
    current = closes[-1]
    ratio = current / sma200
    return {
        "gate": "price_above_200sma",
        "pass": current > sma200,
        "current_price": round(current, 2),
        "sma200": round(sma200, 2),
        "ratio": round(ratio, 3),
        "reason": (f"price ${current:.2f} vs 200SMA ${sma200:.2f} "
                   f"({(ratio - 1) * 100:+.1f}%)"),
    }


def check_sector_momentum_positive(sector: str) -> Dict[str, Any]:
    """PRIORITY 2: is the stock's sector showing positive 3-month momentum?

    Faber TAA-style regime filter at the sector level. Prevents entering picks
    in dying sectors even if the individual signals look attractive.
    """
    etf = SECTOR_ETF_MAP.get(sector)
    if not etf:
        return {
            "gate": "sector_momentum_positive",
            "pass": None,
            "reason": f"unknown sector: {sector}",
        }
    closes = _yahoo_closes(etf, days_back=90)
    if not closes or len(closes) < 60:
        return {
            "gate": "sector_momentum_positive",
            "pass": None,
            "reason": f"insufficient sector ETF ({etf}) bars",
        }
    entry = closes[0]
    current = closes[-1]
    ret_pct = (current - entry) / entry * 100
    return {
        "gate": "sector_momentum_positive",
        "pass": ret_pct > 0,
        "sector": sector,
        "sector_etf": etf,
        "return_3mo_pct": round(ret_pct, 2),
        "reason": f"{etf} 3-month return {ret_pct:+.2f}%",
    }


def check_growth_value_regime() -> Dict[str, Any]:
    """PRIORITY 5: growth-vs-value regime detector.

    Compares large-cap growth (IWF = Russell 1000 Growth) to small/mid-cap
    value (IWD = Russell 1000 Value) over trailing 6 months. When growth
    heavily beats value, the confluence framework's value-tilt picks
    struggle (backtest 2026-08-30: current picks -9.74% vs sector).

    Returns:
        mode: "growth_dominant" | "value_dominant" | "neutral"
        spread_pct: growth return - value return (6mo)
        suggested_size_multiplier: 0.5 (growth dominant) | 1.0 (neutral) | 1.2 (value dominant)

    UI/executor can use suggested_size_multiplier to adjust position sizes.
    Advisory only — does not block or auto-adjust.
    """
    iwf_closes = _yahoo_closes("IWF", days_back=200)  # ~130 trading days = 6mo
    iwd_closes = _yahoo_closes("IWD", days_back=200)

    if not iwf_closes or not iwd_closes or len(iwf_closes) < 100 or len(iwd_closes) < 100:
        return {
            "mode": "UNKNOWN",
            "spread_pct": None,
            "suggested_size_multiplier": 1.0,
            "reason": "insufficient IWF/IWD data",
        }

    # 6-month return proxy: use ~120 trading days back
    lookback = min(120, len(iwf_closes) - 1, len(iwd_closes) - 1)
    iwf_ret = (iwf_closes[-1] - iwf_closes[-lookback]) / iwf_closes[-lookback] * 100
    iwd_ret = (iwd_closes[-1] - iwd_closes[-lookback]) / iwd_closes[-lookback] * 100
    spread = iwf_ret - iwd_ret

    # Thresholds calibrated for meaningful regime shifts, not noise:
    # 5%+ growth outperformance over 6mo = growth-dominant regime
    # -5% or worse (value beats growth) = value-dominant regime
    if spread > 5.0:
        mode = "growth_dominant"
        # Value-tilt picks struggle here — reduce size
        multiplier = 0.5
    elif spread < -5.0:
        mode = "value_dominant"
        # Value-tilt picks (which is what framework picks) benefit — normal or up-size
        multiplier = 1.2
    else:
        mode = "neutral"
        multiplier = 1.0

    return {
        "mode": mode,
        "spread_pct": round(spread, 2),
        "iwf_return_6mo_pct": round(iwf_ret, 2),
        "iwd_return_6mo_pct": round(iwd_ret, 2),
        "suggested_size_multiplier": multiplier,
        "reason": (f"6mo growth (IWF) {iwf_ret:+.1f}% vs value (IWD) {iwd_ret:+.1f}% "
                   f"= {spread:+.1f}% spread → {mode}"),
    }


def evaluate_trend_gates(symbol: str, sector: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate both gates for a symbol. Returns combined result + advisory.

    - `passed_all`: True if both gates pass (or UNTESTABLE — data missing)
    - `hard_fail`: True if at least one gate DEFINITIVELY fails
    - `gates`: per-gate results

    Callers can decide whether hard_fail should block arm entirely or just
    flag a warning. Current arm endpoint uses hard_fail as a soft veto —
    logs it, adds to rule_compliance, allows override with force=true flag.
    """
    gate_price = check_price_above_200sma(symbol)
    gate_sector = check_sector_momentum_positive(sector) if sector else {
        "gate": "sector_momentum_positive",
        "pass": None,
        "reason": "no sector provided",
    }

    # hard_fail = at least one gate returned False explicitly
    hard_fail = (gate_price.get("pass") is False) or (gate_sector.get("pass") is False)
    # passed_all = both gates returned True
    passed_all = (gate_price.get("pass") is True) and (gate_sector.get("pass") is True)

    # PRIORITY 5: regime overlay
    regime = check_growth_value_regime()

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "sector": sector,
        "passed_all": passed_all,
        "hard_fail": hard_fail,
        "gates": [gate_price, gate_sector],
        "regime": regime,
    }
