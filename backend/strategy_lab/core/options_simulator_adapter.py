"""Adapter: connect options_simulator to the backtester pipeline."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
import yfinance as yf

from strategy_lab.core.options_simulator import mechanical_expected_value, simulate_iron_condor

logger = logging.getLogger(__name__)


def run_options_backtest(
    strategy_name: str,
    ticker: str,
    start_date: str,
    end_date: str,
    dte_target: int = 45,
    short_delta: float = 0.16,
    spread_width: float = 5.0,
    profit_target: float = 0.50,
    stop_loss_mult: float = 2.0,
    time_stop_dte: int = 21,
    entry_frequency_days: int = 30,
) -> dict:
    """Run a walk-forward iron condor backtest on a single underlying.

    Downloads daily bars from Yahoo Finance, then simulates one iron condor
    trade every ``entry_frequency_days`` calendar days.

    Args:
        strategy_name: Label for this backtest run (stored in results).
        ticker: Yahoo Finance ticker symbol (e.g. ``"SPY"``).
        start_date: Inclusive start date in ``"YYYY-MM-DD"`` format.
        end_date: Inclusive end date in ``"YYYY-MM-DD"`` format.
        dte_target: Target days-to-expiry at each entry.
        short_delta: Target delta for both short strikes (e.g. 0.16).
        spread_width: Width of each vertical spread in dollars.
        profit_target: Close early at this fraction of credit received.
        stop_loss_mult: Close early when loss equals this multiple of credit.
        time_stop_dte: Close early when DTE drops to this value.
        entry_frequency_days: Minimum calendar days between new entries.

    Returns:
        dict with keys ``strategy_name``, ``ticker``, ``trades`` (list of
        per-trade result dicts), and ``metrics`` (aggregate stats).
        On error: ``{"strategy_name": strategy_name, "error": "<message>"}``.
    """
    try:
        # ── Download bars ─────────────────────────────────────────────────────
        raw = yf.Ticker(ticker).history(
            start=start_date,
            end=end_date,
            interval="1d",
            auto_adjust=True,
        )
        if raw.empty:
            return {
                "strategy_name": strategy_name,
                "error": f"No price data returned for {ticker} [{start_date} – {end_date}]",
            }

        bars = raw.copy()
        bars.columns = [c.lower() for c in bars.columns]

        # Ensure a clean DatetimeIndex (strip tz if present)
        if bars.index.tz is not None:
            bars.index = bars.index.tz_localize(None)
        bars.index = bars.index.normalize()

        # ── Build entry schedule ──────────────────────────────────────────────
        start_dt = pd.Timestamp(start_date).date()
        end_dt = pd.Timestamp(end_date).date()
        # Do not enter if there would be fewer than dte_target days remaining
        latest_entry = end_dt - timedelta(days=dte_target)

        trades: list[dict[str, Any]] = []
        current_entry = start_dt

        while current_entry <= latest_entry:
            # Find the nearest trading day on or after current_entry
            candidate_ts = pd.Timestamp(current_entry)
            available = bars.index[bars.index >= candidate_ts]
            if available.empty:
                break

            actual_entry_ts = available[0]
            actual_entry: date = actual_entry_ts.date()

            result = simulate_iron_condor(
                bars=bars,
                entry_date=actual_entry,
                dte_target=dte_target,
                short_delta=short_delta,
                spread_width=spread_width,
                profit_target=profit_target,
                stop_loss_mult=stop_loss_mult,
                time_stop_dte=time_stop_dte,
            )

            if "error" not in result:
                trades.append(result)
            else:
                logger.debug(
                    "Skipping entry %s for %s: %s",
                    actual_entry,
                    ticker,
                    result["error"],
                )

            current_entry = actual_entry + timedelta(days=entry_frequency_days)

        # ── Aggregate metrics ─────────────────────────────────────────────────
        metrics = _aggregate_metrics(trades, spread_width, short_delta)

        return {
            "strategy_name": strategy_name,
            "ticker": ticker,
            "trades": trades,
            "metrics": metrics,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("run_options_backtest failed for %s / %s", strategy_name, ticker)
        return {"strategy_name": strategy_name, "error": str(exc)}


# ── Private helpers ───────────────────────────────────────────────────────────


def _aggregate_metrics(
    trades: list[dict[str, Any]],
    spread_width: float,
    short_delta: float,
) -> dict[str, Any]:
    """Compute aggregate performance statistics from a list of trade results."""
    if not trades:
        return {
            "n_trades": 0,
            "total_return_pct": 0.0,
            "win_rate": 0.0,
            "avg_pnl_pct": 0.0,
            "max_single_loss_pct": 0.0,
            "avg_days_held": 0.0,
            "exit_reason_counts": {},
            "mechanical_ev": {},
        }

    pnl_pcts = [t["pnl_pct"] for t in trades]
    credits = [t["credit_received"] for t in trades]
    max_losses = [t["max_loss"] for t in trades]
    days_held = [t["days_held"] for t in trades]

    n = len(trades)
    wins = sum(1 for p in pnl_pcts if p > 0)
    win_rate = wins / n

    total_return_pct = float(sum(pnl_pcts))
    avg_pnl_pct = total_return_pct / n
    max_single_loss_pct = float(min(pnl_pcts)) if pnl_pcts else 0.0
    avg_days_held = float(sum(days_held) / n)

    exit_counts: dict[str, int] = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    # Mechanical EV using average credit and max_loss across the run
    avg_credit = sum(credits) / n if n else 0.0
    avg_max_loss = sum(max_losses) / n if n else 0.0
    mev = mechanical_expected_value(short_delta, avg_credit, avg_max_loss)

    return {
        "n_trades": n,
        "total_return_pct": total_return_pct,
        "win_rate": float(win_rate),
        "avg_pnl_pct": float(avg_pnl_pct),
        "max_single_loss_pct": max_single_loss_pct,
        "avg_days_held": avg_days_held,
        "exit_reason_counts": exit_counts,
        "mechanical_ev": mev,
    }
