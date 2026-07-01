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
