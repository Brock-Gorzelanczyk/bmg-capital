"""
Walk-forward backtester for Strategy Lab.
Full implementation requires Polygon historical data.
Stub returns deterministic demo results for UI development.
"""
from __future__ import annotations

import datetime
import hashlib
import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class BacktestResult:
    """Backtest performance summary and equity curve."""

    strategy: str
    start_date: str
    end_date: str
    capital: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    equity_curve: list[dict]    # [{date, equity, drawdown_pct}]
    monte_carlo_sharpe_p5: float
    monte_carlo_sharpe_p95: float
    benchmark_sharpe: float
    beta_spy: float


def run_backtest(
    strategy_name: str,
    profile_config: dict,
    start_date: str,
    end_date: str,
    capital: float = 100_000,
    regime_filter: Optional[str] = None,
) -> BacktestResult:
    """Run walk-forward backtest.

    Currently returns deterministic demo results.
    Full implementation requires POLYGON_API_KEY + historical bars.

    Args:
        strategy_name: Name of the strategy (used to seed the RNG for
                       reproducible deterministic results).
        profile_config: Profile YAML dict (used for stop_loss_pct,
                        take_profit_pct, etc. in future full implementation).
        start_date: ISO date string, e.g. "2019-01-01".
        end_date: ISO date string, e.g. "2024-01-01".
        capital: Starting capital in USD.
        regime_filter: Optional regime filter string (reserved for future use).

    Returns:
        BacktestResult with metrics and day-by-day equity curve.
    """
    seed = int(hashlib.md5(f"{strategy_name}{start_date}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Demo equity curve
    start = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date)
    days = (end - start).days

    equity = capital
    peak = capital
    curve: list[dict] = []

    for i in range(days):
        day = start + datetime.timedelta(days=i)
        change = rng.gauss(0.0004, 0.008)   # ~10% annual, ~12.6% annual vol
        equity = round(equity * (1 + change), 2)
        peak = max(peak, equity)
        dd = (equity - peak) / peak * 100
        curve.append({
            "date": day.isoformat(),
            "equity": equity,
            "drawdown_pct": round(dd, 2),
        })

    final_equity = curve[-1]["equity"] if curve else capital
    total_return = (final_equity - capital) / capital
    years = days / 365
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

    sharpe = rng.uniform(0.8, 2.8)

    return BacktestResult(
        strategy=strategy_name,
        start_date=start_date,
        end_date=end_date,
        capital=capital,
        sharpe=round(sharpe, 2),
        sortino=round(sharpe * 1.4, 2),
        calmar=round(sharpe * 0.6, 2),
        max_drawdown_pct=round(rng.uniform(-8, -25), 1),
        win_rate_pct=round(rng.uniform(48, 65), 1),
        profit_factor=round(rng.uniform(1.2, 2.1), 2),
        total_trades=rng.randint(80, 800),
        equity_curve=curve,
        monte_carlo_sharpe_p5=round(sharpe * 0.4, 2),
        monte_carlo_sharpe_p95=round(sharpe * 1.6, 2),
        benchmark_sharpe=round(rng.uniform(0.6, 1.2), 2),
        beta_spy=round(rng.uniform(0.1, 0.8), 2),
    )
