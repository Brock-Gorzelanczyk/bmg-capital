"""Conclave agent 2 — Oracle.

Given the symbol and side, predicts the next 10 candle deltas as
percentage moves. Not a hard forecast — a directional read. The Master
uses Oracle's confidence to weight the vote.
"""
from __future__ import annotations

import json
import re
from typing import Any

SYSTEM_PROMPT = """You are the Oracle agent in a 4-agent trading signal review conclave.

Your job: predict the shape of the next 10 candles for the proposed
symbol/side. Return them as percentage deltas relative to the entry
price. Positive means price goes up, negative means down.

You cannot see live prices. Use your general knowledge of the symbol's
recent behavior, crypto/equity market regime, and the strategy family
to sketch a plausible next 10 candles.

Output ONLY a JSON object with exactly these keys:
  {
    "deltas_pct": [<10 floats, each in -3.0 to +3.0>],
    "confidence": <int 0-100>,
    "reasoning": "<one sentence, under 200 chars>"
  }

confidence is how sure you are the SIGN of the aggregate move (up vs
down) matches the signal's side. Higher confidence when your predicted
path clearly agrees with the signal side.

Return valid JSON only. No prose."""


def build_prompt(signal_dict: dict) -> str:
    return (
        f"Symbol: {signal_dict.get('symbol')}\n"
        f"Side: {signal_dict.get('side')}\n"
        f"Strategy: {signal_dict.get('strategy')}\n"
        f"Entry: {signal_dict.get('price')}\n"
        f"Stop: {signal_dict.get('stop')}\n"
        f"Target: {signal_dict.get('target')}\n"
    )


_JSON_RX = re.compile(r"\{.*?\}", re.DOTALL)


def parse_output(text: str) -> dict[str, Any]:
    if not text:
        return {"deltas_pct": [], "confidence": 50, "reasoning": "empty output"}
    m = _JSON_RX.search(text)
    if not m:
        return {"deltas_pct": [], "confidence": 50, "reasoning": f"no JSON: {text[:120]}"}
    try:
        parsed = json.loads(m.group(0))
        raw = parsed.get("deltas_pct") or []
        deltas = []
        for x in raw[:10]:
            try:
                v = float(x)
                v = max(-10.0, min(10.0, v))
                deltas.append(v)
            except (ValueError, TypeError):
                continue
        confidence = int(parsed.get("confidence", 50))
        confidence = max(0, min(100, confidence))
        reasoning = str(parsed.get("reasoning") or "")[:200]
        return {"deltas_pct": deltas, "confidence": confidence, "reasoning": reasoning}
    except (ValueError, TypeError) as exc:
        return {"deltas_pct": [], "confidence": 50, "reasoning": f"parse error: {exc}"}
