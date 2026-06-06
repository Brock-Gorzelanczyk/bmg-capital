from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String, Text, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotProfile(Base):
    __tablename__ = "bot_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asset_class: Mapped[str] = mapped_column(String, nullable=False)  # stock|crypto
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )


class BotAllocation(Base):
    __tablename__ = "bot_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=False, index=True)
    capital_pct: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    risk_profile: Mapped[str] = mapped_column(String, default="standard", nullable=False)  # conservative|standard|aggressive
    paper_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    go_live_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    paused_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    starting_capital_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # snapshot of paper balance at activation, used for all-time return calc
    card_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # per-user per-bot display preferences:
    # {visible_metrics: [...], show_equity_curve: bool, show_watchlist: bool,
    #  pnl_avg_window: '7d'|'30d'|'all_time', density: 'compact'|'standard'|'expanded'}
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    portfolio_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("strategy_portfolios.id"), nullable=True, index=True)
    capital_cents_within_portfolio: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class BotSignal(Base):
    __tablename__ = "bot_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # buy|sell|hold
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0-1
    size_hint: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discord_posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discord_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class BotPosition(Base):
    __tablename__ = "bot_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BotTrade(Base):
    __tablename__ = "bot_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # buy|sell
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    fees_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    alpaca_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    position_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bot_positions.id"), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expected_fill_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    slippage_bps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class BotDailyPnL(Base):
    __tablename__ = "bot_daily_pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    realized_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unrealized_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fees_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peak_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    portfolio_value_eod_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # end-of-day portfolio value snapshot for sparkline


class GoLiveWaitlist(Base):
    __tablename__ = "go_live_waitlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bot_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    opted_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BotWatchlist(Base):
    __tablename__ = "bot_watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reasons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {component: score}
    status: Mapped[str] = mapped_column(String, default="active")  # active|inactive|blacklisted
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BotHealth(Base):
    __tablename__ = "bot_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    live_sharpe_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    backtest_sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    divergence_sigma: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    paused_by_health: Mapped[bool] = mapped_column(Boolean, default=False)
    strategies_disabled: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    heartbeat_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True, default=lambda: datetime.now(timezone.utc))
    vix_regime: Mapped[str] = mapped_column(String, default="mid")   # low|mid|high|panic
    trend_regime: Mapped[str] = mapped_column(String, default="chop")  # bull|bear|chop
    vol_pctile: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btc_dominance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btc_funding_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spy_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vix_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class CatalystEvent(Base):
    __tablename__ = "catalyst_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # earnings|fomc|cpi|nfp|pce|token_unlock|rebalance
    symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class StrategyWeight(Base):
    """Thompson sampling weights per strategy per bot profile."""
    __tablename__ = "strategy_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"))
    strategy_name: Mapped[str] = mapped_column(String(100))
    current_weight: Mapped[float] = mapped_column(Float, default=1.0)
    base_weight: Mapped[float] = mapped_column(Float, default=1.0)
    wins: Mapped[int] = mapped_column(Integer, default=0)  # for Thompson sampling Beta
    losses: Mapped[int] = mapped_column(Integer, default=0)
    last_30_trades: Mapped[dict] = mapped_column(JSON, default=list)  # [{won, pnl_pct, ts}]
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("profile_id", "strategy_name"),)


class CrossBotPosition(Base):
    """Aggregate position across all bots for conflict resolution."""
    __tablename__ = "cross_bot_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    total_qty: Mapped[float] = mapped_column(Float, default=0.0)
    by_bot: Mapped[dict] = mapped_column(JSON, default=dict)  # {"stock_swing": qty, ...}
    net_exposure_pct: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "symbol"),)


class NewsEvent(Base):
    """News events with sentiment for stop adjustment and blackouts."""
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # null = market-wide
    ts: Mapped[datetime] = mapped_column(DateTime)
    sentiment: Mapped[str] = mapped_column(String(20))  # bullish|bearish|neutral
    severity: Mapped[str] = mapped_column(String(20))  # major|normal|minor
    headline: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(100))


class WatchlistAnalysis(Base):
    """AI Analyst thesis for a watchlisted symbol."""
    __tablename__ = "watchlist_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    thesis_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conviction_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    reasons_to_own: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    risks: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    suggested_hold: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    concerns_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    inputs_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class AnalystDailyRun(Base):
    """Summary of an analyst run for a bot."""
    __tablename__ = "analyst_daily_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    bot_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=False, index=True)
    num_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    num_high_conviction: Mapped[int] = mapped_column(Integer, default=0)
    num_flagged_concerns: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AnomalyEvent(Base):
    """Market anomalies detected by anomaly_detector.py."""
    __tablename__ = "anomaly_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"))
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    anomaly_type: Mapped[str] = mapped_column(String(50))  # flash_crash|vol_spike|halt|circuit_breaker
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class StrategyPortfolio(Base):
    __tablename__ = "strategy_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)           # "Stocks" / "Crypto" / "Options"
    asset_class: Mapped[str] = mapped_column(String, nullable=False)    # "stocks" / "crypto" / "options"
    starting_capital_cents: Mapped[int] = mapped_column(Integer, default=5_000_000, nullable=False)
    paper_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    emoji: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    color_hex: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    __table_args__ = (UniqueConstraint("user_id", "asset_class"),)


class PortfolioDailyPnL(Base):
    __tablename__ = "portfolio_daily_pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategy_portfolios.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    realized_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unrealized_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    value_eod_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("portfolio_id", "date"),)
