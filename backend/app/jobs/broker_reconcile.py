"""Scheduled job — daily broker vs DB position reconciliation.

Runs after market close (4:05 PM ET). Posts to Discord ops channel if the
severity is anything other than 'ok'.

READ-ONLY against the broker; never mutates positions. Per
`06-decision-history.md` mass-action restraint: surface diffs, let Brock
decide per-row.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_broker_reconcile_job() -> None:
    """Entry point invoked by APScheduler.

    Opens a fresh DB session, runs the reconciler for user_id=1, logs the
    result, and posts a Discord ops alert if severity != 'ok'.

    Swallows all exceptions — scheduler jobs must not raise (other jobs in
    the loop should keep running). Errors are logged and surfaced via the
    ops alert path.
    """
    try:
        from app.db.session import SessionLocal
        from app.ops.broker_reconciliation import (
            reconcile_positions,
            format_report_for_discord,
        )
    except Exception:
        logger.exception("[broker-reconcile] import failed — job aborted")
        return

    db = None
    try:
        db = SessionLocal()
        report = reconcile_positions(db, user_id=1)
    except Exception as exc:
        logger.exception("[broker-reconcile] reconciler raised")
        report = {
            "divergence_severity": "error",
            "error": f"reconciler raised: {exc}",
        }
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    sev = report.get("divergence_severity", "unknown")
    logger.warning("[broker-reconcile] severity=%s report=%s", sev, {
        "broker_positions_count": report.get("broker_positions_count"),
        "db_positions_count": report.get("db_positions_count"),
        "matched_count": len(report.get("matched", [])),
        "broker_only_count": len(report.get("broker_only", [])),
        "db_only_count": len(report.get("db_only", [])),
        "qty_mismatched_count": len(report.get("qty_mismatched", [])),
    })

    if sev == "ok":
        return

    # Post to Discord ops channel for warn / alert / error
    try:
        from app.services.discord import send_ops_alert
        severity_map = {"warn": "warn", "alert": "critical", "error": "critical"}
        send_ops_alert(
            title=f"Broker reconciliation: {sev}",
            message=format_report_for_discord(report),
            severity=severity_map.get(sev, "warn"),
            source="ops.broker_reconcile",
            fields=[
                {"name": "Broker positions", "value": str(report.get("broker_positions_count", 0)), "inline": True},
                {"name": "DB positions", "value": str(report.get("db_positions_count", 0)), "inline": True},
                {"name": "Severity", "value": sev, "inline": True},
            ],
        )
    except Exception:
        logger.exception("[broker-reconcile] failed to post ops alert")
