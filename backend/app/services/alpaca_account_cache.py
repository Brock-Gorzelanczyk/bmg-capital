"""Process-local TTL cache for Alpaca /v2/account.

Reason: the request-path endpoints /portfolio/summary and
/admin/invariants/run each trigger a synchronous Alpaca account fetch.
Under load (heavy scheduler + concurrent requests), Alpaca latency spikes
push these past Railway's ~30s edge timeout, returning 502 to the user.

Every caller within a 30s window shares the same payload. Miss triggers
a fresh fetch under a lock so we never issue N concurrent identical calls.

Usage:
    from app.services.alpaca_account_cache import get_alpaca_account
    acct = get_alpaca_account()   # dict or None on failure

Cache is invalidatable via clear_alpaca_account_cache() if a caller needs
guaranteed-fresh state (e.g. write-gate pre-check).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS_DEFAULT = float(os.getenv("ALPACA_ACCOUNT_CACHE_TTL_SECONDS", "30"))
_TTL_SECONDS_PAUSED = float(os.getenv("ALPACA_ACCOUNT_CACHE_TTL_PAUSED_SECONDS", "300"))


def _effective_ttl() -> float:
    """Cost cut 2026-08-12 (Brock): while globally paused, extend TTL to 5min.
    Data is slightly staler but nothing's trading, so it doesn't matter."""
    try:
        from app.services.scans_gate import read_state as _rs
        if _rs().get("global") is False:
            return _TTL_SECONDS_PAUSED
    except Exception:
        pass
    return _TTL_SECONDS_DEFAULT


# Legacy name — some callers may still reference it; keep as default value.
_TTL_SECONDS = _TTL_SECONDS_DEFAULT
_FETCH_TIMEOUT_SECONDS = float(os.getenv("ALPACA_ACCOUNT_FETCH_TIMEOUT_SECONDS", "8"))

_acct_lock = threading.Lock()
_acct_payload: Optional[dict[str, Any]] = None
_acct_fetched_at: float = 0.0

_pos_lock = threading.Lock()
_pos_payload: Optional[list[dict[str, Any]]] = None
_pos_fetched_at: float = 0.0


def _creds() -> Optional[tuple[str, str]]:
    kid = os.environ.get("ALPACA_API_KEY", "") or os.environ.get("ALPACA_PAPER_KEY", "")
    ks = os.environ.get("ALPACA_SECRET_KEY", "") or os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ks:
        return None
    return kid, ks


def _fetch_account() -> Optional[dict[str, Any]]:
    c = _creds()
    if c is None:
        return None
    kid, ks = c
    try:
        req = urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/account",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ks},
        )
        return json.loads(urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS).read())
    except Exception as exc:
        logger.warning("[alpaca-cache] account fetch failed: %s", exc)
        return None


def _fetch_positions() -> Optional[list[dict[str, Any]]]:
    c = _creds()
    if c is None:
        return None
    kid, ks = c
    try:
        req = urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ks},
        )
        return json.loads(urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS).read()) or []
    except Exception as exc:
        logger.warning("[alpaca-cache] positions fetch failed: %s", exc)
        return None


def get_alpaca_account(max_age_seconds: Optional[float] = None) -> Optional[dict[str, Any]]:
    """Return cached Alpaca /v2/account payload or fetch fresh if stale."""
    global _acct_payload, _acct_fetched_at
    ttl = max_age_seconds if max_age_seconds is not None else _effective_ttl()
    now = time.time()
    if _acct_payload is not None and (now - _acct_fetched_at) <= ttl:
        return _acct_payload
    with _acct_lock:
        now = time.time()
        if _acct_payload is not None and (now - _acct_fetched_at) <= ttl:
            return _acct_payload
        fresh = _fetch_account()
        if fresh is not None:
            _acct_payload = fresh
            _acct_fetched_at = now
        return _acct_payload


def get_alpaca_positions(max_age_seconds: Optional[float] = None) -> Optional[list[dict[str, Any]]]:
    """Return cached Alpaca /v2/positions list or fetch fresh if stale.
    Used by canonical to derive per-sleeve PV from broker truth (ledger #26
    doctrine — Alpaca is master for any number it knows).
    """
    global _pos_payload, _pos_fetched_at
    ttl = max_age_seconds if max_age_seconds is not None else _effective_ttl()
    now = time.time()
    if _pos_payload is not None and (now - _pos_fetched_at) <= ttl:
        return _pos_payload
    with _pos_lock:
        now = time.time()
        if _pos_payload is not None and (now - _pos_fetched_at) <= ttl:
            return _pos_payload
        fresh = _fetch_positions()
        if fresh is not None:
            _pos_payload = fresh
            _pos_fetched_at = now
        return _pos_payload


def clear_alpaca_account_cache() -> None:
    """Invalidate both caches. Next call will hit Alpaca."""
    global _acct_payload, _acct_fetched_at, _pos_payload, _pos_fetched_at
    with _acct_lock:
        _acct_payload = None
        _acct_fetched_at = 0.0
    with _pos_lock:
        _pos_payload = None
        _pos_fetched_at = 0.0


def alpaca_account_cache_age_seconds() -> Optional[float]:
    """Age of the current cached account payload in seconds, or None if never fetched."""
    if _acct_fetched_at == 0.0:
        return None
    return time.time() - _acct_fetched_at


def alpaca_positions_cache_age_seconds() -> Optional[float]:
    """Age of the current cached positions payload in seconds, or None if never fetched."""
    if _pos_fetched_at == 0.0:
        return None
    return time.time() - _pos_fetched_at
