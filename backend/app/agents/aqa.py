"""AQA agent core: run_aqa_cycle(db) -> dict.

Single AQA cycle steps (strict order):
  1. Freeze check
  2. Budget check (LLM + deploy)
  3. Build context
  4. Heuristics -- if empty, return no_action (no LLM call)
  5. Build prompt
  6. Call LLM (fail-closed: any exception -> self-freeze + ops alert)
  7. Record LLM call (only on success)
  8. Persist proposal + post to Discord

DO NOT:
  - import anthropic (the Wall will reject the PR)
  - call call_llm() before heuristics return non-empty list
  - spawn subprocesses, run git, write files, or shell out
  - swallow call_llm failures silently
  - pass system_prompt=SYSTEM_PROMPT AND prompt=user_prompt (sys is empty)

# TODO PHASE B: aqa_deployer.py -- git commit/push/Railway deploy interface
# TODO PHASE B: aqa_validator.py -- Sentry post-deploy auto-rollback
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run_aqa_cycle(db: Session) -> dict:
    """Single AQA cycle. Returns outcome dict.

    Possible status values:
      "frozen"      -- aqa_safety.is_frozen returned True; nothing else done
      "budget_hit"  -- deploy or LLM budget exhausted; self-froze + ops alert
      "no_action"   -- heuristics returned empty; no LLM call, no proposal
      "proposed"    -- full path: built context, called LLM, persisted, posted

    Returned dict always includes: status, cycle_id, started_at, finished_at.
    On 'proposed': also proposal_id, issue_tags, discord_message_id (may be None).
    On 'budget_hit'/'frozen': also reason.
    """
    from app.services import aqa_safety
    from app.services.aqa_context_builder import build_context
    from app.services.aqa_heuristics import find_actionable_issues
    from app.services.aqa_proposal_writer import (
        write_proposal,
        post_to_discord,
        mark_posted,
    )
    from app.services.llm_client import call_llm
    from app.services.discord import send_ops_alert
    from app.agents.aqa_system_prompt import SYSTEM_PROMPT

    now = datetime.now(timezone.utc)
    cycle_id = f"aqa-{now.strftime('%Y%m%dT%H%MZ')}-{uuid.uuid4().hex[:8]}"
    started_at = now.isoformat().replace("+00:00", "Z")

    # 1. Freeze check
    if aqa_safety.is_frozen(db):
        return {
            "status": "frozen",
            "cycle_id": cycle_id,
            "started_at": started_at,
            "finished_at": started_at,
            "reason": "aqa_state.frozen=1",
        }

    # 2. Budget check (LLM + deploy)
    if not aqa_safety.check_llm_budget(db):
        aqa_safety.freeze(db, reason="llm_budget_exhausted", by="system")
        send_ops_alert(
            title="AQA self-froze: LLM budget",
            message=f"cycle {cycle_id} hit AQA_DAILY_MAX_LLM_CALLS",
            severity="warn",
            source="aqa",
        )
        return {
            "status": "budget_hit",
            "cycle_id": cycle_id,
            "started_at": started_at,
            "finished_at": started_at,
            "reason": "llm_budget_exhausted",
        }

    if not aqa_safety.check_deploy_budget(db):
        aqa_safety.freeze(db, reason="deploy_budget_exhausted", by="system")
        send_ops_alert(
            title="AQA self-froze: deploy budget",
            message=f"cycle {cycle_id} hit AQA_MAX_DEPLOYS_PER_24H",
            severity="warn",
            source="aqa",
        )
        return {
            "status": "budget_hit",
            "cycle_id": cycle_id,
            "started_at": started_at,
            "finished_at": started_at,
            "reason": "deploy_budget_exhausted",
        }

    # 3. Build context
    context = build_context(db)

    # 4. Heuristics
    issue_tags = find_actionable_issues(context)
    if not issue_tags:
        return {
            "status": "no_action",
            "cycle_id": cycle_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": "no actionable issues",
        }

    # 5. Build prompt
    context_json = json.dumps(context, default=str)[:30000]  # token-cap
    user_prompt = SYSTEM_PROMPT.format(
        context_json=context_json,
        issue_tags=json.dumps(issue_tags),
    )

    # 6. Call LLM (fail-closed). If call_llm raises, self-freeze + alert.
    try:
        llm_response = call_llm(
            model="claude-haiku-4-5-20251001",
            prompt=user_prompt,
            system_prompt="",  # full prompt is in user channel; sys empty
            max_tokens=4000,
            agent_name="aqa",
            db=db,
        )
    except Exception as exc:
        aqa_safety.freeze(db, reason=f"llm_call_failed: {exc}", by="system")
        send_ops_alert(
            title="AQA self-froze: LLM call failed",
            message=f"cycle {cycle_id}: {exc}",
            severity="critical",
            source="aqa",
        )
        return {
            "status": "budget_hit",
            "cycle_id": cycle_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": f"llm_call_failed: {exc}",
        }

    # 7. Record LLM call AFTER success (failures don't burn budget -- they freeze instead)
    aqa_safety.record_llm_call(db, agent="aqa")

    # 8. Persist + post
    context_summary = {
        "bot_count": len(
            (context.get("bot_diagnostic") or {}).get("bots", []) or []
        ),
        "journal_count": len(context.get("bot_journals") or []),
        "data_gaps": context.get("data_gaps", []),
        "built_at": context.get("built_at"),
    }
    proposal_id = write_proposal(
        db=db,
        cycle_id=cycle_id,
        issue_tags=issue_tags,
        llm_response_md=llm_response,
        context_summary=context_summary,
    )
    proposal_dict = {
        "id": proposal_id,
        "cycle_id": cycle_id,
        "issue_tags": issue_tags,
        "llm_response_md": llm_response,
        "created_at": started_at,
    }
    msg_id = post_to_discord(proposal_dict)
    if msg_id:
        mark_posted(db, proposal_id, msg_id)

    finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "status": "proposed",
        "cycle_id": cycle_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "proposal_id": proposal_id,
        "issue_tags": issue_tags,
        "discord_message_id": msg_id,
    }
