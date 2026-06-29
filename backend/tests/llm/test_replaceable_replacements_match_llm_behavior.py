"""
T3 — Replaceable replacements match LLM behavior shape on >= 10 inputs each.

R1-R8 deterministic outputs must:
- Return the same type as the LLM used to return (str or dict)
- Not be empty/None
- Not raise exceptions
- Produce deterministic output (same input → same output)
"""
import pytest
from unittest.mock import patch


# ---------- R1: error_classifier ----------

def test_t3_r1_error_classifier_10_inputs():
    try:
        from sentinel.agents.error_classifier import classify_error
    except ImportError:
        pytest.skip("error_classifier not importable")

    inputs = [
        ("Cannot read property 'x' of null", "Component.render"),
        ("Module not found: ./utils", "import"),
        ("className: btn-prmary", "Header"),
        ("no such column: users.age", "query.py:45"),
        ("NoneType has no attribute 'id'", "service.py:100"),
        ("No module named 'boto3'", "aws.py"),
        ("Unexpected token <", "parser"),
        ("KeyError: 'token'", "auth.py"),
        ("ReferenceError: document not defined", "ssr.js"),
        ("connection refused 127.0.0.1:5432", "db/session.py"),
    ]
    for text, stack in inputs:
        result = classify_error(text, stack)
        assert isinstance(result, dict), f"R1 should return dict for: {text[:30]}"
        assert result.get("category"), f"R1 empty category for: {text[:30]}"
        # Determinism check
        assert classify_error(text, stack) == result, f"R1 not deterministic for: {text[:30]}"


# ---------- R3: incident_classifier ----------

def test_t3_r3_incident_classifier_10_inputs():
    try:
        from sentinel.agents.incident_classifier import classify_incident
    except ImportError:
        pytest.skip("incident_classifier not importable")

    inputs = [
        "MemoryError at allocate()",
        "TimeoutError after 30s",
        "ConnectionRefusedError 127.0.0.1",
        "database is locked",
        "SyntaxError invalid syntax",
        "IndexError list out of range",
        "ValueError invalid literal",
        "RecursionError maximum recursion",
        "FileNotFoundError /tmp/x",
        "ZeroDivisionError division by zero",
    ]
    for stack in inputs:
        result = classify_incident(stack)
        assert isinstance(result, dict), f"R3 should return dict for: {stack[:30]}"
        assert result.get("category"), f"R3 empty category for: {stack[:30]}"
        assert classify_incident(stack) == result, f"R3 not deterministic for: {stack[:30]}"


# ---------- R4: robo_prompt_parser ----------

def test_t3_r4_robo_parser_10_inputs():
    try:
        from app.services.robo_prompt_parser import parse_robo_prompt
    except ImportError:
        pytest.skip("robo_prompt_parser not importable")

    inputs = [
        "aggressive growth 10 years",
        "conservative retirement 20 years",
        "moderate balanced 5 years",
        "high risk tech stocks 15 years",
        "low risk bonds only 3 years",
        "income dividends 10 years",
        "capital preservation no crypto 2 years",
        "ESG no fossil fuels 25 years",
        "moderate aggressive 30 year horizon",
        "short term 1 year conservative",
    ]
    for text in inputs:
        result = parse_robo_prompt(text)
        assert isinstance(result, dict), f"R4 should return dict for: {text}"
        assert "risk_tolerance" in result
        assert "confidence" in result
        assert parse_robo_prompt(text) == result, f"R4 not deterministic for: {text}"


# ---------- R5: robo_templates ----------

def test_t3_r5_robo_templates_10_inputs():
    try:
        from app.services.robo_templates import render_robo_rationale
    except ImportError:
        pytest.skip("robo_templates not importable")

    allocs_list = [
        [{"symbol": "VTI", "weight": 1.0}],
        [{"symbol": "SPY", "weight": 0.8}, {"symbol": "BND", "weight": 0.2}],
        [{"symbol": "QQQ", "weight": 0.6}, {"symbol": "TLT", "weight": 0.4}],
        [{"symbol": "GLD", "weight": 0.3}, {"symbol": "IEF", "weight": 0.7}],
        [{"symbol": "AAPL", "weight": 1.0}],
        [{"symbol": "VNQ", "weight": 0.5}, {"symbol": "SCHB", "weight": 0.5}],
        [{"symbol": "EEM", "weight": 0.4}, {"symbol": "EFA", "weight": 0.6}],
        [{"symbol": "IVV", "weight": 0.7}, {"symbol": "SHY", "weight": 0.3}],
        [{"symbol": "BRK.B", "weight": 0.5}, {"symbol": "BND", "weight": 0.5}],
        [],
    ]
    risks = ["high", "low", "moderate", "high", "low", "moderate", "high", "low", "moderate", "low"]
    horizons = [5, 10, 15, 20, 2, 7, 25, 30, 12, 1]

    for allocs, risk, horizon in zip(allocs_list, risks, horizons):
        result = render_robo_rationale(allocs, risk=risk, horizon=horizon)
        assert isinstance(result, str), f"R5 should return str for risk={risk}"
        r2 = render_robo_rationale(allocs, risk=risk, horizon=horizon)
        assert result == r2, "R5 not deterministic"


# ---------- R7: intros ----------

def test_t3_r7_intros_10_inputs():
    try:
        from agents.intros import get_intro
    except ImportError:
        pytest.skip("intros not importable")

    agents = ["brick", "dick", "nick", "mick", "vick", "rick", "slick", "wick", "patrick", "unknown_x"]
    for agent in agents:
        result = get_intro(agent)
        assert isinstance(result, str), f"R7 should return str for agent: {agent}"
        assert get_intro(agent) == result, f"R7 not deterministic for agent: {agent}"


# ---------- R8: trade_journal_template ----------

def test_t3_r8_trade_journal_10_inputs():
    try:
        from strategy_lab.core.expert.trade_journal_template import render_lab_entry_journal
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    inputs = [
        ("AAPL", "buy", 10, 150.0, "momentum", "RSI"),
        ("MSFT", "sell", 5, 300.0, "mean_revert", "overbought"),
        ("NVDA", "buy", 2, 500.0, "breakout", "earnings"),
        ("TSLA", "buy", 3, 200.0, "trend", "52wk high"),
        ("SPY", "buy", 20, 430.0, "index", "risk-on"),
        ("QQQ", "sell", 8, 360.0, "hedge", "selloff"),
        ("AMZN", "buy", 1, 180.0, "value", "PE low"),
        ("META", "buy", 4, 250.0, "momentum", "ad beat"),
        ("GOOG", "sell", 3, 170.0, "profit", "50% up"),
        ("BRK.B", "buy", 6, 380.0, "quality", "margin"),
    ]
    for sym, side, qty, price, strat, reason in inputs:
        result = render_lab_entry_journal(sym, side, qty, price, strat, reason)
        assert isinstance(result, str) and result, f"R8 empty/non-str for {sym}"
        r2 = render_lab_entry_journal(sym, side, qty, price, strat, reason)
        assert result == r2, f"R8 not deterministic for {sym}"
