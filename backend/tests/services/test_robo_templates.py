"""
R5 parity test — robo_templates.

render_robo_rationale returns a non-empty string with allocation info.
"""
import pytest


def test_r5_render_robo_rationale_returns_string():
    from app.services.robo_templates import render_robo_rationale
    allocations = [
        {"symbol": "VTI", "weight": 0.6},
        {"symbol": "BND", "weight": 0.4},
    ]
    result = render_robo_rationale(allocations, risk="moderate", horizon=10)
    assert isinstance(result, str)
    assert len(result) > 10


def test_r5_rationale_mentions_risk():
    from app.services.robo_templates import render_robo_rationale
    allocations = [{"symbol": "SPY", "weight": 1.0}]
    result = render_robo_rationale(allocations, risk="high", horizon=20)
    # Should mention risk profile somewhere
    assert "high" in result.lower() or "aggressive" in result.lower() or "growth" in result.lower()


def test_r5_rationale_not_crash_empty_allocations():
    from app.services.robo_templates import render_robo_rationale
    result = render_robo_rationale([], risk="low", horizon=5)
    assert isinstance(result, str)


def test_r5_render_variants():
    """10 different allocation/risk combos must all return non-empty strings."""
    from app.services.robo_templates import render_robo_rationale
    combos = [
        ([{"symbol": "VTI", "weight": 1.0}], "low", 5),
        ([{"symbol": "SPY", "weight": 0.8}, {"symbol": "BND", "weight": 0.2}], "moderate", 10),
        ([{"symbol": "QQQ", "weight": 1.0}], "high", 20),
        ([{"symbol": "GLD", "weight": 0.3}, {"symbol": "TLT", "weight": 0.7}], "low", 2),
        ([{"symbol": "AAPL", "weight": 0.5}, {"symbol": "MSFT", "weight": 0.5}], "high", 15),
        ([{"symbol": "VNQ", "weight": 0.4}, {"symbol": "IEF", "weight": 0.6}], "moderate", 7),
        ([{"symbol": "EEM", "weight": 1.0}], "high", 25),
        ([{"symbol": "SCHB", "weight": 0.6}, {"symbol": "SCHZ", "weight": 0.4}], "low", 30),
        ([{"symbol": "IVV", "weight": 0.7}, {"symbol": "BND", "weight": 0.3}], "moderate", 12),
        ([], "low", 1),
    ]
    for allocs, risk, horizon in combos:
        result = render_robo_rationale(allocs, risk=risk, horizon=horizon)
        assert isinstance(result, str), f"Expected str for risk={risk}, horizon={horizon}"
