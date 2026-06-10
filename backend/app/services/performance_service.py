"""
Read-only performance analytics service.
Computes Sharpe, Sortino, drawdown, win rate, profit factor, equity curves,
strategy attribution, and symbol attribution from bot trade history.
"""

import math
import time
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Any, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.models.bots import (
    BotDailyPnL,
    BotTrade,
    BotPosition,
    BotSignal,
    BotAllocation,
    BotProfile,
    StrategyWeight,
    RegimeSnapshot,
    BotHealth,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------

_CACHE: Dict[str, tuple] = {}  # key -> (timestamp, value)
_DEFAULT_TTL = 300       # 5 minutes
_EQUITY_CURVE_TTL = 3600  # 1 hour


def _ckey(*parts) -> str:
    """Build a cache key from parts."""
    return ":".join(str(p) for p in parts)


def _cget(key: str, ttl: int = _DEFAULT_TTL) -> Any:
    """Return cached value if still fresh, else None."""
    entry = _CACHE.get(key)
    if entry is None:
        return None
    ts, val = entry
    if time.time() - ts > ttl:
        del _CACHE[key]
        return None
    return val


def _cset(key: str, val: Any) -> None:
    """Store value in cache with current timestamp."""
    _CACHE[key] = (time.time(), val)


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def sharpe(daily_returns: List[float], rf: float = 0.04) -> Optional[float]:
    """
    Annualized Sharpe ratio.
    Requires at least 5 data points. Returns None if insufficient data.
    """
    if not daily_returns or len(daily_returns) < 5:
        logger.warning("sharpe: insufficient data (%d points)", len(daily_returns) if daily_returns else 0)
        return None
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / n
    std = math.sqrt(variance)
    if std == 0:
        return None
    daily_rf = rf / 252
    return (mean - daily_rf) / std * math.sqrt(252)


def sortino(daily_returns: List[float], rf: float = 0.04) -> Optional[float]:
    """
    Annualized Sortino ratio using only downside deviation.
    Requires at least 5 data points. Returns None if insufficient data.
    """
    if not daily_returns or len(daily_returns) < 5:
        logger.warning("sortino: insufficient data (%d points)", len(daily_returns) if daily_returns else 0)
        return None
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    daily_rf = rf / 252
    downside = [r for r in daily_returns if r < daily_rf]
    if not downside:
        return None
    downside_variance = sum((r - daily_rf) ** 2 for r in downside) / n
    downside_std = math.sqrt(downside_variance)
    if downside_std == 0:
        return None
    return (mean - daily_rf) / downside_std * math.sqrt(252)


def max_drawdown(equity_series: List[float]) -> tuple:
    """
    Compute maximum drawdown from an equity series.
    Returns (pct as negative float e.g. -0.083, dollar_loss as negative float).
    Returns (None, None) if insufficient data.
    """
    if not equity_series or len(equity_series) < 2:
        return (None, None)
    peak = equity_series[0]
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    peak_val = equity_series[0]
    for val in equity_series:
        if val > peak:
            peak = val
            peak_val = val
        dd = val - peak
        dd_pct = dd / peak if peak != 0 else 0.0
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_dollar = dd
    if max_dd_pct == 0.0:
        return (0.0, 0.0)
    return (max_dd_pct, max_dd_dollar)


def calmar(annual_return_pct: Optional[float], max_dd_pct: Optional[float]) -> Optional[float]:
    """
    Calmar ratio = annual_return_pct / abs(max_dd_pct). Capped at ±99.
    Returns None if either input is None or max_dd_pct is zero.
    """
    if annual_return_pct is None or max_dd_pct is None:
        return None
    if max_dd_pct == 0:
        return None
    ratio = annual_return_pct / abs(max_dd_pct)
    return max(-99.0, min(99.0, ratio))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _position_pnl_cents(trades: List[Any]) -> float:
    """
    Compute net PnL in cents for a closed position.
    sum(sell_fill * qty) - sum(buy_fill * qty) - sum(fees)
    Works for both long and short positions.
    """
    sell_proceeds = sum(
        t.fill_price_cents * t.qty for t in trades if t.side.lower() in ("sell", "short_sell", "short")
    )
    buy_costs = sum(
        t.fill_price_cents * t.qty for t in trades if t.side.lower() in ("buy", "cover", "short_cover")
    )
    total_fees = sum(t.fees_cents or 0 for t in trades)
    return sell_proceeds - buy_costs - total_fees


def _build_equity_curve(
    daily_pnl_rows: List[Any],
    starting_capital_cents: float,
    days: Optional[int] = None,
) -> List[Dict]:
    """
    Build an equity curve from BotDailyPnL rows.
    Returns list of {date, equity_usd, drawdown_pct}.
    """
    if not daily_pnl_rows:
        return []

    rows = sorted(daily_pnl_rows, key=lambda r: r.date)
    if days is not None:
        rows = rows[-days:]

    curve = []
    cumulative_cents = starting_capital_cents
    peak_cents = starting_capital_cents

    for row in rows:
        if row.portfolio_value_eod_cents is not None:
            equity_cents = row.portfolio_value_eod_cents
        else:
            realized = row.realized_cents or 0
            unrealized = row.unrealized_cents or 0
            fees = row.fees_cents or 0
            cumulative_cents += realized + unrealized - fees
            equity_cents = cumulative_cents

        if equity_cents > peak_cents:
            peak_cents = equity_cents

        drawdown_pct = (equity_cents - peak_cents) / peak_cents if peak_cents != 0 else 0.0

        curve.append({
            "date": row.date,
            "equity_usd": equity_cents / 100,
            "drawdown_pct": drawdown_pct,
        })

    return curve


def _get_closed_trade_pnls(
    db: Session,
    alloc_ids: List[int],
    since_date: Optional[date] = None,
) -> List[Dict]:
    """
    Return closed trade PnL records for the given allocation IDs.
    Each record: {pnl_cents, symbol, opened_at, closed_at, hold_hours, position_id}
    """
    if not alloc_ids:
        return []

    q = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.isnot(None),
            BotPosition.quarantined_at.is_(None),
        )
    )
    if since_date is not None:
        since_dt = datetime.combine(since_date, datetime.min.time())
        q = q.filter(BotPosition.opened_at >= since_dt)

    positions = q.all()
    results = []

    for pos in positions:
        trades = (
            db.query(BotTrade)
            .filter(
                BotTrade.position_id == pos.id,
                BotTrade.quarantined_at.is_(None),
            )
            .all()
        )
        pnl = _position_pnl_cents(trades)
        hold_hours = (
            (pos.closed_at - pos.opened_at).total_seconds() / 3600
            if pos.opened_at and pos.closed_at
            else None
        )
        results.append({
            "pnl_cents": pnl,
            "symbol": pos.symbol,
            "opened_at": pos.opened_at,
            "closed_at": pos.closed_at,
            "hold_hours": hold_hours,
            "position_id": pos.id,
            "allocation_id": pos.allocation_id,
        })

    return results


def _get_strategy_attribution(
    db: Session,
    alloc_id: int,
    closed_trades: List[Dict],
) -> List[Dict]:
    """
    Attribute PnL to strategies by matching closed trades to nearest BotSignal.
    Returns list of {strategy, pnl_cents, num_trades, weight_pct} sorted by pnl_cents desc.
    """
    signals = (
        db.query(BotSignal)
        .filter(
            BotSignal.allocation_id == alloc_id,
            BotSignal.is_test.isnot(True),
        )
        .order_by(BotSignal.ts)
        .all()
    )

    # Build symbol -> sorted list of signals
    signal_map: Dict[str, List[Any]] = {}
    for sig in signals:
        signal_map.setdefault(sig.symbol, []).append(sig)

    attribution: Dict[str, Dict] = {}
    ten_minutes = timedelta(minutes=10)

    for trade in closed_trades:
        sym = trade["symbol"]
        opened_at = trade["opened_at"]
        if sym not in signal_map or opened_at is None:
            strategy = "unknown"
        else:
            best_sig = None
            best_delta = None
            for sig in signal_map[sym]:
                sig_ts = sig.ts
                if sig_ts.tzinfo is None and opened_at.tzinfo is not None:
                    sig_ts = sig_ts.replace(tzinfo=timezone.utc)
                elif sig_ts.tzinfo is not None and opened_at.tzinfo is None:
                    sig_ts = sig_ts.replace(tzinfo=None)
                delta = abs((sig_ts - opened_at).total_seconds())
                if delta <= ten_minutes.total_seconds():
                    if best_delta is None or delta < best_delta:
                        best_delta = delta
                        best_sig = sig
            strategy = best_sig.strategy if best_sig else "unknown"

        if strategy not in attribution:
            attribution[strategy] = {"strategy": strategy, "pnl_cents": 0.0, "num_trades": 0}
        attribution[strategy]["pnl_cents"] += trade["pnl_cents"]
        attribution[strategy]["num_trades"] += 1

    # Get strategy weights
    alloc = db.query(BotAllocation).filter(BotAllocation.id == alloc_id).first()
    strategy_weights: Dict[str, float] = {}
    total_weight = 0.0

    if alloc:
        profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        if profile:
            sw_rows = (
                db.query(StrategyWeight)
                .filter(StrategyWeight.profile_id == profile.id)
                .all()
            )
            for sw in sw_rows:
                strategy_weights[sw.strategy_name] = sw.current_weight or 0.0
                total_weight += sw.current_weight or 0.0

    result = []
    for strat, data in attribution.items():
        weight_pct = None
        if total_weight > 0 and strat in strategy_weights:
            weight_pct = strategy_weights[strat] / total_weight * 100
        result.append({
            "strategy": strat,
            "pnl_cents": data["pnl_cents"],
            "num_trades": data["num_trades"],
            "weight_pct": weight_pct,
        })

    result.sort(key=lambda x: x["pnl_cents"], reverse=True)
    return result


def _get_symbol_attribution(closed_trades: List[Dict], top: int = 5) -> List[Dict]:
    """
    Aggregate PnL by symbol, return top N by pnl_cents descending.
    Returns list of {symbol, pnl_cents, num_trades}.
    """
    by_symbol: Dict[str, Dict] = {}
    for trade in closed_trades:
        sym = trade["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"symbol": sym, "pnl_cents": 0.0, "num_trades": 0}
        by_symbol[sym]["pnl_cents"] += trade["pnl_cents"]
        by_symbol[sym]["num_trades"] += 1

    result = sorted(by_symbol.values(), key=lambda x: x["pnl_cents"], reverse=True)
    return result[:top]


def _get_time_of_day(closed_trades: List[Dict]) -> List[Dict]:
    """
    Aggregate average PnL by hour of day (0-23) using closed_at hour.
    Returns list of {hour, avg_pnl_cents, num_trades}.
    """
    by_hour: Dict[int, Dict] = {h: {"hour": h, "total_pnl_cents": 0.0, "num_trades": 0} for h in range(24)}

    for trade in closed_trades:
        closed_at = trade.get("closed_at")
        if closed_at is None:
            continue
        hour = closed_at.hour
        by_hour[hour]["total_pnl_cents"] += trade["pnl_cents"]
        by_hour[hour]["num_trades"] += 1

    result = []
    for h in range(24):
        entry = by_hour[h]
        n = entry["num_trades"]
        avg = entry["total_pnl_cents"] / n if n > 0 else 0.0
        result.append({"hour": h, "avg_pnl_cents": avg, "num_trades": n})

    return result


def _get_regime_breakdown(db: Session, closed_trades: List[Dict]) -> List[Dict]:
    """
    Attribute PnL to market regimes by matching each closed trade to the nearest
    RegimeSnapshot within 2 hours. Groups by trend_regime.
    Returns list of {regime, pnl_cents, num_trades}.
    """
    if not closed_trades:
        return []

    regime_snapshots = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts).all()
    if not regime_snapshots:
        return []

    two_hours_sec = 7200.0
    by_regime: Dict[str, Dict] = {}

    for trade in closed_trades:
        opened_at = trade.get("opened_at")
        if opened_at is None:
            continue

        best_snap = None
        best_delta = None
        for snap in regime_snapshots:
            snap_ts = snap.ts
            trade_ts = opened_at
            if snap_ts.tzinfo is None and trade_ts.tzinfo is not None:
                snap_ts = snap_ts.replace(tzinfo=timezone.utc)
            elif snap_ts.tzinfo is not None and trade_ts.tzinfo is None:
                snap_ts = snap_ts.replace(tzinfo=None)
            delta = abs((snap_ts - trade_ts).total_seconds())
            if delta <= two_hours_sec:
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best_snap = snap

        regime = best_snap.trend_regime if best_snap else "unknown"
        if regime not in by_regime:
            by_regime[regime] = {"regime": regime, "pnl_cents": 0.0, "num_trades": 0}
        by_regime[regime]["pnl_cents"] += trade["pnl_cents"]
        by_regime[regime]["num_trades"] += 1

    return list(by_regime.values())


def _get_monthly_returns(equity_curve: List[Dict]) -> List[Dict]:
    """
    Compute monthly returns from an equity curve.
    Return as flat list of {year, month, return_pct}.
    """
    if not equity_curve:
        return []

    # Group by (year, month)
    monthly: Dict[tuple, List[float]] = {}
    for point in equity_curve:
        d = point["date"]
        if isinstance(d, datetime):
            d = d.date()
        key = (d.year, d.month)
        monthly.setdefault(key, []).append(point["equity_usd"])

    result = []
    for (year, month), equities in sorted(monthly.items()):
        if len(equities) < 2:
            result.append({"year": year, "month": month, "return_pct": None})
            continue
        first_eq = equities[0]
        last_eq = equities[-1]
        if first_eq == 0:
            result.append({"year": year, "month": month, "return_pct": None})
            continue
        ret_pct = (last_eq / first_eq - 1) * 100
        result.append({"year": year, "month": month, "return_pct": ret_pct})

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_bot_metrics(
    db: Session,
    alloc_id: int,
    days: Optional[int] = None,
) -> Dict:
    """
    Compute full performance metrics for a single bot allocation.
    Cached for 5 minutes.
    """
    cache_key = _ckey("bot_metrics", alloc_id, days)
    cached = _cget(cache_key, _DEFAULT_TTL)
    if cached is not None:
        return cached

    # Fetch allocation and profile
    alloc = db.query(BotAllocation).filter(BotAllocation.id == alloc_id).first()
    if not alloc:
        logger.warning("compute_bot_metrics: allocation %d not found", alloc_id)
        result = {"allocation_id": alloc_id, "error": "not found"}
        _cset(cache_key, result)
        return result

    profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
    bot_name = profile.name if profile else f"alloc_{alloc_id}"
    starting_capital_cents = alloc.starting_capital_cents or 0
    starting_capital_usd = starting_capital_cents / 100

    # All BotDailyPnL rows (no day filter) for equity curve
    all_pnl_rows = (
        db.query(BotDailyPnL)
        .filter(BotDailyPnL.allocation_id == alloc_id)
        .order_by(BotDailyPnL.date)
        .all()
    )
    data_days = len(all_pnl_rows)

    # Full equity curve (all time)
    full_curve = _build_equity_curve(all_pnl_rows, starting_capital_cents)

    # Today's PnL from most recent row
    today_pnl_usd = None
    if all_pnl_rows:
        last_row = all_pnl_rows[-1]
        realized = last_row.realized_cents or 0
        unrealized = last_row.unrealized_cents or 0
        fees = last_row.fees_cents or 0
        today_pnl_usd = (realized + unrealized - fees) / 100

    # Total return (all time)
    total_return_pct = None
    total_return_usd = None
    if full_curve and starting_capital_usd > 0:
        final_equity = full_curve[-1]["equity_usd"]
        total_return_usd = final_equity - starting_capital_usd
        total_return_pct = (total_return_usd / starting_capital_usd) * 100

    # Period return (filtered by days)
    period_return_pct = None
    period_curve = full_curve
    if days is not None:
        period_curve = full_curve[-days:] if len(full_curve) > days else full_curve
    if period_curve and len(period_curve) >= 2:
        start_eq = period_curve[0]["equity_usd"]
        end_eq = period_curve[-1]["equity_usd"]
        if start_eq > 0:
            period_return_pct = (end_eq / start_eq - 1) * 100

    # Daily returns for Sharpe/Sortino
    def _daily_returns_from_curve(curve: List[Dict]) -> List[float]:
        rets = []
        for i in range(1, len(curve)):
            prev = curve[i - 1]["equity_usd"]
            curr = curve[i]["equity_usd"]
            if prev > 0:
                rets.append((curr - prev) / prev)
        return rets

    all_daily_returns = _daily_returns_from_curve(full_curve)
    period_daily_returns = _daily_returns_from_curve(period_curve)

    sharpe_val = sharpe(period_daily_returns if days else all_daily_returns)
    sortino_val = sortino(period_daily_returns if days else all_daily_returns)

    # Max drawdown
    equity_series = [p["equity_usd"] for p in full_curve]
    dd_pct, dd_usd = max_drawdown(equity_series)

    # Calmar
    calmar_val = None
    if total_return_pct is not None and dd_pct is not None:
        # Approximate annualized return: scale by 252/data_days
        ann_factor = 252 / data_days if data_days > 0 else 1
        ann_return = total_return_pct * ann_factor / 100
        calmar_val = calmar(ann_return, dd_pct)

    # Closed trade stats
    since_date = None
    if days is not None:
        since_date = (datetime.utcnow() - timedelta(days=days)).date()

    closed_trades = _get_closed_trade_pnls(db, [alloc_id], since_date=since_date)
    total_trades = len(closed_trades)

    wins = [t for t in closed_trades if t["pnl_cents"] > 0]
    losses = [t for t in closed_trades if t["pnl_cents"] <= 0]

    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else None
    total_win = sum(t["pnl_cents"] for t in wins)
    total_loss = abs(sum(t["pnl_cents"] for t in losses))
    profit_factor = total_win / total_loss if total_loss > 0 else None
    avg_win_usd = (total_win / len(wins) / 100) if wins else None
    avg_loss_usd = (total_loss / len(losses) / 100) if losses else None
    win_loss_ratio = (avg_win_usd / avg_loss_usd) if avg_win_usd and avg_loss_usd and avg_loss_usd != 0 else None

    hold_hours = [t["hold_hours"] for t in closed_trades if t["hold_hours"] is not None]
    avg_hold_hours = sum(hold_hours) / len(hold_hours) if hold_hours else None

    best_trade_usd = max((t["pnl_cents"] for t in closed_trades), default=None)
    worst_trade_usd = min((t["pnl_cents"] for t in closed_trades), default=None)
    if best_trade_usd is not None:
        best_trade_usd /= 100
    if worst_trade_usd is not None:
        worst_trade_usd /= 100

    # Open positions
    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == alloc_id,
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .count()
    )

    result = {
        "allocation_id": alloc_id,
        "bot_name": bot_name,
        "starting_capital_usd": starting_capital_usd,
        "total_return_pct": total_return_pct,
        "total_return_usd": total_return_usd,
        "today_pnl_usd": today_pnl_usd,
        "period_return_pct": period_return_pct,
        "sharpe": sharpe_val,
        "sortino": sortino_val,
        "calmar": calmar_val,
        "max_drawdown_pct": dd_pct,
        "max_drawdown_usd": dd_usd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win_usd": avg_win_usd,
        "avg_loss_usd": avg_loss_usd,
        "win_loss_ratio": win_loss_ratio,
        "avg_hold_hours": avg_hold_hours,
        "best_trade_usd": best_trade_usd,
        "worst_trade_usd": worst_trade_usd,
        "total_trades": total_trades,
        "open_positions": open_positions,
        "data_days": data_days,
    }

    _cset(cache_key, result)
    return result


def compute_portfolio_metrics(
    db: Session,
    user_id: int,
    days: Optional[int] = None,
) -> Dict:
    """
    Compute aggregated performance metrics across all enabled allocations for a user.
    Cached for 5 minutes.
    """
    cache_key = _ckey("portfolio_metrics", user_id, days)
    cached = _cget(cache_key, _DEFAULT_TTL)
    if cached is not None:
        return cached

    allocations = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id, BotAllocation.enabled == True)
        .all()
    )

    if not allocations:
        logger.warning("compute_portfolio_metrics: no enabled allocations for user %d", user_id)
        result = {
            "allocation_id": None,
            "bot_name": "Portfolio",
            "starting_capital_usd": 0.0,
            "total_return_pct": None,
            "total_return_usd": None,
            "today_pnl_usd": None,
            "period_return_pct": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "max_drawdown_pct": None,
            "max_drawdown_usd": None,
            "win_rate": None,
            "profit_factor": None,
            "avg_win_usd": None,
            "avg_loss_usd": None,
            "win_loss_ratio": None,
            "avg_hold_hours": None,
            "best_trade_usd": None,
            "worst_trade_usd": None,
            "total_trades": 0,
            "open_positions": 0,
            "data_days": 0,
        }
        _cset(cache_key, result)
        return result

    alloc_ids = [a.id for a in allocations]
    total_starting_capital_cents = sum(a.starting_capital_cents or 0 for a in allocations)
    starting_capital_usd = total_starting_capital_cents / 100

    # Aggregate daily PnL rows across all allocations by date
    all_pnl_rows = (
        db.query(BotDailyPnL)
        .filter(BotDailyPnL.allocation_id.in_(alloc_ids))
        .order_by(BotDailyPnL.date)
        .all()
    )

    # Merge rows by date: sum pnl values per day
    from collections import defaultdict
    daily_merged: Dict[Any, Dict] = defaultdict(lambda: {
        "date": None,
        "realized_cents": 0,
        "unrealized_cents": 0,
        "fees_cents": 0,
        "portfolio_value_eod_cents": 0,
        "_has_portfolio_value": False,
    })

    for row in all_pnl_rows:
        d = row.date
        daily_merged[d]["date"] = d
        daily_merged[d]["realized_cents"] += row.realized_cents or 0
        daily_merged[d]["unrealized_cents"] += row.unrealized_cents or 0
        daily_merged[d]["fees_cents"] += row.fees_cents or 0
        if row.portfolio_value_eod_cents is not None:
            daily_merged[d]["portfolio_value_eod_cents"] += row.portfolio_value_eod_cents
            daily_merged[d]["_has_portfolio_value"] = True

    # Build synthetic row-like objects for equity curve
    class _SyntheticRow:
        def __init__(self, d):
            self.date = d["date"]
            self.realized_cents = d["realized_cents"]
            self.unrealized_cents = d["unrealized_cents"]
            self.fees_cents = d["fees_cents"]
            self.portfolio_value_eod_cents = (
                d["portfolio_value_eod_cents"] if d["_has_portfolio_value"] else None
            )

    merged_rows = sorted(
        [_SyntheticRow(v) for v in daily_merged.values()],
        key=lambda r: r.date,
    )
    data_days = len(merged_rows)

    full_curve = _build_equity_curve(merged_rows, total_starting_capital_cents)

    # Today's PnL
    today_pnl_usd = None
    if merged_rows:
        last = merged_rows[-1]
        today_pnl_usd = (
            (last.realized_cents + last.unrealized_cents - last.fees_cents) / 100
        )

    # Total return
    total_return_pct = None
    total_return_usd = None
    if full_curve and starting_capital_usd > 0:
        final_equity = full_curve[-1]["equity_usd"]
        total_return_usd = final_equity - starting_capital_usd
        total_return_pct = (total_return_usd / starting_capital_usd) * 100

    # Period return
    period_return_pct = None
    period_curve = full_curve
    if days is not None:
        period_curve = full_curve[-days:] if len(full_curve) > days else full_curve
    if period_curve and len(period_curve) >= 2:
        start_eq = period_curve[0]["equity_usd"]
        end_eq = period_curve[-1]["equity_usd"]
        if start_eq > 0:
            period_return_pct = (end_eq / start_eq - 1) * 100

    def _daily_returns_from_curve(curve):
        rets = []
        for i in range(1, len(curve)):
            prev = curve[i - 1]["equity_usd"]
            curr = curve[i]["equity_usd"]
            if prev > 0:
                rets.append((curr - prev) / prev)
        return rets

    use_curve = period_curve if days else full_curve
    daily_returns = _daily_returns_from_curve(use_curve)

    sharpe_val = sharpe(daily_returns)
    sortino_val = sortino(daily_returns)

    equity_series = [p["equity_usd"] for p in full_curve]
    dd_pct, dd_usd = max_drawdown(equity_series)

    calmar_val = None
    if total_return_pct is not None and dd_pct is not None and data_days > 0:
        ann_factor = 252 / data_days
        ann_return = total_return_pct * ann_factor / 100
        calmar_val = calmar(ann_return, dd_pct)

    since_date = None
    if days is not None:
        since_date = (datetime.utcnow() - timedelta(days=days)).date()

    closed_trades = _get_closed_trade_pnls(db, alloc_ids, since_date=since_date)
    total_trades = len(closed_trades)

    wins = [t for t in closed_trades if t["pnl_cents"] > 0]
    losses = [t for t in closed_trades if t["pnl_cents"] <= 0]
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else None
    total_win = sum(t["pnl_cents"] for t in wins)
    total_loss = abs(sum(t["pnl_cents"] for t in losses))
    profit_factor = total_win / total_loss if total_loss > 0 else None
    avg_win_usd = (total_win / len(wins) / 100) if wins else None
    avg_loss_usd = (total_loss / len(losses) / 100) if losses else None
    win_loss_ratio = (avg_win_usd / avg_loss_usd) if avg_win_usd and avg_loss_usd and avg_loss_usd != 0 else None

    hold_hours = [t["hold_hours"] for t in closed_trades if t["hold_hours"] is not None]
    avg_hold_hours = sum(hold_hours) / len(hold_hours) if hold_hours else None

    best_trade_usd = max((t["pnl_cents"] for t in closed_trades), default=None)
    worst_trade_usd = min((t["pnl_cents"] for t in closed_trades), default=None)
    if best_trade_usd is not None:
        best_trade_usd /= 100
    if worst_trade_usd is not None:
        worst_trade_usd /= 100

    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .count()
    )

    result = {
        "allocation_id": None,
        "bot_name": "Portfolio",
        "starting_capital_usd": starting_capital_usd,
        "total_return_pct": total_return_pct,
        "total_return_usd": total_return_usd,
        "today_pnl_usd": today_pnl_usd,
        "period_return_pct": period_return_pct,
        "sharpe": sharpe_val,
        "sortino": sortino_val,
        "calmar": calmar_val,
        "max_drawdown_pct": dd_pct,
        "max_drawdown_usd": dd_usd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win_usd": avg_win_usd,
        "avg_loss_usd": avg_loss_usd,
        "win_loss_ratio": win_loss_ratio,
        "avg_hold_hours": avg_hold_hours,
        "best_trade_usd": best_trade_usd,
        "worst_trade_usd": worst_trade_usd,
        "total_trades": total_trades,
        "open_positions": open_positions,
        "data_days": data_days,
    }

    _cset(cache_key, result)
    return result


def compute_leaderboard(
    db: Session,
    user_id: int,
    metric: str = "sharpe",
    days: int = 30,
) -> List[Dict]:
    """
    Compute a leaderboard across all enabled allocations for a user.
    Returns list sorted by the requested metric (None values last).
    """
    cache_key = _ckey("leaderboard", user_id, metric, days)
    cached = _cget(cache_key, _DEFAULT_TTL)
    if cached is not None:
        return cached

    allocations = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id, BotAllocation.enabled == True)
        .all()
    )

    if not allocations:
        _cset(cache_key, [])
        return []

    rows = []
    for alloc in allocations:
        metrics = compute_bot_metrics(db, alloc.id, days=days)
        profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        rows.append({
            "allocation_id": alloc.id,
            "bot_name": profile.name if profile else f"alloc_{alloc.id}",
            "sharpe": metrics.get("sharpe"),
            "total_return_pct": metrics.get("total_return_pct"),
            "win_rate": metrics.get("win_rate"),
            "profit_factor": metrics.get("profit_factor"),
            "total_trades": metrics.get("total_trades", 0),
            "today_pnl_usd": metrics.get("today_pnl_usd"),
        })

    valid_metric = metric if metric in ("sharpe", "total_return_pct", "win_rate", "profit_factor", "today_pnl_usd") else "sharpe"

    rows.sort(
        key=lambda x: (x[valid_metric] is None, -(x[valid_metric] or 0))
    )

    _cset(cache_key, rows)
    return rows


# ---------------------------------------------------------------------------
# Strategy Leaderboard (cross-bot, cross-source aggregation)
# ---------------------------------------------------------------------------

def compute_strategy_leaderboard(
    db: Session,
    user_id: int,
    period_days: Optional[int] = 30,
    sort_by: str = "pnl",
) -> List[Dict]:
    """
    Aggregate every strategy's performance across all sources (bot_signals,
    user_scout_signals, user_forge_signals). Returns dollar-weighted metrics.
    """
    cache_key = _ckey("strategy_lb", user_id, period_days, sort_by)
    cached = _cget(cache_key, _EQUITY_CURVE_TTL)
    if cached is not None:
        return cached

    try:
        from strategy_lab.scout_catalog import SCOUT_CATALOG
    except ImportError:
        SCOUT_CATALOG = {}

    since_dt = None
    if period_days:
        since_dt = datetime.now(timezone.utc) - timedelta(days=period_days)

    # Structure: strategy_id -> {pnl_cents, capital_deployed_cents, trades, wins, losses, bots_using, source}
    agg: Dict[str, Dict] = {}

    def _ensure(sid: str, source: str = "bot") -> Dict:
        if sid not in agg:
            agg[sid] = {
                "strategy_id": sid,
                "pnl_cents": 0.0,
                "capital_deployed_cents": 0.0,
                "num_trades": 0,
                "wins": 0,
                "losses": 0,
                "bots_using": set(),
                "source": source,
            }
        return agg[sid]

    # ── Prebuilt bot strategies (via realized P&L) ────────────────────────
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id, BotAllocation.enabled == True)
        .all()
    )
    for alloc in allocs:
        profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        bot_label = profile.name if profile else f"alloc_{alloc.id}"
        capital = alloc.starting_capital_cents or 0

        closed = _get_closed_trade_pnls(db, [alloc.id], since_date=since_dt)
        if not closed:
            continue

        # Match each closed position to nearest signal for strategy attribution
        signals = (
            db.query(BotSignal)
            .filter(
                BotSignal.allocation_id == alloc.id,
                BotSignal.is_test.isnot(True),
            )
            .all()
        )
        sig_map: Dict[str, List] = {}
        for sig in signals:
            sig_map.setdefault(sig.symbol, []).append(sig)

        for trade in closed:
            sym = trade["symbol"]
            opened_at = trade["opened_at"]
            strategy_id = "unattributed"
            if sym in sig_map and opened_at:
                best, best_delta = None, None
                for sig in sig_map[sym]:
                    sig_ts = sig.ts
                    if sig_ts.tzinfo is None and opened_at.tzinfo is not None:
                        sig_ts = sig_ts.replace(tzinfo=timezone.utc)
                    elif sig_ts.tzinfo is not None and opened_at.tzinfo is None:
                        sig_ts = sig_ts.replace(tzinfo=None)
                    d = abs((sig_ts - opened_at).total_seconds())
                    if d <= 600 and (best_delta is None or d < best_delta):
                        best_delta = d
                        best = sig
                if best and best.strategy:
                    strategy_id = best.strategy

            entry = _ensure(strategy_id, "bot")
            entry["pnl_cents"] += trade["pnl_cents"]
            entry["num_trades"] += 1
            # Approximate capital deployed = qty * avg_cost (entry value)
            entry["capital_deployed_cents"] += capital / max(len(closed), 1)
            entry["bots_using"].add(bot_label)
            if trade["pnl_cents"] > 0:
                entry["wins"] += 1
            else:
                entry["losses"] += 1

    # ── Scout signals (theoretical return from entry→target) ─────────────
    try:
        from app.db.models.scout import UserScoutSignal
        scout_q = db.query(UserScoutSignal).filter(UserScoutSignal.user_id == user_id)
        if since_dt:
            scout_q = scout_q.filter(UserScoutSignal.created_at >= since_dt)
        for sig in scout_q.all():
            if not sig.strategy_id:
                continue
            entry = _ensure(sig.strategy_id, "scout")
            entry["bots_using"].add("scout")
            entry["num_trades"] += 1
            if sig.entry_price and sig.target_price and sig.entry_price > 0:
                theoretical_pct = (sig.target_price - sig.entry_price) / sig.entry_price
                theoretical_cents = theoretical_pct * (sig.entry_price * 100 * 10)  # ~10 share notional
                entry["pnl_cents"] += theoretical_cents * sig.confidence
                entry["capital_deployed_cents"] += sig.entry_price * 100 * 10
                if theoretical_pct > 0:
                    entry["wins"] += 1
                else:
                    entry["losses"] += 1
    except Exception as exc:
        logger.warning("strategy_lb: scout pass failed: %s", exc)

    # ── Forge signals (theoretical return) ───────────────────────────────
    try:
        from app.db.models.forge import UserForgeSignal
        forge_q = db.query(UserForgeSignal).filter(UserForgeSignal.user_id == user_id)
        if since_dt:
            forge_q = forge_q.filter(UserForgeSignal.created_at >= since_dt)
        for sig in forge_q.all():
            if not sig.strategy_id:
                continue
            entry = _ensure(sig.strategy_id, "forge")
            entry["bots_using"].add(f"forge:{sig.forge_bot_id}")
            entry["num_trades"] += 1
            if sig.entry_price and sig.target_price and sig.entry_price > 0:
                theoretical_pct = (sig.target_price - sig.entry_price) / sig.entry_price
                theoretical_cents = theoretical_pct * (sig.entry_price * 100 * 10)
                entry["pnl_cents"] += theoretical_cents * sig.confidence
                entry["capital_deployed_cents"] += sig.entry_price * 100 * 10
                if theoretical_pct > 0:
                    entry["wins"] += 1
                else:
                    entry["losses"] += 1
    except Exception as exc:
        logger.warning("strategy_lb: forge pass failed: %s", exc)

    # ── Build output rows ─────────────────────────────────────────────────
    rows = []
    for sid, data in agg.items():
        cat_info = SCOUT_CATALOG.get(sid, {})
        total_trades = data["num_trades"]
        pnl_usd = data["pnl_cents"] / 100
        capital_usd = data["capital_deployed_cents"] / 100
        win_rate = (data["wins"] / total_trades) if total_trades > 0 else None
        w_return = (pnl_usd / capital_usd) if capital_usd > 0 else None
        rows.append({
            "strategy_id": sid,
            "strategy_name": cat_info.get("display_name", sid.replace("_", " ").title()),
            "category": cat_info.get("category", "Unknown"),
            "total_pnl_usd": round(pnl_usd, 2),
            "weighted_return_pct": round(w_return, 4) if w_return is not None else None,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "sharpe": None,  # would need daily timeseries per strategy — expensive, skip for now
            "bots_using": len(data["bots_using"]),
            "source": data["source"],
        })

    valid_sorts = {"pnl": "total_pnl_usd", "return": "weighted_return_pct",
                   "win_rate": "win_rate", "trades": "total_trades", "sharpe": "sharpe"}
    sort_field = valid_sorts.get(sort_by, "total_pnl_usd")
    rows.sort(key=lambda x: (x[sort_field] is None, -(x[sort_field] or 0)))

    _cset(cache_key, rows, _EQUITY_CURVE_TTL)
    return rows
