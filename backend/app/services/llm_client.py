"""LLM relay client — SHIP 4.

This module is the SOLE entry point for all LLM inference in BMG Capital code.
ZERO files may import anthropic directly. ZERO subprocess calls to `claude`.
ZERO reads of ANTHROPIC_API_KEY outside this file.

The relay (SHIP 4) handles model routing, cost logging to llm_call_log,
rate limiting, and optional caching. This stub is present so SHIP 5 imports
resolve before SHIP 4 lands on main; it will be replaced by the full relay
implementation when both ships merge.

Usage:
    from app.services.llm_client import call_llm

    text = call_llm(
        model="claude-haiku-4-5-20251001",
        prompt="...",
        system_prompt="...",
        max_tokens=600,
        agent_name="equity_researcher",
        db=db,
    )

On relay unavailable + FALLBACK_TO_API=false: raises RuntimeError.
Callers (agent_opening_read, cio_chair) catch RuntimeError and set status='relay_down'.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# SHIP 4 will replace this with the full relay implementation.
# The lazy anthropic import lives HERE and ONLY HERE.


def call_llm(
    *,
    model: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 1024,
    agent_name: str = "unknown",
    db=None,
    temperature: float = 0.3,
) -> str:
    """Route LLM inference through the BMG relay.

    Parameters
    ----------
    model:        Claude model identifier (e.g. 'claude-haiku-4-5-20251001')
    prompt:       User-turn content
    system_prompt: System anchor (pre-pended to message)
    max_tokens:   Hard cap on completion tokens
    agent_name:   Role ID for cost roll-up in llm_call_log
    db:           SQLAlchemy Session (for llm_call_log inserts by relay)
    temperature:  Sampling temperature

    Returns
    -------
    str — raw completion text

    Raises
    ------
    RuntimeError — relay unreachable AND FALLBACK_TO_API != 'true'
    """
    relay_url = os.getenv("LLM_RELAY_URL", "").strip()
    fallback_ok = os.getenv("FALLBACK_TO_API", "false").strip().lower() in ("true", "1")

    if relay_url:
        try:
            return _call_relay(
                relay_url=relay_url,
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                agent_name=agent_name,
                db=db,
                temperature=temperature,
            )
        except Exception as exc:
            logger.error("[llm_client] relay call failed: %s", exc)
            if not fallback_ok:
                raise RuntimeError(f"relay unreachable and FALLBACK_TO_API=false: {exc}") from exc
            logger.warning("[llm_client] falling back to direct API (FALLBACK_TO_API=true)")

    # Direct API path (only reached when relay absent OR fallback enabled)
    if not fallback_ok and not relay_url:
        raise RuntimeError(
            "LLM_RELAY_URL is unset and FALLBACK_TO_API=false — cannot call LLM. "
            "Set LLM_RELAY_URL to point at the SHIP-4 relay."
        )
    return _call_direct_api(
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        agent_name=agent_name,
        db=db,
        temperature=temperature,
    )


def call_llm_cached(
    *,
    model: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 1024,
    agent_name: str = "unknown",
    db=None,
    temperature: float = 0.0,
) -> str:
    """call_llm with caching hint (temperature=0 default for deterministic prompts)."""
    return call_llm(
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        agent_name=agent_name,
        db=db,
        temperature=temperature,
    )


def _call_relay(
    *,
    relay_url: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    agent_name: str,
    db,
    temperature: float,
) -> str:
    """POST to the SHIP-4 LLM relay HTTP endpoint."""
    import httpx  # lazy import — not available in all test envs

    payload = {
        "model": model,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "max_tokens": max_tokens,
        "agent_name": agent_name,
        "temperature": temperature,
    }
    resp = httpx.post(f"{relay_url}/relay/llm", json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["text"]


def _call_direct_api(
    *,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    agent_name: str,
    db,
    temperature: float,
) -> str:
    """Direct Anthropic API call — lazy import of anthropic lives ONLY HERE."""
    import anthropic  # noqa: PLC0415 — intentional lazy import; only this file may import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set and relay unavailable")

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system_prompt:
        kwargs["system"] = system_prompt

    response = client.messages.create(**kwargs)
    text_out = response.content[0].text if response.content else ""

    # Log to llm_call_log as api_fallback if db available
    if db is not None:
        try:
            from sqlalchemy import text as sql_text
            # Estimate cost: haiku ~$0.00025/1k input + $0.00125/1k output; rough floor $0.01
            estimated_cents = 1
            db.execute(
                sql_text(
                    "INSERT INTO llm_call_log "
                    "(agent_name, model, prompt_tokens, completion_tokens, "
                    " estimated_cost_cents, source, created_at) "
                    "VALUES (:an, :m, :pt, :ct, :ec, 'api_fallback', CURRENT_TIMESTAMP)"
                ),
                {
                    "an": agent_name,
                    "m": model,
                    "pt": getattr(response.usage, "input_tokens", 0),
                    "ct": getattr(response.usage, "output_tokens", 0),
                    "ec": estimated_cents,
                },
            )
            db.commit()
        except Exception as log_exc:
            logger.warning("[llm_client] llm_call_log insert failed: %s", log_exc)

    return text_out
