"""Parameter sampling for Strategy Farm templates.

Takes a template's param_schema and returns N unique parameter dicts.
For int / float schemas, samples uniformly across [min, max] snapped
to `step`. For int_list (variable-length integer lists such as EMA
ribbon lengths), builds a length-3-to-6 list of steps.

No LLM. No math library beyond stdlib. Deterministic when passed a
seeded random.Random.
"""
from __future__ import annotations

import random
from typing import Any


def _sample_one(spec: dict, rng: random.Random) -> Any:
    t = str(spec.get("type", "float")).lower()
    lo = float(spec.get("min", 0))
    hi = float(spec.get("max", 1))
    step = float(spec.get("step", 1))
    if hi < lo:
        lo, hi = hi, lo
    if step <= 0:
        step = 1.0

    if t == "int":
        n_steps = max(1, int(round((hi - lo) / step)))
        k = rng.randint(0, n_steps)
        return int(round(lo + k * step))
    if t == "float":
        n_steps = max(1, int(round((hi - lo) / step)))
        k = rng.randint(0, n_steps)
        return round(lo + k * step, 4)
    if t == "int_list":
        # Variable-length integer list. Take 3-6 evenly spaced values
        # spanning [lo, hi] but with jitter so different candidates
        # explore different ribbon layouts.
        length = rng.randint(3, 6)
        span = max(1.0, hi - lo)
        base = [lo + (i + 0.5) * span / length for i in range(length)]
        jitter = [rng.uniform(-step, step) for _ in range(length)]
        vals = sorted({max(int(lo), min(int(hi), int(round(b + j))))
                       for b, j in zip(base, jitter)})
        return vals or [int(lo)]
    # unknown types default to float
    return round(rng.uniform(lo, hi), 4)


def sample_parameters(param_schema: dict, rng: random.Random) -> dict:
    """Return a single parameter dict following the schema."""
    return {k: _sample_one(v, rng) for k, v in param_schema.items()}


def unique_samples(param_schema: dict, n: int, seed: int = 0) -> list[dict]:
    """Return up to n unique parameter dicts.

    Tries up to 5*n attempts, deduplicated by JSON representation.
    Returns fewer than n if the schema space is smaller than n.
    """
    import json
    rng = random.Random(seed)
    seen: set[str] = set()
    out: list[dict] = []
    attempts = 0
    max_attempts = max(20, 5 * n)
    while len(out) < n and attempts < max_attempts:
        attempts += 1
        params = sample_parameters(param_schema, rng)
        key = json.dumps(params, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(params)
    return out
