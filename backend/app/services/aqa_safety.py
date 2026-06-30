"""AQA safety layer: freeze/unfreeze + daily budget tracking.

All DB operations go through sqlalchemy text() + db.execute() / db.commit().
Env vars are read at call time (NOT module load) so tests can monkeypatch.

Standing decisions:
  - DO NOT auto-unfreeze on day rollover; freeze is sticky until explicit unfreeze().
  - DO NOT send ops alerts from inside freeze() -- caller decides whether to alert.
  - Multiple aqa_state rows (shouldn't exist) resolved via MIN(id) throughout.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Clause to always target the canonical single row
_ROW_WHERE = "WHERE id = (SELECT MIN(id) FROM aqa_state)"


# ---------------------------------------------------------------------------
# Env-var helpers -- read at call time so tests can monkeypatch os.environ
# ---------------------------------------------------------------------------

def _max_deploys_per_24h() -> int:
    import os
    return int(os.getenv("AQA_MAX_DEPLOYS_PER_24H", "10"))


def _max_llm_calls_per_day() -> int:
    import os
    return int(os.getenv("AQA_DAILY_MAX_LLM_CALLS", "2000"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assert_table_exists(db: Session) -> None:
    """Raise a clear error if aqa_state table hasn't been created yet."""
    result = db.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='aqa_state'"
        )
    ).scalar()
    if not result:
        raise RuntimeError(
            "aqa_state table does not exist -- m048 migration has not run. "
            "Run m048_aqa_state.run(conn) before using aqa_safety functions."
        )


def _ensure_counters_current(db: Session) -> None:
    """If counter_date != today UTC, reset deploys_today + llm_calls_today to 0.

    Idempotent within a UTC day. Treats NULL counter_date as != today.
    """
    db.execute(
        text(
            "UPDATE aqa_state "
            "SET deploys_today = 0, "
            "    llm_calls_today = 0, "
            "    counter_date = date('now'), "
            "    updated_at = CURRENT_TIMESTAMP "
            "WHERE id = (SELECT MIN(id) FROM aqa_state) "
            "  AND (counter_date IS NULL OR counter_date != date('now'))"
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_frozen(db: Session) -> bool:
    """Return True if aqa_state.frozen == 1."""
    _assert_table_exists(db)
    row = db.execute(
        text(f"SELECT frozen FROM aqa_state {_ROW_WHERE}")
    ).fetchone()
    if row is None:
        return False
    return bool(row[0])


def freeze(db: Session, reason: str, by: str = "system") -> None:
    """Set frozen=1, frozen_reason, frozen_at=now UTC, frozen_by. Idempotent.

    If already frozen, updates reason + timestamp (last-writer-wins).
    """
    _assert_table_exists(db)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.execute(
        text(
            "UPDATE aqa_state "
            "SET frozen = 1, "
            "    frozen_reason = :reason, "
            "    frozen_at = :now, "
            "    frozen_by = :by, "
            "    updated_at = CURRENT_TIMESTAMP "
            f"{_ROW_WHERE}"
        ),
        {"reason": reason, "now": now_iso, "by": by},
    )
    db.commit()
    logger.warning("[aqa-safety] freeze() reason=%r by=%r", reason, by)


def unfreeze(db: Session, by: str) -> None:
    """Set frozen=0, frozen_reason=NULL, frozen_at=NULL.

    `by` is logged for audit trail (not persisted to a separate column in Phase A).
    """
    _assert_table_exists(db)
    db.execute(
        text(
            "UPDATE aqa_state "
            "SET frozen = 0, "
            "    frozen_reason = NULL, "
            "    frozen_at = NULL, "
            "    frozen_by = NULL, "
            "    updated_at = CURRENT_TIMESTAMP "
            f"{_ROW_WHERE}"
        )
    )
    db.commit()
    logger.warning("[aqa-safety] unfreeze() by=%r", by)


def check_deploy_budget(db: Session) -> bool:
    """Return True if deploys_today < AQA_MAX_DEPLOYS_PER_24H.

    Resets counters first if the UTC date has rolled.
    """
    _assert_table_exists(db)
    _ensure_counters_current(db)
    row = db.execute(
        text(f"SELECT deploys_today FROM aqa_state {_ROW_WHERE}")
    ).fetchone()
    if row is None:
        return True  # no row = table just seeded; allow
    return int(row[0]) < _max_deploys_per_24h()


def check_llm_budget(db: Session) -> bool:
    """Return True if llm_calls_today < AQA_DAILY_MAX_LLM_CALLS.

    Resets counters first if the UTC date has rolled.
    """
    _assert_table_exists(db)
    _ensure_counters_current(db)
    row = db.execute(
        text(f"SELECT llm_calls_today FROM aqa_state {_ROW_WHERE}")
    ).fetchone()
    if row is None:
        return True
    return int(row[0]) < _max_llm_calls_per_day()


def record_deploy(db: Session) -> None:
    """Increment deploys_today by 1. Resets counters first if day rolled."""
    _assert_table_exists(db)
    _ensure_counters_current(db)
    db.execute(
        text(
            "UPDATE aqa_state "
            "SET deploys_today = deploys_today + 1, "
            "    updated_at = CURRENT_TIMESTAMP "
            f"{_ROW_WHERE}"
        )
    )
    db.commit()


def record_llm_call(db: Session, agent: str = "aqa") -> None:
    """Increment llm_calls_today by 1. Resets counters first if day rolled.

    `agent` accepted for future per-agent breakdown; single counter in Phase A.
    """
    _assert_table_exists(db)
    _ensure_counters_current(db)
    db.execute(
        text(
            "UPDATE aqa_state "
            "SET llm_calls_today = llm_calls_today + 1, "
            "    updated_at = CURRENT_TIMESTAMP "
            f"{_ROW_WHERE}"
        )
    )
    db.commit()
    logger.debug("[aqa-safety] record_llm_call agent=%r", agent)
