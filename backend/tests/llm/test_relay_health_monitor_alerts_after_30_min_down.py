"""
T14 — Relay health monitor alerts after 30 min down.

Simulate 6 consecutive failures → send_ops_alert called with severity='critical'.
"""
import os
import pytest
from unittest.mock import patch, MagicMock


_RELAY_ENV = {"RELAY_URL": "http://test-relay:8080"}


def test_t14_alert_after_6_consecutive_failures():
    """6 consecutive failures → severity='critical' ops alert."""
    from app.jobs.relay_health_monitor import check_relay_health, reset_state

    reset_state()

    alerts_sent = []

    def _capture_alert(*, severity, title, message, source, fields=None, **kw):
        alerts_sent.append({"severity": severity, "title": title})

    def _relay_down(*a, **kw):
        raise Exception("connection refused")

    with patch.dict(os.environ, _RELAY_ENV):
        with patch("app.jobs.relay_health_monitor._send_relay_down_alert") as mock_send:
            mock_send.side_effect = lambda now: alerts_sent.append({
                "severity": "critical",
                "title": "LLM relay offline > 30 min",
            })
            with patch("httpx.get", side_effect=_relay_down):
                # 5 failures — not yet at threshold (6)
                for i in range(5):
                    result = check_relay_health()
                    assert result["ok"] is False
                    assert result["consecutive_failures"] == i + 1

                # No alert yet
                assert not alerts_sent, f"Alert sent too early at {len(alerts_sent)} failures"

                # 6th failure — crosses 30-min threshold
                result = check_relay_health()
                assert result["ok"] is False
                assert result["consecutive_failures"] == 6
                assert result["alert_sent"] is True

    assert alerts_sent, "Expected ops alert after 6 consecutive failures"
    assert alerts_sent[0]["severity"] == "critical"
    assert "offline" in alerts_sent[0]["title"].lower()

    reset_state()


def test_t14_no_alert_before_threshold():
    """Fewer than 6 failures → no alert."""
    from app.jobs.relay_health_monitor import check_relay_health, reset_state

    reset_state()

    def _relay_down(*a, **kw):
        raise Exception("connection refused")

    with patch.dict(os.environ, _RELAY_ENV):
        with patch("app.jobs.relay_health_monitor._send_relay_down_alert") as mock_send:
            with patch("httpx.get", side_effect=_relay_down):
                for i in range(5):
                    result = check_relay_health()

    mock_send.assert_not_called()
    reset_state()


def test_t14_recovery_resets_counter():
    """After recovery, consecutive_failures resets to 0."""
    from app.jobs.relay_health_monitor import check_relay_health, reset_state

    reset_state()

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    call_count = [0]

    def _alternating(*a, **kw):
        call_count[0] += 1
        if call_count[0] <= 3:
            raise Exception("down")
        return mock_resp

    with patch.dict(os.environ, _RELAY_ENV):
        with patch("app.jobs.relay_health_monitor._send_relay_down_alert"):
            with patch("httpx.get", side_effect=_alternating):
                # 3 failures
                for _ in range(3):
                    check_relay_health()
                # Recovery
                result = check_relay_health()

    assert result["ok"] is True
    assert result["consecutive_failures"] == 0

    reset_state()
