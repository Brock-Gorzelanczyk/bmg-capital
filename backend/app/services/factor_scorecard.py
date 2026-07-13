"""Alphalens-style factor scorecard for portfolio-rank bots.

For each PR bot, computes:
  - Information Coefficient (IC): Spearman rank correlation between the
    bot's factor score at rebalance time T and the forward N-day return
    of each ranked symbol. Averaged across all rebalances.
  - IC t-stat: mean(IC) / (std(IC) / sqrt(N)) — tests whether IC is
    statistically different from zero.
  - Quintile spread: mean forward return of top quintile minus bottom
    quintile of ranked symbols, per rebalance, averaged.
  - Sample size counts: n_rebalances, n_symbol_periods, missing.

Data sources:
  - portfolio_rank_rebalance_log.ranking_output — JSON {symbol: score}
    at rebalance time
  - yfinance daily bars for forward returns

Cost control:
  - Bar fetches memoized in a per-run dict (symbol → DataFrame) so one
  fetch per symbol regardless of how many rebalances reference it.
  - Bots with < 3 rebalances return `insufficient_data` verdict — IC
    stats aren't meaningful otherwise.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_MIN_REBALANCES = 3
_DEFAULT_FORWARD_DAYS = 21    # ~1 month forward for IC
_YF_LOOKBACK_DAYS = 400       # buffer around all rebalance windows


def _spearman(x: list[float], y: list[float]) -> Optional[float]:
    """Compute Spearman rank correlation without pulling in scipy."""
    n = len(x)
    if n != len(y) or n < 2:
        return None
    def _ranks(vals: list[float]) -> list[float]:
        idx = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[idx[j + 1]] == vals[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r
    rx = _ranks(x)
    ry = _ranks(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    varx = sum((rx[i] - mx) ** 2 for i in range(n))
    vary = sum((ry[i] - my) ** 2 for i in range(n))
    if varx <= 0 or vary <= 0:
        return None
    return float(cov / math.sqrt(varx * vary))


def _forward_return(bars: dict[str, list], symbol: str,
                     start: date, days: int) -> Optional[float]:
    """Fetch forward return for a symbol from start → start + days trading
    days. Returns None if bars not available for that window."""
    hist = bars.get(symbol)
    if not hist:
        return None
    # Find first bar on/after start
    start_dt = datetime.combine(start, datetime.min.time())
    entry_i = None
    for i, b in enumerate(hist):
        if b["date"] >= start_dt.date():
            entry_i = i
            break
    if entry_i is None or entry_i >= len(hist):
        return None
    exit_i = min(entry_i + days, len(hist) - 1)
    entry_close = hist[entry_i]["close"]
    exit_close = hist[exit_i]["close"]
    if not entry_close or entry_close <= 0:
        return None
    return (exit_close / entry_close) - 1.0


def _fetch_bars(symbol: str) -> Optional[list[dict]]:
    """Fetch daily bars via yfinance. Returns list of {date, close}."""
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[scorecard] yfinance import failed: %s", exc)
        return None
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=_YF_LOOKBACK_DAYS)
    try:
        hist = yf.Ticker(symbol).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.debug("[scorecard] %s history failed: %s", symbol, exc)
        return None
    if hist is None or hist.empty:
        return None
    out = []
    for ts, row in hist.iterrows():
        try:
            out.append({"date": ts.date(), "close": float(row["Close"])})
        except Exception:
            continue
    return out


def compute_bot_scorecard(
    db: Session,
    bot_id: int,
    bot_name: str,
    forward_days: int = _DEFAULT_FORWARD_DAYS,
    bar_cache: Optional[dict[str, list]] = None,
) -> dict[str, Any]:
    """Compute IC + quintile spread for one PR bot from its rebalance log."""
    if bar_cache is None:
        bar_cache = {}

    rows = db.execute(text("""
        SELECT ranking_output, created_at
          FROM portfolio_rank_rebalance_log
         WHERE bot_id = :bid AND ranking_output IS NOT NULL
           AND error IS NULL
         ORDER BY created_at ASC
    """), {"bid": bot_id}).fetchall()

    rebalances: list[tuple[dict, date]] = []
    for r in rows:
        try:
            ranks = json.loads(r[0] or "{}")
            if not ranks:
                continue
        except Exception:
            continue
        # Only include rebalances at least forward_days ago so forward returns exist
        ts = r[1]
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except Exception:
                continue
        rebal_date = ts.date() if isinstance(ts, datetime) else ts
        if (date.today() - rebal_date).days < forward_days:
            continue
        rebalances.append((ranks, rebal_date))

    if len(rebalances) < _MIN_REBALANCES:
        return {
            "bot_id": bot_id,
            "bot_name": bot_name,
            "verdict": "insufficient_data",
            "n_rebalances": len(rebalances),
            "min_required": _MIN_REBALANCES,
            "forward_days": forward_days,
        }

    # Build per-rebalance IC + quintile spread
    per_rebal: list[dict] = []
    all_symbols = set()
    for ranks, _ in rebalances:
        all_symbols.update(ranks.keys())
    # Warm bar cache in one pass
    for sym in all_symbols:
        if sym not in bar_cache:
            bar_cache[sym] = _fetch_bars(sym) or []

    ic_series: list[float] = []
    q_spread_series: list[float] = []
    for ranks, rebal_date in rebalances:
        scored_symbols = [(s, float(v)) for s, v in ranks.items()
                          if v is not None and math.isfinite(float(v))]
        if len(scored_symbols) < 10:
            continue
        # Forward returns
        pairs = []
        for sym, score in scored_symbols:
            fr = _forward_return(bar_cache, sym, rebal_date, forward_days)
            if fr is None or not math.isfinite(fr):
                continue
            pairs.append((score, fr))
        if len(pairs) < 10:
            continue
        scores = [p[0] for p in pairs]
        rets = [p[1] for p in pairs]
        ic = _spearman(scores, rets)
        if ic is None:
            continue
        # Quintile spread (top - bottom)
        sorted_pairs = sorted(pairs, key=lambda p: -p[0])
        q_size = max(1, len(sorted_pairs) // 5)
        top = sorted_pairs[:q_size]
        bot = sorted_pairs[-q_size:]
        top_avg = sum(p[1] for p in top) / len(top)
        bot_avg = sum(p[1] for p in bot) / len(bot)
        q_spread = top_avg - bot_avg
        ic_series.append(ic)
        q_spread_series.append(q_spread)
        per_rebal.append({
            "rebal_date": rebal_date.isoformat(),
            "n_symbols_scored": len(pairs),
            "ic": round(ic, 4),
            "quintile_spread_pct": round(q_spread * 100, 3),
        })

    if not ic_series:
        return {
            "bot_id": bot_id,
            "bot_name": bot_name,
            "verdict": "no_valid_forward_returns",
            "n_rebalances": len(rebalances),
        }

    n = len(ic_series)
    ic_mean = sum(ic_series) / n
    ic_var = sum((x - ic_mean) ** 2 for x in ic_series) / max(1, n - 1) if n > 1 else 0.0
    ic_std = math.sqrt(ic_var) if ic_var > 0 else 0.0
    # IC t-stat: mean / (std / sqrt(N))
    ic_tstat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0.0
    q_mean = sum(q_spread_series) / n

    if ic_tstat > 2.0:
        verdict = "significant_positive"
    elif ic_tstat < -2.0:
        verdict = "significant_inverse"
    elif abs(ic_mean) < 0.02:
        verdict = "no_signal"
    else:
        verdict = "weak_signal"

    return {
        "bot_id": bot_id,
        "bot_name": bot_name,
        "verdict": verdict,
        "n_rebalances": n,
        "forward_days": forward_days,
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_tstat": round(ic_tstat, 2),
        "quintile_spread_pct": round(q_mean * 100, 3),
        "per_rebal_sample": per_rebal[-5:],  # most recent 5
    }


def compute_all_scorecards(db: Session,
                            forward_days: int = _DEFAULT_FORWARD_DAYS) -> dict:
    """Iterate all enabled PR bots, compute one scorecard each."""
    rows = db.execute(text(
        "SELECT id, name FROM portfolio_rank_bots WHERE enabled = 1 "
        "ORDER BY name"
    )).fetchall()
    bar_cache: dict[str, list] = {}
    scorecards = []
    for r in rows:
        try:
            scorecards.append(
                compute_bot_scorecard(db, int(r[0]), r[1], forward_days, bar_cache)
            )
        except Exception as exc:
            logger.error("[scorecard] compute failed for %s: %s", r[1], exc)
            scorecards.append({"bot_id": int(r[0]), "bot_name": r[1],
                               "verdict": "error", "error": str(exc)[:200]})
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "forward_days": forward_days,
        "n_bots": len(scorecards),
        "scorecards": scorecards,
    }
