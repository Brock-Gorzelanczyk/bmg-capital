"""Strategy Farm — admin router (Phase 1).

Endpoints
---------
  GET  /api/admin/farm/templates          list all templates
  GET  /api/admin/farm/candidates         list farm candidates (paginated)
  POST /api/admin/farm/generate           sample N params for a template
                                          insert as farm_candidates rows
                                          status='generated'
  GET  /api/admin/farm/status             health + counts

Feature flag
------------
BMG_STRATEGY_FARM_ENABLED must be 'true' to POST /generate. GET
endpoints work regardless so the panel can render.

Phase 1 does NOT backtest. Rows are inserted with status='generated'
and empty stats. Phase 2 wires the backtester.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/farm", tags=["admin", "farm"])


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


def _max_samples_night() -> int:
    return int(os.getenv("BMG_STRATEGY_FARM_MAX_SAMPLES_NIGHT", "500"))


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    rows = db.execute(text(
        "SELECT id, name, category, base_indicators, param_schema, "
        "  asset_classes, min_bars_required, enabled, created_at "
        "FROM strategy_templates ORDER BY name"
    )).fetchall()
    return {
        "count": len(rows),
        "templates": [
            {
                "id": int(r[0]),
                "name": r[1],
                "category": r[2],
                "base_indicators": json.loads(r[3] or "[]"),
                "param_schema": json.loads(r[4] or "{}"),
                "asset_classes": json.loads(r[5] or "[]"),
                "min_bars_required": int(r[6] or 0),
                "enabled": bool(r[7]),
                "created_at": str(r[8]) if r[8] else None,
            }
            for r in rows
        ],
    }


@router.get("/candidates")
def list_candidates(
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    limit = max(1, min(1000, limit))
    q = (
        "SELECT c.id, c.template_id, t.name, c.parameters, c.status, "
        "  c.backtest_stats, c.walkforward_stats, c.robustness_score, "
        "  c.rejected_reason, c.promoted_at, c.created_at "
        "FROM farm_candidates c "
        "LEFT JOIN strategy_templates t ON t.id = c.template_id "
    )
    params: dict = {"lim": limit}
    if status:
        q += "WHERE c.status = :status "
        params["status"] = status
    q += "ORDER BY c.created_at DESC LIMIT :lim"
    rows = db.execute(text(q), params).fetchall()
    return {
        "count": len(rows),
        "filter": {"status": status, "limit": limit},
        "candidates": [
            {
                "id": int(r[0]),
                "template_id": int(r[1]),
                "template_name": r[2],
                "parameters": json.loads(r[3] or "{}"),
                "status": r[4],
                "backtest_stats": json.loads(r[5]) if r[5] else None,
                "walkforward_stats": json.loads(r[6]) if r[6] else None,
                "robustness_score": float(r[7]) if r[7] is not None else None,
                "rejected_reason": r[8],
                "promoted_at": str(r[9]) if r[9] else None,
                "created_at": str(r[10]) if r[10] else None,
            }
            for r in rows
        ],
    }


@router.post("/generate")
def generate_candidates(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Sample N parameter combos for a template and insert as farm_candidates.

    Body: {"template_name": str, "n_samples": int, "seed": Optional[int]}

    Returns: {"candidate_ids": [int, ...], "template_name": str, "requested": int}
    """
    if not _env_flag("BMG_STRATEGY_FARM_ENABLED", "false"):
        raise HTTPException(
            status_code=403,
            detail="strategy farm disabled — set BMG_STRATEGY_FARM_ENABLED=true",
        )

    template_name = str(body.get("template_name") or "").strip()
    if not template_name:
        raise HTTPException(status_code=400, detail="template_name is required")
    try:
        n_requested = int(body.get("n_samples") or 0)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="n_samples must be int")
    if n_requested <= 0:
        raise HTTPException(status_code=400, detail="n_samples must be > 0")
    cap = _max_samples_night()
    if n_requested > cap:
        logger.warning(
            "[farm] requested n=%d exceeds MAX_SAMPLES_NIGHT=%d, halving per spec",
            n_requested, cap,
        )
        n_requested = max(1, cap // 2)

    seed = int(body.get("seed") or int(time.time()))

    row = db.execute(text(
        "SELECT id, name, param_schema, enabled "
        "FROM strategy_templates WHERE name = :n"
    ), {"n": template_name}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"template not found: {template_name}")
    if not bool(row[3]):
        raise HTTPException(status_code=400, detail=f"template disabled: {template_name}")

    template_id = int(row[0])
    try:
        schema = json.loads(row[2] or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"template schema corrupt: {exc}")

    from app.services.farm_sampler import unique_samples
    samples = unique_samples(schema, n_requested, seed=seed)

    inserted_ids: list[int] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for params in samples:
        result = db.execute(text("""
            INSERT INTO farm_candidates
              (template_id, parameters, status, created_at)
            VALUES
              (:tid, :params, 'generated', :ts)
        """), {
            "tid": template_id,
            "params": json.dumps(params, sort_keys=True),
            "ts": now_iso,
        })
        # SQLite: use lastrowid off the result proxy.
        cid = getattr(result, "lastrowid", None)
        if cid:
            inserted_ids.append(int(cid))
    db.commit()

    return {
        "template_name": template_name,
        "template_id": template_id,
        "requested": n_requested,
        "seed": seed,
        "generated": len(inserted_ids),
        "candidate_ids": inserted_ids,
    }


@router.get("/status")
def farm_status(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    counts_row = db.execute(text(
        "SELECT status, COUNT(*) FROM farm_candidates GROUP BY status"
    )).fetchall()
    counts = {r[0]: int(r[1]) for r in counts_row}
    tc_row = db.execute(text(
        "SELECT COUNT(*) FROM strategy_templates WHERE enabled = 1"
    )).fetchone()
    template_count_enabled = int(tc_row[0]) if tc_row else 0
    return {
        "enabled": _env_flag("BMG_STRATEGY_FARM_ENABLED", "false"),
        "max_samples_night": _max_samples_night(),
        "template_count_enabled": template_count_enabled,
        "candidates_by_status": counts,
        "candidates_total": sum(counts.values()),
    }
