"""R5 — Deterministic robo rationale template (replaces Haiku LLM call).

No LLM required.
"""
from __future__ import annotations


def render_robo_rationale(allocations: list[dict], risk: str, horizon: int) -> str:
    """Render a 2-sentence portfolio rationale from structured allocation data.

    Args:
        allocations: list of {symbol, weight} dicts
        risk: risk tolerance string (e.g. 'conservative', 'moderate', 'aggressive')
        horizon: time horizon in years
    """
    top = sorted(allocations, key=lambda a: -a.get("weight", 0))[:3]
    top_str = ", ".join(
        f"{a['symbol']} {int(a['weight'] * 100)}%" for a in top
    ) if top else "diversified holdings"
    return (
        f"This {risk} portfolio targets a {horizon}-year horizon with "
        f"{top_str} as the core sleeve. "
        f"Rebalanced quarterly to stay within plus or minus 2% of targets."
    )
