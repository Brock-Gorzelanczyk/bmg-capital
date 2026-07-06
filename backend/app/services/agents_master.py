"""Conclave agent 4 — Master.

Reads the three prior agent outputs and makes the final approve/reject
call. Master is the accountable voice — its reasoning is what posts to
Discord alongside the trade if approved, or gets logged privately if
rejected.
"""
from __future__ import annotations

import json
import re
from typing import Any

SYSTEM_PROMPT = """You are the Master agent in a 4-agent trading signal review conclave.

Three specialists have voted. You now decide approve or reject.

Weighting guidance:
  - Quant.verdict is the strongest signal. If Quant rejects with a real
    sample (n>=20 and win_rate<45%), you should reject unless Analyst
    AND Oracle both strongly disagree.
  - Analyst.score under 40 is a structural red flag. Above 70 is a
    strong go signal.
  - Oracle.confidence under 40 means the model doesn't see the setup;
    require the other two to compensate.
  - When all three lean the same way, follow them. Do not overrule the
    majority to look smart.

Output ONLY a JSON object with exactly these keys:
  {"final": "approve" | "reject", "reasoning": "<one sentence explaining the call, under 240 chars>"}

Return valid JSON only. No prose."""


def build_prompt(
    signal_dict: dict,
    analyst: dict,
    oracle: dict,
    quant: dict,
) -> str:
    return (
        f"SIGNAL:\n"
        f"  bot={signal_dict.get('bot')} symbol={signal_dict.get('symbol')} "
        f"side={signal_dict.get('side')} strategy={signal_dict.get('strategy')}\n"
        f"  confidence={signal_dict.get('confidence')} entry={signal_dict.get('price')} "
        f"stop={signal_dict.get('stop')} target={signal_dict.get('target')}\n\n"
        f"ANALYST:\n"
        f"  score={analyst.get('score')}\n"
        f"  reasoning={analyst.get('reasoning')}\n\n"
        f"ORACLE:\n"
        f"  confidence={oracle.get('confidence')}\n"
        f"  deltas_pct_sum={round(sum(oracle.get('deltas_pct') or [0.0]), 3)}\n"
        f"  reasoning={oracle.get('reasoning')}\n\n"
        f"QUANT:\n"
        f"  verdict={quant.get('verdict')}\n"
        f"  win_rate={quant.get('win_rate')}\n"
        f"  sample_size={quant.get('sample_size')}\n"
        f"  reasoning={quant.get('reasoning')}\n"
    )


_JSON_RX = re.compile(r"\{.*?\}", re.DOTALL)


def parse_output(text: str) -> dict[str, Any]:
    if not text:
        return {"final": "approve", "reasoning": "empty master output; fail-open"}
    m = _JSON_RX.search(text)
    if not m:
        return {"final": "approve", "reasoning": f"no JSON in master output: {text[:120]}"}
    try:
        parsed = json.loads(m.group(0))
        final = str(parsed.get("final") or "").strip().lower()
        if final not in ("approve", "reject"):
            return {"final": "approve", "reasoning": f"invalid final={final!r}; fail-open"}
        reasoning = str(parsed.get("reasoning") or "")[:240]
        return {"final": final, "reasoning": reasoning}
    except (ValueError, TypeError) as exc:
        return {"final": "approve", "reasoning": f"master parse error: {exc}; fail-open"}
