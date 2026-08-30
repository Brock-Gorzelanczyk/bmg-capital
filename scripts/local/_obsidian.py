"""Obsidian vault writer for local jobs.

Every local job writes its output to `~/Documents/BMG-Capital-Vault/context/local-jobs/`
as markdown. This gives us:
1. Automatic git backup (vault is a git repo)
2. Full-text search via Obsidian
3. Zero Railway storage cost
4. Timeline audit trail
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

VAULT_ROOT = Path.home() / "Documents" / "BMG-Capital-Vault"
LOCAL_JOBS_DIR = VAULT_ROOT / "context" / "local-jobs"


def write_job_output(
    job_name: str,
    body: str,
    date: str = None,
    subdir: str = None,
) -> Path:
    """Write a local job's output to the vault.

    Args:
        job_name: e.g. "daily_recap", "morning_brief"
        body: markdown content
        date: YYYY-MM-DD (defaults to today UTC)
        subdir: optional subdirectory under local-jobs/

    Returns absolute path written.
    """
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    target_dir = LOCAL_JOBS_DIR
    if subdir:
        target_dir = target_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{date}-{job_name}.md"
    path = target_dir / fname

    # Prepend metadata header
    header = f"""# {job_name} — {date}

*Generated: {datetime.now(timezone.utc).isoformat()} UTC*
*Runner: scripts/local/ (Mac)*

---

"""

    path.write_text(header + body, encoding="utf-8")
    return path


def append_job_log(job_name: str, line: str) -> Path:
    """Append a one-line entry to the rolling log for this job.

    Useful for jobs that run frequently (e.g. sentiment poller) where a
    single daily file would be more useful than one file per run.
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = LOCAL_JOBS_DIR / "logs" / job_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date}.md"
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"- `{ts}` {line}\n")
    return log_path
