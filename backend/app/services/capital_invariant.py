"""capital_invariant — watchdog asserting SUM(starting_capital_cents) == $1M.

Three layers, per the m027 spec:
  1. check_capital_invariant(user_id, db) — pure check, returns
     (is_valid, current_sum_cents, drift_cents).
  2. Scheduled every 5 min via the existing scheduler (registered in
     screener/scheduler.py).
  3. Diagnostics card endpoint at /admin/diagnostics/capital-invariant
     surfaces current state + audit_log activity in last 24h.

Drift > $1 triggers:
  - logger.critical with the drift amount + per-bot breakdown
  - POST to ops Discord webhook (env DISCORD_WH_OPS) if set

The intent: catch any new auto-grow source within 5 minutes of it firing.
If the m027 fix to _ensure_portfolios_for_user is durable, this watchdog
NEVER fires. If any future change reintroduces a capital write outside
migrations, we know within 5 minutes.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

EXPECTED_SUM_CENTS = 100_000_000  # $1,000,000.00
DRIFT_OK_CENTS = 100              # ±$1 OK band
DRIFT_WARN_CENTS = 10_000         # $100 = WARN
# Above WARN = CRIT


@dataclass
class CapitalInvariantStatus:
    is_valid: bool
    current_sum_cents: int
    drift_cents: int
    drift_dollars: float
    status: str          # "ok" | "warn" | "crit"
    enabled_count: int
    expected_count: int
    last_checked_at: str
    audit_log_rows_24h: int
    per_bot: list[dict]


_EXPECTED_NAMES = (
    "stock_swing", "stock_lt", "stock_day",
    "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
    "options_income", "options_directional",
    "crypto_quant_aggressive", "crypto_quant_mean_reversion",
    "crypto_quant_scalper", "cash_floor",
)


def check_capital_invariant(db, user_id: int = 1) -> CapitalInvariantStatus:
    """Pure check. Returns CapitalInvariantStatus."""
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT p.name, a.starting_capital_cents
          FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = :uid AND a.enabled = 1
    """), {"uid": user_id}).fetchall()

    per_bot = [{"name": r[0], "starting_cents": int(r[1] or 0)} for r in rows]
    current_sum = sum(b["starting_cents"] for b in per_bot)
    drift = current_sum - EXPECTED_SUM_CENTS

    abs_drift = abs(drift)
    if abs_drift <= DRIFT_OK_CENTS:
        status = "ok"
    elif abs_drift <= DRIFT_WARN_CENTS:
        status = "warn"
    else:
        status = "crit"

    # Audit log activity in last 24h (proves auto-grow source is/isn't live).
    audit_rows = 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = db.execute(text("""
            SELECT COUNT(*) FROM capital_audit_log
             WHERE ts >= :cutoff
               AND note NOT IN ('m027_pre_reset', 'm027_post_reset')
        """), {"cutoff": cutoff}).fetchone()
        audit_rows = int(row[0]) if row else 0
    except Exception:
        audit_rows = -1  # table missing

    return CapitalInvariantStatus(
        is_valid=(status == "ok"),
        current_sum_cents=current_sum,
        drift_cents=drift,
        drift_dollars=drift / 100.0,
        status=status,
        enabled_count=len(per_bot),
        expected_count=len(_EXPECTED_NAMES),
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        audit_log_rows_24h=audit_rows,
        per_bot=per_bot,
    )


def _post_discord_ops(message: str) -> None:
    """Best-effort POST to DISCORD_WH_OPS. Never raises."""
    webhook = os.environ.get("DISCORD_WH_OPS", "").strip()
    if not webhook:
        return
    try:
        import urllib.request
        import json as _json
        data = _json.dumps({"content": message[:1900]}).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        logger.warning("[capital_invariant] discord post failed: %s", exc)


def run_check_and_alert(db, user_id: int = 1) -> CapitalInvariantStatus:
    """Run check; alert on WARN/CRIT. Returns the status."""
    status = check_capital_invariant(db, user_id)
    if status.status == "ok":
        logger.info(
            "[capital_invariant] OK user=%d sum=%d drift=%d audit_24h=%d",
            user_id, status.current_sum_cents, status.drift_cents,
            status.audit_log_rows_24h,
        )
        return status

    severity_word = "CRITICAL" if status.status == "crit" else "WARN"
    log_level = logging.CRITICAL if status.status == "crit" else logging.WARNING

    breakdown = "\n".join(
        f"  - {b['name']}: ${b['starting_cents']/100:,.2f}"
        for b in status.per_bot
    )
    msg = (
        f"[capital_invariant] {severity_word} user={user_id} "
        f"sum=${status.current_sum_cents/100:,.2f} "
        f"drift=${status.drift_dollars:+,.2f} "
        f"enabled={status.enabled_count}/{status.expected_count} "
        f"audit_24h={status.audit_log_rows_24h}\n{breakdown}"
    )
    logger.log(log_level, msg)
    _post_discord_ops(
        f":rotating_light: capital invariant {severity_word} — "
        f"sum=${status.current_sum_cents/100:,.2f} "
        f"drift=${status.drift_dollars:+,.2f} (expected $1,000,000.00)"
    )
    return status


def run_check_with_session(user_id: int = 1) -> Optional[CapitalInvariantStatus]:
    """Wrapper that opens its own session — used by the scheduler so the
    job is self-contained.
    """
    try:
        from app.db.session import SessionLocal
    except Exception as exc:
        logger.warning("[capital_invariant] no SessionLocal available: %s", exc)
        return None
    db = SessionLocal()
    try:
        return run_check_and_alert(db, user_id)
    except Exception as exc:
        logger.error("[capital_invariant] check failed: %s", exc, exc_info=True)
        return None
    finally:
        db.close()
