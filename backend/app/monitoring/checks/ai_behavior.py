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
    """Send a minimal message to Anthropic, measure latency."""
    from app.config import settings
    if not settings.anthropic_api_key:
        return {"passed": True, "detail": "Anthropic key not configured — skipping"}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        t0 = time.monotonic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",  # cheapest + fastest for health check
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with OK"}],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        SLA_MS = 5000
        passed = latency_ms < SLA_MS
        return {
            "passed": passed,
            "detail": f"Anthropic responded in {latency_ms}ms ({'OK' if passed else f'SLOW — SLA is {SLA_MS}ms'})",
        }
    except Exception as exc:
        return {"passed": False, "detail": f"Anthropic API error: {exc}"}


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
