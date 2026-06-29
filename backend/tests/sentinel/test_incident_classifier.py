"""
R3 parity test — sentinel incident_classifier.

classify_incident(stacktrace) returns a dict with 'category' key.
5 regex rules tested + fallback.
"""
import pytest

FIXTURES = [
    ("MemoryError: cannot allocate array size 2GB\n  in allocate()", "memory_error"),
    ("TimeoutError: Request timed out after 30s\n  in client.get()", "timeout"),
    ("ConnectionRefusedError: [Errno 111] Connection refused\n  in connect()", "connection_refused"),
    ("OperationalError: database is locked\n  in execute()", "database_error"),
    ("SyntaxError: invalid syntax at line 42\n  File main.py", "syntax_error"),
    ("Some completely unrecognized error we haven't seen before", "unclassified"),
    ("ImportError: No module named 'requests'\n  in app.py", "unclassified"),
]


def test_r3_incident_classifier_returns_dict():
    from sentinel.agents.incident_classifier import classify_incident
    for stack, _ in FIXTURES:
        result = classify_incident(stack)
        assert isinstance(result, dict), f"Expected dict for: {stack[:40]}"


def test_r3_incident_classifier_has_category():
    from sentinel.agents.incident_classifier import classify_incident
    for stack, _ in FIXTURES:
        result = classify_incident(stack)
        assert "category" in result, f"Missing 'category' key for: {stack[:40]}"
        assert result["category"], f"Empty category for: {stack[:40]}"


def test_r3_incident_classifier_known_patterns():
    from sentinel.agents.incident_classifier import classify_incident
    for stack, expected in FIXTURES:
        result = classify_incident(stack)
        if expected != "unclassified":
            assert result["category"] == expected, (
                f"Input: '{stack[:60]}'\n"
                f"Expected '{expected}', got '{result['category']}'"
            )


def test_r3_fallback_is_unclassified():
    from sentinel.agents.incident_classifier import classify_incident
    result = classify_incident("random noise that matches nothing")
    assert result["category"] == "unclassified"
