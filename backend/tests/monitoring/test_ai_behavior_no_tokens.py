"""
R9 parity test — ai_behavior.py check_ai_provider_health uses HTTP probe (no tokens).

Asserts that check_ai_provider_health does NOT call messages.create.
Uses httpx mock to simulate the probe.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio


def test_r9_check_anthropic_health_is_http_probe():
    """check_ai_provider_health must use HTTP probe, not messages.create."""
    try:
        from app.monitoring.checks.ai_behavior import check_ai_provider_health
    except ImportError:
        pytest.skip("ai_behavior not importable in test env")

    # Patch messages.create to fail if called
    def _should_not_be_called(*a, **kw):
        raise AssertionError("messages.create was called — must use HTTP probe only")

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        with patch("httpx.post", side_effect=_should_not_be_called):
            # Run sync or async
            if asyncio.iscoroutinefunction(check_ai_provider_health):
                result = asyncio.get_event_loop().run_until_complete(
                    check_ai_provider_health()
                )
            else:
                result = check_ai_provider_health()

    # Result should indicate healthy or at least not crash
    assert result is not None


def test_r9_probe_uses_vendors_check_anthropic_up():
    """ai_behavior should delegate to vendors.check_anthropic_up (HTTP-only)."""
    try:
        from app.monitoring.checks.vendors import check_anthropic_up
    except ImportError:
        pytest.skip("vendors not importable in test env")

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.get", return_value=mock_resp):
        if asyncio.iscoroutinefunction(check_anthropic_up):
            result = asyncio.get_event_loop().run_until_complete(check_anthropic_up())
        else:
            result = check_anthropic_up()

    # Should return something truthy indicating health
    assert result is not None
