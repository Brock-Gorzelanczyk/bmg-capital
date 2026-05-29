"""
Monitoring service — health checks, financial integrity, AI sentinel.

All functions are wrapped in try/except so monitoring NEVER crashes the app.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def check_health() -> dict:
    """
    Check DB connectivity and API liveness.

    Returns::
        {db: "ok"|"error", api: "ok"|"error", latency_ms: int, timestamp: str}
    """
    result: dict = {
        "db": "error",
        "api": "error",
        "latency_ms": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- DB check ---
    try:
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
            result["db"] = "ok"
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Health check — DB error: %s", exc)

    # --- API latency check ---
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:8000/health")
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        result["latency_ms"] = elapsed_ms
        if resp.status_code == 200:
            result["api"] = "ok"
    except Exception as exc:
        logger.warning("Health check — API error: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Financial integrity check
# ---------------------------------------------------------------------------

def _is_bad_number(v) -> bool:
    """Return True if v is NaN or infinite."""
    try:
        return v is not None and (math.isnan(float(v)) or math.isinf(float(v)))
    except (TypeError, ValueError):
        return False


async def check_financial_integrity(db: Session) -> dict:
    """
    Run financial math integrity checks against PaperAccount / PaperPosition.

    Returns::
        {passed: bool, checks: [{name, passed, detail}], timestamp: str}
    """
    checks: list[dict] = []

    try:
        from app.db.models.paper import PaperAccount, PaperPosition

        # Check 1: No negative share quantities
        neg_positions = (
            db.query(PaperPosition)
            .filter(PaperPosition.qty < 0)
            .all()
        )
        checks.append({
            "name": "No negative share quantities",
            "passed": len(neg_positions) == 0,
            "detail": (
                "All clear"
                if not neg_positions
                else f"{len(neg_positions)} position(s) with qty < 0: "
                     + ", ".join(f"{p.symbol}={p.qty}" for p in neg_positions[:5])
            ),
        })

        # Check 2: No NaN/Infinity in position monetary fields
        all_positions = db.query(PaperPosition).all()
        bad_positions = [
            p for p in all_positions
            if _is_bad_number(p.qty)
            or _is_bad_number(p.avg_cost)
            or _is_bad_number(p.prev_close)
        ]
        checks.append({
            "name": "No NaN/Infinity in position fields",
            "passed": len(bad_positions) == 0,
            "detail": (
                "All clear"
                if not bad_positions
                else f"{len(bad_positions)} position(s) with NaN/Inf values: "
                     + ", ".join(p.symbol for p in bad_positions[:5])
            ),
        })

        # Check 3: Cash balance >= 0 for all accounts
        neg_cash_accounts = (
            db.query(PaperAccount)
            .filter(PaperAccount.cash < 0)
            .all()
        )
        checks.append({
            "name": "Cash balance >= 0 for all accounts",
            "passed": len(neg_cash_accounts) == 0,
            "detail": (
                "All clear"
                if not neg_cash_accounts
                else f"{len(neg_cash_accounts)} account(s) with negative cash: "
                     + ", ".join(
                         f"user_id={a.user_id} cash={a.cash:.2f}"
                         for a in neg_cash_accounts[:5]
                     )
            ),
        })

        # Check 4: No NaN/Infinity in account monetary fields
        all_accounts = db.query(PaperAccount).all()
        bad_accounts = [
            a for a in all_accounts
            if _is_bad_number(a.cash) or _is_bad_number(a.starting_balance)
        ]
        checks.append({
            "name": "No NaN/Infinity in account fields",
            "passed": len(bad_accounts) == 0,
            "detail": (
                "All clear"
                if not bad_accounts
                else f"{len(bad_accounts)} account(s) with NaN/Inf cash values"
            ),
        })

    except Exception as exc:
        logger.error("Financial integrity check failed: %s", exc, exc_info=True)
        checks.append({
            "name": "integrity_check_runner",
            "passed": False,
            "detail": f"Check runner error: {exc}",
        })

    all_passed = all(c["passed"] for c in checks)
    return {
        "passed": all_passed,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# AI sentinel
# ---------------------------------------------------------------------------

async def run_ai_sentinel(db: Session, anthropic_api_key: str) -> dict:
    """
    Nightly LLM review. Sample recent anomalies and get a structured digest from
    Claude claude-sonnet-4-5.

    Returns::
        {findings: [{priority, title, description, action}], generated_at: str}
    """
    if not anthropic_api_key:
        return {
            "findings": [{
                "priority": "P3",
                "title": "AI Sentinel disabled",
                "description": "ANTHROPIC_API_KEY is not configured.",
                "action": "Set the ANTHROPIC_API_KEY environment variable to enable nightly AI analysis.",
            }],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        from app.db.models.paper import PaperOrder, PaperAccount

        since = datetime.now(timezone.utc) - timedelta(hours=24)

        # Accounts with > 50 trades in last 24h
        high_activity: list[dict] = []
        try:
            from sqlalchemy import func
            rows = (
                db.query(PaperOrder.user_id, func.count(PaperOrder.id).label("cnt"))
                .filter(PaperOrder.created_at >= since)
                .group_by(PaperOrder.user_id)
                .all()
            )
            high_activity = [
                {"user_id": r.user_id, "trade_count": r.cnt}
                for r in rows
                if r.cnt > 50
            ]
        except Exception as exc:
            logger.warning("Sentinel: could not query paper orders: %s", exc)

        # Account summary
        account_summary: list[dict] = []
        try:
            accounts = db.query(PaperAccount).all()
            account_summary = [
                {
                    "user_id": a.user_id,
                    "cash": round(a.cash, 2),
                    "starting_balance": round(a.starting_balance, 2),
                    "pnl_estimate": round(a.cash - a.starting_balance, 2),
                }
                for a in accounts
            ]
        except Exception as exc:
            logger.warning("Sentinel: could not query paper accounts: %s", exc)

        context = {
            "high_activity_accounts_last_24h": high_activity,
            "paper_accounts_summary": account_summary,
        }

        prompt = (
            "You are a financial-system monitoring AI. Analyze the following operational "
            "snapshot from BMG Capital's paper-trading system and identify any anomalies, "
            "risks, or notable patterns. Return ONLY a JSON object — no markdown fences.\n\n"
            "JSON shape required:\n"
            '{"findings": [{"priority": "P1|P2|P3", "title": "...", '
            '"description": "...", "action": "..."}]}\n\n'
            "P1 = critical (data loss risk, security issue), "
            "P2 = warning (performance anomaly, unusual behavior), "
            "P3 = informational.\n\n"
            f"Snapshot:\n{json.dumps(context, indent=2)}\n\n"
            "Return only the JSON object. Maximum 500 tokens."
        )

        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()

        # Strip markdown fences if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        parsed = json.loads(raw_text)
        findings = parsed.get("findings", [])

        # Normalise — ensure all required keys exist
        for f in findings:
            f.setdefault("priority", "P3")
            f.setdefault("title", "Untitled finding")
            f.setdefault("description", "")
            f.setdefault("action", "")

        return {
            "findings": findings,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.error("AI sentinel failed: %s", exc, exc_info=True)
        return {
            "findings": [{
                "priority": "P2",
                "title": "AI Sentinel execution error",
                "description": str(exc),
                "action": "Check server logs for details.",
            }],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Webhook alert delivery
# ---------------------------------------------------------------------------

async def send_webhook_alert(
    webhook_url: str,
    title: str,
    message: str,
    priority: str,
) -> None:
    """
    POST to Slack/Discord webhook. Fail silently — never crashes the app.
    Uses Slack format which Discord also accepts.
    """
    if not webhook_url:
        return
    try:
        payload = {"text": f"*[{priority}] {title}*\n{message}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(webhook_url, json=payload)
    except Exception as exc:
        logger.warning("Webhook alert delivery failed (ignored): %s", exc)
