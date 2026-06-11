"""IC metrics API — signal quality by strategy."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.models.ic_metrics import SignalIcAlert, SignalIcMetric
from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ic", tags=["ic"])


@router.get("/strategies")
def list_ic_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Latest 63d IC snapshot for all strategies."""
    today = date.today()

    # Get latest snapshot date per strategy for 63d window
    rows = (
        db.query(SignalIcMetric)
        .filter(SignalIcMetric.window_days == 63)
        .order_by(SignalIcMetric.strategy_name, SignalIcMetric.snapshot_date.desc())
        .all()
    )

    # Deduplicate — keep latest per strategy
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.strategy_name in seen:
            continue
        seen.add(row.strategy_name)
        out.append({
            "strategy_name":          row.strategy_name,
            "snapshot_date":          row.snapshot_date.isoformat(),
            "ic_63d":                 row.ic_spearman,
            "ic_pearson":             row.ic_pearson,
            "p_value":                row.ic_p_value,
            "t_stat":                 row.ic_t_stat,
            "n_signals":              row.n_signals,
            "classification":         row.classification,
            "recommendation":         row.recommendation,
            "direction_hit_rate":     row.direction_hit_rate,
            "confidence_correlation": row.confidence_correlation,
            "last_updated":           row.snapshot_date.isoformat(),
        })

    out.sort(key=lambda x: (x["ic_63d"] or -99), reverse=True)
    return out


@router.get("/strategies/{name}/history")
def strategy_ic_history(
    name: str,
    days: int = Query(default=180, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Time series of IC values for a strategy (63d window)."""
    cutoff = date.today() - timedelta(days=days)

    rows = (
        db.query(SignalIcMetric)
        .filter(
            SignalIcMetric.strategy_name == name,
            SignalIcMetric.window_days == 63,
            SignalIcMetric.snapshot_date >= cutoff,
        )
        .order_by(SignalIcMetric.snapshot_date.asc())
        .all()
    )

    # Get the latest for the summary
    latest_row = rows[-1] if rows else None

    return {
        "strategy_name": name,
        "latest": {
            "ic_63d":                 latest_row.ic_spearman if latest_row else None,
            "p_value":                latest_row.ic_p_value  if latest_row else None,
            "n_signals":              latest_row.n_signals   if latest_row else 0,
            "classification":         latest_row.classification   if latest_row else None,
            "recommendation":         latest_row.recommendation   if latest_row else None,
            "direction_hit_rate":     latest_row.direction_hit_rate   if latest_row else None,
            "confidence_correlation": latest_row.confidence_correlation if latest_row else None,
        } if latest_row else None,
        "history": [
            {
                "snapshot_date": r.snapshot_date.isoformat(),
                "ic_spearman":   r.ic_spearman,
                "ic_pearson":    r.ic_pearson,
                "n_signals":     r.n_signals,
                "classification": r.classification,
            }
            for r in rows
        ],
    }


@router.get("/alerts")
def list_ic_alerts(
    days: int = Query(default=14, ge=1, le=90),
    unacknowledged_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Recent IC classification change alerts."""
    from datetime import datetime, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = db.query(SignalIcAlert).filter(SignalIcAlert.triggered_at >= cutoff)
    if unacknowledged_only:
        q = q.filter(SignalIcAlert.acknowledged_at.is_(None))
    alerts = q.order_by(SignalIcAlert.triggered_at.desc()).all()

    return {
        "alerts": [
            {
                "id":                      a.id,
                "strategy_name":           a.strategy_name,
                "triggered_at":            a.triggered_at.isoformat(),
                "ic_value":                a.ic_value,
                "classification":          a.classification,
                "previous_classification": a.previous_classification,
                "discord_posted":          bool(a.discord_posted),
                "acknowledged_at":         a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                "acknowledged_by":         a.acknowledged_by,
            }
            for a in alerts
        ]
    }


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark an IC alert as acknowledged."""
    if not current_user.is_admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin only")
    from datetime import datetime, timezone
    alert = db.query(SignalIcAlert).filter(SignalIcAlert.id == alert_id).first()
    if not alert:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = str(current_user.id)
    db.commit()
    return {"ok": True}
