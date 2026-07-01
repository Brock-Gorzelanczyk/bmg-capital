"""Regression: /api/live/bot-activity — Trading Desk live-data feed.

Structural guards for the endpoint that powers the Trading Desk UI's real
bot activity (replaces the scripted demo). Static checks only — the actual
DB queries are exercised in production against the real bot_signals /
bot_trades / bot_daily_pnl tables.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_live_activity_router_exists_and_mounted():
    """The router file must exist and be included in main.py."""
    router = BACKEND / "app" / "routers" / "live_activity.py"
    assert router.exists(), "live_activity.py router missing"
    main_src = (BACKEND / "app" / "main.py").read_text()
    assert "live_activity" in main_src, (
        "main.py must include the live_activity router so /api/live/bot-activity is reachable"
    )
    assert "live_activity_router" in main_src or "include_router" in main_src


def test_live_activity_scopes_to_current_user():
    """Every query in live_activity.py must filter by current_user.id — this
    is per-user data and must NEVER leak across users.
    """
    src = (BACKEND / "app" / "routers" / "live_activity.py").read_text()
    # Every SELECT must reference user_id or filter by allocation ownership.
    # Look for the pattern that binds :uid to current_user.id.
    assert "current_user: User = Depends(get_current_user)" in src, (
        "endpoint must require authentication"
    )
    assert 'current_user.id' in src, "queries must scope to current_user.id"
    # No raw `SELECT ... FROM bot_signals` without a user_id filter.
    signal_queries = re.findall(r"SELECT[^;]*FROM bot_signals[^;]*", src, re.IGNORECASE | re.DOTALL)
    for q in signal_queries:
        assert "user_id" in q, (
            f"bot_signals SELECT must join+filter on user_id (found: {q[:200]!r})"
        )


def test_live_activity_bounds_result_sizes():
    """Response must be bounded — no risk of returning thousands of rows and
    hanging the client. Hard limits should be in the code, not user-controlled.
    """
    src = (BACKEND / "app" / "routers" / "live_activity.py").read_text()
    assert "MAX_SIGNALS_PER_CALL" in src, (
        "endpoint must define a hard MAX_SIGNALS_PER_CALL limit"
    )
    assert "MAX_TRADES_PER_CALL" in src, (
        "endpoint must define a hard MAX_TRADES_PER_CALL limit"
    )
    # Both must be reasonable — not > 500.
    for name in ("MAX_SIGNALS_PER_CALL", "MAX_TRADES_PER_CALL"):
        m = re.search(rf"{name}\s*=\s*(\d+)", src)
        assert m is not None, f"{name} constant missing"
        assert int(m.group(1)) <= 500, (
            f"{name} = {m.group(1)} is too large; keep it <= 500 to bound response size"
        )


def test_live_activity_cold_start_returns_most_recent_not_oldest():
    """Cold-start (since_id=0) must return the LATEST N items, not the
    oldest — otherwise the poller has to churn through weeks of historical
    data before reaching real-time.

    Verified via grep for the 'ORDER BY ... DESC LIMIT ... ORDER BY id ASC'
    pattern (double-sort trick to get last N chronologically).
    """
    src = (BACKEND / "app" / "routers" / "live_activity.py").read_text()
    # Signals cold-start pattern
    signal_cold = re.search(
        r"since_signal_id\s*==\s*0.*?ORDER BY s\.id DESC LIMIT.*?ORDER BY id ASC",
        src,
        re.DOTALL,
    )
    assert signal_cold is not None, (
        "signals cold-start (since_signal_id=0) must use ORDER BY id DESC "
        "LIMIT + outer ORDER BY id ASC so client seeds watermark from the "
        "true tail, not from signal id 1"
    )
    # Trades cold-start pattern
    trade_cold = re.search(
        r"since_trade_id\s*==\s*0.*?ORDER BY t\.id DESC LIMIT.*?ORDER BY id ASC",
        src,
        re.DOTALL,
    )
    assert trade_cold is not None, (
        "trades cold-start (since_trade_id=0) must return most-recent N, "
        "not oldest N"
    )


def test_trading_desk_wrapper_silently_seeds_watermark_on_first_poll():
    """The frontend must NOT spam the desk with 50 historical toasts on
    cold-start. First poll silently advances the watermark; subsequent
    polls display new events as toasts.
    """
    src = (BACKEND.parent / "frontend" / "src" / "pages" / "TradingDeskIframePage.tsx").read_text()
    assert "seededRef" in src or "isSeeding" in src, (
        "TradingDeskIframePage must gate the first-poll postMessage so 50 "
        "historical events don't all render as toasts simultaneously"
    )
    # Summary should NOT be gated — it drives session P&L and should update
    # immediately on first load.
    assert re.search(
        r"summary.*postMessage.*td:summary",
        src,
        re.DOTALL,
    ), "summary postMessage must fire on every poll (including seed)"


def test_live_activity_returns_expected_shape():
    """Response dict must include the keys the Trading Desk iframe expects:
    signals, trades, summary (with session_pnl_usd, active_bot_count, etc).
    """
    src = (BACKEND / "app" / "routers" / "live_activity.py").read_text()
    for key in ('"signals"', '"trades"', '"summary"', '"session_pnl_usd"',
                '"active_bot_count"', '"signals_last_hour"', '"trades_last_hour"'):
        assert key in src, f"response shape must include {key}"


def test_trading_desk_html_listens_for_live_events():
    """The Trading Desk HTML must have a postMessage listener that consumes
    the td:signal / td:fill / td:summary events from the iframe wrapper.
    Without this the endpoint's output goes nowhere.
    """
    src = (BACKEND.parent / "frontend" / "public" / "trading-desk.html").read_text()
    assert "td:signal" in src, "trading-desk.html must handle td:signal messages"
    assert "td:fill" in src, "trading-desk.html must handle td:fill messages"
    assert "td:summary" in src, "trading-desk.html must handle td:summary messages"
    assert "window.location.origin" in src, (
        "trading-desk.html postMessage listener must verify origin"
    )


def test_trading_desk_iframe_wrapper_polls_endpoint():
    """The React wrapper page must poll /api/live/bot-activity and post
    signals/trades to the iframe.
    """
    src = (BACKEND.parent / "frontend" / "src" / "pages" / "TradingDeskIframePage.tsx").read_text()
    assert "/api/live/bot-activity" in src, (
        "TradingDeskIframePage must call /api/live/bot-activity"
    )
    assert "since_signal_id" in src and "since_trade_id" in src, (
        "wrapper must send both watermarks so it only receives NEW events"
    )
    for msg_type in ('"td:signal"', '"td:fill"', '"td:summary"'):
        assert msg_type in src, f"wrapper must postMessage {msg_type} to iframe"


def test_candles_endpoint_exists_and_validated():
    """Phase 3: /api/live/candles must exist, require symbol, cap limit at
    128, and reject option OCC symbols (chart doesn't make sense for a
    specific options contract).
    """
    src = (BACKEND / "app" / "routers" / "live_activity.py").read_text()
    assert '@router.get("/candles")' in src, (
        "candles endpoint must be registered at /api/live/candles"
    )
    assert "MAX_CANDLES" in src and "le=MAX_CANDLES" in src, (
        "candles endpoint must cap `limit` at MAX_CANDLES to bound response size"
    )
    assert 'kind == "option"' in src, (
        "candles endpoint must reject OCC options with a clear error path"
    )
    # Timeframe must be validated against a fixed enum, not free-form user input.
    assert re.search(r'pattern=.+1m.+5m.+1d', src) is not None, (
        "candles endpoint must validate timeframe against a fixed enum"
    )


def test_candles_endpoint_scopes_and_caches_correctly():
    """Candles endpoint must require auth (per-user cache invalidation is
    less critical since candles are market-wide, but auth is required so
    unauth users don't hammer yfinance/kraken via our infra).
    """
    src = (BACKEND / "app" / "routers" / "live_activity.py").read_text()
    # find the candles handler and verify the get_current_user dependency
    handler_start = src.find('@router.get("/candles")')
    handler_end = src.find("\n\n", handler_start)
    handler = src[handler_start:handler_end]
    assert "get_current_user" in handler, (
        "candles endpoint must require authentication"
    )
    assert "_candles_cache" in src, (
        "candles endpoint must be cached to protect upstream data sources"
    )


def test_trading_desk_html_handles_candle_and_symbol_events():
    """HTML must handle td:candles + td:symbol postMessages so Phase 3 chart
    swap-in and header update work.
    """
    src = (BACKEND.parent / "frontend" / "public" / "trading-desk.html").read_text()
    assert "td:candles" in src, "HTML must handle td:candles message"
    assert "td:symbol" in src, "HTML must handle td:symbol message"
    assert 'id="td-symbol"' in src, (
        "HTML header must have id='td-symbol' so the symbol name is dynamically updatable"
    )
    # Replacing the candles array (not merely appending) is the correct
    # semantic when historical bars arrive from the API.
    assert "candles.length = 0" in src, (
        "td:candles handler must replace the candles array, not append"
    )


def test_trading_desk_wrapper_supports_deep_link():
    """The wrapper must parse ?bot=X&symbol=Y from the URL and poll candles
    when a symbol is specified.
    """
    src = (BACKEND.parent / "frontend" / "src" / "pages" / "TradingDeskIframePage.tsx").read_text()
    assert "useSearchParams" in src, (
        "wrapper must use useSearchParams to read deep-link query params"
    )
    assert '"symbol"' in src and '"bot"' in src, (
        "wrapper must read ?symbol= and ?bot= query params"
    )
    assert "/api/live/candles" in src, (
        "wrapper must poll /api/live/candles when focus symbol is set"
    )
    assert '"td:candles"' in src, "wrapper must postMessage td:candles to iframe"
    assert '"td:symbol"' in src, "wrapper must postMessage td:symbol to iframe"
    # Focus-bot filter — if a bot is specified, only its events flow to the iframe
    assert "focusBot" in src, (
        "wrapper must filter signals/trades to focus_bot when specified so the "
        "desk shows only the bot the user came to watch"
    )
