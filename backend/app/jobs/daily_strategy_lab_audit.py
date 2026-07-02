"""Daily Strategy Lab audit job.

Runs 8 checks against existing in-process diagnostics and DB queries.
Persists results to daily_audit_log table (m050).
Optionally posts a Discord summary via DISCORD_WH_DAILY_AUDIT webhook.

Public function:
    run_daily_audit(db: Session) -> dict

THE WALL: no anthropic import, no LLM. This job READS Wall state; never calls APIs.
READ-ONLY against bot_trades, bot_positions, bot_allocations, bot_daily_pnl.
WRITES only to daily_audit_log.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


# ─────────────────────────────────────────────────────────────────────────────
# Check 1: Bot count
# ─────────────────────────────────────────────────────────────────────────────

def _check_bot_count(db: Session) -> dict:
    """Verify exactly 13 enabled bots for user_id=1."""
    try:
        row = db.execute(text(
            "SELECT COUNT(*) FROM bot_allocations WHERE enabled=1 AND user_id=1"
        )).fetchone()
        n = int(row[0]) if row else 0
        if n != 13:
            return {
                "name": "bot_count",
                "status": "ALERT",
                "details": f"expected 13 enabled bots, found {n}",
            }
        return {"name": "bot_count", "status": "GREEN", "details": "13 bots"}
    except Exception as exc:
        return {"name": "bot_count", "status": "ALERT", "details": f"check failed: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# Check 2: Per-bot verdicts
# ─────────────────────────────────────────────────────────────────────────────

def _check_per_bot_verdicts(db: Session) -> tuple[dict, list[str]]:
    """Call compute_bot_diagnostics in-process and evaluate each bot's verdict.

    Returns (check_dict, alert_strings).
    """
    try:
        from app.routers.admin import compute_bot_diagnostics
        bots = compute_bot_diagnostics(db, user_id=1)
    except Exception as exc:
        check = {
            "name": "per_bot_verdicts",
            "status": "ALERT",
            "details": f"check failed: {exc}",
        }
        return check, [f"per_bot_verdicts check failed: {exc}"]

    alerts: list[str] = []
    n_alerts = 0
    n_warns = 0
    now = datetime.now(timezone.utc)

    for bot in bots:
        bot_id = bot.get("bot_id", "unknown")
        verdict = bot.get("verdict", "")
        last_signal_at = bot.get("last_signal_at")

        if verdict == "no_signals":
            days_silent = None
            if last_signal_at:
                try:
                    ts = datetime.fromisoformat(last_signal_at.replace("Z", "+00:00"))
                    days_silent = (now - ts).days
                except (ValueError, TypeError):
                    days_silent = None
            if days_silent is None or days_silent > 7:
                days_str = f"{days_silent}d" if days_silent is not None else "unknown"
                alerts.append(f"bot {bot_id} silent {days_str} since last signal")
                n_alerts += 1
        elif verdict == "stale":
            alerts.append(f"bot {bot_id} verdict=stale (was working, stopped)")
            n_alerts += 1
        elif verdict == "profile_disabled":
            n_warns += 1

    if n_alerts > 0:
        status = "ALERT"
    elif n_warns > 0:
        status = "WARN"
    else:
        status = "GREEN"

    check = {
        "name": "per_bot_verdicts",
        "status": status,
        "details": f"{n_alerts} alerts, {n_warns} warns across {len(bots)} bots",
    }
    return check, alerts


# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Capital invariant
# ─────────────────────────────────────────────────────────────────────────────

def _check_capital_invariant(db: Session) -> dict:
    """Verify sum of starting_capital_cents == $1M across ALL Brock allocations.

    Must include halted bots (enabled=0 with paused_reason set) because their
    capital is still part of the $1M fleet — it's earmarked for the halted
    bot, not returned to the pool. Filtering by enabled=1 alone produced a
    false-positive "-$150k drift" alert every time a bot was halted via Path B.
    """
    try:
        row = db.execute(text(
            "SELECT COALESCE(SUM(starting_capital_cents), 0) "
            "FROM bot_allocations "
            "WHERE user_id=1 AND (enabled=1 OR paused_reason IS NOT NULL)"
        )).fetchone()
        total_cents = int(row[0]) if row else 0
        if total_cents == 100_000_000:
            return {
                "name": "capital_invariant",
                "status": "GREEN",
                "details": "$1,000,000 exact",
            }
        drift = total_cents - 100_000_000
        return {
            "name": "capital_invariant",
            "status": "ALERT",
            "details": (
                f"sum={total_cents} cents, expected 100000000 (drift={drift})"
            ),
        }
    except Exception as exc:
        return {
            "name": "capital_invariant",
            "status": "ALERT",
            "details": f"check failed: {exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Check 4: The Wall (LLM usage)
# ─────────────────────────────────────────────────────────────────────────────

def _check_the_wall(db: Session) -> dict:
    """Verify no paid Anthropic API calls today (THE WALL enforcement)."""
    try:
        from app.routers.admin import compute_llm_usage
        data = compute_llm_usage(db)
        n = data.get("today", {}).get("api_fallback_calls", 0)
        if n > 0:
            return {
                "name": "wall",
                "status": "ALERT",
                "details": f"{n} paid API calls today (Wall broken)",
            }
        return {"name": "wall", "status": "GREEN", "details": "0 paid API calls"}
    except Exception as exc:
        return {"name": "wall", "status": "ALERT", "details": f"check failed: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# Check 5: Crypto-bot equity violations
# ─────────────────────────────────────────────────────────────────────────────

def _check_crypto_equity_violations(db: Session) -> dict:
    """Verify no crypto bots hold equity positions (cross-sleeve violations)."""
    try:
        from app.routers.admin import compute_migration_status
        data = compute_migration_status(db)
        violations = data.get("crypto_bot_equity_violations", [])
        n = len(violations)
        if n > 0:
            return {
                "name": "crypto_equity_violations",
                "status": "ALERT",
                "details": f"{n} crypto-bot equity positions still open",
            }
        return {
            "name": "crypto_equity_violations",
            "status": "GREEN",
            "details": "0 violations",
        }
    except Exception as exc:
        return {
            "name": "crypto_equity_violations",
            "status": "ALERT",
            "details": f"check failed: {exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Check 6: Options OCC format
# ─────────────────────────────────────────────────────────────────────────────

def _check_options_occ_format(db: Session) -> tuple[dict, list[str]]:
    """Verify all options trades in last 24h use OCC symbol format.

    Joins through bot_allocations + bot_profiles to identify options bots by name,
    since bot_trades does not have a bot_id column. Uses ts column (not created_at).
    """
    try:
        rows = db.execute(text("""
            SELECT bt.symbol
              FROM bot_trades bt
              JOIN bot_allocations a ON a.id = bt.allocation_id
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE p.name IN ('options_directional', 'options_income')
               AND a.user_id = 1
               AND bt.ts >= datetime('now', '-24 hours')
               AND bt.quarantined_at IS NULL
        """)).fetchall()
        symbols = [r[0] for r in rows]
        n_total = len(symbols)
        if n_total == 0:
            return (
                {
                    "name": "options_occ_format",
                    "status": "GREEN",
                    "details": "0 options trades in 24h (informational, not an alert)",
                },
                [],
            )
        bad = [s for s in symbols if not _OCC_RE.match(str(s or ""))]
        n_bad = len(bad)
        if n_bad > 0:
            alert_str = (
                f"options OCC-format regression: {n_bad}/{n_total} trades "
                "equity-format (PR #42 gap reopened)"
            )
            return (
                {
                    "name": "options_occ_format",
                    "status": "ALERT",
                    "details": f"{n_bad}/{n_total} options trades non-OCC format",
                },
                [alert_str],
            )
        return (
            {
                "name": "options_occ_format",
                "status": "GREEN",
                "details": f"{n_total} options trades, all OCC format",
            },
            [],
        )
    except Exception as exc:
        return (
            {
                "name": "options_occ_format",
                "status": "ALERT",
                "details": f"check failed: {exc}",
            },
            [f"options_occ_format check failed: {exc}"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Check 7: AQA status (informational only)
# ─────────────────────────────────────────────────────────────────────────────

def _check_aqa_status(db: Session) -> dict:
    """Report AQA status. Informational only — never ALERT or WARN."""
    try:
        from app.routers.aqa_admin import compute_aqa_status
        data = compute_aqa_status(db)
        enabled = data.get("aqa_enabled", False)
        frozen = data.get("frozen", False)
        dt = data.get("deploys_today", 0)
        lt = data.get("llm_calls_today", 0)
        return {
            "name": "aqa_status",
            "status": "GREEN",
            "details": f"enabled={enabled} frozen={frozen} deploys_today={dt} llm_today={lt}",
        }
    except Exception as exc:
        # aqa_status is informational; failure still reports GREEN (non-blocking)
        return {
            "name": "aqa_status",
            "status": "GREEN",
            "details": f"aqa_status unavailable: {exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Check 8: Fund deployment
# ─────────────────────────────────────────────────────────────────────────────

def _check_fund_deployment(db: Session) -> dict:
    """Verify deployment % is within 30-90% range.

    Reads bot_positions directly (not via canonical.py) because deployment
    notional is a positional metric. Uses qty * avg_cost_cents (already in cents)
    joined through bot_allocations to scope to user_id=1.
    """
    try:
        row = db.execute(text("""
            SELECT COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0) AS notional_cents
              FROM bot_positions bp
              JOIN bot_allocations a ON a.id = bp.allocation_id
             WHERE bp.closed_at IS NULL
               AND bp.quarantined_at IS NULL
               AND a.user_id = 1
        """)).fetchone()
        notional_cents = float(row[0]) if row else 0.0
        deployment_pct = notional_cents / 100_000_000 * 100
        if deployment_pct < 30:
            return {
                "name": "fund_deployment",
                "status": "WARN",
                "details": f"deployment {deployment_pct:.1f}% (idle capital)",
            }
        if deployment_pct > 90:
            return {
                "name": "fund_deployment",
                "status": "WARN",
                "details": f"deployment {deployment_pct:.1f}% (no cash buffer)",
            }
        return {
            "name": "fund_deployment",
            "status": "GREEN",
            "details": f"deployment {deployment_pct:.1f}%",
        }
    except Exception as exc:
        return {
            "name": "fund_deployment",
            "status": "ALERT",
            "details": f"check failed: {exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Discord formatter
# ─────────────────────────────────────────────────────────────────────────────

def _build_summary_markdown(
    as_of: str,
    overall: str,
    checks: list[dict],
    alerts: list[str],
) -> str:
    emoji = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}
    check_emoji = {"GREEN": "✅", "WARN": "⚠️", "ALERT": "🚨"}
    date_str = as_of[:10]
    lines = [
        f"🔍 BMG Strategy Lab Daily Audit — {date_str}",
        f"Status: {emoji.get(overall, '❓')} {overall}",
        "",
    ]
    for c in checks:
        lines.append(f"{check_emoji.get(c['status'], '❓')} {c['name']}: {c['details']}")
    if alerts:
        lines.append("")
        lines.append("Top issues:")
        for a in alerts:
            lines.append(f"- {a}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Discord poster
# ─────────────────────────────────────────────────────────────────────────────

def _post_discord(summary_markdown: str) -> None:
    webhook = os.environ.get("DISCORD_WH_DAILY_AUDIT")
    if not webhook:
        logger.info("DISCORD_WH_DAILY_AUDIT not set, skipping Discord post")
        return
    if not os.environ.get("DISCORD_OPS_ALERTS_ENABLED", "").lower() == "true":
        logger.info("DISCORD_OPS_ALERTS_ENABLED!=true, skipping Discord post")
        return
    try:
        import httpx
        resp = httpx.post(webhook, json={"content": summary_markdown}, timeout=10.0)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Discord post failed: {e}")
        # swallow, do not raise — audit must persist regardless


# ─────────────────────────────────────────────────────────────────────────────
# Persist
# ─────────────────────────────────────────────────────────────────────────────

def _persist(db: Session, result: dict) -> None:
    db.execute(text("""
        INSERT INTO daily_audit_log (run_at, overall_status, checks_json, alerts_json, summary_markdown)
        VALUES (:run_at, :overall, :checks, :alerts, :summary)
    """), {
        "run_at": result["as_of"],
        "overall": result["overall_status"],
        "checks": json.dumps(result["checks"]),
        "alerts": json.dumps(result["alerts"]),
        "summary": result["summary_markdown"],
    })
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_daily_audit(db: Session) -> dict:
    """Run all 8 audit checks, persist to daily_audit_log, optionally post Discord.

    Returns the audit result dict (keys: as_of, overall_status, checks, alerts,
    summary_markdown).

    Never raises — individual check failures are captured as ALERT-level findings.
    """
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    checks: list[dict] = []
    alerts: list[str] = []

    # 1. Bot count
    try:
        checks.append(_check_bot_count(db))
    except Exception as exc:
        checks.append({"name": "bot_count", "status": "ALERT", "details": f"check failed: {exc}"})

    # 2. Per-bot verdicts
    try:
        c, a = _check_per_bot_verdicts(db)
        checks.append(c)
        alerts.extend(a)
    except Exception as exc:
        checks.append({"name": "per_bot_verdicts", "status": "ALERT", "details": f"check failed: {exc}"})
        alerts.append(f"per_bot_verdicts check failed: {exc}")

    # 3. Capital invariant
    try:
        c = _check_capital_invariant(db)
        checks.append(c)
        if c["status"] == "ALERT":
            # Extract drift from details for a nicer alert message
            total_cents_match = None
            try:
                import re as _re
                m = _re.search(r"sum=(\d+)", c["details"])
                if m:
                    total_cents = int(m.group(1))
                    drift_usd = (total_cents - 100_000_000) / 100
                    alerts.append(f"capital invariant drift: ${drift_usd:.2f} off $1M")
                else:
                    alerts.append("capital invariant drift detected")
            except Exception:
                alerts.append("capital invariant drift detected")
    except Exception as exc:
        checks.append({"name": "capital_invariant", "status": "ALERT", "details": f"check failed: {exc}"})
        alerts.append(f"capital_invariant check failed: {exc}")

    # 4. The Wall
    try:
        c = _check_the_wall(db)
        checks.append(c)
        if c["status"] == "ALERT":
            try:
                n = int(c["details"].split()[0])
                alerts.append(f"THE WALL broken: {n} paid Anthropic API calls today")
            except Exception:
                alerts.append("THE WALL broken: paid Anthropic API calls today")
    except Exception as exc:
        checks.append({"name": "wall", "status": "ALERT", "details": f"check failed: {exc}"})
        alerts.append(f"wall check failed: {exc}")

    # 5. Crypto-equity violations
    try:
        c = _check_crypto_equity_violations(db)
        checks.append(c)
        if c["status"] == "ALERT":
            try:
                n = int(c["details"].split()[0])
                alerts.append(
                    f"crypto-bot equity violations: {n} positions — "
                    "re-run m033/m044/m045 cleanup pattern"
                )
            except Exception:
                alerts.append("crypto-bot equity violations detected")
    except Exception as exc:
        checks.append({"name": "crypto_equity_violations", "status": "ALERT", "details": f"check failed: {exc}"})
        alerts.append(f"crypto_equity_violations check failed: {exc}")

    # 6. Options OCC format
    try:
        c, a = _check_options_occ_format(db)
        checks.append(c)
        alerts.extend(a)
    except Exception as exc:
        checks.append({"name": "options_occ_format", "status": "ALERT", "details": f"check failed: {exc}"})
        alerts.append(f"options_occ_format check failed: {exc}")

    # 7. AQA status (informational)
    try:
        checks.append(_check_aqa_status(db))
    except Exception as exc:
        checks.append({"name": "aqa_status", "status": "GREEN", "details": f"aqa_status unavailable: {exc}"})

    # 8. Fund deployment
    try:
        checks.append(_check_fund_deployment(db))
    except Exception as exc:
        checks.append({"name": "fund_deployment", "status": "ALERT", "details": f"check failed: {exc}"})
        alerts.append(f"fund_deployment check failed: {exc}")

    # Derive overall status
    if any(c["status"] == "ALERT" for c in checks):
        overall = "RED"
    elif any(c["status"] == "WARN" for c in checks):
        overall = "YELLOW"
    else:
        overall = "GREEN"

    summary_md = _build_summary_markdown(as_of, overall, checks, alerts)
    result = {
        "as_of": as_of,
        "overall_status": overall,
        "checks": checks,
        "alerts": alerts,
        "summary_markdown": summary_md,
    }

    _persist(db, result)

    try:
        _post_discord(summary_md)
    except Exception as exc:
        logger.warning("Discord post raised unexpectedly: %s", exc)

    return result
