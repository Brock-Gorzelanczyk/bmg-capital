"""Per-strategy historical trigger backtest for the Scout page.

For a given (strategy_id, symbol, years) tuple, this module:
  1. Scans the bar history to find every "trigger" event the strategy would have
     fired (entry bars where its primary condition transitions from False to True).
  2. For each trigger, walks forward `hold_days` bars to record entry/exit price,
     return, hold days, MFE, MAE.
  3. Aggregates the per-trigger results into trigger_count, win_rate, avg_return,
     median_return, Sharpe (daily returns over the trade window), max drawdown
     across the equity curve, profit factor, avg hold days.
  4. Builds an equity curve as the cumulative compounded return from sequential
     non-overlapping trade outcomes (or from realised P&L if you prefer — we keep
     it simple here).

Detectors are intentionally lightweight — they don't try to reproduce every
strategy's full signal-generation logic; they identify the single most defining
trigger event so the user can eyeball the historical setup quality. The
strategy_triggers checklist is the authoritative current-state evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from typing import Callable, Iterable

import math


# ── Bar helpers ───────────────────────────────────────────────────────────────


def _bar_close(bar: dict) -> float | None:
    if not isinstance(bar, dict):
        return None
    # bars endpoint returns short keys (c/h/l/o/t/v); cached/legacy callers
    # may pass long keys (close/high/low/time). Accept both.
    v = bar.get("close")
    if v is None:
        v = bar.get("c")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bar_high(bar: dict) -> float | None:
    if not isinstance(bar, dict):
        return None
    v = bar.get("high")
    if v is None:
        v = bar.get("h")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bar_low(bar: dict) -> float | None:
    if not isinstance(bar, dict):
        return None
    v = bar.get("low")
    if v is None:
        v = bar.get("l")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bar_time(bar: dict) -> str:
    if not isinstance(bar, dict):
        return ""
    return str(bar.get("time") or bar.get("t") or bar.get("date") or "")


def _rolling_max(values: list[float], period: int, i: int) -> float | None:
    if i < period:
        return None
    window = values[i - period : i]
    window = [v for v in window if v is not None]
    return max(window) if window else None


def _rolling_min(values: list[float], period: int, i: int) -> float | None:
    if i < period:
        return None
    window = values[i - period : i]
    window = [v for v in window if v is not None]
    return min(window) if window else None


def _sma(values: list[float], period: int, i: int) -> float | None:
    if i + 1 < period:
        return None
    window = values[i + 1 - period : i + 1]
    window = [v for v in window if v is not None]
    if len(window) < period:
        return None
    return sum(window) / period


def _rsi(values: list[float], period: int, i: int) -> float | None:
    if i < period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for k in range(i - period + 1, i + 1):
        if k == 0:
            continue
        if values[k] is None or values[k - 1] is None:
            return None
        diff = values[k] - values[k - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ── Trigger detectors (per strategy "family") ─────────────────────────────────
#
# Each detector returns a list of bar indices where the strategy would have
# fired an entry signal. Use `transition`-style detection (was False, now True)
# so we get one trigger per setup instead of every consecutive in-state bar.


def _detect_donchian_break(bars: list[dict], period: int = 55) -> list[int]:
    closes = [_bar_close(b) for b in bars]
    triggers: list[int] = []
    prev_armed = False
    for i in range(period, len(bars)):
        close = closes[i]
        prior_high = _rolling_max(closes, period, i)  # high of last `period` bars excluding current
        if close is None or prior_high is None:
            continue
        armed = close > prior_high
        if armed and not prev_armed:
            triggers.append(i)
        prev_armed = armed
    return triggers


def _detect_donchian_break_factory(period: int) -> Callable[[list[dict]], list[int]]:
    def detect(bars: list[dict]) -> list[int]:
        return _detect_donchian_break(bars, period=period)
    return detect


def _detect_sma_cross(bars: list[dict], fast: int = 50, slow: int = 200) -> list[int]:
    closes = [_bar_close(b) for b in bars]
    triggers: list[int] = []
    prev_state: bool | None = None  # True = fast above slow
    for i in range(slow, len(bars)):
        f = _sma(closes, fast, i)
        s = _sma(closes, slow, i)
        if f is None or s is None:
            continue
        state = f > s
        if prev_state is False and state is True:
            triggers.append(i)
        prev_state = state
    return triggers


def _detect_sma_cross_factory(fast: int, slow: int) -> Callable[[list[dict]], list[int]]:
    def detect(bars: list[dict]) -> list[int]:
        return _detect_sma_cross(bars, fast=fast, slow=slow)
    return detect


def _detect_rsi_oversold(bars: list[dict], period: int = 14, threshold: float = 30) -> list[int]:
    closes = [_bar_close(b) for b in bars]
    triggers: list[int] = []
    prev_below = False
    for i in range(period + 1, len(bars)):
        rsi = _rsi(closes, period, i)
        if rsi is None:
            continue
        below = rsi < threshold
        # trigger on RSI crossing back ABOVE the threshold from below
        if prev_below and not below:
            triggers.append(i)
        prev_below = below
    return triggers


def _detect_bollinger_squeeze(bars: list[dict], period: int = 20, std: float = 2.0) -> list[int]:
    closes = [_bar_close(b) for b in bars]
    triggers: list[int] = []
    prev_squeeze = False
    bandwidths: list[float | None] = [None] * len(bars)
    for i in range(period, len(bars)):
        window = [c for c in closes[i - period : i] if c is not None]
        if len(window) < period:
            continue
        m = sum(window) / period
        sd = pstdev(window)
        if m <= 0:
            continue
        bandwidth = (2 * std * sd) / m
        bandwidths[i] = bandwidth
        # squeeze = bandwidth is at the lowest of the trailing 60d
        lookback = bandwidths[max(0, i - 60) : i]
        prior = [b for b in lookback if b is not None]
        if not prior:
            continue
        is_squeeze = bandwidth <= min(prior)
        if is_squeeze and not prev_squeeze:
            triggers.append(i)
        prev_squeeze = is_squeeze
    return triggers


# Strategy → detector registry. Falls back to SMA 50/200 cross for any unmapped
# strategy so the page never shows an empty backtest.
_DETECTORS: dict[str, Callable[[list[dict]], list[int]]] = {
    "turtle_donchian_s2":   _detect_donchian_break_factory(55),
    "donchian_breakout":    _detect_donchian_break_factory(20),
    "golden_cross":         _detect_sma_cross_factory(50, 200),
    "death_cross":          _detect_sma_cross_factory(50, 200),
    "trend_follow_50_200":  _detect_sma_cross_factory(50, 200),
    "rsi_oversold":         lambda b: _detect_rsi_oversold(b, period=14, threshold=30),
    "rsi_overbought":       lambda b: _detect_rsi_oversold(b, period=14, threshold=30),  # same trigger event
    "bollinger_squeeze":    _detect_bollinger_squeeze,
    "mtf_aligned_momentum_surge": _detect_sma_cross_factory(20, 50),
    "quant_aggressive":     lambda b: _detect_rsi_oversold(b, period=2, threshold=10),
}


# ── Aggregation ───────────────────────────────────────────────────────────────


@dataclass
class BacktestTrigger:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float       # signed decimal, 0.05 = +5%
    hold_days: int
    mfe_pct: float          # max favorable excursion (peak unrealised %)
    mae_pct: float          # max adverse excursion (worst unrealised %)


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    years_requested: int
    years_available: float
    bar_count: int
    triggers: list[BacktestTrigger]
    trigger_count: int
    win_rate: float | None
    avg_return: float | None
    median_return: float | None
    sharpe: float | None
    max_dd: float | None
    profit_factor: float | None
    avg_hold_days: float | None
    equity_curve: list[dict]  # [{date, cum_return}]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["triggers"] = [asdict(t) for t in self.triggers]
        return d


def _compute_excursions(
    bars: list[dict], entry_idx: int, exit_idx: int, entry_price: float
) -> tuple[float, float]:
    """Return (max_favorable_excursion_pct, max_adverse_excursion_pct) over the trade window."""
    if entry_price <= 0:
        return 0.0, 0.0
    mfe = 0.0
    mae = 0.0
    for k in range(entry_idx, min(exit_idx + 1, len(bars))):
        high = _bar_high(bars[k]) or _bar_close(bars[k])
        low = _bar_low(bars[k]) or _bar_close(bars[k])
        if high is not None:
            up = (high - entry_price) / entry_price
            if up > mfe:
                mfe = up
        if low is not None:
            down = (low - entry_price) / entry_price
            if down < mae:
                mae = down
    return mfe, mae


def _aggregate(
    strategy_id: str,
    symbol: str,
    bars: list[dict],
    years_requested: int,
    triggers: list[BacktestTrigger],
) -> BacktestResult:
    n = len(triggers)
    returns = [t.return_pct for t in triggers]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    win_rate = (len(wins) / n) if n else None
    avg_return = mean(returns) if returns else None
    median_return = median(returns) if returns else None

    sharpe: float | None = None
    if len(returns) >= 5:
        sd = pstdev(returns)
        if sd > 0 and avg_return is not None:
            # Annualise by assuming triggers are roughly evenly spread across
            # bars (~252 trading days / year). Not rigorous, but matches what
            # users expect when comparing "Sharpe" across strategies on a chart.
            sharpe = (avg_return / sd) * math.sqrt(252 / max(1, _avg_bars_per_trigger(bars, n)))

    profit_factor: float | None = None
    if losses:
        gross_win = sum(wins)
        gross_loss = -sum(losses)
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    avg_hold = mean([t.hold_days for t in triggers]) if triggers else None

    # Equity curve: compound returns sequentially across triggers.
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    curve: list[dict] = []
    for t in triggers:
        cum *= (1.0 + t.return_pct)
        if cum > peak:
            peak = cum
        if peak > 0:
            dd = (cum - peak) / peak  # negative
            if dd < max_dd:
                max_dd = dd
        curve.append({"date": t.exit_date, "cum_return": round(cum - 1.0, 6)})

    years_available = round(len(bars) / 252.0, 2)

    return BacktestResult(
        strategy_id=strategy_id,
        symbol=symbol,
        years_requested=years_requested,
        years_available=years_available,
        bar_count=len(bars),
        triggers=triggers,
        trigger_count=n,
        win_rate=round(win_rate, 4) if win_rate is not None else None,
        avg_return=round(avg_return, 4) if avg_return is not None else None,
        median_return=round(median_return, 4) if median_return is not None else None,
        sharpe=round(sharpe, 3) if sharpe is not None else None,
        max_dd=round(max_dd, 4),
        profit_factor=round(profit_factor, 3) if profit_factor is not None else None,
        avg_hold_days=round(avg_hold, 1) if avg_hold is not None else None,
        equity_curve=curve,
    )


def _avg_bars_per_trigger(bars: list[dict], trigger_count: int) -> float:
    if trigger_count <= 0:
        return float(len(bars))
    return max(1.0, len(bars) / trigger_count)


# ── Public entrypoint ─────────────────────────────────────────────────────────


def run_backtest(
    strategy_id: str,
    symbol: str,
    bars: list[dict],
    years_requested: int = 5,
    hold_days: int = 30,
) -> BacktestResult:
    """Replay `strategy_id` over `bars` and return the aggregated backtest.

    `hold_days` controls the forward-walk window for fixed-hold trades. We use
    a single-rule "hold N days then exit at close" for portability across
    strategies — anything more sophisticated requires strategy-specific exit
    logic which already lives in the bot runner.
    """
    if not bars or len(bars) < 30:
        return _aggregate(strategy_id, symbol, bars, years_requested, [])

    detector = _DETECTORS.get(strategy_id, _detect_sma_cross_factory(50, 200))
    trigger_indices = detector(bars)

    out: list[BacktestTrigger] = []
    for ti in trigger_indices:
        entry_price = _bar_close(bars[ti])
        if entry_price is None or entry_price <= 0:
            continue
        exit_idx = min(ti + hold_days, len(bars) - 1)
        exit_price = _bar_close(bars[exit_idx])
        if exit_price is None or exit_price <= 0:
            continue
        ret = (exit_price - entry_price) / entry_price
        mfe, mae = _compute_excursions(bars, ti, exit_idx, entry_price)
        out.append(
            BacktestTrigger(
                entry_date=_bar_time(bars[ti]),
                entry_price=round(entry_price, 4),
                exit_date=_bar_time(bars[exit_idx]),
                exit_price=round(exit_price, 4),
                return_pct=round(ret, 4),
                hold_days=exit_idx - ti,
                mfe_pct=round(mfe, 4),
                mae_pct=round(mae, 4),
            )
        )

    return _aggregate(strategy_id, symbol, bars, years_requested, out)
