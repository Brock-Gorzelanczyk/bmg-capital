"""Conclave agent 1 — Analyst.

Reads the raw signal (bot, symbol, side, confidence, strategy, reason,
entry/stop/target). Returns a 0-100 conviction score based on whether
the setup looks structurally coherent: does the reason match the
strategy family, is the R:R sane, is the confidence in a reasonable
band for the strategy type.

Not asked to predict — that's Oracle. Not asked to look at history —
that's Quant. Analyst is the first sanity gate.
"""
from __future__ import annotations

import json
import re
from typing import Any

SYSTEM_PROMPT = """You are the Analyst agent in a 4-agent trading signal review conclave.

Your job: score whether a proposed trading signal is STRUCTURALLY COHERENT.

Do NOT predict market direction. Do NOT reference historical data. Only
evaluate whether the setup makes internal sense: R:R ratio, whether the
reason matches the strategy, whether the confidence value is plausible.

Output ONLY a JSON object with exactly these keys:
  {"score": <int 0-100>, "reasoning": "<one sentence, under 200 chars>"}

Higher score means more coherent. Return valid JSON only. No prose."""


def build_prompt(signal_dict: dict) -> str:
    entry = signal_dict.get("price")
    stop = signal_dict.get("stop")
    target = signal_dict.get("target")
    rr = None
    if entry and stop and target and abs(entry - stop) > 1e-9:
        rr = round(abs(target - entry) / abs(entry - stop), 2)
    return (
        f"Bot: {signal_dict.get('bot')}\n"
        f"Strategy: {signal_dict.get('strategy')}\n"
        f"Symbol: {signal_dict.get('symbol')}\n"
        f"Side: {signal_dict.get('side')}\n"
        f"Confidence: {signal_dict.get('confidence')}\n"
        f"Entry: {entry}\n"
        f"Stop: {stop}\n"
        f"Target: {target}\n"
        f"R:R: {rr}\n"
        f"Reason: {str(signal_dict.get('reason') or '')[:600]}\n"
    )


_JSON_RX = re.compile(r"\{.*?\}", re.DOTALL)


def parse_output(text: str) -> dict[str, Any]:
    """Extract {score, reasoning} from LLM output. Fail-soft on malformed."""
    if not text:
        return {"score": 50, "reasoning": "empty output"}
    m = _JSON_RX.search(text)
    if not m:
        return {"score": 50, "reasoning": f"no JSON: {text[:120]}"}
    try:
        parsed = json.loads(m.group(0))
        score = int(parsed.get("score", 50))
        score = max(0, min(100, score))
        reasoning = str(parsed.get("reasoning") or "")[:200]
        return {"score": score, "reasoning": reasoning}
    except (ValueError, TypeError) as exc:
        return {"score": 50, "reasoning": f"parse error: {exc}"}
