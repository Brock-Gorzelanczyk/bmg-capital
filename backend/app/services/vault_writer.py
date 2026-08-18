"""Container-side writer for vault artifacts (audits + postmortem stubs).

Ledger #39 + CLAUDE.md §V8: §V7 (nightly self-audit) failed 11+ times in
August because it required a human/Claude to remember. This module makes
the audit line an automatic artifact of the container's daily job, and
gives auto-pause / outage-detected events a pre-filled stub file so
writing a postmortem is editing rather than starting from blank.

Both flows write to /data/:
  - /data/audits/YYYY-MM-DD.md         — daily audit (single line, appended)
  - /data/postmortems-stub/YYYY-MM-DD-slug.md — pre-filled template

Host-side sync (scripts/bmg_vault_sync.sh) pulls both dirs to the Mac vault
via /admin/audits/list, /admin/audits/{date}, /admin/postmortem-stubs/list,
/admin/postmortem-stubs/{filename}.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

AUDIT_DIR = Path(os.getenv("VAULT_AUDIT_DIR", "/data/audits"))
POSTMORTEM_STUB_DIR = Path(os.getenv("VAULT_POSTMORTEM_STUB_DIR", "/data/postmortems-stub"))

# 2026-08-18 Brock: I28 was checking /data/audits/*.md freshness, but that
# lies — the container auto-writes those. Real question is "did Brock's Mac
# actually pull them into the vault repo?" This file records the last time
# bmg_vault_sync.sh POSTed /admin/vault-sync-ping. I28 reads THIS timestamp.
SYNC_PING_PATH = Path(os.getenv("VAULT_SYNC_PING_PATH", "/data/vault_sync_last_ping.json"))


def _ensure_dirs() -> None:
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        POSTMORTEM_STUB_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("[vault_writer] mkdir failed: %s", exc)


def write_daily_audit_line(
    *,
    invariants_summary: str,  # e.g. "0red/2amber/23green"
    open_issues: int,
    ledger_mtime_iso: str,
    notes: str = "",
) -> Optional[str]:
    """Append the §V7 one-line audit to today's file.

    Returns the path written, or None on failure.
    Format matches daily-audits/README.md:
        HH:MM UTC | invariants=… | open_issues=N | vault_mtime=… | notes
    """
    _ensure_dirs()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    ts_str = now.strftime("%H:%M")
    line = (
        f"{ts_str} UTC | invariants={invariants_summary} | "
        f"open_issues={open_issues} | vault_mtime={ledger_mtime_iso}"
    )
    if notes:
        line = f"{line} | {notes}"
    path = AUDIT_DIR / f"{date_str}.md"
    try:
        with path.open("a") as f:
            f.write(line + "\n")
        return str(path)
    except Exception as exc:
        logger.warning("[vault_writer] audit write failed: %s", exc)
        return None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str) -> str:
    return _SLUG_RE.sub("-", s.lower()).strip("-")[:60] or "event"


def write_postmortem_stub(
    *,
    trigger: str,          # e.g. "auto_pause", "outage_detected", "invariant_red_stale"
    title: str,            # short human title
    context: dict[str, Any],  # timestamps, alloc_id, invariant_id, etc.
) -> Optional[str]:
    """Write a pre-filled postmortem stub. Editing rather than starting blank.

    Filename: YYYY-MM-DD-{slug}.md. If a file for the same trigger already
    exists today, we append the new context section rather than clobbering
    (avoids overwriting a partly-edited stub).
    """
    _ensure_dirs()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    slug = _slugify(f"{trigger}-{title}")
    path = POSTMORTEM_STUB_DIR / f"{date_str}-{slug}.md"

    ts_iso = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []
    is_new = not path.exists()

    if is_new:
        lines.extend([
            f"# {date_str} — {title}",
            "",
            f"**Auto-generated stub. Fill in the analysis before this file leaves postmortems-stub/.**",
            f"**Trigger:** {trigger}",
            f"**Detected at:** {ts_iso}",
            "",
            "## What happened",
            "",
            "_TODO — describe the observable event._",
            "",
            "## Root cause",
            "",
            "_TODO — verified root cause with a specific query or reproduction. Not a hypothesis._",
            "",
            "## How long undetected",
            "",
            "_TODO — from first bad state to detection._",
            "",
            "## What detected it",
            "",
            "_TODO — invariant ID, cron job, external watchdog, operator eyes._",
            "",
            "## What prevents it now",
            "",
            "_TODO — invariant, DB constraint, gate, or CI check. Per §V5, 'a human remembers' is not prevention._",
            "",
            "---",
            "",
            "## Detection context (auto-captured)",
            "",
        ])
    else:
        lines.extend([
            "",
            f"### Additional event at {ts_iso} (same trigger)",
            "",
        ])

    for k, v in sorted(context.items()):
        lines.append(f"- **{k}:** {v}")
    lines.append("")

    try:
        with path.open("a") as f:
            f.write("\n".join(lines) + "\n")
        return str(path)
    except Exception as exc:
        logger.warning("[vault_writer] postmortem stub write failed: %s", exc)
        return None


def newest_audit_age_hours() -> Optional[float]:
    """Return the age (hours) of the newest /data/audits/*.md file, or None if empty.

    NOTE: this is NOT the invariant metric. Container auto-writes audits daily
    so this stays fresh whether the vault is being pulled or not. I28 uses
    last_vault_sync_ping_age_hours() below — that's the real signal.
    """
    try:
        if not AUDIT_DIR.exists():
            return None
        newest_mtime = 0.0
        for p in AUDIT_DIR.glob("*.md"):
            m = p.stat().st_mtime
            if m > newest_mtime:
                newest_mtime = m
        if newest_mtime == 0.0:
            return None
        return (datetime.now(timezone.utc).timestamp() - newest_mtime) / 3600.0
    except Exception as exc:
        logger.warning("[vault_writer] newest_audit_age query failed: %s", exc)
        return None


def record_vault_sync_ping(*, git_commit_sha: Optional[str] = None,
                           git_pushed: Optional[bool] = None,
                           source_ip: Optional[str] = None) -> Optional[str]:
    """Called by POST /admin/vault-sync-ping after bmg_vault_sync.sh pulls
    successfully. Records timestamp + optional git provenance so we know
    the vault repo is actually being kept in sync.
    """
    try:
        import json as _json
        SYNC_PING_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_ping_iso": datetime.now(timezone.utc).isoformat(),
            "last_ping_epoch": datetime.now(timezone.utc).timestamp(),
            "git_commit_sha": git_commit_sha,
            "git_pushed": git_pushed,
            "source_ip": source_ip,
        }
        SYNC_PING_PATH.write_text(_json.dumps(payload, indent=2))
        return str(SYNC_PING_PATH)
    except Exception as exc:
        logger.warning("[vault_writer] sync ping write failed: %s", exc)
        return None


def read_vault_sync_ping() -> Optional[dict[str, Any]]:
    try:
        import json as _json
        if not SYNC_PING_PATH.exists():
            return None
        return _json.loads(SYNC_PING_PATH.read_text())
    except Exception as exc:
        logger.warning("[vault_writer] sync ping read failed: %s", exc)
        return None


def last_vault_sync_ping_age_hours() -> Optional[float]:
    """Hours since bmg_vault_sync.sh last checked in. This is what I28 checks.

    Returns None if never pinged (fresh install / never ran) — surfaced as
    AMBER, not RED, so a first-time install doesn't fire a false alarm.
    """
    p = read_vault_sync_ping()
    if not p or "last_ping_epoch" not in p:
        return None
    try:
        return (datetime.now(timezone.utc).timestamp() - float(p["last_ping_epoch"])) / 3600.0
    except Exception:
        return None


def list_audits() -> list[dict[str, Any]]:
    """Return [{date, path, size_bytes, mtime_iso}] for host-side sync."""
    _ensure_dirs()
    out: list[dict[str, Any]] = []
    for p in sorted(AUDIT_DIR.glob("*.md")):
        try:
            st = p.stat()
            out.append({
                "date": p.stem,
                "path": str(p),
                "size_bytes": st.st_size,
                "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            })
        except Exception:
            continue
    return out


def list_postmortem_stubs() -> list[dict[str, Any]]:
    _ensure_dirs()
    out: list[dict[str, Any]] = []
    for p in sorted(POSTMORTEM_STUB_DIR.glob("*.md")):
        try:
            st = p.stat()
            out.append({
                "filename": p.name,
                "path": str(p),
                "size_bytes": st.st_size,
                "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            })
        except Exception:
            continue
    return out


def read_artifact(kind: str, name: str) -> Optional[str]:
    """Read content of /data/audits/{name}.md or /data/postmortems-stub/{name}.

    kind must be 'audit' or 'postmortem_stub'. Returns None on missing/error.
    """
    if kind == "audit":
        p = AUDIT_DIR / (name if name.endswith(".md") else f"{name}.md")
    elif kind == "postmortem_stub":
        p = POSTMORTEM_STUB_DIR / (name if name.endswith(".md") else f"{name}.md")
    else:
        return None
    try:
        if not p.exists() or not p.is_file():
            return None
        # Guard against path escape
        resolved = p.resolve()
        base = (AUDIT_DIR if kind == "audit" else POSTMORTEM_STUB_DIR).resolve()
        if not str(resolved).startswith(str(base)):
            return None
        return p.read_text()
    except Exception as exc:
        logger.warning("[vault_writer] read_artifact(%s,%s) failed: %s", kind, name, exc)
        return None
