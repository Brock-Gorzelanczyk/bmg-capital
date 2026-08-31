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


def check_momentum_meanreversion_regime() -> Dict[str, Any]:
    """Detect trend-following vs mean-reversion regime.

    Compares MTUM (iShares Momentum Factor ETF) vs VLUE (iShares Value Factor
    ETF) over trailing 3 months. When VLUE beats MTUM materially, it means
    beaten-down names are being bought aggressively — a MEAN-REVERSION regime.
    When MTUM beats VLUE, momentum is being extended — a TREND-FOLLOWING regime.

    Why this matters:
    - Trend-following signals (like sector momentum gate) HELP in trend-following
      regimes but HURT in mean-reversion regimes.
    - Backtest v3 (2026-08-30) showed our sector_momentum gate DESTROYED returns
      in the current mean-reversion regime because it excluded MU/INTC/AMD/MRNA
      (all beaten-down names that rebounded hard).
    - This detector lets the framework dynamically weight signals by regime.

    Returns:
        mode: "trend_following" | "mean_reversion" | "neutral"
        spread_pct: MTUM return - VLUE return over 3mo
        suggested_actions: which framework filters to enable/disable
    """
    mtum_closes = _yahoo_closes("MTUM", days_back=140)
    vlue_closes = _yahoo_closes("VLUE", days_back=140)

    if (not mtum_closes or not vlue_closes
            or len(mtum_closes) < 60 or len(vlue_closes) < 60):
        return {
            "mode": "UNKNOWN",
            "spread_pct": None,
            "reason": "insufficient MTUM/VLUE data",
            "suggested_actions": [],
        }

    # 3-month trailing return (~60 trading days)
    lookback = min(60, len(mtum_closes) - 1, len(vlue_closes) - 1)
    mtum_ret = (mtum_closes[-1] - mtum_closes[-lookback]) / mtum_closes[-lookback] * 100
    vlue_ret = (vlue_closes[-1] - vlue_closes[-lookback]) / vlue_closes[-lookback] * 100
    spread = mtum_ret - vlue_ret  # positive = momentum winning = trend-following

    # Thresholds tuned for meaningful regime shifts:
    # +3% spread = clear momentum leadership → trend-following regime
    # -3% spread = clear value leadership → mean-reversion regime
    if spread > 3.0:
        mode = "trend_following"
        actions = [
            "ENABLE sector_momentum_positive gate (trend-following works)",
            "REDUCE weight on beaten-down value picks",
            "PREFER stocks above 200-SMA (trend confirms)",
        ]
    elif spread < -3.0:
        mode = "mean_reversion"
        actions = [
            "DISABLE sector_momentum_positive gate (kills winners in this regime)",
            "INCREASE weight on beaten-down value picks (they rebound)",
            "KEEP 200-SMA gate but relax the sector filter",
        ]
    else:
        mode = "neutral"
        actions = [
            "sector_momentum_positive: advisory only",
            "size normally, no regime-specific tilt",
        ]

    return {
        "mode": mode,
        "spread_pct": round(spread, 2),
        "mtum_3mo_return_pct": round(mtum_ret, 2),
        "vlue_3mo_return_pct": round(vlue_ret, 2),
        "reason": (f"3mo momentum (MTUM) {mtum_ret:+.1f}% vs value (VLUE) {vlue_ret:+.1f}% "
                   f"= {spread:+.1f}% spread → {mode}"),
        "suggested_actions": actions,
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


def check_safety_composite(symbol: str) -> Dict[str, Any]:
    """QMJ-style Safety sub-composite: beta, idiosyncratic vol, using SPY as market proxy.

    Ships the "S" leg of Asness-Frazzini-Pedersen QMJ (2019, RAS). Their full
    Safety composite has 6 signals; this MVP ships the 2 that can be computed
    from Yahoo closes alone (beta + ivol). Leverage + earnings-vol require
    fundamentals data (yfinance financials, often flaky) — deferred to v2.

    Methodology (per vault research 2026-08-31 QMJ verify note):
      - Compute daily returns for symbol + SPY over trailing 252 trading days
      - Beta: slope of stock returns on SPY returns (OLS)
      - Idiosyncratic vol: annualized stdev of residuals (r_stock - β * r_spy)
      - Safety score = -z(beta) + -z(ivol), higher = safer
        (BMG doesn't yet have a scanned-universe context to z-score against;
         MVP uses fixed academic thresholds: beta < 1.0 = safe, ivol < 25%/yr = safe)

    Returns dict with pass/fail (advisory only — never blocks arming) + numbers.
    """
    stock_closes = _yahoo_closes(symbol, days_back=400)
    spy_closes = _yahoo_closes("SPY", days_back=400)
    if not stock_closes or not spy_closes or len(stock_closes) < 60 or len(spy_closes) < 60:
        return {
            "gate": "safety_composite",
            "pass": None,
            "reason": f"insufficient bars (stock={len(stock_closes) if stock_closes else 0}, spy={len(spy_closes) if spy_closes else 0})",
        }

    # Align to shorter length + compute daily returns
    n = min(len(stock_closes), len(spy_closes), 252)
    s = stock_closes[-n:]
    m = spy_closes[-n:]
    stock_rets = [(s[i] / s[i - 1]) - 1.0 for i in range(1, n)]
    spy_rets = [(m[i] / m[i - 1]) - 1.0 for i in range(1, n)]

    # OLS beta: cov(stock, spy) / var(spy)
    mean_s = sum(stock_rets) / len(stock_rets)
    mean_m = sum(spy_rets) / len(spy_rets)
    cov = sum((stock_rets[i] - mean_s) * (spy_rets[i] - mean_m) for i in range(len(stock_rets))) / len(stock_rets)
    var_m = sum((r - mean_m) ** 2 for r in spy_rets) / len(spy_rets)
    if var_m <= 0:
        return {"gate": "safety_composite", "pass": None, "reason": "SPY variance is zero"}
    beta = cov / var_m
    alpha = mean_s - beta * mean_m

    # Residuals + annualized idiosyncratic vol (sqrt(252) * daily stdev)
    residuals = [stock_rets[i] - (alpha + beta * spy_rets[i]) for i in range(len(stock_rets))]
    residual_var = sum(r * r for r in residuals) / max(1, len(residuals) - 1)
    ivol_daily = residual_var ** 0.5
    ivol_annualized = ivol_daily * (252 ** 0.5)

    # Simple pass thresholds: beta < 1.2 AND ivol < 40%/yr
    beta_ok = beta < 1.2
    ivol_ok = ivol_annualized < 0.40
    passed = beta_ok and ivol_ok
    safety_score = int(beta_ok) + int(ivol_ok)  # 0-2

    return {
        "gate": "safety_composite",
        "pass": passed,
        "beta_252d": round(beta, 3),
        "ivol_annualized_pct": round(ivol_annualized * 100, 2),
        "safety_score": safety_score,  # 0=risky, 2=safe
        "beta_ok": beta_ok,
        "ivol_ok": ivol_ok,
        "reason": (
            f"β={beta:.2f} (<1.2 {'✓' if beta_ok else '✗'}), "
            f"ivol={ivol_annualized*100:.1f}%/yr (<40 {'✓' if ivol_ok else '✗'})"
        ),
    }


def check_value_universe(symbol: str) -> Dict[str, Any]:
    """Piotroski-style value-universe filter: is this a value stock, or growth?

    Ships the universe-filter discipline from Piotroski (2000, JAR) — the F-Score
    only works INSIDE the value quintile. By extension, our confluence framework
    (built for value-turnaround setups per current signal mix) should ALSO run
    only on value-tilted names.

    MVP: uses Yahoo Finance's forwardPE from the free quote endpoint. Value
    universe = forwardPE < 25 OR forwardPE not available (unknown = assume value
    for safety since it doesn't hard-block).

    (Full impl would need P/B and cross-sectional ranking, but Yahoo's free
    endpoint doesn't reliably serve book value. This MVP catches the biggest
    growth-tilt names — NVDA at PE~60, TSLA at PE~100 — with zero deps.)

    Returns dict with:
      pass=True → in value universe (or unknown)
      pass=False → clearly growth (PE > 25 = above ~70th percentile historically)

    Advisory: current wiring will NOT hard-block, just tag in rule_compliance.
    """
    # yfinance is already a backend dep. .info returns fundamentals dict
    # (forwardPE, trailingPE, priceToBook, etc). More reliable than Yahoo's
    # v7 quote endpoint which now requires cookies (returns 401).
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception as e:
        return {"gate": "value_universe", "pass": None, "reason": f"yfinance fetch failed: {e}"}

    fpe = info.get("forwardPE")
    tpe = info.get("trailingPE")
    pb = info.get("priceToBook")

    # Piotroski applies to top-30% B/M = bottom-30% P/B. As a rough proxy,
    # P/B < 3 = value-ish, P/B > 5 = clearly growth.
    if pb is not None and pb > 0:
        pb_verdict = pb < 3.0
    else:
        pb_verdict = None

    # PE < 25 = roughly bottom-2-terciles historically; PE > 25 = growth-tilt
    if fpe is not None and fpe > 0:
        pe_verdict = fpe < 25.0
        pe_used = fpe
        pe_kind = "forward"
    elif tpe is not None and tpe > 0:
        pe_verdict = tpe < 30.0  # trailing runs slightly higher
        pe_used = tpe
        pe_kind = "trailing"
    else:
        pe_verdict = None
        pe_used = None
        pe_kind = None

    # Pass if BOTH available metrics say value, OR at least one says value and
    # the other is unavailable
    verdicts = [v for v in (pb_verdict, pe_verdict) if v is not None]
    if not verdicts:
        # No metrics available → don't block; report untestable
        return {
            "gate": "value_universe",
            "pass": None,
            "reason": "no P/E or P/B available from Yahoo",
        }
    passed = all(verdicts)

    return {
        "gate": "value_universe",
        "pass": passed,
        "price_to_book": pb,
        "pe_ratio": pe_used,
        "pe_kind": pe_kind,
        "pb_ok": pb_verdict,
        "pe_ok": pe_verdict,
        "reason": (
            f"P/B={pb} (<3 {pb_verdict if pb_verdict is not None else 'N/A'}), "
            f"{pe_kind or 'no'} P/E={pe_used} (thresh {'25' if pe_kind == 'forward' else '30'} "
            f"{pe_verdict if pe_verdict is not None else 'N/A'})"
        ),
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

    # PRIORITY 5: regime overlay (growth vs value)
    regime = check_growth_value_regime()
    # Post-backtest v3 addition: momentum vs mean-reversion regime
    mmr_regime = check_momentum_meanreversion_regime()

    # Ship #1 (2026-08-31 QMJ): Safety sub-composite (beta + idiosyncratic vol).
    # Advisory only — never blocks arm. Lands in rule_compliance so scorecard can
    # measure whether safe picks outperform risky ones over trailing 8wk window.
    safety = check_safety_composite(symbol)

    # Ship #2 (2026-08-31 Piotroski): value-universe filter (P/B + P/E).
    # Advisory only — future promotion to hard block after we see whether it
    # discriminates. Piotroski shows F-Score works INSIDE value only.
    value_universe = check_value_universe(symbol)

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "sector": sector,
        "passed_all": passed_all,
        "hard_fail": hard_fail,
        "gates": [gate_price, gate_sector, safety, value_universe],
        "regime_growth_value": regime,
        "regime_momentum_meanreversion": mmr_regime,
        "safety_composite": safety,
        "value_universe": value_universe,
    }
