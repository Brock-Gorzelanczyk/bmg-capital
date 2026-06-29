"""
R4 parity test — robo_prompt_parser.

parse_robo_prompt returns {risk_tolerance, time_horizon_years, goal, restrictions, confidence}.
10 inputs tested.
"""
import pytest

FIXTURES = [
    # (text, expected_risk, expected_goal_contains)
    ("I want aggressive growth with high risk tolerance over 10 years",
     "high", "growth"),
    ("Looking for conservative, low-risk retirement savings for 20 years",
     "low", "retirement"),
    ("Moderate risk, balanced portfolio for 5-7 years",
     "moderate", "balanced"),
    ("I need income from dividends, low volatility, 15 year horizon",
     "low", "income"),
    ("Maximum growth, I can handle 50% drawdowns, 30 year timeframe",
     "high", "growth"),
    ("Preserve capital, no crypto, no options, 3 years",
     "low", "preservation"),
    ("Tech-focused growth with moderate risk over 7 years",
     "moderate", "growth"),
    ("Short term, 2 years, conservative, bonds and cash only",
     "low", "preservation"),
    ("Retirement in 25 years, moderate-aggressive risk",
     "moderate", "retirement"),
    ("ESG investing, no fossil fuels, long horizon, moderate risk",
     "moderate", "growth"),
]


def test_r4_parser_returns_dict_with_required_keys():
    from app.services.robo_prompt_parser import parse_robo_prompt
    for text, _, _ in FIXTURES:
        result = parse_robo_prompt(text)
        assert isinstance(result, dict)
        for key in ("risk_tolerance", "time_horizon_years", "goal", "confidence"):
            assert key in result, f"Missing '{key}' for: {text[:40]}"


def test_r4_parser_risk_tolerance_recognized():
    from app.services.robo_prompt_parser import parse_robo_prompt
    # Basic risk recognition
    assert parse_robo_prompt("aggressive high risk").get("risk_tolerance") == "high"
    assert parse_robo_prompt("conservative low risk").get("risk_tolerance") == "low"
    assert parse_robo_prompt("moderate balanced").get("risk_tolerance") == "moderate"


def test_r4_parser_time_horizon_extracted():
    from app.services.robo_prompt_parser import parse_robo_prompt
    result = parse_robo_prompt("I want to invest for 15 years")
    assert result.get("time_horizon_years") == 15


def test_r4_parser_confidence_is_float():
    from app.services.robo_prompt_parser import parse_robo_prompt
    for text, _, _ in FIXTURES:
        result = parse_robo_prompt(text)
        conf = result.get("confidence", 0)
        assert isinstance(conf, (int, float)), f"confidence should be numeric for: {text[:40]}"
        assert 0.0 <= conf <= 1.0, f"confidence {conf} out of [0,1] range"


def test_r4_parser_does_not_crash_on_empty():
    from app.services.robo_prompt_parser import parse_robo_prompt
    result = parse_robo_prompt("")
    assert isinstance(result, dict)
    assert "risk_tolerance" in result
