"""R3 — Deterministic Railway incident classifier (replaces Haiku LLM call).

No LLM dependency. Regex map, first-hit wins.
"""
from __future__ import annotations

import re


_RULES: list[tuple[re.Pattern, str]] = [
    # OOM / Memory — "OOMKilled" (k8s) stays as memory_error, MemoryError too
    (re.compile(r"OOMKilled|MemoryError", re.I), "memory_error"),
    # Timeout
    (re.compile(r"\bTimeoutError\b|Timeout.*timed out|request timed out", re.I), "timeout"),
    # Connection refused (Python errno 111 pattern, socket refused, etc.)
    (re.compile(r"ConnectionRefusedError|connection refused|ECONNREFUSED", re.I | re.S), "connection_refused"),
    # Database errors — locked, could not connect, operational errors
    (re.compile(r"OperationalError|database is locked|could not connect.*database", re.I | re.S), "database_error"),
    # Syntax errors
    (re.compile(r"\bSyntaxError\b", re.I), "syntax_error"),
    # Upstream 5xx HTTP responses
    (re.compile(r"\b5\d\d\b "), "upstream_5xx"),
]


def classify_incident(stacktrace: str) -> dict:
    """Returns {category}. No LLM."""
    for pattern, category in _RULES:
        if pattern.search(stacktrace):
            return {"category": category}
    return {"category": "unclassified"}
