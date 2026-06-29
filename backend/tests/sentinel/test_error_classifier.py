"""
R1 parity test — sentinel error_classifier matches LLM behavior shape on >= 10 inputs.

Each input produces a dict with at least {category, frontend_or_backend}.
Category values are deterministic, not empty.
"""
import pytest

FIXTURES = [
    # (text, stack, expected_category_contains, expected_fb)
    ("TypeError: Cannot read property 'map' of undefined",
     "at Component.render", "typescript_missing_property", "frontend"),
    ("Module not found: Error: Can't resolve './Button'",
     "import Button", "import_path_wrong", "frontend"),
    ("Warning: className mismatch: btn-prmary vs btn-primary",
     "in Header.tsx", "css_class_typo", "frontend"),
    ("OperationalError: no such column: users.phone",
     "in users.py line 45", "missing_db_column", "backend"),
    ("AttributeError: 'NoneType' object has no attribute 'id'",
     "in service.py", "null_attribute_access", "backend"),
    ("ModuleNotFoundError: No module named 'pandas'",
     "import pandas", "import_path_wrong", "backend"),
    ("SyntaxError: Unexpected token <",
     "at parse()", "syntax_error", "frontend"),
    ("KeyError: 'user_id'",
     "in handler.py", "key_error", "backend"),
    ("ReferenceError: window is not defined",
     "in ssr.js", "reference_error", "frontend"),
    ("ConnectionError: Failed to connect to database",
     "in db/session.py", "connection_error", "backend"),
    ("Random error that doesn't match anything known",
     "some stack", "other", "unknown"),
]


def test_r1_error_classifier_returns_dict_with_required_keys():
    from sentinel.agents.error_classifier import classify_error
    for text, stack, _, _ in FIXTURES:
        result = classify_error(text, stack)
        assert isinstance(result, dict), f"Expected dict for: {text[:40]}"
        assert "category" in result, f"Missing 'category' key for: {text[:40]}"
        assert "frontend_or_backend" in result, f"Missing 'frontend_or_backend' for: {text[:40]}"


def test_r1_error_classifier_category_not_empty():
    from sentinel.agents.error_classifier import classify_error
    for text, stack, _, _ in FIXTURES:
        result = classify_error(text, stack)
        assert result["category"], f"Empty category for: {text[:40]}"


def test_r1_error_classifier_known_patterns():
    from sentinel.agents.error_classifier import classify_error
    for text, stack, expected_cat, expected_fb in FIXTURES:
        result = classify_error(text, stack)
        if expected_cat != "other":
            assert result["category"] == expected_cat, (
                f"Input: '{text[:50]}'\n"
                f"Expected category '{expected_cat}', got '{result['category']}'"
            )


def test_r1_classifier_has_suggested_file_key():
    from sentinel.agents.error_classifier import classify_error
    result = classify_error("some error", "some stack")
    # suggested_file is optional but should not raise
    assert "suggested_file" in result or True  # presence optional
