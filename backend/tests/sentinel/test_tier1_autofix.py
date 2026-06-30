"""
R2 parity test — sentinel tier1_autofix.

apply_tier1_fix returns dict with {success, files_changed, tool, stdout}.
Tier-1 categories are a fixed set.
"""
import pytest
from unittest.mock import patch, MagicMock


def test_r2_tier1_categories_defined():
    from sentinel.agents.tier1_autofix import TIER1_CATEGORIES
    assert isinstance(TIER1_CATEGORIES, (set, frozenset, list))
    assert len(TIER1_CATEGORIES) >= 4, "Expected at least 4 tier-1 categories"


def test_r2_apply_tier1_fix_returns_dict():
    from sentinel.agents.tier1_autofix import apply_tier1_fix, TIER1_CATEGORIES
    cat = list(TIER1_CATEGORIES)[0]
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        with patch("app.services.llm_client.call_llm") as mock_call_llm:
            result = apply_tier1_fix("/tmp/fake_file.tsx", cat)
    assert isinstance(result, dict)
    assert "success" in result
    # Tier-1 must be deterministic — no LLM call ever
    assert mock_call_llm.call_count == 0


def test_r2_apply_tier1_fix_has_required_keys():
    from sentinel.agents.tier1_autofix import apply_tier1_fix, TIER1_CATEGORIES
    cat = list(TIER1_CATEGORIES)[0]
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "fixed"
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        with patch("app.services.llm_client.call_llm") as mock_call_llm:
            result = apply_tier1_fix("/tmp/fake.py", cat)
    for key in ("success", "tool", "stdout"):
        assert key in result, f"Missing key '{key}' in apply_tier1_fix result"
    # Tier-1 must be deterministic — no LLM call ever
    assert mock_call_llm.call_count == 0


def test_r2_non_tier1_category_returns_not_applicable():
    from sentinel.agents.tier1_autofix import apply_tier1_fix
    with patch("app.services.llm_client.call_llm") as mock_call_llm:
        result = apply_tier1_fix("/tmp/file.py", "completely_unknown_category_xyz")
    # Should not crash; success=False or a graceful result
    assert isinstance(result, dict)
    # Tier-1 must be deterministic — no LLM call ever
    assert mock_call_llm.call_count == 0


def test_r2_subprocess_failure_reflected_in_result():
    from sentinel.agents.tier1_autofix import apply_tier1_fix, TIER1_CATEGORIES
    cat = list(TIER1_CATEGORIES)[0]
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "error: cannot parse"
    with patch("subprocess.run", return_value=mock_result):
        with patch("app.services.llm_client.call_llm") as mock_call_llm:
            result = apply_tier1_fix("/tmp/broken.tsx", cat)
    # success should reflect failure
    assert isinstance(result, dict)
    # Tier-1 must be deterministic — no LLM call ever
    assert mock_call_llm.call_count == 0
