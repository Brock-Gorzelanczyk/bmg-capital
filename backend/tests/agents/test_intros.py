"""
R7 parity test — agents/intros.py.

get_intro returns a non-empty string for each of the 9 known agent keys.
No LLM call made.
"""
import pytest
from unittest.mock import patch

KNOWN_AGENTS = ["brick", "dick", "nick", "mick", "vick", "rick", "slick", "wick", "patrick"]


def test_r7_get_intro_returns_string_for_all_agents():
    from agents.intros import get_intro
    for agent in KNOWN_AGENTS:
        result = get_intro(agent)
        assert isinstance(result, str), f"Expected str for agent '{agent}'"
        assert len(result) > 0, f"Empty intro for agent '{agent}'"


def test_r7_get_intro_unknown_agent_returns_fallback():
    from agents.intros import get_intro
    result = get_intro("unknown_agent_xyz")
    assert isinstance(result, str)


def test_r7_no_llm_call_in_get_intro():
    """get_intro must be deterministic — no LLM call."""
    with patch("app.services.llm_client.call_llm") as mock_llm:
        with patch("app.services.llm_client.call_llm_cached") as mock_cached:
            try:
                from agents.intros import get_intro
                get_intro("brick")
            except ImportError:
                pytest.skip("agents.intros not importable in test env")
    mock_llm.assert_not_called()
    mock_cached.assert_not_called()


def test_r7_intros_dict_has_9_keys():
    try:
        from agents.intros import INTROS
        assert len(INTROS) == 9, f"Expected 9 agents in INTROS, got {len(INTROS)}"
        for agent in KNOWN_AGENTS:
            assert agent in INTROS, f"'{agent}' missing from INTROS"
    except ImportError:
        pytest.skip("agents.intros not importable in test env")
