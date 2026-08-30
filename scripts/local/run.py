#!/usr/bin/env python3
"""Local job runner — dispatched by launchd every 15 min.

Reads schedule.yaml, matches cron expressions to current time (with tolerance),
runs matching jobs, logs to Obsidian vault.

**Design decisions:**
- Uses stdlib only (no yaml lib needed — hand-parses the simple format)
- Jobs are imported dynamically as `scripts.local.job_<name>`
- Each job must expose a `run() -> str` returning markdown output
- Failed jobs log to Obsidian but don't crash the runner
- State file at ~/.bmg-local-jobs.json tracks last-run timestamps for catchup

**Usage:**
    python3 scripts/local/run.py                # run scheduled jobs due now
    python3 scripts/local/run.py --job NAME     # force-run one job
    python3 scripts/local/run.py --list         # show configured jobs
    python3 scripts/local/run.py --dry-run      # show what would run, don't run

Called by launchd (see install_launchd.sh). If Mac was asleep when a
scheduled slot passed, the next runner invocation catches it up (once).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add scripts/local to sys.path so `import _bmg_api` works from jobs
HERE = Path(__file__).parent.resolve()
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# ET timezone via stdlib (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    # Fallback for older Python — approximate as UTC-5 (won't handle DST but this is
    # cheap fallback; user should upgrade to 3.9+ for proper timezone handling)
    ET = timezone(timedelta(hours=-5))

STATE_FILE = Path.home() / ".bmg-local-jobs.json"
CATCHUP_WINDOW_HOURS = 24  # if we missed a job in the last 24h, catch it up once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("local-runner")


def _parse_schedule(path: Path) -> List[Dict]:
    """Parse the simple YAML schedule.yaml by hand (no yaml lib dep)."""
    jobs: List[Dict] = []
    current: Optional[Dict] = None
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].rstrip()  # strip comments
        if not line.strip():
            continue
        if line.startswith("jobs:"):
            continue
        if line.strip().startswith("- name:"):
            if current:
                jobs.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
        elif current is not None and ":" in line:
            key, val = line.strip().split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.lower() in ("true", "false"):
                val = (val.lower() == "true")
            current[key] = val
    if current:
        jobs.append(current)
    return jobs


def _cron_matches(cron: str, now: datetime, tolerance_min: int = 15) -> bool:
    """Simple cron matcher for `M H D m W` format. Only supports numbers,
    star, comma-lists, and ranges. Timezone-aware (ET).

    tolerance_min: match if any minute in the current [now - tolerance, now]
    window would have matched the cron. Handles launchd's 15-min tick cadence.
    """
    now_et = now.astimezone(ET)
    parts = cron.split()
    if len(parts) != 5:
        return False
    minute_p, hour_p, dom_p, month_p, dow_p = parts

    def field_matches(spec: str, val: int) -> bool:
        if spec == "*":
            return True
        for chunk in spec.split(","):
            if "/" in chunk:
                # */N or A-B/N
                base, step = chunk.split("/", 1)
                step_i = int(step)
                if base == "*":
                    if val % step_i == 0:
                        return True
                else:
                    lo, hi = (int(base.split("-")[0]), int(base.split("-")[1])) if "-" in base else (int(base), 59)
                    if lo <= val <= hi and (val - lo) % step_i == 0:
                        return True
            elif "-" in chunk:
                lo, hi = map(int, chunk.split("-"))
                if lo <= val <= hi:
                    return True
            else:
                if int(chunk) == val:
                    return True
        return False

    # Check each minute in the tolerance window
    for delta in range(-tolerance_min, 1):
        t = now_et + timedelta(minutes=delta)
        # cron dow: 0=Sun in some flavors, 1-7 in others. Python weekday: 0=Mon.
        # Our format uses 1-5 = Mon-Fri (standard *nix), so remap Python.
        py_wd = t.weekday()  # 0=Mon
        cron_dow = py_wd + 1  # 1=Mon..7=Sun

        if (field_matches(minute_p, t.minute)
            and field_matches(hour_p, t.hour)
            and field_matches(dom_p, t.day)
            and field_matches(month_p, t.month)
            and field_matches(dow_p, cron_dow)):
            return True
    return False


def _load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_runs": {}}


def _save_state(state: Dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _should_run(job: Dict, now: datetime, state: Dict) -> Tuple[bool, str]:
    """Decide if a job should run right now.

    Returns (should_run, reason).
    """
    name = job["name"]
    cron = job.get("cron", "")
    catchup = job.get("catchup", False)

    last_run_iso = state["last_runs"].get(name)
    last_run = None
    if last_run_iso:
        try:
            last_run = datetime.fromisoformat(last_run_iso)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Case 1: cron matches right now → run
    if _cron_matches(cron, now):
        # But not if we already ran within the last 20 min (prevent double-run)
        if last_run and (now - last_run).total_seconds() < 20 * 60:
            return False, f"already ran at {last_run.isoformat()}"
        return True, "cron-match"

    # Case 2: catchup — cron matched in the last CATCHUP_WINDOW_HOURS AND we haven't
    # run since then → run once to catch up
    if not catchup:
        return False, "cron-miss (no catchup)"

    catchup_start = now - timedelta(hours=CATCHUP_WINDOW_HOURS)
    if last_run and last_run > catchup_start:
        return False, f"catchup: already ran at {last_run.isoformat()}"

    # Look back in 15-min steps for a missed cron slot
    check = now - timedelta(minutes=15)
    while check > catchup_start:
        if _cron_matches(cron, check, tolerance_min=0):
            return True, f"catchup-match at {check.isoformat()}"
        check -= timedelta(minutes=15)

    return False, "no catchup match"


def _run_job(name: str) -> Tuple[bool, str]:
    """Import and invoke `scripts/local/<name>.py::run()`. Returns (ok, output_or_err)."""
    job_path = HERE / f"{name}.py"
    if not job_path.exists():
        return False, f"job file not found: {job_path}"

    try:
        spec = importlib.util.spec_from_file_location(name, job_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "run"):
            return False, f"job {name} has no run() function"
        output = mod.run()
        return True, output or "(no output)"
    except Exception as e:
        tb = traceback.format_exc()
        return False, f"{type(e).__name__}: {e}\n\n{tb}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", help="force-run one job by name")
    ap.add_argument("--list", action="store_true", help="show configured jobs")
    ap.add_argument("--dry-run", action="store_true", help="show what would run")
    args = ap.parse_args()

    schedule_path = HERE / "schedule.yaml"
    if not schedule_path.exists():
        logger.error("schedule.yaml not found at %s", schedule_path)
        sys.exit(1)

    jobs = _parse_schedule(schedule_path)

    if args.list:
        for j in jobs:
            print(f"{j['name']:30} {j.get('cron', ''):20} {j.get('description', '')}")
        return

    if args.job:
        logger.info("force-running job: %s", args.job)
        ok, out = _run_job(args.job)
        print(out)
        sys.exit(0 if ok else 1)

    now = datetime.now(timezone.utc)
    state = _load_state()

    ran = 0
    for job in jobs:
        should, reason = _should_run(job, now, state)
        if not should:
            logger.debug("skip %s: %s", job["name"], reason)
            continue

        logger.info("running %s (%s)", job["name"], reason)
        if args.dry_run:
            print(f"[dry-run] would run: {job['name']}")
            continue

        ok, output = _run_job(job["name"])
        state["last_runs"][job["name"]] = now.isoformat()
        _save_state(state)

        # Log outcome via Obsidian
        try:
            from _obsidian import append_job_log
            append_job_log(job["name"],
                           f"{'ok' if ok else 'FAIL'} — {output[:200].replace(chr(10), ' ')}")
        except Exception as e:
            logger.warning("obsidian log failed: %s", e)

        if ok:
            logger.info("  ✓ %s completed", job["name"])
            ran += 1
        else:
            logger.error("  ✗ %s failed: %s", job["name"], output[:500])

    logger.info("done. ran=%d checked=%d", ran, len(jobs))


if __name__ == "__main__":
    main()
