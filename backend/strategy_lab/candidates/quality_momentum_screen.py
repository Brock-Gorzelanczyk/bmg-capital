"""
CANDIDATE — not scheduled. Monthly QMJ + momentum + low-beta stock screen.
Reference: Asness, Frazzini, Pedersen (2019) Quality Minus Junk.
"""
from __future__ import annotations

import logging
import os
import time

import numpy as np

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "name": "Quality Momentum Screen",
    "asset_class": "equity",
    "style": "quality_momentum",
    "data_source": "yfinance+simfin",
    "expected_sharpe": "0.7-1.5 combined",
    "academic_refs": ["Asness, Frazzini, Pedersen (2019) QMJ"],
    "promotion_minimum_paper_trades": 30,
    "promotion_minimum_days_observed": 60,
}

STRATEGY_NAME = "quality_momentum_screen"
TOP_N_HOLDINGS = 25
QUALITY_WEIGHT = 0.45
MOMENTUM_WEIGHT = 0.40
LOW_BETA_WEIGHT = 0.15
SIMFIN_CACHE_TTL_HOURS = 48
_simfin_cache: dict = {}


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    from datetime import datetime

    today = datetime.now()
    # Only rebalance in the first 5 days of the month
    if today.day > 5:
        return [
            Signal(
                symbol=s, side="hold", confidence=0.0, size_hint=0.0,
                reason="QMJ: waiting for month-start rebalance",
                strategy=STRATEGY_NAME,
            )
            for s in bars
        ]

    credit_mult = 1.0
    try:
        from strategy_lab.core.altdata.credit_spread_signal import get_credit_regime
        credit = get_credit_regime()
        if credit["state"] == "red":
            return [
                Signal(
                    symbol=s, side="hold", confidence=0.0, size_hint=0.0,
                    reason=f"QMJ: credit red — {credit['reason']}",
                    strategy=STRATEGY_NAME,
                )
                for s in bars
            ]
        credit_mult = credit["equity_multiplier"]
    except Exception:
        pass

    quality = _get_quality_scores(list(bars.keys()))
    momentum = _compute_momentum_scores(bars)
    beta = _compute_low_beta_scores(bars)

    if not quality:
        logger.warning("QMJ: SimFin unavailable — no signals generated")
        return []

    composite: dict[str, float] = {}
    for sym in set(quality) & set(momentum):
        q = quality.get(sym, 0.5)
        m = momentum.get(sym, 0.5)
        b = beta.get(sym, 0.5)
        composite[sym] = QUALITY_WEIGHT * q + MOMENTUM_WEIGHT * m + LOW_BETA_WEIGHT * b

    if not composite:
        return []

    ranked = sorted(composite.items(), key=lambda x: x[1], reverse=True)
    top_symbols = {s for s, _ in ranked[:TOP_N_HOLDINGS]}

    signals = []
    for i, (sym, score) in enumerate(ranked[:TOP_N_HOLDINGS]):
        confidence = min(1.0, max(0.55, (0.80 - i * 0.01)) * credit_mult)
        signals.append(Signal(
            symbol=sym, side="buy", confidence=confidence,
            size_hint=1.0 / TOP_N_HOLDINGS,
            reason=(
                f"QMJ: rank={i + 1} composite={score:.3f} "
                f"q={quality.get(sym, 0):.2f} m={momentum.get(sym, 0):.2f}"
            ),
            strategy=STRATEGY_NAME,
        ))
    for sym in bars:
        if sym not in top_symbols:
            signals.append(Signal(
                symbol=sym, side="hold", confidence=0.0, size_hint=0.0,
                reason="QMJ: not in top-25", strategy=STRATEGY_NAME,
            ))
    return signals


def _get_quality_scores(tickers: list[str]) -> dict[str, float]:
    now = time.time()
    if _simfin_cache.get("ts") and now - _simfin_cache["ts"] < SIMFIN_CACHE_TTL_HOURS * 3600:
        return _simfin_cache.get("scores", {})
    try:
        import simfin as sf
        import pandas as pd

        sf.set_api_key(os.getenv("SIMFIN_API_KEY", "free"))
        sf.set_data_dir(os.path.expanduser("~/.simfin"))
        income = sf.load_income(variant="ttm", market="us")
        balance = sf.load_balance(variant="ttm", market="us")
        cashflow = sf.load_cashflow(variant="ttm", market="us")
        df = income[["Revenue", "Gross Profit", "Net Income"]].copy()
        df = df.join(balance[["Total Assets", "Total Equity", "Total Liabilities"]], how="inner")
        df = df.join(cashflow[["Net Cash from Operating Activities"]], how="inner")
        df.columns = ["revenue", "gross_profit", "net_income",
                      "total_assets", "book_equity", "total_liab", "cfo"]
        df = df.dropna()
        df = df[(df["total_assets"] > 0) & (df["book_equity"] > 0)]
        df["gp_assets"] = df["gross_profit"] / df["total_assets"]
        df["roe"] = df["net_income"] / df["book_equity"]
        df["roa"] = df["net_income"] / df["total_assets"]
        df["cfo_assets"] = df["cfo"] / df["total_assets"]
        df["gross_margin"] = df["gross_profit"] / df["revenue"].replace(0, float("nan"))
        df["accruals"] = -((df["net_income"] - df["cfo"]) / df["total_assets"])
        df["low_leverage"] = -(df["total_liab"] / df["total_assets"])
        cols = ["gp_assets", "roe", "roa", "cfo_assets", "gross_margin", "accruals", "low_leverage"]
        df[cols] = df[cols].rank(pct=True)
        df["quality_score"] = df[cols].mean(axis=1)
        score_map = df["quality_score"].to_dict()
        filtered = {t: score_map[t] for t in tickers if t in score_map}
        _simfin_cache["scores"] = filtered
        _simfin_cache["ts"] = now
        return filtered
    except Exception as exc:
        logger.warning("QMJ: SimFin failed: %s", exc)
        return {}


def _compute_momentum_scores(bars: dict) -> dict[str, float]:
    raw: dict[str, float] = {}
    for sym, bar_list in bars.items():
        closes = [float(b.get("c", 0) or 0) for b in bar_list if b.get("c")]
        if len(closes) < 252:
            continue
        mom = (closes[-21] - closes[-252]) / closes[-252]
        raw[sym] = mom
    if not raw:
        return {}
    mn, mx = min(raw.values()), max(raw.values())
    if mx == mn:
        return {s: 0.5 for s in raw}
    return {s: (v - mn) / (mx - mn) for s, v in raw.items()}


def _compute_low_beta_scores(bars: dict) -> dict[str, float]:
    raw: dict[str, float] = {}
    for sym, bar_list in bars.items():
        closes = [float(b.get("c", 0) or 0) for b in bar_list if b.get("c")]
        if len(closes) < 60:
            continue
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        vol = float(np.std(rets[-252:]) if len(rets) >= 252 else np.std(rets))
        raw[sym] = -vol
    if not raw:
        return {}
    mn, mx = min(raw.values()), max(raw.values())
    if mx == mn:
        return {s: 0.5 for s in raw}
    return {s: (v - mn) / (mx - mn) for s, v in raw.items()}
