"""SHIP 3 — central LLM client. Routes through local relay by default.
Fail-closed: relay down AND FALLBACK_TO_API!='true' => RuntimeError.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
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

# ── Relay resilience state (2026-07-06) ───────────────────────────────────────
# Tracks last-known status so /api/health can surface relay status without
# actively probing, and so the client can trip a circuit breaker after a
# short burst of failures instead of spending 3-5 seconds per call retrying
# a dead relay.
#
# State fields:
#   last_success_at:        datetime of the most recent 200 from /infer
#   consecutive_failures:   count since the last success
#   circuit_open_until:     datetime beyond which calls short-circuit
#   failure_history:        rolling window of failure timestamps for the
#                           "3 failures in 5 min" circuit trip rule
#   last_alert_by_type:     debounce map keyed by RELAY_CONNECT_ERROR /
#                           RELAY_TIMEOUT / RELAY_5XX to prevent
#                           duplicate ops alerts within 15 min
_RELAY_STATE: dict = {
    "last_success_at": None,
    "consecutive_failures": 0,
    "circuit_open_until": None,
    "failure_history": [],
    "last_alert_by_type": {},
    "last_error_type": None,
    "last_error_message": None,
}

# Circuit breaker parameters — matches Brock's spec.
_CIRCUIT_TRIP_FAILURES = 3         # trip after this many failures
_CIRCUIT_TRIP_WINDOW_SEC = 300     # ... within 5 min
_CIRCUIT_OPEN_DURATION_SEC = 60    # short-circuit for this long
_ALERT_DEBOUNCE_SEC = 900          # 15 min per error type


def _classify_relay_error(exc: Exception) -> str:
    """Return a stable error-type string for alert dedup + health surfacing."""
    import httpx as _hx
    if isinstance(exc, _hx.ConnectError):
        return "RELAY_CONNECT_ERROR"
    if isinstance(exc, _hx.TimeoutException):
        return "RELAY_TIMEOUT"
    msg = str(exc)
    # 5xx bucket. _post_to_relay wraps 5xx into a RuntimeError with the
    # status code in the message, so we string-match here.
    for code in ("500", "502", "503", "504"):
        if f"relay {code}" in msg or f"relay returned {code}" in msg:
            return "RELAY_5XX"
    # Terminal "unreachable after 3 attempts" wrapper. Best-effort extract of
    # the wrapped exception class name from the message.
    if "unreachable after 3 attempts" in msg:
        for known in ("ConnectError", "ReadTimeout", "ConnectTimeout"):
            if known in msg:
                if known == "ConnectError":
                    return "RELAY_CONNECT_ERROR"
                return "RELAY_TIMEOUT"
    return "RELAY_UNKNOWN"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record_relay_success() -> None:
    _RELAY_STATE["last_success_at"] = _now()
    _RELAY_STATE["consecutive_failures"] = 0
    _RELAY_STATE["circuit_open_until"] = None
    _RELAY_STATE["failure_history"] = []
    _RELAY_STATE["last_error_type"] = None
    _RELAY_STATE["last_error_message"] = None


def _record_relay_failure(exc: Exception) -> str:
    """Update state after a failure. Returns the classified error type."""
    err_type = _classify_relay_error(exc)
    now = _now()
    _RELAY_STATE["consecutive_failures"] += 1
    _RELAY_STATE["last_error_type"] = err_type
    _RELAY_STATE["last_error_message"] = str(exc)[:400]
    # Rolling 5-min failure history — trip the circuit if it fills up.
    history: list = _RELAY_STATE["failure_history"]
    history.append(now)
    cutoff = now - timedelta(seconds=_CIRCUIT_TRIP_WINDOW_SEC)
    _RELAY_STATE["failure_history"] = [t for t in history if t >= cutoff]
    if len(_RELAY_STATE["failure_history"]) >= _CIRCUIT_TRIP_FAILURES:
        _RELAY_STATE["circuit_open_until"] = now + timedelta(seconds=_CIRCUIT_OPEN_DURATION_SEC)
        logger.warning(
            "[llm_client] circuit breaker OPEN for %ds after %d failures in %ds "
            "(last error: %s)",
            _CIRCUIT_OPEN_DURATION_SEC, len(_RELAY_STATE["failure_history"]),
            _CIRCUIT_TRIP_WINDOW_SEC, err_type,
        )
    return err_type


def _circuit_open() -> bool:
    open_until = _RELAY_STATE["circuit_open_until"]
    if open_until is None:
        return False
    if _now() >= open_until:
        # Cooldown elapsed. Half-open: reset circuit but keep failure count so
        # a single success closes it cleanly and a fresh failure re-trips.
        _RELAY_STATE["circuit_open_until"] = None
        return False
    return True


def get_relay_state() -> dict:
    """Return a serializable snapshot for /api/health."""
    open_until = _RELAY_STATE["circuit_open_until"]
    last_success = _RELAY_STATE["last_success_at"]
    return {
        "status": "circuit_open" if open_until and _now() < open_until
                  else "healthy" if _RELAY_STATE["consecutive_failures"] == 0 and last_success
                  else "unknown" if last_success is None and _RELAY_STATE["consecutive_failures"] == 0
                  else "degraded",
        "last_success_at": last_success.isoformat() if last_success else None,
        "consecutive_failures": _RELAY_STATE["consecutive_failures"],
        "circuit_open": open_until is not None and _now() < open_until,
        "circuit_open_until": open_until.isoformat() if open_until else None,
        "last_error_type": _RELAY_STATE["last_error_type"],
        "last_error_message": _RELAY_STATE["last_error_message"],
        "failures_in_window": len(_RELAY_STATE["failure_history"]),
    }


# Legacy single-key debounce retained so existing callers of
# _emit_relay_down_alert do not crash. New alert path uses
# _emit_typed_relay_alert.
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
        # Circuit breaker: after 3 failures within 5 min, short-circuit new
        # calls for 60 seconds. Avoids burning 3-5s per attempt on a dead
        # relay while ops recovers.
        if _circuit_open():
            open_until = _RELAY_STATE["circuit_open_until"]
            secs_left = int((open_until - _now()).total_seconds()) if open_until else 0
            err = RuntimeError(
                f"relay circuit_open — short-circuiting for {secs_left}s "
                f"(last error: {_RELAY_STATE['last_error_type']})"
            )
            raise err

        t0 = time.monotonic()
        try:
            text_out = _post_to_relay(model, prompt, system_prompt, max_tokens, agent_name)
            _record_relay_success()
            duration_ms = int((time.monotonic() - t0) * 1000)
            _log_llm_call(agent_name=agent_name, model=model,
                          prompt_chars=len(system_prompt) + len(prompt),
                          response_chars=len(text_out), source="relay",
                          duration_ms=duration_ms, db=db)
            return text_out
        except Exception as relay_exc:
            err_type = _record_relay_failure(relay_exc)
            if os.getenv("FALLBACK_TO_API", "false").strip().lower() != "true":
                _emit_typed_relay_alert(err_type, relay_exc)
                raise RuntimeError(
                    f"relay unreachable and FALLBACK_TO_API=false ({err_type}): {relay_exc}"
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
    backoffs = [0.5, 1.5]  # 2 retries, then give up (worst-case +2s)
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=60) as c:
                r = c.post(
                    f"{url}/infer",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json={"model": model, "prompt": prompt,
                          "system_prompt": system_prompt,
                          "max_tokens": max_tokens, "agent_name": agent_name},
                )
            if r.status_code == 200:
                return r.json()["response_text"]
            # 5xx is transient — retry. 4xx is deterministic (auth, malformed) — fail fast.
            if 500 <= r.status_code < 600 and attempt < 2:
                last_exc = RuntimeError(f"relay {r.status_code}: {r.text[:200]}")
                logger.warning("[llm_client] relay 5xx attempt %d/3: %s",
                               attempt + 1, last_exc)
                time.sleep(backoffs[attempt])
                continue
            raise RuntimeError(f"relay returned {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < 2:
                logger.warning("[llm_client] relay httpx attempt %d/3 failed: %s: %s",
                               attempt + 1, type(exc).__name__, str(exc)[:200])
                time.sleep(backoffs[attempt])
                continue
            raise RuntimeError(
                f"relay unreachable after 3 attempts: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
    raise RuntimeError(
        f"relay unreachable after 3 attempts: "
        f"{type(last_exc).__name__ if last_exc else 'Unknown'}: "
        f"{str(last_exc)[:300]}"
    )


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
    """Legacy entry point. Delegates to the typed alert so callers still work."""
    _emit_typed_relay_alert(_classify_relay_error(exc), exc)


def _emit_typed_relay_alert(err_type: str, exc: Exception) -> None:
    """Post one ops alert per error type per 15-min window.

    Prevents the "100 duplicate CRITs" pile-up when the Mac relay is dead:
    first failure alerts, subsequent failures within 15 min stay silent,
    a different error type still alerts once (so a Connect->5xx transition
    surfaces).
    """
    now = _now()
    last_alerts = _RELAY_STATE["last_alert_by_type"]
    last = last_alerts.get(err_type)
    if last and (now - last).total_seconds() < _ALERT_DEBOUNCE_SEC:
        return
    last_alerts[err_type] = now

    # Human-readable recovery hint keyed by error type.
    recovery_hint = {
        "RELAY_CONNECT_ERROR":
            "DNS resolution or TCP connect failed. Mac relay is likely "
            "asleep, the tunnel (ngrok/cloudflared) is down, or RELAY_URL "
            "points to a stale hostname. Wake the Mac, restart the tunnel, "
            "verify `nslookup <relay-host>` from a shell.",
        "RELAY_TIMEOUT":
            "Relay accepted the connection but did not respond within the "
            "client timeout. Mac is up but the relay process is stuck or "
            "overloaded. Check `ps aux | grep relay` on the Mac.",
        "RELAY_5XX":
            "Relay returned a 5xx status. The relay process is running "
            "but errored on this request. Check the relay's own logs "
            "for the underlying exception.",
        "RELAY_UNKNOWN":
            "Unclassified relay error. Read the exception text for context.",
    }.get(err_type, "See exception for details.")

    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            severity="critical",
            title=f"[RELAY-DOWN] {err_type} + fallback disabled",
            message=(
                f"call_llm() raised {err_type}.\n"
                f"Exception: {str(exc)[:400]}\n\n"
                f"Recovery: {recovery_hint}\n\n"
                f"Consecutive failures: {_RELAY_STATE['consecutive_failures']}. "
                f"Circuit breaker: "
                f"{'OPEN' if _circuit_open() else 'CLOSED'}. "
                f"Next alert for {err_type}: in {_ALERT_DEBOUNCE_SEC // 60} min if the "
                f"outage persists."
            ),
            source="llm_client",
        )
    except Exception:
        logger.warning("[llm_client] could not emit typed relay-down alert", exc_info=True)


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
