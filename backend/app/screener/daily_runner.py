from __future__ import annotations

"""
Daily automation engine.

Runs every weekday at 4:05 PM ET (after market close):
  1. Check market regime (SPY vs 200-day MA)
  2. Run all 19 screener presets → add new candidates
  3. Check entry triggers on existing candidates → open positions
  4. Expire stale candidates (> 14 calendar days)
  5. Mark-to-market open positions, apply stop/target/time exits
  6. Write daily log entries
  7. Snapshot equity curve
"""

import asyncio
import logging
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Set

import pandas as pd
import ta
import yfinance as yf
from sqlalchemy.orm import Session

from app.db.models.strategy import DailyEquitySnapshot, DailyLog, StrategyTrade
from app.db.models.paper import PaperAccount, PaperOrder, PaperPosition, PaperTransaction, STARTING_BALANCE
from app.db.session import SessionLocal
from app.screener.entry_triggers import (
    CANDIDATE_MAX_DAYS,
    CONVICTION,
    MOMENTUM_PRESETS,
    R_MULTIPLE,
    RISK_DOLLARS,
    TRIGGER_MAP,
)
from app.alpaca.assets import get_universe
from app.screener.filters import PRESET_SCREENS
from app.screener.runner import _fetch_bars_sync, run_screen, run_screen_sync

logger = logging.getLogger(__name__)

PAPER_PORTFOLIO = 100_000.0
MAX_CANDIDATES_PER_STRATEGY = 15  # max watching per strategy (keeps list manageable)
MAX_HOLD_DAYS = 30
MAX_POSITION_VALUE = 5_000.0     # cap each position at $5k (5% of portfolio)
MAX_OPEN_PER_STRATEGY = 5        # no single strategy monopolises capital
MAX_TOTAL_OPEN = 25              # hard ceiling across all 19 strategies

PRESET_LABELS: Dict[str, str] = {
    "canslim_leaders":        "CAN SLIM Leaders",
    "stage2_breakout":        "Stage 2 Breakout",
    "momentum_surge":         "Momentum Surge",
    "high_rs_momentum":       "High RS Leaders",
    "power_trend":            "Power Trend",
    "mean_reversion_quality": "Quality Dip Buy",
    "deep_value_bounce":      "Quality Oversold",
    "volatility_contraction": "Volatility Squeeze",
    "ema_stack_uptrend":      "EMA Stack",
    "consecutive_gains":      "Momentum Continuation",
    "rsi_oversold":           "RSI Oversold",
    "golden_cross":           "Golden Cross",
    "macd_bullish":           "MACD Crossover",
    "volume_surge":           "Volume Surge",
    "breakout_52w":           "52-Week High",
    "turtle_breakout":        "Turtle Breakout",
    "momentum_12m":           "12-Month Momentum",
    "zscore_reversion":       "Z-Score Reversion",
    "darvas_box":             "Darvas Box",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    try:
        atr_series = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=period
        ).average_true_range()
        val = float(atr_series.iloc[-1])
        return val if val > 0 else float(df["close"].iloc[-1]) * 0.02
    except Exception:
        return float(df["close"].iloc[-1]) * 0.02


def _get_prices_sync(symbols: List[str]) -> Dict[str, float]:
    if not symbols:
        return {}
    prices: Dict[str, float] = {}
    missing: List[str] = []

    # Real-time prices when market is open
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                p = tickers.tickers[sym].fast_info.last_price
                if p and p > 0:
                    prices[sym] = float(p)
                else:
                    missing.append(sym)
            except Exception:
                missing.append(sym)
    except Exception as e:
        logger.error(f"Price fetch error: {e}", exc_info=True)
        missing = list(symbols)

    # Fallback for market-closed / missing: last close from recent history
    if missing:
        try:
            data = yf.download(missing, period="5d", progress=False, auto_adjust=True)
            if not data.empty:
                closes = data["Close"]
                if len(missing) == 1:
                    col = closes.dropna()
                    if not col.empty:
                        last = col.iloc[-1]
                        if last and last > 0:
                            prices[missing[0]] = float(last)
                else:
                    for sym in missing:
                        try:
                            col = closes[sym].dropna()
                            if not col.empty:
                                last = col.iloc[-1]
                                if last and last > 0:
                                    prices[sym] = float(last)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Price history fallback error: {e}", exc_info=True)

    return prices


def _get_prev_closes_sync(symbols: List[str]) -> Dict[str, float]:
    """Return the previous session's closing price for each symbol."""
    if not symbols:
        return {}
    prev: Dict[str, float] = {}
    try:
        data = yf.download(symbols, period="5d", progress=False, auto_adjust=True)
        if not data.empty:
            closes = data["Close"]
            if len(symbols) == 1:
                col = closes.dropna()
                if len(col) >= 2:
                    prev[symbols[0]] = float(col.iloc[-2])
                elif len(col) == 1:
                    prev[symbols[0]] = float(col.iloc[-1])
            else:
                for sym in symbols:
                    try:
                        col = closes[sym].dropna()
                        if len(col) >= 2:
                            prev[sym] = float(col.iloc[-2])
                        elif len(col) == 1:
                            prev[sym] = float(col.iloc[-1])
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Prev-close fetch error: {e}", exc_info=True)
    return prev


def _add_log(
    db: Session,
    log_date: date,
    event_type: str,
    notes: str,
    user_id: int,
    symbol: str | None = None,
    preset_key: str | None = None,
    price: float | None = None,
    pnl_pct: float | None = None,
    trade_id: int | None = None,
) -> None:
    db.add(DailyLog(
        log_date=log_date,
        event_type=event_type,
        symbol=symbol,
        preset_key=preset_key,
        preset_label=PRESET_LABELS.get(preset_key or "", preset_key) if preset_key else None,
        price=price,
        pnl_pct=pnl_pct,
        notes=notes,
        trade_id=trade_id,
        user_id=user_id,
    ))


# ---------------------------------------------------------------------------
# Step 1: Market regime
# ---------------------------------------------------------------------------

def _check_regime_sync() -> str:
    try:
        df_dict = _fetch_bars_sync(["SPY"], period="1y")
        df = df_dict.get("SPY")
        if df is None or len(df) < 200:
            return "unknown"
        sma200 = df["close"].rolling(200).mean().iloc[-1]
        return "bull" if df["close"].iloc[-1] > sma200 else "risk_off"
    except Exception as e:
        logger.error(f"Regime check failed: {e}", exc_info=True)
        return "unknown"


# ---------------------------------------------------------------------------
# Step 2: Screen all presets → collect candidate symbols
# ---------------------------------------------------------------------------

async def _collect_screen_results(regime: str, universe_bars: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Apply all preset screens to pre-fetched universe bars (one download for all screeners)."""
    results: Dict[str, Set[str]] = {}
    loop = asyncio.get_running_loop()
    for preset_key, filter_configs in PRESET_SCREENS.items():
        if regime == "risk_off" and preset_key in MOMENTUM_PRESETS:
            logger.info(f"Skipping {preset_key} — risk-off regime")
            continue
        try:
            matches = await loop.run_in_executor(None, lambda fc=filter_configs: run_screen_sync(fc, universe_bars))
            results[preset_key] = {r["symbol"] for r in matches}
            logger.info(f"Screened {preset_key}: {len(results[preset_key])} hits")
        except Exception as e:
            logger.error(f"Screen error for {preset_key}: {e}", exc_info=True)
    return results


# ---------------------------------------------------------------------------
# Step 3: Add new candidates
# ---------------------------------------------------------------------------

def _add_candidates(
    db: Session,
    screen_results: Dict[str, Set[str]],
    today: date,
    user_id: int,
) -> List[StrategyTrade]:
    tracked = db.query(StrategyTrade).filter(
        StrategyTrade.status.in_(["open", "candidate"]),
        StrategyTrade.user_id == user_id,
    ).all()
    existing_pairs: set = {(t.preset_key, t.symbol) for t in tracked}
    candidates_per_preset: Dict[str, int] = {}
    for t in tracked:
        if t.status == "candidate":
            candidates_per_preset[t.preset_key] = candidates_per_preset.get(t.preset_key, 0) + 1

    new_candidates: List[StrategyTrade] = []
    for preset_key, symbols in screen_results.items():
        watching_count = candidates_per_preset.get(preset_key, 0)
        trigger_fn = TRIGGER_MAP.get(preset_key)
        trigger_name = trigger_fn.__name__ if trigger_fn else "auto"
        for sym in symbols:
            if (preset_key, sym) in existing_pairs:
                continue
            if watching_count >= MAX_CANDIDATES_PER_STRATEGY:
                break
            trade = StrategyTrade(
                preset_key=preset_key,
                symbol=sym,
                status="candidate",
                candidate_since=_now(),
                entry_trigger=trigger_name,
                entry_price=0.0,
                shares=0.0,
                stop_price=0.0,
                target_price=0.0,
                user_id=user_id,
            )
            db.add(trade)
            new_candidates.append(trade)
            watching_count += 1

    db.flush()
    return new_candidates


# ---------------------------------------------------------------------------
# Step 4: Check entry triggers on candidates
# ---------------------------------------------------------------------------

def _process_candidates(
    db: Session,
    today: date,
    bars: Dict[str, pd.DataFrame],
    prices: Dict[str, float],
    user_id: int,
) -> List[StrategyTrade]:
    candidates = db.query(StrategyTrade).filter(
        StrategyTrade.status == "candidate",
        StrategyTrade.user_id == user_id,
    ).all()
    entered: List[StrategyTrade] = []

    # Pre-compute current open position counts for capital guardrails
    open_trades = db.query(StrategyTrade).filter(
        StrategyTrade.status == "open",
        StrategyTrade.user_id == user_id,
    ).all()
    total_open = len(open_trades)
    open_per_strategy: Dict[str, int] = {}
    for t in open_trades:
        open_per_strategy[t.preset_key] = open_per_strategy.get(t.preset_key, 0) + 1

    for trade in candidates:
        # Hard ceiling — portfolio full
        if total_open >= MAX_TOTAL_OPEN:
            break

        days_waiting = (today - (trade.candidate_since or _now()).date()).days
        # Let candidates settle one day before checking triggers — except _next_open
        # which is explicitly designed to enter on the very next run
        if days_waiting == 0 and trade.entry_trigger != "_next_open":
            continue
        # Expiry check
        if days_waiting > CANDIDATE_MAX_DAYS:
            trade.status = "closed"
            trade.exit_reason = "expired"
            trade.exit_date = _now()
            trade.exit_price = prices.get(trade.symbol, 0.0)
            db.add(trade)
            continue

        # Per-strategy cap
        if open_per_strategy.get(trade.preset_key, 0) >= MAX_OPEN_PER_STRATEGY:
            continue

        df = bars.get(trade.symbol)
        current_price = prices.get(trade.symbol)
        if df is None or not current_price or current_price <= 0:
            continue

        trigger_fn = TRIGGER_MAP.get(trade.preset_key)
        if trigger_fn is None or not trigger_fn(df, trade):
            continue

        # Trigger fired — compute ATR-based position sizing
        atr = _compute_atr(df)
        stop_dist = max(2.0 * atr, current_price * 0.05)  # floor at 5%
        conviction = CONVICTION.get(trade.preset_key, "low")
        risk_amt = RISK_DOLLARS[conviction]
        r_mult = R_MULTIPLE.get(trade.preset_key, 2.0)
        shares = risk_amt / stop_dist
        # Cap position value so no single trade ties up too much capital
        shares = min(shares, MAX_POSITION_VALUE / current_price)

        trade.status = "open"
        trade.entry_date = _now()
        trade.entry_price = current_price
        trade.shares = round(shares, 4)
        trade.stop_price = round(current_price - stop_dist, 4)
        trade.target_price = round(current_price + r_mult * stop_dist, 4)
        trade.atr = round(atr, 4)
        trade.risk_dollars = risk_amt
        trade.entry_notes = f"Trigger: {trade.entry_trigger or 'auto'}"
        db.add(trade)
        entered.append(trade)

        # Update running counts so subsequent candidates see the new state
        total_open += 1
        open_per_strategy[trade.preset_key] = open_per_strategy.get(trade.preset_key, 0) + 1

    return entered


# ---------------------------------------------------------------------------
# Step 5: Update open positions — apply exits
# ---------------------------------------------------------------------------

def _update_positions(
    db: Session,
    today: date,
    prices: Dict[str, float],
    user_id: int,
) -> List[StrategyTrade]:
    open_trades = db.query(StrategyTrade).filter(
        StrategyTrade.status == "open",
        StrategyTrade.user_id == user_id,
    ).all()
    now = _now()
    exited: List[StrategyTrade] = []

    for trade in open_trades:
        current = prices.get(trade.symbol)
        if not current or current <= 0:
            continue

        days_held = (today - trade.entry_date.date()).days if trade.entry_date else 0
        exit_reason = None

        if current <= trade.stop_price:
            exit_reason = "stop"
        elif current >= trade.target_price:
            exit_reason = "target"
        elif days_held >= MAX_HOLD_DAYS:
            exit_reason = "time"

        if exit_reason:
            trade.status = "closed"
            trade.exit_price = current
            trade.exit_date = now
            trade.exit_reason = exit_reason
            db.add(trade)
            exited.append(trade)

    return exited


# ---------------------------------------------------------------------------
# Step 6: Equity snapshot
# ---------------------------------------------------------------------------

def _snapshot_equity(
    db: Session,
    today: date,
    prices: Dict[str, float],
    new_entries: int,
    exits_today: int,
    user_id: int,
) -> None:
    if today.isoweekday() >= 6:  # never snapshot on weekends
        return
    # Realized P&L from all closed non-expired trades for this user
    closed = db.query(StrategyTrade).filter(
        StrategyTrade.status == "closed",
        StrategyTrade.exit_reason.notin_(["expired"]),
        StrategyTrade.user_id == user_id,
    ).all()
    realized = sum(
        ((t.exit_price - t.entry_price) * t.shares)
        for t in closed
        if t.exit_price and t.entry_price and t.shares and t.entry_price > 0
    )

    # Open P&L
    open_trades = db.query(StrategyTrade).filter(
        StrategyTrade.status == "open",
        StrategyTrade.user_id == user_id,
    ).all()
    open_pnl = sum(
        ((prices.get(t.symbol, t.entry_price) - t.entry_price) * t.shares)
        for t in open_trades
        if t.entry_price and t.entry_price > 0 and t.shares
    )
    candidates_count = db.query(StrategyTrade).filter(
        StrategyTrade.status == "candidate",
        StrategyTrade.user_id == user_id,
    ).count()

    # Upsert snapshot (per user + date)
    existing = db.query(DailyEquitySnapshot).filter(
        DailyEquitySnapshot.snapshot_date == today,
        DailyEquitySnapshot.user_id == user_id,
    ).first()
    if existing:
        snap = existing
    else:
        snap = DailyEquitySnapshot(snapshot_date=today, user_id=user_id)
        db.add(snap)

    snap.portfolio_value = round(PAPER_PORTFOLIO + realized + open_pnl, 2)
    snap.realized_pnl = round(realized, 2)
    snap.open_pnl = round(open_pnl, 2)
    snap.open_positions = len(open_trades)
    snap.candidates = candidates_count
    snap.new_entries = new_entries
    snap.exits_today = exits_today


# ---------------------------------------------------------------------------
# Auto-trading bridge: sync StrategyTrade records → PaperOrders
# ---------------------------------------------------------------------------

def _get_or_create_paper_account(db: Session, user_id: int) -> PaperAccount:
    acct = db.query(PaperAccount).filter_by(user_id=user_id).first()
    if not acct:
        acct = PaperAccount(
            user_id=user_id,
            cash=STARTING_BALANCE,
            starting_balance=STARTING_BALANCE,
        )
        db.add(acct)
        db.flush()
    return acct


def _sync_paper_orders(db: Session, user_id: int) -> None:
    """
    Bridge between StrategyTrade records and the paper trading system.

    1. For every open StrategyTrade that hasn't been placed yet (paper_order_placed=False),
       create a BUY PaperOrder, update PaperPosition, and deduct cash.
    2. For every closed StrategyTrade that was placed (paper_order_placed=True) but whose
       exit hasn't been placed yet (paper_sell_placed=False), create a SELL PaperOrder,
       update/remove PaperPosition, add cash, and write a PaperTransaction.
    """
    today = date.today()
    now = _now()

    # ------------------------------------------------------------------
    # Part 1: Open trades without a BUY order
    # ------------------------------------------------------------------
    unplaced_buys = db.query(StrategyTrade).filter(
        StrategyTrade.status == "open",
        StrategyTrade.user_id == user_id,
        StrategyTrade.paper_order_placed.is_(False),
    ).all()

    # Also catch rows where the column is NULL (older records before migration)
    unplaced_buys_null = db.query(StrategyTrade).filter(
        StrategyTrade.status == "open",
        StrategyTrade.user_id == user_id,
        StrategyTrade.paper_order_placed.is_(None),
    ).all()
    unplaced_buys = unplaced_buys + unplaced_buys_null

    for trade in unplaced_buys:
        if not trade.entry_price or trade.entry_price <= 0 or not trade.shares or trade.shares <= 0:
            logger.warning(f"Skipping auto-buy for {trade.symbol} (trade {trade.id}): invalid price/shares")
            trade.paper_order_placed = True  # mark to avoid retry spam
            db.add(trade)
            continue

        acct = _get_or_create_paper_account(db, user_id)
        total_cost = round(trade.entry_price * trade.shares, 4)

        if acct.cash < total_cost:
            logger.warning(
                f"Auto-buy skipped for {trade.symbol} (trade {trade.id}): "
                f"need ${total_cost:.2f}, have ${acct.cash:.2f}"
            )
            continue

        # Create the filled BUY order
        buy_order = PaperOrder(
            user_id=user_id,
            symbol=trade.symbol,
            side="buy",
            qty=trade.shares,
            order_type="market",
            tif="day",
            status="filled",
            fill_price=trade.entry_price,
            fill_qty=trade.shares,
            slippage=0.0,
            filled_at=trade.entry_date or now,
        )
        db.add(buy_order)
        db.flush()  # need buy_order.id

        # Update / create PaperPosition
        existing_pos = db.query(PaperPosition).filter_by(user_id=user_id, symbol=trade.symbol).first()
        if existing_pos:
            old_qty = existing_pos.qty
            new_qty = trade.shares
            total_qty = old_qty + new_qty
            existing_pos.avg_cost = round(
                (existing_pos.avg_cost * old_qty + trade.entry_price * new_qty) / total_qty, 6
            )
            existing_pos.qty = round(total_qty, 6)
        else:
            db.add(PaperPosition(
                user_id=user_id,
                symbol=trade.symbol,
                qty=trade.shares,
                avg_cost=trade.entry_price,
            ))

        # Deduct cash
        acct.cash = round(acct.cash - total_cost, 2)
        logger.info(
            f"CASH_CHANGE user={user_id} delta={-total_cost:.4f} "
            f"new_balance={acct.cash:.4f} reason='auto-buy {trade.symbol} "
            f"qty={trade.shares} @ {trade.entry_price}'"
        )

        trade.paper_order_placed = True
        db.add(trade)

        # Log the auto-entry event
        _add_log(
            db, today, "auto_entry",
            "Auto-placed by strategy agent",
            user_id=user_id,
            symbol=trade.symbol,
            preset_key=trade.preset_key,
            price=trade.entry_price,
            trade_id=trade.id,
        )
        logger.info(f"Auto-buy placed: {trade.symbol} {trade.shares} shares @ ${trade.entry_price}")

    # ------------------------------------------------------------------
    # Part 2: Closed trades that need a SELL order
    # ------------------------------------------------------------------
    unplaced_sells = db.query(StrategyTrade).filter(
        StrategyTrade.status == "closed",
        StrategyTrade.user_id == user_id,
        StrategyTrade.paper_order_placed.is_(True),
        StrategyTrade.paper_sell_placed.is_(False),
    ).all()

    unplaced_sells_null = db.query(StrategyTrade).filter(
        StrategyTrade.status == "closed",
        StrategyTrade.user_id == user_id,
        StrategyTrade.paper_order_placed.is_(True),
        StrategyTrade.paper_sell_placed.is_(None),
    ).all()
    unplaced_sells = unplaced_sells + unplaced_sells_null

    for trade in unplaced_sells:
        if not trade.exit_price or trade.exit_price <= 0 or not trade.shares or trade.shares <= 0:
            logger.warning(f"Skipping auto-sell for {trade.symbol} (trade {trade.id}): invalid exit_price/shares")
            trade.paper_sell_placed = True
            db.add(trade)
            continue

        position = db.query(PaperPosition).filter_by(user_id=user_id, symbol=trade.symbol).first()
        if not position:
            logger.warning(
                f"Auto-sell skipped for {trade.symbol} (trade {trade.id}): no open position found"
            )
            trade.paper_sell_placed = True
            db.add(trade)
            continue

        # Sell quantity is the lesser of strategy shares and actual position qty
        sell_qty = min(trade.shares, position.qty)
        if sell_qty <= 0:
            logger.warning(f"Auto-sell skipped for {trade.symbol} (trade {trade.id}): position qty is 0")
            trade.paper_sell_placed = True
            db.add(trade)
            continue

        total_proceeds = round(trade.exit_price * sell_qty, 4)
        cost_basis = position.avg_cost
        realized_pnl = round((trade.exit_price - cost_basis) * sell_qty, 4)

        # Create filled SELL order
        sell_order = PaperOrder(
            user_id=user_id,
            symbol=trade.symbol,
            side="sell",
            qty=sell_qty,
            order_type="market",
            tif="day",
            status="filled",
            fill_price=trade.exit_price,
            fill_qty=sell_qty,
            slippage=0.0,
            filled_at=trade.exit_date or now,
        )
        db.add(sell_order)
        db.flush()

        # Write PaperTransaction (realized P&L ledger)
        db.add(PaperTransaction(
            user_id=user_id,
            order_id=sell_order.id,
            symbol=trade.symbol,
            side="sell",
            qty=sell_qty,
            fill_price=trade.exit_price,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
            notes=f"Auto-close by strategy agent ({trade.exit_reason or 'unknown'})",
        ))

        # Update / remove PaperPosition
        remaining_qty = round(position.qty - sell_qty, 6)
        if remaining_qty < 0.0001:
            db.delete(position)
        else:
            position.qty = remaining_qty

        # Add cash back
        acct = _get_or_create_paper_account(db, user_id)
        acct.cash = round(acct.cash + total_proceeds, 2)
        logger.info(
            f"CASH_CHANGE user={user_id} delta={total_proceeds:.4f} "
            f"new_balance={acct.cash:.4f} reason='auto-sell {trade.symbol} "
            f"qty={sell_qty} @ {trade.exit_price} pnl={realized_pnl:.2f}'"
        )

        trade.paper_sell_placed = True
        db.add(trade)

        _add_log(
            db, today, "auto_exit",
            f"Auto-closed by strategy agent ({trade.exit_reason or 'unknown'}) "
            f"P&L: ${realized_pnl:+.2f}",
            user_id=user_id,
            symbol=trade.symbol,
            preset_key=trade.preset_key,
            price=trade.exit_price,
            trade_id=trade.id,
        )
        logger.info(
            f"Auto-sell placed: {trade.symbol} {sell_qty} shares @ ${trade.exit_price} "
            f"| P&L ${realized_pnl:+.2f}"
        )


# ---------------------------------------------------------------------------
# Main daily job
# ---------------------------------------------------------------------------

async def run_daily_automation(user_id: int) -> Dict:
    logger.info(f"=== Daily automation starting for user {user_id} ===")
    today = date.today()
    db = SessionLocal()
    loop = asyncio.get_running_loop()

    try:
        # 1. Market regime (needs SPY bars — fetch first)
        regime = await loop.run_in_executor(None, _check_regime_sync)
        logger.info(f"Market regime: {regime}")

        # 2. Download universe bars ONCE — shared across all screeners
        universe = get_universe()
        candidate_symbols = [
            t.symbol for t in db.query(StrategyTrade).filter(
                StrategyTrade.status == "candidate",
                StrategyTrade.user_id == user_id,
            ).all()
        ]
        all_symbols = list(set(universe) | set(candidate_symbols) | {"SPY"})
        logger.info(f"Fetching bars for {len(all_symbols)} symbols (universe + candidates)...")
        bars = await loop.run_in_executor(None, lambda: _fetch_bars_sync(all_symbols, period="1y"))
        logger.info(f"Bars fetched: {len(bars)} symbols loaded")

        # 3. Run screeners using shared bars (no extra downloads)
        screen_results = await _collect_screen_results(regime, bars)

        prices = await loop.run_in_executor(None, lambda: _get_prices_sync(all_symbols))

        # 4. Add new candidates
        new_candidates = _add_candidates(db, screen_results, today, user_id)
        db.flush()

        # 5. Check entry triggers
        entered = _process_candidates(db, today, bars, prices, user_id)

        # 6. Update open positions (exits)
        exited = _update_positions(db, today, prices, user_id)

        # 7. Write log entries
        _add_log(db, today, "daily_summary",
                 f"Regime: {regime} | New candidates: {len(new_candidates)} | "
                 f"Entries: {len(entered)} | Exits: {len(exited)}",
                 user_id=user_id)

        for t in new_candidates:
            _add_log(db, today, "candidate_added",
                     f"Added to watchlist — awaiting {t.entry_trigger or 'trigger'}",
                     user_id=user_id, symbol=t.symbol, preset_key=t.preset_key, trade_id=t.id)

        for t in entered:
            _add_log(db, today, "entry",
                     f"Entered @ ${t.entry_price:.2f} | Stop: ${t.stop_price:.2f} | "
                     f"Target: ${t.target_price:.2f} | Risk: ${t.risk_dollars:.0f}",
                     user_id=user_id, symbol=t.symbol, preset_key=t.preset_key,
                     price=t.entry_price, trade_id=t.id)

        for t in exited:
            pnl_pct = ((t.exit_price - t.entry_price) / t.entry_price * 100) if t.entry_price else 0
            _add_log(db, today, "exit",
                     f"Closed ({t.exit_reason}) @ ${t.exit_price:.2f} | "
                     f"P&L: {pnl_pct:+.2f}%",
                     user_id=user_id, symbol=t.symbol, preset_key=t.preset_key,
                     price=t.exit_price, pnl_pct=round(pnl_pct, 2), trade_id=t.id)

        # 8. Equity snapshot
        _snapshot_equity(db, today, prices, len(entered), len(exited), user_id)

        # 9. Sync paper orders for all open/closed strategy trades
        _sync_paper_orders(db, user_id)

        db.commit()
        logger.info(f"=== Daily automation complete for user {user_id}: {len(entered)} entries, {len(exited)} exits ===")
        return {
            "regime": regime,
            "new_candidates": len(new_candidates),
            "entries": len(entered),
            "exits": len(exited),
        }

    except Exception as e:
        logger.error(f"Daily automation error for user {user_id}: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
