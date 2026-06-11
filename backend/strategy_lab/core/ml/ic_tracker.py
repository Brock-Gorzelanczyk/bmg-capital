"""Rolling Information Coefficient tracker — Spearman/Pearson IC per strategy."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

STRONG_THRESHOLD    =  0.05
MARGINAL_THRESHOLD  =  0.02
INVERSION_THRESHOLD = -0.02
MIN_SIGNALS         = 30
WINDOWS             = [30, 63, 90]


@dataclass
class ICResult:
    strategy_name: str
    window_days: int
    n_signals: int
    ic_spearman: float
    ic_pearson: float
    ic_p_value: float
    ic_t_stat: float
    direction_hit_rate: float
    confidence_correlation: float
    classification: str
    recommendation: str
    sample_signals: list = field(default_factory=list)


def t_stat_of_ic(ic: float, n: int) -> float:
    """t = IC * sqrt(n-2) / sqrt(1 - IC^2)"""
    if n <= 2:
        return 0.0
    denom = math.sqrt(max(1e-12, 1.0 - ic ** 2))
    return ic * math.sqrt(n - 2) / denom


def classify(ic: float, p_value: float, n_signals: int) -> tuple[str, str]:
    """Return (classification, recommendation). Significance gate applies."""
    if n_signals < MIN_SIGNALS:
        return "INSUFFICIENT", "HOLD"
    # Significance gate: classification only sticks if p < 0.10 or n >= 100
    if p_value >= 0.10 and n_signals < 100:
        return "INSUFFICIENT", "HOLD"
    if ic >= STRONG_THRESHOLD:
        return "STRONG", "HOLD"
    if ic >= MARGINAL_THRESHOLD:
        return "MARGINAL", "HOLD"
    if ic > INVERSION_THRESHOLD:
        return "NOISE", "DOWNWEIGHT"
    # ic <= -0.02
    return "INVERTED", "INVESTIGATE"


def compute_strategy_ic(
    strategy_name: str,
    window_days: int = 63,
    end_date: Optional[date] = None,
    db=None,
) -> ICResult:
    """Pull signals + matched positions, compute Spearman and Pearson IC."""
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        _close_db = True
    else:
        _close_db = False

    try:
        return _compute_ic(strategy_name, window_days, end_date, db)
    finally:
        if _close_db:
            db.close()


def _compute_ic(strategy_name: str, window_days: int, end_date: Optional[date], db) -> ICResult:
    from datetime import timedelta
    from sqlalchemy import text

    end_dt  = datetime.combine(end_date or date.today(), datetime.max.time()).replace(tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=window_days)

    # Get all buy/sell signals for this strategy in the window
    rows = db.execute(text("""
        SELECT s.id, s.ts, s.symbol, s.side, s.confidence, s.allocation_id
        FROM bot_signals s
        WHERE s.strategy = :name
          AND s.side IN ('buy', 'sell')
          AND s.ts >= :start
          AND s.ts <= :end
        ORDER BY s.ts ASC
    """), {"name": strategy_name, "start": start_dt.isoformat(), "end": end_dt.isoformat()}).fetchall()

    if not rows:
        # Fallback: try to match by allocation → profile name
        rows = db.execute(text("""
            SELECT s.id, s.ts, s.symbol, s.side, s.confidence, s.allocation_id
            FROM bot_signals s
            JOIN bot_allocations a ON s.allocation_id = a.id
            JOIN bot_profiles p ON a.profile_id = p.id
            WHERE p.name = :name
              AND s.side IN ('buy', 'sell')
              AND s.ts >= :start
              AND s.ts <= :end
            ORDER BY s.ts ASC
        """), {"name": strategy_name, "start": start_dt.isoformat(), "end": end_dt.isoformat()}).fetchall()

    n_total = len(rows)

    # For each signal, find the matching closed position
    confidences: list[float] = []
    direction_returns: list[float] = []
    sample: list[dict] = []

    for sig_row in rows:
        sig_id, sig_ts, symbol, side, confidence, alloc_id = sig_row

        # Find closed position opened within 2 hours of signal for same (alloc_id, symbol)
        pos = db.execute(text("""
            SELECT p.id, p.avg_cost_cents, p.opened_at, p.closed_at,
                   (SELECT t.fill_price_cents FROM bot_trades t
                    WHERE t.position_id = p.id AND t.side = 'sell'
                    ORDER BY t.ts DESC LIMIT 1) as exit_price_cents
            FROM bot_positions p
            WHERE p.allocation_id = :alloc_id
              AND p.symbol = :symbol
              AND p.opened_at >= :sig_ts
              AND p.opened_at <= :sig_ts_plus2h
              AND p.closed_at IS NOT NULL
              AND p.quarantined_at IS NULL
            ORDER BY p.opened_at ASC
            LIMIT 1
        """), {
            "alloc_id": alloc_id,
            "symbol": symbol,
            "sig_ts": sig_ts if isinstance(sig_ts, str) else sig_ts.isoformat() if hasattr(sig_ts, 'isoformat') else str(sig_ts),
            "sig_ts_plus2h": (
                (sig_ts + timedelta(hours=2)).isoformat()
                if hasattr(sig_ts, '__add__') else
                (datetime.fromisoformat(str(sig_ts).replace("Z", "+00:00")) + timedelta(hours=2)).isoformat()
            ),
        }).fetchone()

        if pos is None or pos[4] is None or pos[1] is None or float(pos[1]) <= 0:
            continue

        entry_price = float(pos[1])
        exit_price  = float(pos[4])
        raw_return  = (exit_price - entry_price) / entry_price

        # Direction-signed return
        dir_return = raw_return if side == "buy" else -raw_return

        confidences.append(float(confidence))
        direction_returns.append(dir_return)
        if len(sample) < 20:
            sample.append({"symbol": symbol, "confidence": confidence, "return": round(dir_return, 4)})

    n_matched = len(confidences)

    if n_matched < 3:
        # Not enough matched pairs; return with n_total to preserve signal count for INSUFFICIENT
        cls, rec = classify(0.0, 1.0, n_total)
        return ICResult(
            strategy_name=strategy_name, window_days=window_days,
            n_signals=n_total, ic_spearman=0.0, ic_pearson=0.0,
            ic_p_value=1.0, ic_t_stat=0.0, direction_hit_rate=0.0,
            confidence_correlation=0.0, classification=cls, recommendation=rec,
            sample_signals=sample,
        )

    conf_arr = np.array(confidences)
    ret_arr  = np.array(direction_returns)

    # Spearman IC
    sp_corr, sp_pval = stats.spearmanr(conf_arr, ret_arr)
    sp_corr = float(sp_corr) if not math.isnan(sp_corr) else 0.0
    sp_pval = float(sp_pval) if not math.isnan(sp_pval) else 1.0

    # Pearson IC
    pe_corr, _ = stats.pearsonr(conf_arr, ret_arr) if np.std(conf_arr) > 0 and np.std(ret_arr) > 0 else (0.0, 1.0)
    pe_corr = float(pe_corr) if not math.isnan(pe_corr) else 0.0

    # Direction hit rate
    hit_rate = float(np.mean(ret_arr > 0))

    # Confidence correlation: does higher confidence predict better outcome?
    conf_ret_corr, _ = stats.spearmanr(conf_arr, np.abs(ret_arr)) if len(conf_arr) >= 3 else (0.0, 1.0)
    conf_ret_corr = float(conf_ret_corr) if not math.isnan(conf_ret_corr) else 0.0

    t_stat = t_stat_of_ic(sp_corr, n_matched)
    cls, rec = classify(sp_corr, sp_pval, n_matched)

    return ICResult(
        strategy_name=strategy_name,
        window_days=window_days,
        n_signals=n_matched,
        ic_spearman=round(sp_corr, 5),
        ic_pearson=round(pe_corr, 5),
        ic_p_value=round(sp_pval, 5),
        ic_t_stat=round(t_stat, 3),
        direction_hit_rate=round(hit_rate, 4),
        confidence_correlation=round(conf_ret_corr, 5),
        classification=cls,
        recommendation=rec,
        sample_signals=sample,
    )
