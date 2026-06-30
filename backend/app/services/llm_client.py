"""SHIP 3 — central LLM client. Routes through local relay by default.
Fail-closed: relay down AND FALLBACK_TO_API!='true' => RuntimeError.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (input, output) in USD as of Nov 2025
_PRICING = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6":         (3.0, 15.0),
}

# Module-scope debounce for the relay-down alert
_LAST_RELAY_DOWN_ALERT_TS = 0.0


# --- Public API -------------------------------------------------------------

def call_llm(
    model: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 1024,
    *,
    agent_name: str = "unknown",
    db: Optional[Session] = None,
) -> str:
    """Route an LLM call through the local relay. Fail-closed by default.

    Raises:
        RuntimeError: if relay unreachable and FALLBACK_TO_API != "true".
        RuntimeError: if API fallback used and 24h fallback spend > LLM_DAILY_FALLBACK_BUDGET_USD.
    """
    owns_db = False
    if db is None:
        db = SessionLocal()
        owns_db = True
    try:
        t0 = time.monotonic()
        try:
            text_out = _post_to_relay(model, prompt, system_prompt, max_tokens, agent_name)
            duration_ms = int((time.monotonic() - t0) * 1000)
            _log_llm_call(agent_name=agent_name, model=model,
                          prompt_chars=len(system_prompt) + len(prompt),
                          response_chars=len(text_out), source="relay",
                          duration_ms=duration_ms, db=db)
            return text_out
        except Exception as relay_exc:
            if os.getenv("FALLBACK_TO_API", "false").strip().lower() != "true":
                _emit_relay_down_alert(relay_exc)
                raise RuntimeError(
                    f"relay unreachable and FALLBACK_TO_API=false: {relay_exc}"
                ) from relay_exc
            _check_fallback_budget(db)  # raises RuntimeError if over cap
            text_out = _fallback_to_api(model, prompt, system_prompt, max_tokens)
            duration_ms = int((time.monotonic() - t0) * 1000)
            _log_llm_call(agent_name=agent_name, model=model,
                          prompt_chars=len(system_prompt) + len(prompt),
                          response_chars=len(text_out), source="api_fallback",
                          duration_ms=duration_ms, db=db)
            _emit_fallback_active_alert(model, len(prompt))
            return text_out
    finally:
        if owns_db:
            db.close()


def call_llm_cached(
    model: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 1024,
    *,
    ttl_seconds: int = 21600,
    cache_key_extra: str = "",
    agent_name: str = "unknown",
    db: Optional[Session] = None,
) -> str:
    """Cache wrapper: SELECT first, INSERT-or-REPLACE on miss after call_llm().

    1. key = sha256(model|system_prompt|prompt|cache_key_extra)
    2. SELECT response_text WHERE cache_key=key AND expires_at > now
    3. Hit: UPDATE hit_count, log with source='cache', return text.
    4. Miss: call call_llm(), INSERT cache row, return text.
    """
    owns_db = False
    if db is None:
        db = SessionLocal()
        owns_db = True
    try:
        key = hashlib.sha256(
            f"{model}|{system_prompt}|{prompt}|{cache_key_extra}".encode()
        ).hexdigest()

        # Try cache hit
        try:
            row = db.execute(text(
                "SELECT response_text FROM anthropic_call_cache "
                "WHERE cache_key = :k AND expires_at > datetime('now')"
            ), {"k": key}).fetchone()
        except Exception:
            row = None

        if row is not None:
            try:
                db.execute(text(
                    "UPDATE anthropic_call_cache "
                    "SET hit_count = hit_count + 1, last_hit_at = CURRENT_TIMESTAMP "
                    "WHERE cache_key = :k"
                ), {"k": key})
                db.commit()
            except Exception:
                pass
            _log_llm_call(agent_name=agent_name, model=model,
                          prompt_chars=len(system_prompt) + len(prompt),
                          response_chars=len(row[0]), source="cache",
                          duration_ms=0, db=db)
            return row[0]

        # Cache miss — call relay
        text_out = call_llm(
            model=model, prompt=prompt, system_prompt=system_prompt,
            max_tokens=max_tokens, agent_name=agent_name, db=db,
        )

        # Write to cache
        try:
            expires_sql = f"datetime('now', '+{ttl_seconds} seconds')"
            db.execute(text(
                "INSERT OR REPLACE INTO anthropic_call_cache "
                "(cache_key, model, prompt_hash, response_json, response_text, expires_at) "
                f"VALUES (:k, :m, :ph, :rj, :rt, {expires_sql})"
            ), {
                "k": key,
                "m": model,
                "ph": hashlib.sha256(prompt.encode()).hexdigest(),
                "rj": json.dumps({"text": text_out}),
                "rt": text_out,
            })
            db.commit()
        except Exception as cache_exc:
            logger.warning("[llm_client] cache write failed: %s", cache_exc)

        return text_out
    finally:
        if owns_db:
            db.close()


def reset_fallback_budget(db: Session) -> int:
    """Delete all api_fallback rows from last 24h. Returns deleted count.
    Called by POST /api/admin/llm/reset-fallback-budget."""
    result = db.execute(text(
        "DELETE FROM llm_call_log "
        "WHERE source = 'api_fallback' AND created_at >= datetime('now', '-24 hours')"
    ))
    db.commit()
    return result.rowcount or 0


# --- Internals --------------------------------------------------------------

def _post_to_relay(model, prompt, system_prompt, max_tokens, agent_name) -> str:
    url = os.getenv("RELAY_URL", "").rstrip("/")
    token = os.getenv("RELAY_AUTH_TOKEN", "")
    if not url or not token:
        raise RuntimeError("RELAY_URL or RELAY_AUTH_TOKEN not configured")
    with httpx.Client(timeout=60) as c:
        r = c.post(
            f"{url}/infer",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": model, "prompt": prompt, "system_prompt": system_prompt,
                  "max_tokens": max_tokens, "agent_name": agent_name},
        )
    if r.status_code != 200:
        raise RuntimeError(f"relay returned {r.status_code}: {r.text[:200]}")
    return r.json()["response_text"]


def _fallback_to_api(model, prompt, system_prompt, max_tokens) -> str:
    # Lazy import — anthropic SDK only loaded when explicitly enabled.
    import anthropic  # noqa: F401  (whitelisted in tests/no_anthropic_imports test)
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("FALLBACK_TO_API=true but ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model, max_tokens=max_tokens,
        system=system_prompt or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def _log_llm_call(*, agent_name, model, prompt_chars, response_chars,
                  source, duration_ms, db) -> None:
    in_per_m, out_per_m = _PRICING.get(model, (1.0, 5.0))
    cost_cents = int(
        ((prompt_chars / 4) * in_per_m + (response_chars / 4) * out_per_m) / 1_000_000 * 100 + 0.5
    )
    try:
        db.execute(text(
            "INSERT INTO llm_call_log "
            "(agent_name, model, prompt_chars, response_chars, source, duration_ms, estimated_cost_cents) "
            "VALUES (:a,:m,:pc,:rc,:s,:d,:c)"
        ), {"a": agent_name, "m": model, "pc": prompt_chars, "rc": response_chars,
            "s": source, "d": duration_ms, "c": cost_cents})
        db.commit()
    except Exception as exc:
        logger.warning("[llm_client] log write failed: %s", exc)


def _check_fallback_budget(db) -> None:
    cap_usd = float(os.getenv("LLM_DAILY_FALLBACK_BUDGET_USD", "5"))
    sum_cents = db.execute(text(
        "SELECT COALESCE(SUM(estimated_cost_cents),0) FROM llm_call_log "
        "WHERE source='api_fallback' AND created_at >= datetime('now','-24 hours')"
    )).scalar() or 0
    if (sum_cents / 100.0) > cap_usd:
        try:
            from app.services.discord import send_ops_alert
            send_ops_alert(
                severity="critical",
                title="LLM API fallback budget exceeded",
                message=(
                    f"24h api_fallback spend = ${sum_cents/100:.2f} > cap ${cap_usd}. "
                    f"All call_llm() raises until POST /api/admin/llm/reset-fallback-budget."
                ),
                source="llm_client",
            )
        except Exception:
            pass
        raise RuntimeError(
            f"LLM API fallback budget exceeded: ${sum_cents/100:.2f} > ${cap_usd}"
        )


def _emit_relay_down_alert(exc: Exception) -> None:
    global _LAST_RELAY_DOWN_ALERT_TS
    now = time.monotonic()
    if now - _LAST_RELAY_DOWN_ALERT_TS < 300:  # 5 min debounce
        return
    _LAST_RELAY_DOWN_ALERT_TS = now
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            severity="critical",
            title="LLM relay unreachable + fallback disabled",
            message=f"call_llm() raised RuntimeError. Exc: {exc}",
            source="llm_client",
        )
    except Exception:
        logger.warning("[llm_client] could not emit relay-down alert", exc_info=True)


def _emit_fallback_active_alert(model: str, prompt_len: int) -> None:
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            severity="warn",
            title="LLM API fallback ACTIVE (billing live)",
            message=(
                f"model={model} prompt_chars={prompt_len}. "
                f"Set FALLBACK_TO_API=false in Railway to silence."
            ),
            source="llm_client",
        )
    except Exception:
        logger.warning("[llm_client] could not emit fallback-active alert", exc_info=True)
