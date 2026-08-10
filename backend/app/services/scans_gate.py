"""Kill switch for bot scans — global + per-sleeve.

Ledger #22 (2026-08-07): backend is monolithic; no way to pause bot
runners short of full redeploy. When the 2026-08-07 restart-drift
incident hit, 30 duplicate BotPosition inserts landed between the
first quarantine and the next restart because there was no "stop
scans, keep API up" toggle.

This module provides three layers of override, checked in order at
`strategy_lab/bot_scheduler.py::_run_and_log` before any scan runs:

  1. Env-var master:  SCANS_ENABLED=false disables ALL scans.
     Requires Railway redeploy. Highest priority.
  2. Env-var sleeve:  SCANS_ENABLED_<SLEEVE>=false disables one sleeve.
     Sleeves: STOCKS, CRYPTO, OPTIONS, QUANT.
  3. Runtime state file at /data/scans_state.json — flipped via
     POST /admin/scans/{pause,resume}. Survives redeploy. Written
     atomically via tmp+rename.

Fail-open: if the state file is malformed or unreadable, scans run.
Reason: a bug in the gate should not silently stop the fleet. A
disk error should never mean "trading is halted" without a human
knowing. The env-var master is the escape hatch when file-based
gate itself misbehaves.

Sleeve inference: uses profile-name prefix (`stock_*` → stocks,
`crypto_*` → crypto, `options_*` → options, `pr_*` → pr, else
`quant`). Reason: BotProfile.asset_class isn't always populated and
this is called on every scan tick — avoid a DB round-trip.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

STATE_PATH = "/data/scans_state.json"
_write_lock = threading.Lock()

SLEEVES = ("stocks", "crypto", "options", "quant", "pr")
_ALL_KEY = "global"


def _sleeve_for_profile(profile_name: str) -> str:
    """Map profile name → sleeve. Prefix-based; matches how bots are named."""
    p = (profile_name or "").lower()
    if p.startswith("stock_"):
        return "stocks"
    if p.startswith("crypto_"):
        # crypto_quant_* still routes to crypto (asset class = crypto)
        return "crypto"
    if p.startswith("options_"):
        return "options"
    if p.startswith("pr_") or p.startswith("portfolio_rank"):
        return "pr"
    # Fallback: everything else lands in "quant"
    return "quant"


def _empty_state() -> dict:
    return {
        _ALL_KEY: True,
        "stocks": True,
        "crypto": True,
        "options": True,
        "quant": True,
        "pr": True,
        "muted_at": None,
        "muted_by": None,
        "muted_reason": None,
        "history": [],
    }


def read_state() -> dict:
    """Read current runtime state. Returns default (all enabled) if missing.
    Never raises — a corrupt file yields the default so scans keep running
    (fail-open per module doctrine)."""
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
        # Fill in missing fields from default
        base = _empty_state()
        base.update({k: v for k, v in data.items() if k in base})
        # History is preserved separately (may be a list of arbitrary shape)
        base["history"] = data.get("history", [])
        return base
    except FileNotFoundError:
        return _empty_state()
    except Exception as exc:
        logger.warning("[scan-gate] state read failed (fail-open): %s", exc)
        return _empty_state()


def _write_state_atomic(new_state: dict) -> None:
    """Atomic tmp+rename write to STATE_PATH. Caller holds _write_lock."""
    d = os.path.dirname(STATE_PATH) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".scans_state_", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(new_state, f)
        os.replace(tmp, STATE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def set_paused(
    sleeve: str,
    paused: bool,
    muted_by: str = "admin",
    muted_reason: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Set a sleeve (or 'all'/'global') to paused/resumed.

    sleeve values: 'global'/'all' (master), or one of SLEEVES.
    paused=True → sleeve blocked. paused=False → sleeve allowed.

    RESUME GATE (Brock 2026-08-10): if there are any unacknowledged
    AUTO_PAUSE records in human_ack_required, resume is REFUSED unless
    force=True. Prevents the "silently resumed a fund the auto-action
    halted" failure class.

    Returns the new state dict OR {"error": "..."} when blocked.
    """
    sleeve_key = "global" if sleeve in ("all", "global") else sleeve
    if sleeve_key not in (_ALL_KEY,) + SLEEVES:
        raise ValueError(f"unknown sleeve: {sleeve!r}; valid: global|{'|'.join(SLEEVES)}")

    # Resume gate: block if any unacked auto-pause exists.
    if not paused and not force:
        try:
            from app.services.human_ack import list_unacked
            from app.db.session import SessionLocal as _SL
            _db = _SL()
            try:
                unacked = list_unacked(_db, category="AUTO_PAUSE")
            finally:
                _db.close()
            if unacked:
                logger.warning(
                    "[scan-gate] RESUME BLOCKED for %s — %d unacked auto-pause(s): %s",
                    sleeve_key, len(unacked),
                    ", ".join(a["ref_key"] for a in unacked[:5])
                )
                return {
                    "error": "resume_blocked_unacked_auto_pauses",
                    "unacked_count": len(unacked),
                    "unacked": unacked[:10],
                    "hint": "POST /admin/ack?ack_id=<id>&by=<user> for each, "
                            "then retry resume. Or pass force=true to override "
                            "(logged; consider carefully).",
                }
        except Exception as _rg_exc:
            logger.warning("[scan-gate] resume gate check failed (allowing resume): %s", _rg_exc)
    with _write_lock:
        st = read_state()
        prior = st.get(sleeve_key)
        st[sleeve_key] = not paused  # state file stores enabled=True, paused=False
        now_iso = datetime.now(timezone.utc).isoformat()
        if paused:
            st["muted_at"] = now_iso
            st["muted_by"] = muted_by
            st["muted_reason"] = muted_reason
        elif all(st.get(k) is True for k in (_ALL_KEY,) + SLEEVES):
            # All resumed → clear the mute metadata
            st["muted_at"] = None
            st["muted_by"] = None
            st["muted_reason"] = None
        # Append to history (bounded)
        hist = list(st.get("history", []))[-99:]
        hist.append({
            "ts": now_iso,
            "sleeve": sleeve_key,
            "action": "pause" if paused else "resume",
            "prior_enabled": prior,
            "by": muted_by,
            "reason": muted_reason,
        })
        st["history"] = hist
        _write_state_atomic(st)
        logger.warning("[scan-gate] %s %s by=%s reason=%s",
                       "PAUSE" if paused else "RESUME",
                       sleeve_key, muted_by, muted_reason)
        return st


def is_scans_enabled(profile_name: str) -> tuple[bool, str]:
    """Return (enabled, reason_if_disabled). Called at scan entry.

    Order of precedence:
      1. SCANS_ENABLED env var — master kill (redeploy required to toggle)
      2. SCANS_ENABLED_<SLEEVE> env var — per-sleeve env kill
      3. State file global — runtime master kill (survives redeploy)
      4. State file sleeve — runtime per-sleeve kill
    """
    # 1. Master env
    if os.getenv("SCANS_ENABLED", "true").strip().lower() == "false":
        return False, "env:SCANS_ENABLED=false"

    # 2. Sleeve env
    sleeve = _sleeve_for_profile(profile_name)
    env_key = f"SCANS_ENABLED_{sleeve.upper()}"
    if os.getenv(env_key, "true").strip().lower() == "false":
        return False, f"env:{env_key}=false"

    # 3+4. State file
    st = read_state()
    if st.get(_ALL_KEY) is False:
        reason = st.get("muted_reason") or ""
        return False, f"state:global_paused (reason={reason!r})"
    if st.get(sleeve) is False:
        reason = st.get("muted_reason") or ""
        return False, f"state:{sleeve}_paused (reason={reason!r})"

    return True, ""


def status_summary() -> dict:
    """Compact snapshot for the admin GET endpoint."""
    st = read_state()
    env_master = os.getenv("SCANS_ENABLED", "true").strip().lower() != "false"
    env_sleeves = {
        s: os.getenv(f"SCANS_ENABLED_{s.upper()}", "true").strip().lower() != "false"
        for s in SLEEVES
    }
    return {
        "state_path": STATE_PATH,
        "env": {"master": env_master, "sleeves": env_sleeves},
        "state": {
            "global": st.get(_ALL_KEY, True),
            **{s: st.get(s, True) for s in SLEEVES},
            "muted_at": st.get("muted_at"),
            "muted_by": st.get("muted_by"),
            "muted_reason": st.get("muted_reason"),
        },
        "effective": {
            s: (env_master and env_sleeves[s] and st.get(_ALL_KEY, True) and st.get(s, True))
            for s in SLEEVES
        },
        "history_tail": st.get("history", [])[-10:],
    }
