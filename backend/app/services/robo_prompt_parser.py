"""R4 — Deterministic robo prompt parser (replaces Haiku LLM call).

No LLM required. Keyword classifier with confidence score.
If confidence < 0.6, callers should fall back to call_llm_cached.
"""
from __future__ import annotations

import re


_RISK_BAGS: dict[str, list[str]] = {
    "high":     ["aggressive", "high-risk", "high risk", "yolo", "maximum risk", "max risk"],
    "moderate": ["balanced", "moderate", "moderate-aggressive", "moderate risk"],
    "low":      ["conservative", "safe", "preserve", "low-risk", "low risk", "minimal risk"],
}

_HORIZON_WORDS: dict[str, int] = {
    "retire": 25, "retirement": 25,
    "short":  3,
    "long":   15,
    "decade": 10,
}

_GOAL_BAGS: dict[str, list[str]] = {
    "income":       ["income", "dividend", "yield"],
    "growth":       ["growth", "appreciation"],
    "preservation": ["preserve", "safe", "protect"],
}

_RESTRICTION_KEYWORDS = ["no oil", "no tobacco", "esg", "halal", "sin"]

_YEARS_RE = re.compile(r"(\d+)\s*year", re.I)


def parse_robo_prompt(text: str) -> dict:
    """Returns {risk_tolerance, time_horizon_years, goal, restrictions, confidence}.

    Deterministic keyword classifier. confidence in [0,1].
    confidence < 0.6 means caller should use LLM fallback.
    """
    lower = text.lower()
    hits = 0
    total = 3  # risk + horizon + goal each worth 1 point

    # --- Risk tolerance ---
    risk_tolerance = "moderate"  # default
    for risk, keywords in _RISK_BAGS.items():
        if any(kw in lower for kw in keywords):
            risk_tolerance = risk
            hits += 1
            break

    # --- Time horizon ---
    time_horizon_years = 10  # default
    m = _YEARS_RE.search(lower)
    if m:
        time_horizon_years = int(m.group(1))
        hits += 1
    else:
        for word, years in _HORIZON_WORDS.items():
            if word in lower:
                time_horizon_years = years
                hits += 1
                break

    # --- Goal ---
    goal = "growth"  # default
    for g, keywords in _GOAL_BAGS.items():
        if any(kw in lower for kw in keywords):
            goal = g
            hits += 1
            break

    # --- Restrictions ---
    restrictions = [kw for kw in _RESTRICTION_KEYWORDS if kw in lower]

    confidence = hits / total

    return {
        "risk_tolerance": risk_tolerance,
        "time_horizon_years": time_horizon_years,
        "goal": goal,
        "restrictions": restrictions,
        "confidence": round(confidence, 2),
    }
