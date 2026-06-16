"""strategy_lab/core/backtester.py — real yfinance backtester for candidates."""
from __future__ import annotations

import importlib
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from strategy_lab.core.signals import Signal
from strategy_lab.core.cost_model import cost_per_trade

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulation constants
# ---------------------------------------------------------------------------

INITIAL_CAPITAL: float = 100_000.0
POSITION_SIZE_PCT: float = 0.05   # 5 % per position
MAX_POSITIONS: int = 20
STOP_PCT: float = -0.08
TARGET_PCT: float = 0.20
MAX_HOLD_DAYS: int = 30
_SPY: str = "SPY"
_WARMUP_DAYS: int = 290            # trading-day warmup for indicator computation



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
    equity_curve: list[dict]           # [{date, equity, drawdown_pct}]
    monte_carlo_sharpe_p5: float
    monte_carlo_sharpe_p95: float
    benchmark_sharpe: float
    beta_spy: float
    # Extended fields — not present in the old stub interface
    net_sharpe: float = 0.0
    total_cost_pct: float = 0.0        # cumulative cost as % of initial capital
    avg_cost_per_trade_bps: float = 0.0



def _load_module(strategy_name: str):
    for prefix in ("strategy_lab.candidates", "strategy_lab.strategies"):
        try:
            return importlib.import_module(f"{prefix}.{strategy_name}")
        except ImportError:
            pass
    raise ImportError(
        f"Strategy '{strategy_name}' not found in candidates/ or strategies/"
    )


def _get_universe(module, profile_config: dict) -> list[str]:
    config = getattr(module, "CANDIDATE_CONFIG", {})
    universe = (
        config.get("universe_hint")
        or profile_config.get("universe")
        or [_SPY, "QQQ", "IWM", "TLT", "GLD"]
    )
    return list(universe)


def _exchange_for(module) -> str:
    config = getattr(module, "CANDIDATE_CONFIG", {})
    asset = config.get("asset_class", "equity").lower()
    return "binance_spot" if "crypto" in asset else "alpaca_equity"



def _download(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Download OHLCV from yfinance; returns {symbol: DataFrame}."""
    tickers = list(dict.fromkeys(symbols + [_SPY]))   # dedup, SPY always present
    raw = yf.download(
        tickers, start=start, end=end,
        auto_adjust=True, progress=False, threads=True,
    )
    if raw.empty:
        return {}
    out: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in tickers:
            try:
                df = raw.xs(sym, axis=1, level=1).dropna(how="all")
                if len(df) > 30:
                    out[sym] = df
            except KeyError:
                pass
    else:
        out[tickers[0]] = raw.dropna(how="all")
    return out


OPTIONS_HOLD_DAYS: int = 21     # max hold for short-vol / credit positions
OPTIONS_STOP_PCT: float = 0.05   # 5% underlying move = condor breach
OPTIONS_TARGET_PCT: float = 0.15  # 15% underlying fall = take-profit for short


@dataclass
class _Pos:
    symbol: str; entry_date: date; entry_price: float; shares: float
    stop_price: float; target_price: float
    exit_date: Optional[date] = None; exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    short: bool = False

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.short:
            return (self.entry_price - self.exit_price) * self.shares
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.short:
            return (self.entry_price - self.exit_price) / self.entry_price * 100.0
        return (self.exit_price - self.entry_price) / self.entry_price * 100.0


def _precompute_bars(price_data: dict[str, pd.DataFrame]) -> dict[str, list[dict]]:
    return {
        sym: [{"t": str(i.date()), "o": float(r.get("Open") or 0), "h": float(r.get("High") or 0),
               "l": float(r.get("Low") or 0), "c": float(r.get("Close") or 0), "v": float(r.get("Volume") or 0)}
              for i, r in df.iterrows()]
        for sym, df in price_data.items()
    }


def _simulate(
    module, price_data: dict[str, pd.DataFrame], universe: list[str],
    profile_config: dict, exchange: str,
) -> Tuple[list[_Pos], list[float], float, float]:
    """Day-by-day portfolio simulation. Returns (trades, equity_curve, cost_dollars, avg_cost_bps)."""
    ref_sym = _SPY if _SPY in price_data else next(iter(price_data))
    trading_days = price_data[ref_sym].index
    sym_index = {sym: {ts: i for i, ts in enumerate(df.index)} for sym, df in price_data.items()}
    sym_close = {sym: df["Close"].to_numpy(dtype=float) for sym, df in price_data.items()}
    sym_open  = {sym: df["Open"].to_numpy(dtype=float) for sym, df in price_data.items()}
    precomputed = _precompute_bars(price_data)
    regime = {"vix": 18.0, "trend": "neutral", "state": "normal"}
    cash = INITIAL_CAPITAL
    open_positions: list[_Pos] = []
    closed_trades: list[_Pos] = []
    equity_curve: list[float] = []
    held: set[str] = set()
    total_cost_dollars = 0.0
    total_cost_bps_sum = 0.0
    n_cost_estimates = 0
    n_days = len(trading_days)

    for day_idx in range(n_days):
        dt = trading_days[day_idx]
        dt_date = dt.date()
        still_open: list[_Pos] = []
        for pos in open_positions:
            close_arr = sym_close.get(pos.symbol)
            row_map = sym_index.get(pos.symbol, {})
            ri = row_map.get(dt)
            if close_arr is None or ri is None:
                still_open.append(pos)
                continue
            current = close_arr[ri]
            days_held = (dt_date - pos.entry_date).days
            reason: Optional[str] = None
            max_hold = OPTIONS_HOLD_DAYS if pos.short else MAX_HOLD_DAYS
            if pos.short:
                if current >= pos.stop_price:   # underlying moved up past stop
                    reason = "stop"
                elif current <= pos.target_price:  # underlying fell to target
                    reason = "target"
                elif days_held >= max_hold:
                    reason = "time"
            else:
                if current <= pos.stop_price:
                    reason = "stop"
                elif current >= pos.target_price:
                    reason = "target"
                elif days_held >= max_hold:
                    reason = "time"
            if reason:
                try:
                    cost = cost_per_trade(pos.symbol, "sell", pos.shares, current, exchange)
                    exit_net = current * (1.0 - cost.total_pct)
                    total_cost_dollars += cost.to_dollars(current * pos.shares)
                    total_cost_bps_sum += cost.total_bps
                    n_cost_estimates += 1
                except Exception:
                    exit_net = current
                pos.exit_date = dt_date
                pos.exit_price = exit_net
                pos.exit_reason = reason
                if pos.short:
                    # return margin + P&L: cash posted was entry*shares, now recoup (2*entry - exit)*shares
                    cash += (2.0 * pos.entry_price - exit_net) * pos.shares
                else:
                    cash += exit_net * pos.shares
                held.discard(pos.symbol)
                closed_trades.append(pos)
            else:
                still_open.append(pos)
        open_positions = still_open

        if day_idx >= _WARMUP_DAYS and len(open_positions) < MAX_POSITIONS:
            try:
                bd = {s: precomputed[s][:day_idx + 1] for s in universe if s in precomputed}
                signals: list[Signal] = module.generate_signals(bd, profile_config, regime)
            except Exception as exc:
                logger.debug("generate_signals error on %s: %s", dt_date, exc)
                signals = []

            for sig in signals:
                if sig.side not in ("buy", "sell", "short"):
                    continue
                is_short = sig.side in ("sell", "short")
                if sig.symbol in held:
                    continue
                if len(open_positions) >= MAX_POSITIONS:
                    break

                open_arr = sym_open.get(sig.symbol)
                row_map_s = sym_index.get(sig.symbol, {})
                next_open: Optional[float] = None
                next_entry_date: Optional[date] = None
                for fwd in range(day_idx + 1, min(day_idx + 4, n_days)):
                    fwd_ts = trading_days[fwd]
                    ri_fwd = row_map_s.get(fwd_ts)
                    if ri_fwd is not None and open_arr is not None and open_arr[ri_fwd] > 0:
                        next_open = open_arr[ri_fwd]
                        next_entry_date = fwd_ts.date()
                        break

                if next_open is None or next_entry_date is None:
                    continue

                size_hint = sig.size_hint if sig.size_hint > 0 else POSITION_SIZE_PCT
                position_dollars = min(
                    INITIAL_CAPITAL * size_hint,
                    INITIAL_CAPITAL * POSITION_SIZE_PCT,
                )
                shares = position_dollars / next_open

                try:
                    cost = cost_per_trade(
                        sig.symbol, "buy", shares, next_open, exchange
                    )
                    entry_net = next_open * (1.0 + cost.total_pct)
                    total_cost_dollars += cost.to_dollars(position_dollars)
                    total_cost_bps_sum += cost.total_bps
                    n_cost_estimates += 1
                except Exception:
                    entry_net = next_open

                actual_cost = entry_net * shares
                if actual_cost > cash:
                    continue

                if is_short:
                    pos = _Pos(
                        symbol=sig.symbol,
                        entry_date=next_entry_date,
                        entry_price=entry_net,
                        shares=shares,
                        stop_price=entry_net * (1.0 + OPTIONS_STOP_PCT),
                        target_price=entry_net * (1.0 - OPTIONS_TARGET_PCT),
                        short=True,
                    )
                else:
                    pos = _Pos(
                        symbol=sig.symbol,
                        entry_date=next_entry_date,
                        entry_price=entry_net,
                        shares=shares,
                        stop_price=entry_net * (1.0 + STOP_PCT),
                        target_price=entry_net * (1.0 + TARGET_PCT),
                        short=False,
                    )
                cash -= actual_cost
                open_positions.append(pos)
                held.add(sig.symbol)

        open_value = 0.0
        for pos in open_positions:
            close_arr = sym_close.get(pos.symbol)
            ri = sym_index.get(pos.symbol, {}).get(dt)
            if close_arr is not None and ri is not None:
                current_price = close_arr[ri]
                if pos.short:
                    open_value += (2.0 * pos.entry_price - current_price) * pos.shares
                else:
                    open_value += current_price * pos.shares
            else:
                open_value += pos.entry_price * pos.shares
        equity_curve.append(cash + open_value)

    last_dt = trading_days[-1]
    for pos in open_positions:
        ca = sym_close.get(pos.symbol)
        ri = sym_index.get(pos.symbol, {}).get(last_dt)
        pos.exit_price = float(ca[ri]) if (ca is not None and ri is not None) else pos.entry_price
        pos.exit_date = last_dt.date()
        pos.exit_reason = "time"
        closed_trades.append(pos)

    avg_bps = (total_cost_bps_sum / n_cost_estimates) if n_cost_estimates > 0 else 0.0
    return closed_trades, equity_curve, total_cost_dollars, avg_bps



def _metrics(
    trades: list[_Pos],
    equity_curve: list[float],
    spy_rets: Optional[np.ndarray],
    total_cost_dollars: float,
    avg_cost_bps: float,
    period_years: float,
) -> dict:
    arr = np.asarray(equity_curve, dtype=float)
    if len(arr) < 2:
        return {}

    daily_rets = np.diff(arr) / np.maximum(arr[:-1], 1.0)
    final = arr[-1]
    total_ret = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0
    cagr = ((final / INITIAL_CAPITAL) ** (1.0 / max(period_years, 0.01)) - 1.0) * 100.0

    std = float(np.std(daily_rets, ddof=1))
    sharpe = float(np.mean(daily_rets) / std * math.sqrt(252)) if std > 0 else 0.0

    downside = daily_rets[daily_rets < 0]
    ds = float(downside.std(ddof=1)) if len(downside) > 1 else std
    sortino = float(np.mean(daily_rets) / ds * math.sqrt(252)) if ds > 0 else 0.0

    peak = np.maximum.accumulate(arr)
    dd_pct = (arr - peak) / peak * 100.0
    max_dd = float(abs(dd_pct.min()))
    calmar = abs(cagr / max_dd) if max_dd > 0 else 0.0

    wins = [t for t in trades if (t.pnl or 0) > 0]
    losses = [t for t in trades if (t.pnl or 0) <= 0]
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    gp = sum(t.pnl for t in wins if t.pnl)
    gl = abs(sum(t.pnl for t in losses if t.pnl))
    profit_factor = gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0)

    beta = 0.0
    if spy_rets is not None:
        n = min(len(spy_rets), len(daily_rets))
        if n > 2:
            cov = np.cov(daily_rets[-n:], spy_rets[-n:])
            beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else 0.0

    total_cost_pct = (total_cost_dollars / INITIAL_CAPITAL) * 100.0
    net_rets = daily_rets - total_cost_pct / (100.0 * max(len(arr) - 1, 1))
    ns = float(np.std(net_rets, ddof=1))
    net_sharpe = float(np.mean(net_rets) / ns * math.sqrt(252)) if ns > 0 else 0.0

    rng = np.random.default_rng(42)
    mc = []
    for _ in range(500):
        s = rng.choice(daily_rets, size=len(daily_rets), replace=True)
        sd = float(s.std(ddof=1))
        mc.append(float(s.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0)
    mc_arr = np.array(mc)

    return {
        "total_return_pct": round(total_ret, 2), "cagr": round(cagr, 2),
        "sharpe": round(sharpe, 2), "sortino": round(sortino, 2), "calmar": round(calmar, 2),
        "max_drawdown_pct": round(max_dd, 1), "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2), "total_trades": len(trades),
        "beta_spy": round(beta, 3),
        "mc_p5": round(float(np.percentile(mc_arr, 5)), 2),
        "mc_p95": round(float(np.percentile(mc_arr, 95)), 2),
        "net_sharpe": round(net_sharpe, 2), "total_cost_pct": round(total_cost_pct, 2),
        "avg_cost_per_trade_bps": round(avg_cost_bps, 1),
    }


def run_backtest(
    strategy_name: str,
    profile_config: dict,
    start_date: str,
    end_date: str,
    capital: float = 100_000,
    regime_filter: Optional[str] = None,
) -> BacktestResult:
    """Download bars, simulate trades, return real BacktestResult with cost model applied."""
    module = _load_module(strategy_name)
    universe = _get_universe(module, profile_config)
    exchange = _exchange_for(module)
    warmup_start = (datetime.fromisoformat(start_date) - timedelta(days=int(_WARMUP_DAYS * 1.5))).strftime("%Y-%m-%d")

    price_data = _download(universe, warmup_start, end_date)
    if not price_data:
        raise RuntimeError(f"yfinance returned no data for universe {universe}")

    # SPY benchmark metrics
    spy_df = price_data.get(_SPY)
    spy_sharpe = 0.0
    spy_rets_arr: Optional[np.ndarray] = None
    if spy_df is not None:
        spy_close = spy_df["Close"]
        sr = spy_close.pct_change().dropna()
        sig_start = pd.Timestamp(start_date)
        sr = sr[sr.index >= sig_start]
        if len(sr) > 1:
            s = float(sr.std(ddof=1))
            spy_sharpe = float(sr.mean() / s * math.sqrt(252)) if s > 0 else 0.0
            spy_rets_arr = sr.to_numpy(dtype=float)

    trades, equity_curve, total_cost_dollars, avg_cost_bps = _simulate(
        module=module,
        price_data=price_data,
        universe=universe,
        profile_config=profile_config,
        exchange=exchange,
    )

    if not equity_curve:
        raise RuntimeError(f"Simulation produced no equity data for '{strategy_name}'")

    # Trim equity curve to the requested start_date
    ref_df = price_data.get(_SPY)
    if ref_df is None:
        ref_df = next(iter(price_data.values()))
    signal_mask = ref_df.index >= pd.Timestamp(start_date)
    n_signal = int(signal_mask.sum())
    if len(equity_curve) > n_signal:
        equity_curve = equity_curve[-n_signal:]
    signal_days = ref_df[signal_mask].index

    period_years = (
        datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)
    ).days / 365.0

    m = _metrics(trades, equity_curve, spy_rets_arr, total_cost_dollars, avg_cost_bps, period_years)

    # Build downsampled equity curve for API response
    peak = INITIAL_CAPITAL
    step = max(1, len(equity_curve) // 200)
    curve_out = []
    for i in range(0, len(equity_curve), step):
        v = equity_curve[i]
        peak = max(peak, v)
        dd = (v - peak) / peak * 100.0
        dt_str = signal_days[i].date().isoformat() if i < len(signal_days) else ""
        curve_out.append({"date": dt_str, "equity": round(v, 2), "drawdown_pct": round(dd, 2)})

    return BacktestResult(
        strategy=strategy_name,
        start_date=start_date,
        end_date=end_date,
        capital=capital,
        sharpe=m.get("sharpe", 0.0),
        sortino=m.get("sortino", 0.0),
        calmar=m.get("calmar", 0.0),
        max_drawdown_pct=m.get("max_drawdown_pct", 0.0),
        win_rate_pct=m.get("win_rate_pct", 0.0),
        profit_factor=m.get("profit_factor", 0.0),
        total_trades=m.get("total_trades", 0),
        equity_curve=curve_out,
        monte_carlo_sharpe_p5=m.get("mc_p5", 0.0),
        monte_carlo_sharpe_p95=m.get("mc_p95", 0.0),
        benchmark_sharpe=round(spy_sharpe, 2),
        beta_spy=m.get("beta_spy", 0.0),
        net_sharpe=m.get("net_sharpe", 0.0),
        total_cost_pct=m.get("total_cost_pct", 0.0),
        avg_cost_per_trade_bps=m.get("avg_cost_per_trade_bps", 0.0),
    )


def make_wfa_strategy_fn(
    strategy_name: str,
    universe: Optional[list[str]] = None,
    profile_config: Optional[dict] = None,
):
    """Return a fn(bars: pd.DataFrame, params: dict) -> list[float] for run_walk_forward()."""
    module = _load_module(strategy_name)
    _universe = universe or _get_universe(module, profile_config or {})
    _profile = profile_config or {}

    def _fn(bars: pd.DataFrame, params: dict) -> list[float]:
        merged = {**_profile, **params}
        precomputed = _precompute_bars({sym: bars for sym in _universe})
        close_arr = bars["Close"].to_numpy(dtype=float)
        n = len(bars)
        regime = {"vix": 18.0, "trend": "neutral", "state": "normal"}
        daily_rets: list[float] = []
        held: Optional[str] = None
        entry_p = 0.0
        entry_i = 0

        for i in range(min(_WARMUP_DAYS, n - 1), n):
            bd = {s: precomputed[s][:i + 1] for s in _universe if s in precomputed}
            try:
                sigs = [s for s in module.generate_signals(bd, merged, regime) if s.side == "buy"]
            except Exception:
                sigs = []

            if held is None and sigs and i + 1 < n:
                entry_p = close_arr[i + 1]
                held = sigs[0].symbol
                entry_i = i + 1
                daily_rets.append(0.0)
            elif held is not None:
                cur = close_arr[i]
                prev = close_arr[i - 1] if i > 0 else cur
                daily_rets.append((cur - prev) / prev if prev > 0 else 0.0)
                if (cur <= entry_p * (1 + STOP_PCT) or cur >= entry_p * (1 + TARGET_PCT)
                        or (i - entry_i) >= MAX_HOLD_DAYS or not sigs):
                    held = None
            else:
                daily_rets.append(0.0)

        return daily_rets

    return _fn
