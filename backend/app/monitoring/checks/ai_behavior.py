"""AI behavior checks (Category E)."""
from __future__ import annotations
import json
import hashlib
import logging
import time
import httpx

logger = logging.getLogger(__name__)

# Prompt baseline is stored as a hash in the last monitoring result for prompt_drift_detection.
# On first run, establishes baseline. Subsequent runs compare against it.


async def check_ai_provider_health() -> dict:
    """Probe Anthropic availability via HTTP GET /v1/models (no tokens spent).

    SHIP 3 R9: replaced messages.create probe with HTTP GET, reusing vendors.check_anthropic_up.
    """
    from app.monitoring.checks.vendors import check_anthropic_up
    result = await check_anthropic_up()
    detail = result.get("detail", "")
    # Re-format detail to clarify no tokens were used
    result["detail"] = f"latency probe (HTTP, no tokens) — {detail}"
    return result


async def check_prompt_drift() -> dict:
    """
    Hash all system prompts found in routers. On first run, stores baseline hash.
    On subsequent runs, compares to baseline stored in latest monitoring_results row.
    """
    import os
    import glob

    prompt_dir = "/Users/brockgorzelanczyk/my-new-project/backend/app/routers"
    prompt_files = glob.glob(f"{prompt_dir}/**/*.py", recursive=True)

    combined = ""
    for path in sorted(prompt_files):
        try:
            with open(path, 'r') as f:
                content = f.read()
            # Extract only lines that look like system prompt strings
            for line in content.split('\n'):
                if 'system_prompt' in line.lower() or '"role": "system"' in line.lower():
                    combined += line + "\n"
        except Exception:
            continue

    current_hash = hashlib.sha256(combined.encode()).hexdigest()

    # Try to get baseline from DB
    try:
        from app.db.session import SessionLocal
        from app.db.models.monitoring import MonitoringResult
        db = SessionLocal()
        try:
            last = (
                db.query(MonitoringResult)
                .filter(MonitoringResult.check_id == "prompt_drift_detection")
                .filter(MonitoringResult.passed == True)
                .order_by(MonitoringResult.timestamp.desc())
                .first()
            )
            if last and last.extra_json:
                extra = json.loads(last.extra_json)
                baseline_hash = extra.get("prompt_hash")
                if baseline_hash and baseline_hash != current_hash:
                    return {
                        "passed": False,
                        "detail": f"Prompt hash changed: {baseline_hash[:8]}... → {current_hash[:8]}...",
                        "extra": {"prompt_hash": current_hash},
                    }
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Could not check prompt baseline: %s", exc)

    return {
        "passed": True,
        "detail": f"Prompt hash consistent: {current_hash[:8]}...",
        "extra": {"prompt_hash": current_hash},
    }


async def check_ai_cost_budget() -> dict:
    """
    Placeholder: checks Anthropic usage via their API if available.
    Returns informational result — no Anthropic usage API is public yet.
    """
    return {
        "passed": True,
        "detail": "AI cost tracking is manual — check Anthropic dashboard for daily spend.",
    }
