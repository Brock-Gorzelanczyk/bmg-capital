"""Brain Graph — knowledge-graph view of recent trading activity.

Single endpoint returning a force-graph payload of sessions, strategies,
symbols, signals, trades, and lessons over the last N days.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin
from app.services.brain_graph import get_cached_graph

router = APIRouter(prefix="/api/brain", tags=["brain"])
logger = logging.getLogger(__name__)


@router.get("/graph", dependencies=[Depends(require_admin)])
def get_brain_graph(
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Return force-graph payload for the brain view.

    Soft-fails to an empty graph (status 200) so the page never sees a 500.
    """
    try:
        return get_cached_graph(db, days=days)
    except Exception as exc:
        logger.error("[brain] /graph failed: %s", exc, exc_info=True)
        return {
            "nodes": [],
            "edges": [],
            "stats": {"node_count": 0, "edge_count": 0, "error": str(exc)},
        }
