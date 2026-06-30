"""CIO Chair — pure logic for the CIO Morning Meeting orchestrator.

Zero direct SDK usage. Zero calls to claude binary.
ALL inference routed through call_llm from app.services.llm_client.

State machine:
  Phase 0 — daily-cap pre-check
  Phase 1 — INSERT fund_meetings (status='running')
  Phase 2 — build canonical snapshot + load memory
  Phase 3 — 9 agent opening reads (parallel via asyncio.gather + asyncio.to_thread)
  Phase 4 — chair pick top-3 items
  Phase 5 — 2 debate rounds + chair resolution per item
  Phase 6 — Dick veto poll (capital/risk items only)
  Phase 7 — persist agent_commitments
  Phase 8 — carry-forward strike increment
  Phase 9 — wall-clock + budget enforcement after each call
  Phase 10 — UPDATE fund_meetings (final status)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm_client import call_llm
from app.services.agent_opening_read import (
    VALID_AGENTS,
    run_opening_read,
    OpeningReadResult,
    SYSTEM_ANCHOR,
)
from app.core.canonical import compute_strategy_lab_aggregate

logger = logging.getLogger(__name__)

CHAIR_SYSTEM_ANCHOR = (
    "You are the CIO chair. Skeptical. Demand evidence. Identify contradictions. "
    "Never accept 'we should explore' without owner + ISO deadline. "
    "When a metric appears in two opening reads with different values, surface the conflict. "
    "Top items MUST include any P0 flag from any opening read. "
    "Standing decisions: equity-fallback gate (0931c1e); DISCORD_SIGNAL_POSTING_ENABLED=false; "
    "vol-targeting cap 35% NAV; inception_capital_cents immutable; mass-action restraint. "
    "Output STRICT JSON only — no markdown, no prose outside JSON."
)

# Items eligible for Dick veto (chair-side enforced scope)
CAPITAL_OR_RISK_KEYWORDS = (
    "allocat", "rebalance", "deploy", "leverage", "vol target", "drawdown",
    "veto", "concentration", "halt", "unwind", "risk budget", "var",
)

_AGENT_ORDER = [
    "portfolio_manager",
    "chief_risk_officer",
    "equity_researcher",
    "quant_researcher",
    "macro_strategist",
    "data_quality_watcher",
    "execution_auditor",
    "operations",
    "sentinel_devops",
]


@dataclass
class MeetingItem:
    item_id: str
    title: str                        # ≤120 chars
    surfaced_by: list[str]            # role IDs
    tension: str
    severity: str                     # P0|P1|P2
    is_capital_or_risk: bool          # gates veto eligibility
    debate_round_1: list[dict] = field(default_factory=list)  # [{agent, position_words}]
    debate_round_2: Optional[dict] = None                      # {question, target_agent, response}
    resolution: str = ""
    veto_polled: bool = False
    veto_used: bool = False
    veto_reason: Optional[str] = None
    action_items: list[dict] = field(default_factory=list)    # [{owner, action, deadline_iso}]


@dataclass
class MeetingResult:
    meeting_id: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    total_cost_usd: float
    opening_reads: list[OpeningReadResult]
    top_items: list[MeetingItem]
    deferred_items: list[str]
    decisions_made: list[dict]
    vetoes_used: int
    status: str           # completed|failed_budget|failed_timeout|failed_partial
    failure_reason: Optional[str] = None


def _daily_llm_spend_usd(db: Session) -> float:
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(estimated_cost_cents), 0) FROM llm_call_log "
            "WHERE created_at >= datetime('now', 'start of day')"
        )
    ).scalar() or 0
    return float(row) / 100.0


def _meeting_window_spend_usd(db: Session, started_at_iso: str) -> float:
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(estimated_cost_cents), 0) FROM llm_call_log "
            "WHERE created_at >= :ts"
        ),
        {"ts": started_at_iso},
    ).scalar() or 0
    return float(row) / 100.0


def _load_memory(db: Session) -> dict:
    """Last 5 fund_briefings markdown bodies + all open agent_commitments."""
    try:
        briefings = db.execute(
            text(
                "SELECT briefing_id, markdown_body, created_at FROM fund_briefings "
                "ORDER BY created_at DESC LIMIT 5"
            )
        ).fetchall()
        commitments = db.execute(
            text(
                "SELECT id, meeting_id, owner_agent, action_description, deadline, "
                "       status, strike_count, created_at "
                "FROM agent_commitments WHERE status = 'open' ORDER BY deadline ASC"
            )
        ).fetchall()
        return {
            "recent_briefings": [dict(r._mapping) for r in briefings],
            "open_commitments": [dict(r._mapping) for r in commitments],
        }
    except Exception as exc:
        logger.warning("[cio_chair] _load_memory failed: %s", exc)
        return {"recent_briefings": [], "open_commitments": []}


def build_canonical_snapshot(db: Session) -> dict:
    """Return the chair-facing snapshot dict.

    Sourced from compute_strategy_lab_aggregate(1, db).
    NEVER uses BotDailyPnL.unrealized_cents for PV (known-issue #1).
    Multi-user scoping: always passes user_id=1 (known-issue #6).
    """
    try:
        agg = compute_strategy_lab_aggregate(1, db)
        if not agg:
            return {
                "pv_cents": 0, "pv_dollars": 0,
                "today_pnl_cents": 0, "return_30d_pct": 0.0,
                "drawdown_pct": 0.0, "drawdown_distance_to_halt_pct": 0.0,
                "open_positions_count": 0, "sleeves": [],
                "top_sleeve_pnl": None, "bottom_sleeve_pnl": None,
                "daily_api_budget_spent_usd": _daily_llm_spend_usd(db),
                "daily_api_budget_cap_usd": 3.00,
                "regime": "UNKNOWN", "vix": None, "btc_dominance": None,
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "_banner": "no positions to report",
            }

        pv_cents = agg.get("portfolio_value_cents") or agg.get("pv_cents") or 0
        today_pnl = agg.get("today_pnl_cents") or 0
        return_30d = agg.get("return_30d_pct") or 0.0
        open_pos = agg.get("open_positions_count") or 0

        # Drawdown distance to -1.5% halt
        dd_pct = agg.get("drawdown_pct") or 0.0
        dd_distance = max(0.0, 1.5 + dd_pct)  # dd_pct is negative when loss

        # Sleeves from agg portfolios
        sleeves = []
        for ps in (agg.get("portfolio_snapshots") or agg.get("portfolios") or []):
            sleeves.append({
                "sleeve": ps.get("name") or ps.get("sleeve") or "unknown",
                "dollars": (ps.get("portfolio_value_cents") or 0) / 100,
                "pct": ps.get("weight_pct") or 0.0,
                "today_pnl_cents": ps.get("today_pnl_cents") or 0,
            })

        return {
            "pv_cents": pv_cents,
            "pv_dollars": pv_cents / 100,
            "today_pnl_cents": today_pnl,
            "return_30d_pct": return_30d,
            "drawdown_pct": dd_pct,
            "drawdown_distance_to_halt_pct": dd_distance,
            "open_positions_count": open_pos,
            "sleeves": sleeves,
            "top_sleeve_pnl": None,
            "bottom_sleeve_pnl": None,
            "daily_api_budget_spent_usd": _daily_llm_spend_usd(db),
            "daily_api_budget_cap_usd": 3.00,
            "regime": agg.get("regime") or "UNKNOWN",
            "vix": agg.get("vix"),
            "btc_dominance": agg.get("btc_dominance"),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("[cio_chair] build_canonical_snapshot failed: %s", exc)
        return {
            "pv_cents": 0, "pv_dollars": 0,
            "today_pnl_cents": 0, "return_30d_pct": 0.0,
            "drawdown_pct": 0.0, "drawdown_distance_to_halt_pct": 0.0,
            "open_positions_count": 0, "sleeves": [],
            "top_sleeve_pnl": None, "bottom_sleeve_pnl": None,
            "daily_api_budget_spent_usd": 0.0, "daily_api_budget_cap_usd": 3.00,
            "regime": "UNKNOWN", "vix": None, "btc_dominance": None,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "_error": str(exc),
        }


def _is_capital_or_risk(title: str, tension: str) -> bool:
    blob = (title + " " + tension).lower()
    return any(k in blob for k in CAPITAL_OR_RISK_KEYWORDS)


def _parse_json_response(raw: str) -> tuple[dict, Optional[str]]:
    """Strip fences, parse JSON. Returns (parsed, error_text)."""
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        end = -1 if (lines and lines[-1].strip() == "```") else len(lines)
        clean = "\n".join(lines[1:end])
    try:
        return json.loads(clean), None
    except (json.JSONDecodeError, ValueError) as exc:
        return {}, str(exc)


def _call_chair_llm(
    db: Session,
    prompt: str,
    agent_name: str = "cio",
    max_tokens: int = 600,
    model: str = "claude-haiku-4-5-20251001",
) -> tuple[str, Optional[str]]:
    """Call LLM via relay. Returns (raw_text, error_text). Never raises."""
    try:
        raw = call_llm(
            model=model,
            prompt=prompt,
            system_prompt=CHAIR_SYSTEM_ANCHOR,
            max_tokens=max_tokens,
            agent_name=agent_name,
            db=db,
        )
        return raw, None
    except RuntimeError as exc:
        return "", str(exc)


def _run_debate_and_resolution(
    item: MeetingItem,
    opening_reads: list[OpeningReadResult],
    db: Session,
    meeting_id: str,
    started_at: datetime,
    budget_cap_usd: float,
    wall_clock_cap_seconds: int,
    t_start: float,
) -> tuple[bool, str]:
    """Run 2 debate rounds + chair resolution for one top item.
    Returns (budget_ok, failure_reason).
    """
    # Build agents available for debate (surfaced_by + any ok reads)
    ok_reads = {r.agent_name: r for r in opening_reads if r.status == "ok"}
    debate_agents = [a for a in item.surfaced_by if a in ok_reads]
    if not debate_agents:
        debate_agents = list(ok_reads.keys())[:3]

    started_at_iso = started_at.isoformat()

    # Round 1: 2-3 agents give position
    round1_prompts = []
    for agent in debate_agents[:3]:
        read = ok_reads.get(agent)
        context = read.what_im_seeing[:400] if read else ""
        round1_prompts.append((agent, (
            f"ITEM: {item.title}\nTENSION: {item.tension}\n"
            f"Your opening-read context: {context}\n"
            f"Give your position on this item in ≤150 words. "
            f"Return JSON: {{\"position_words\": \"...\"}}"
        )))

    for agent, prompt in round1_prompts:
        # Budget check
        spend = _meeting_window_spend_usd(db, started_at_iso)
        if spend > 0.6 * budget_cap_usd:
            return False, "per_meeting_budget_exceeded"
        if time.monotonic() - t_start > wall_clock_cap_seconds:
            return False, "wall_clock_exceeded"

        raw, err = _call_chair_llm(db, prompt, agent_name=agent, max_tokens=200)
        if err:
            item.debate_round_1.append({"agent": agent, "position_words": f"[RELAY ERROR: {err}]"})
            continue
        parsed, _ = _parse_json_response(raw)
        item.debate_round_1.append({
            "agent": agent,
            "position_words": parsed.get("position_words", raw[:200]),
        })

    # Round 2: pick most-disputed claim, ask 1 agent to respond
    if len(item.debate_round_1) >= 2:
        # Pick the agent who wasn't in round 1 or the 3rd agent from round 1
        remaining = [a for a in list(ok_reads.keys())[:4] if a not in [r["agent"] for r in item.debate_round_1]]
        target = remaining[0] if remaining else (item.debate_round_1[-1]["agent"] if item.debate_round_1 else "cio")

        spend = _meeting_window_spend_usd(db, started_at_iso)
        if spend <= 0.6 * budget_cap_usd and time.monotonic() - t_start <= wall_clock_cap_seconds:
            round1_summary = "; ".join(
                f'{r["agent"]}: {r["position_words"][:100]}' for r in item.debate_round_1
            )
            r2_prompt = (
                f"ITEM: {item.title}\nROUND 1 POSITIONS: {round1_summary}\n"
                f"Most disputed claim: surface the key tension and ask {target} to respond. "
                f"Return JSON: {{\"question\": \"...\", \"target_agent\": \"{target}\", \"response\": \"...\"}}"
            )
            r2_read = ok_reads.get(target)
            r2_context = r2_read.what_im_seeing[:300] if r2_read else ""
            full_r2_prompt = r2_prompt + f"\nYour context as {target}: {r2_context}"

            raw2, err2 = _call_chair_llm(db, full_r2_prompt, agent_name=target, max_tokens=200)
            if not err2:
                parsed2, _ = _parse_json_response(raw2)
                item.debate_round_2 = {
                    "question": parsed2.get("question", ""),
                    "target_agent": target,
                    "response": parsed2.get("response", raw2[:200]),
                }

    # Chair resolution
    spend = _meeting_window_spend_usd(db, started_at_iso)
    if spend > 0.6 * budget_cap_usd or time.monotonic() - t_start > wall_clock_cap_seconds:
        item.resolution = f"[SKIPPED — budget/time exceeded mid-debate]"
        return False, "per_meeting_budget_exceeded"

    r1_text = "; ".join(f'{r["agent"]}: {r["position_words"][:100]}' for r in item.debate_round_1)
    r2_text = ""
    if item.debate_round_2:
        r2_text = f"Round 2 — {item.debate_round_2.get('response', '')[:200]}"

    resolution_prompt = (
        f"ITEM: {item.title} [{item.severity}]\nTENSION: {item.tension}\n"
        f"ROUND 1: {r1_text}\n{r2_text}\n"
        "As CIO chair: synthesize a resolution. Demand concrete owner + ISO deadline for each action. "
        "Return JSON: {\"resolution\": \"str\", \"action_items\": "
        "[{\"owner\": \"role_id\", \"action\": \"str\", \"deadline_iso\": \"YYYY-MM-DDTHH:MM:SSZ\"}]}"
    )
    raw_res, err_res = _call_chair_llm(db, resolution_prompt, agent_name="cio", max_tokens=300)
    if err_res:
        item.resolution = f"[RESOLUTION FAILED: {err_res}]"
    else:
        parsed_res, parse_err = _parse_json_response(raw_res)
        if parse_err:
            item.resolution = raw_res[:500]
        else:
            item.resolution = str(parsed_res.get("resolution", raw_res[:400]))
            raw_actions = parsed_res.get("action_items", [])
            if isinstance(raw_actions, list):
                for act in raw_actions[:3]:
                    if isinstance(act, dict) and act.get("owner") and act.get("deadline_iso"):
                        item.action_items.append({
                            "owner": str(act["owner"]),
                            "action": str(act.get("action", ""))[:500],
                            "deadline_iso": str(act["deadline_iso"]),
                        })

    return True, ""


def _run_veto_poll(
    item: MeetingItem,
    db: Session,
    meeting_id: str,
    started_at: datetime,
    vetoes_used_ref: list[int],  # mutable int wrapper
) -> None:
    """Poll Dick for veto on capital/risk items. Modifies item in-place."""
    if not item.is_capital_or_risk:
        return  # scope guard — never veto operational items

    item.veto_polled = True
    veto_prompt = (
        f"CIO VETO POLL\nITEM: {item.title}\nRESILUTION: {item.resolution[:400]}\n"
        "As Chief Risk Officer (Dick): should this item be VETOED?\n"
        "Veto ONLY if it involves capital deployment, rebalancing, leverage change, "
        "concentration increase, or halt-trigger modification.\n"
        "Return JSON: {\"decision\": \"VETO\" or \"PASS\", \"reason\": \"str\"}"
    )
    raw, err = _call_chair_llm(
        db, veto_prompt, agent_name="chief_risk_officer", max_tokens=120
    )
    if err:
        # Relay down during veto poll → fail-closed (treat as VETO)
        item.veto_used = True
        item.veto_reason = f"relay_error: {err[:200]}"
        item.resolution = f"VETOED (relay error during veto poll) — {item.resolution}"
        _insert_veto_log(db, meeting_id, item, "relay_error")
        vetoes_used_ref[0] += 1
        return

    parsed, parse_err = _parse_json_response(raw)
    decision = str(parsed.get("decision", "")).upper().strip() if not parse_err else ""

    if decision == "VETO":
        reason = str(parsed.get("reason", "no reason given"))
        item.veto_used = True
        item.veto_reason = reason
        item.resolution = f"VETOED BY DICK — {reason}\nOriginal: {item.resolution}"
        _insert_veto_log(db, meeting_id, item, reason)
        vetoes_used_ref[0] += 1

    elif decision == "PASS":
        pass  # resolution unchanged

    else:
        # Ambiguous — ONE clarifying call
        clarify_prompt = (
            f"Your previous veto response was ambiguous: {raw[:200]}\n"
            "Answer strictly: {\"decision\": \"VETO\" or \"PASS\", \"reason\": \"str\"}"
        )
        raw2, err2 = _call_chair_llm(
            db, clarify_prompt, agent_name="chief_risk_officer", max_tokens=80
        )
        if err2:
            decision2 = ""
        else:
            parsed2, _ = _parse_json_response(raw2)
            decision2 = str(parsed2.get("decision", "")).upper().strip()

        if decision2 != "PASS":
            # Still ambiguous → fail-CLOSED (treat as VETO)
            item.veto_used = True
            item.veto_reason = "ambiguous_response"
            item.resolution = f"VETOED (ambiguous Dick response) — original kept on file"
            _insert_veto_log(db, meeting_id, item, "ambiguous_response")
            vetoes_used_ref[0] += 1


def _insert_veto_log(
    db: Session, meeting_id: str, item: MeetingItem, reason: str
) -> None:
    try:
        db.execute(
            text(
                "INSERT INTO veto_log "
                "(meeting_id, vetoed_by, vetoed_target_proposal, reason) "
                "VALUES (:mid, 'chief_risk_officer', :tp, :r)"
            ),
            {
                "mid": meeting_id,
                "tp": item.title[:500],
                "r": reason[:1000],
            },
        )
        db.commit()
    except Exception as exc:
        logger.warning("[cio_chair] veto_log insert failed: %s", exc)


def _persist_commitments(
    db: Session,
    meeting_id: str,
    top_items: list[MeetingItem],
) -> None:
    """Insert agent_commitments rows from action_items across all top items."""
    for item in top_items:
        for act in item.action_items:
            owner = act.get("owner", "")
            action = act.get("action", "")
            deadline_iso = act.get("deadline_iso", "")
            if not owner or not deadline_iso:
                continue
            try:
                db.execute(
                    text(
                        "INSERT INTO agent_commitments "
                        "(meeting_id, owner_agent, action_description, deadline) "
                        "VALUES (:mid, :oa, :ad, :dl)"
                    ),
                    {
                        "mid": meeting_id,
                        "oa": owner,
                        "ad": action[:1000],
                        "dl": deadline_iso,
                    },
                )
            except Exception as exc:
                logger.warning("[cio_chair] commitment insert failed: %s", exc)
    try:
        db.commit()
    except Exception as exc:
        logger.warning("[cio_chair] commitment commit failed: %s", exc)


def _increment_overdue_strikes(db: Session) -> int:
    """Carry-forward: increment strike_count for any open past-deadline commitments."""
    try:
        result = db.execute(
            text(
                "UPDATE agent_commitments SET strike_count = strike_count + 1 "
                "WHERE status = 'open' AND deadline < datetime('now')"
            )
        )
        db.commit()
        return result.rowcount or 0
    except Exception as exc:
        logger.warning("[cio_chair] strike increment failed: %s", exc)
        return 0


def run_meeting(
    db: Session,
    *,
    meeting_id: str,
    budget_cap_usd: float = 1.50,
    daily_cap_usd: float = 3.00,
    wall_clock_cap_seconds: int = 600,
    poll_dick_veto: bool = True,
    dry_run: bool = False,
    skip_row_insert: bool = False,
    _session_factory=None,
) -> MeetingResult:
    """Sync wrapper around run_meeting_async. For callers not already in an event loop.

    If dry_run=True: skip all DB INSERTs to fund_meetings/agent_opening_reads/
    agent_commitments/veto_log; return result for inspection.

    If skip_row_insert=True: skip Phase 1 INSERT (caller already inserted the row).

    _session_factory: optional callable that returns a new SQLAlchemy Session for worker
    threads. If None, resolves to the real SessionLocal at call time. Pass a test factory
    to ensure worker threads use the same in-memory DB as the test session.
    """
    try:
        loop = asyncio.get_running_loop()
        # If a loop is already running, the caller MUST use run_meeting_async.
        raise RuntimeError(
            "run_meeting() called inside a running event loop — use run_meeting_async() instead"
        )
    except RuntimeError as exc:
        # No running loop → fine to asyncio.run
        if "no running event loop" not in str(exc):
            raise
    return asyncio.run(run_meeting_async(
        db, meeting_id=meeting_id,
        budget_cap_usd=budget_cap_usd, daily_cap_usd=daily_cap_usd,
        wall_clock_cap_seconds=wall_clock_cap_seconds,
        poll_dick_veto=poll_dick_veto, dry_run=dry_run,
        skip_row_insert=skip_row_insert,
        _session_factory=_session_factory,
    ))


async def run_meeting_async(
    db: Session,
    *,
    meeting_id: str,
    budget_cap_usd: float = 1.50,
    daily_cap_usd: float = 3.00,
    wall_clock_cap_seconds: int = 600,
    poll_dick_veto: bool = True,
    dry_run: bool = False,
    skip_row_insert: bool = False,
    _session_factory=None,
) -> MeetingResult:
    """Async-capable variant of run_meeting.

    Phases 0, 1, 2 run identically (sync calls, fast).
    Phase 3 fans out the 9 opening reads via asyncio.gather + asyncio.to_thread.
    Phases 4-10 run sequentially as today (they depend on opening_reads).

    If skip_row_insert=True: skip Phase 1 INSERT (caller already inserted the row).

    _session_factory: optional callable returning a new SQLAlchemy Session for worker
    threads. Resolved once here (not inside worker closure) so test fixtures can inject
    the in-memory test DB factory without hitting the module-level SessionLocal mock.
    """
    # Resolve session factory at function-entry scope so workers close over the local,
    # not the module-level name (which may be a MagicMock in test environments).
    if _session_factory is None:
        from app.db.session import SessionLocal as _session_factory

    started_at = datetime.now(timezone.utc)
    started_at_iso = started_at.isoformat()
    t_start = time.monotonic()

    # Phase 0 — daily-cap pre-check
    # Reject if running a full meeting would push us over the daily cap.
    # Guard: daily_spend + per_meeting_budget > daily_cap (conservative; avoids
    # starting a meeting we know will be cut off mid-way).
    daily_spend = _daily_llm_spend_usd(db)
    if daily_spend + budget_cap_usd > daily_cap_usd:
        logger.warning(
            "[cio_chair] daily cap would be exceeded (%.2f + %.2f > %.2f) — aborting meeting %s",
            daily_spend, budget_cap_usd, daily_cap_usd, meeting_id,
        )
        ended_at = datetime.now(timezone.utc)
        if not dry_run:
            # Write a short row for diagnostics
            try:
                db.execute(
                    text(
                        "INSERT INTO fund_meetings "
                        "(meeting_id, started_at, ended_at, duration_seconds, "
                        " model_cost_usd, status, failure_reason) "
                        "VALUES (:mid, :sa, :ea, 0, 0.0, 'failed_budget', 'daily_cap_exceeded')"
                    ),
                    {"mid": meeting_id, "sa": started_at_iso, "ea": ended_at.isoformat()},
                )
                db.commit()
            except Exception as exc:
                logger.warning("[cio_chair] failed_budget row insert failed: %s", exc)
        return MeetingResult(
            meeting_id=meeting_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=0,
            total_cost_usd=daily_spend,
            opening_reads=[],
            top_items=[],
            deferred_items=[],
            decisions_made=[],
            vetoes_used=0,
            status="failed_budget",
            failure_reason="daily_cap_exceeded",
        )

    # Phase 1 — INSERT fund_meetings (status='running')
    if not dry_run and not skip_row_insert:
        try:
            db.execute(
                text(
                    "INSERT INTO fund_meetings "
                    "(meeting_id, started_at, status) "
                    "VALUES (:mid, :sa, 'running')"
                ),
                {"mid": meeting_id, "sa": started_at_iso},
            )
            db.commit()
        except Exception as exc:
            logger.error("[cio_chair] fund_meetings INSERT failed: %s", exc)

    # Phase 2 — snapshot + memory
    snapshot = build_canonical_snapshot(db)
    memory = _load_memory(db)
    open_commitments = memory.get("open_commitments", [])

    # Phase 8 (pre-read) — increment overdue strikes before opening reads
    if not dry_run:
        _increment_overdue_strikes(db)

    # Phase 3 — 9 agent opening reads (parallel via asyncio.gather + asyncio.to_thread)
    opening_reads: list[OpeningReadResult] = []
    dick_available = True

    # Budget pre-check (single check before fan-out — concurrent calls cannot
    # enforce per-agent budget gates, so we pre-allocate by total cap and post-check.)
    current_spend = _meeting_window_spend_usd(db, started_at_iso)
    elapsed = time.monotonic() - t_start
    if current_spend > 0.6 * budget_cap_usd or elapsed > wall_clock_cap_seconds:
        # All-skip — same shape as serial path's per-agent budget_skip
        opening_reads = [
            OpeningReadResult(
                agent_name=agent, meeting_id=meeting_id,
                what_im_seeing="", whats_working="", whats_broken="", asks="",
                metrics_i_track={}, confidence_in_book="",
                cost_usd=0.0, response_time_ms=0, raw_text="",
                status="budget_skip",
                error_text="pre_fanout_budget_or_time_exceeded",
            )
            for agent in _AGENT_ORDER
        ]
        if not dry_run:
            for r in opening_reads:
                try:
                    db.execute(
                        text(
                            "INSERT OR IGNORE INTO agent_opening_reads "
                            "(meeting_id, agent_name, structured_read_json, "
                            " response_time_ms, cost_usd, status) "
                            "VALUES (:mid, :an, '{}', 0, 0.0, 'budget_skip')"
                        ),
                        {"mid": meeting_id, "an": r.agent_name},
                    )
                except Exception as exc:
                    logger.warning("[cio_chair] budget_skip persist failed: %s", exc)
            db.commit()
        dick_available = False
    else:
        # Fan out — each agent gets its own thread-bound DB session (cannot share
        # the request db across threads safely with SQLite).
        async def _one(agent_name: str) -> OpeningReadResult:
            # SQLAlchemy Session is NOT thread-safe. Create a fresh session in the worker thread.
            # _session_factory is closed over from the enclosing function scope (resolved above),
            # NOT imported inside the closure, so test fixtures can inject a real test DB factory.
            def _run_with_own_session():
                worker_db = _session_factory()
                try:
                    return run_opening_read(
                        agent_name=agent_name,
                        meeting_id=meeting_id,
                        canonical_snapshot=snapshot,
                        recent_activity=[],
                        open_commitments=[c for c in open_commitments if c.get("owner_agent") == agent_name],
                        db=worker_db,
                        started_at_iso=started_at_iso,
                    )
                finally:
                    worker_db.close()
            return await asyncio.to_thread(_run_with_own_session)

        gather_results = await asyncio.gather(
            *[_one(agent) for agent in _AGENT_ORDER],
            return_exceptions=True,
        )

        opening_reads = []
        for agent, res in zip(_AGENT_ORDER, gather_results):
            if isinstance(res, Exception):
                logger.error("[cio_chair] agent %s raised in gather: %s", agent, res)
                opening_reads.append(OpeningReadResult(
                    agent_name=agent, meeting_id=meeting_id,
                    what_im_seeing="", whats_working="", whats_broken="", asks="",
                    metrics_i_track={}, confidence_in_book="",
                    cost_usd=0.0, response_time_ms=0, raw_text="",
                    status="relay_down",
                    error_text=f"gather_exception: {str(res)[:400]}",
                ))
                # Persist failure row so the meeting record reflects all 9 agents
                if not dry_run:
                    try:
                        db.execute(
                            text(
                                "INSERT OR IGNORE INTO agent_opening_reads "
                                "(meeting_id, agent_name, structured_read_json, "
                                " response_time_ms, cost_usd, status, error_text) "
                                "VALUES (:mid, :an, '{}', 0, 0.0, 'relay_down', :et)"
                            ),
                            {"mid": meeting_id, "an": agent, "et": str(res)[:500]},
                        )
                        db.commit()
                    except Exception as exc:
                        logger.warning("[cio_chair] gather-exception persist failed: %s", exc)
            else:
                opening_reads.append(res)

        # Dick availability — same check as serial path
        dick_result = next((r for r in opening_reads if r.agent_name == "chief_risk_officer"), None)
        dick_available = bool(dick_result and dick_result.status == "ok")
        if not dick_available:
            logger.warning("[cio_chair] Dick opening read failed — veto polls disabled")

        # POST-FANOUT budget enforcement (concurrent calls can blow past cap;
        # if we did, mark failed_budget instead of continuing into chair phase)
        post_spend = _meeting_window_spend_usd(db, started_at_iso)
        if post_spend > budget_cap_usd:
            ended_at = datetime.now(timezone.utc)
            duration = int((ended_at - started_at).total_seconds())
            if not dry_run:
                _finalize_meeting(db, meeting_id, ended_at, duration, post_spend,
                                  "failed_budget", "post_fanout_budget_exceeded", 0)
            return MeetingResult(
                meeting_id=meeting_id, started_at=started_at, ended_at=ended_at,
                duration_seconds=duration, total_cost_usd=post_spend,
                opening_reads=opening_reads, top_items=[], deferred_items=[],
                decisions_made=[], vetoes_used=0,
                status="failed_budget", failure_reason="post_fanout_budget_exceeded",
            )

    # Check relay-down threshold (≥5 agents relay_down → failed_partial)
    relay_down_count = sum(1 for r in opening_reads if r.status == "relay_down")
    if relay_down_count >= 5:
        ended_at = datetime.now(timezone.utc)
        duration = int((ended_at - started_at).total_seconds())
        status = "failed_partial"
        failure_reason = "relay_unavailable"
        if not dry_run:
            _finalize_meeting(db, meeting_id, ended_at, duration, 0.0, status, failure_reason, 0)
        return MeetingResult(
            meeting_id=meeting_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total_cost_usd=_meeting_window_spend_usd(db, started_at_iso),
            opening_reads=opening_reads,
            top_items=[],
            deferred_items=[],
            decisions_made=[],
            vetoes_used=0,
            status=status,
            failure_reason=failure_reason,
        )

    # Phase 4 — chair pick top-3 items
    ok_reads = [r for r in opening_reads if r.status == "ok"]
    top_items: list[MeetingItem] = []
    deferred_items: list[str] = []
    current_status = "completed"
    current_failure = None

    # Budget/time check before chair phase
    current_spend = _meeting_window_spend_usd(db, started_at_iso)
    elapsed = time.monotonic() - t_start

    if current_spend > budget_cap_usd or elapsed > wall_clock_cap_seconds:
        current_status = "failed_budget" if current_spend > budget_cap_usd else "failed_timeout"
        current_failure = "post_opening_reads_exceeded"
    else:
        reads_summary = "\n".join(
            f"- {r.agent_name} [{r.status}]: {r.what_im_seeing[:200]} | broken: {r.whats_broken[:150]} | asks: {r.asks[:100]}"
            for r in ok_reads
        )
        p0_flags = [r.agent_name for r in ok_reads if "[P0]" in r.whats_broken]

        chair_prompt = (
            f"OPENING READS SUMMARY:\n{reads_summary}\n\n"
            f"P0 flagging agents: {p0_flags}\n\n"
            "Pick the top 3 agenda items. MUST include any P0 flagged items. "
            "For each item surface which agents have conflicting metrics.\n"
            "Return JSON: {\"top_items\": ["
            "{\"title\": \"str≤120\", \"surfaced_by\": [\"role_id\"], "
            "\"tension\": \"str\", \"severity\": \"P0|P1|P2\", "
            "\"is_capital_or_risk\": true|false}, ...], "
            "\"deferred\": [\"str\"]}"
        )
        raw_chair, err_chair = _call_chair_llm(
            db, chair_prompt, agent_name="cio", max_tokens=600
        )

        if err_chair:
            current_status = "failed_partial"
            current_failure = f"chair_relay_error: {err_chair[:100]}"
        else:
            parsed_chair, parse_err = _parse_json_response(raw_chair)
            if parse_err:
                current_status = "failed_partial"
                current_failure = f"chair_parse_error: {parse_err[:100]}"
            else:
                raw_top = parsed_chair.get("top_items", [])
                if not isinstance(raw_top, list):
                    raw_top = []
                deferred_items = parsed_chair.get("deferred", [])
                if not isinstance(deferred_items, list):
                    deferred_items = []
                for i, it in enumerate(raw_top[:3]):
                    if not isinstance(it, dict):
                        continue
                    title = str(it.get("title", f"Item {i+1}"))[:120]
                    tension = str(it.get("tension", ""))
                    severity = str(it.get("severity", "P2"))
                    surfaced_by = it.get("surfaced_by", [])
                    if not isinstance(surfaced_by, list):
                        surfaced_by = []
                    # chair flag or keyword check
                    is_cap = bool(it.get("is_capital_or_risk", False)) or _is_capital_or_risk(title, tension)
                    top_items.append(MeetingItem(
                        item_id=f"item_{i+1}_{meeting_id}",
                        title=title,
                        surfaced_by=surfaced_by,
                        tension=tension,
                        severity=severity,
                        is_capital_or_risk=is_cap,
                    ))

    # Phase 5 — debate + resolution per item
    vetoes_used_ref = [0]
    active_poll = poll_dick_veto and dick_available

    for item in top_items:
        current_spend = _meeting_window_spend_usd(db, started_at_iso)
        elapsed = time.monotonic() - t_start

        if current_spend > budget_cap_usd:
            current_status = "failed_budget"
            current_failure = "per_meeting_budget_exceeded"
            break
        if elapsed > wall_clock_cap_seconds:
            current_status = "failed_timeout"
            current_failure = "wall_clock_exceeded"
            break

        ok, fail_reason = _run_debate_and_resolution(
            item=item,
            opening_reads=opening_reads,
            db=db,
            meeting_id=meeting_id,
            started_at=started_at,
            budget_cap_usd=budget_cap_usd,
            wall_clock_cap_seconds=wall_clock_cap_seconds,
            t_start=t_start,
        )
        if not ok:
            current_status = "failed_budget"
            current_failure = fail_reason
            break

        # Phase 6 — Dick veto poll
        if active_poll and item.is_capital_or_risk:
            current_spend = _meeting_window_spend_usd(db, started_at_iso)
            if current_spend <= budget_cap_usd and time.monotonic() - t_start <= wall_clock_cap_seconds:
                if not dry_run:
                    _run_veto_poll(item, db, meeting_id, started_at, vetoes_used_ref)
        elif not dick_available and item.is_capital_or_risk:
            item.veto_polled = False
            # briefing will note DICK UNAVAILABLE

    # If Dick was unavailable and there were capital/risk items, surface it
    has_cap_risk = any(it.is_capital_or_risk for it in top_items)
    if not dick_available and has_cap_risk:
        if current_status == "completed":
            current_status = "failed_partial"
            current_failure = "dick_unavailable_veto_polls_skipped"

    # Phase 7 — persist agent_commitments
    if not dry_run:
        _persist_commitments(db, meeting_id, top_items)

    # Finalize
    ended_at = datetime.now(timezone.utc)
    duration = int((ended_at - started_at).total_seconds())
    total_cost = _meeting_window_spend_usd(db, started_at_iso)

    if not dry_run:
        _finalize_meeting(
            db, meeting_id, ended_at, duration, total_cost,
            current_status, current_failure, vetoes_used_ref[0],
        )

    decisions_made = [
        {"item": it.title, "resolution": it.resolution, "action_items": it.action_items}
        for it in top_items
    ]

    return MeetingResult(
        meeting_id=meeting_id,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration,
        total_cost_usd=total_cost,
        opening_reads=opening_reads,
        top_items=top_items,
        deferred_items=deferred_items,
        decisions_made=decisions_made,
        vetoes_used=vetoes_used_ref[0],
        status=current_status,
        failure_reason=current_failure,
    )


def _finalize_meeting(
    db: Session,
    meeting_id: str,
    ended_at: datetime,
    duration: int,
    cost_usd: float,
    status: str,
    failure_reason: Optional[str],
    vetoes_used: int,
) -> None:
    try:
        db.execute(
            text(
                "UPDATE fund_meetings SET "
                "ended_at=:ea, duration_seconds=:ds, model_cost_usd=:cu, "
                "status=:st, failure_reason=:fr, vetoes_used=:vu "
                "WHERE meeting_id=:mid"
            ),
            {
                "ea": ended_at.isoformat(),
                "ds": duration,
                "cu": cost_usd,
                "st": status,
                "fr": failure_reason,
                "vu": vetoes_used,
                "mid": meeting_id,
            },
        )
        db.commit()
    except Exception as exc:
        logger.error("[cio_chair] finalize meeting failed: %s", exc)


def render_briefing_markdown(
    result: MeetingResult,
    canonical: dict,
    memory: dict,
) -> str:
    """Render the 8-section briefing markdown."""
    now_et = datetime.now(timezone.utc)
    date_str = now_et.strftime("%Y-%m-%d %H:%M ET")

    pv_dollars = canonical.get("pv_dollars", 0)
    today_pnl_cents = canonical.get("today_pnl_cents", 0)
    today_pnl_dollars = today_pnl_cents / 100
    pv_total = pv_dollars or 1  # avoid div/0
    today_pnl_pct = (today_pnl_dollars / pv_total) * 100 if pv_total else 0.0
    return_30d = canonical.get("return_30d_pct", 0.0)
    dd_pct = canonical.get("drawdown_pct", 0.0)
    dd_dist = canonical.get("drawdown_distance_to_halt_pct", 0.0)
    regime = canonical.get("regime", "UNKNOWN")
    vix = canonical.get("vix") or "N/A"
    btc_dom = canonical.get("btc_dominance") or "N/A"
    sleeves = canonical.get("sleeves", [])
    banner = canonical.get("_banner", "")

    # Summary one-liner
    if result.status in ("failed_budget", "failed_timeout", "failed_partial"):
        summary = f"PARTIAL MEETING — {result.failure_reason or result.status}"
    elif result.top_items:
        top = result.top_items[0]
        summary = f"{top.severity}: {top.title[:80]} — {result.vetoes_used} veto(s)"
    else:
        summary = f"Meeting completed — no top items surfaced"

    # P0 items for section 8
    p0_items = [it for it in result.top_items if it.severity == "P0"]
    open_vetoes = [it for it in result.top_items if it.veto_used and not it.veto_reason == "resolved"]

    # Open commitments from memory
    open_commitments = memory.get("open_commitments", [])
    broken_commitments = [c for c in open_commitments if c.get("strike_count", 0) > 0]
    overdue_commitments = [c for c in open_commitments if c.get("deadline", "") < now_et.isoformat()]

    # Section 1: Portfolio Snapshot
    if banner:
        s1 = f"**{banner}**\n"
    else:
        s1 = (
            f"PV ${pv_dollars:,.0f}  |  Today {today_pnl_pct:+.2f}% (${today_pnl_dollars:+,.0f})\n"
            f"30d {return_30d:+.2f}%  |  Drawdown distance to -1.5% halt: {dd_dist:+.2f}%\n"
            f"Regime: {regime}  |  VIX {vix}  |  BTC dominance {btc_dom}%\n"
        )

    # Section 2: Sleeve Read
    sleeve_rows = ""
    if sleeves:
        sleeve_rows = "| Sleeve | $ | % NAV | Today |\n|---|---|---|---|\n"
        for s in sleeves:
            sleeve_rows += (
                f"| {s.get('sleeve','?')} | ${s.get('dollars',0):,.0f} "
                f"| {s.get('pct',0):.1f}% "
                f"| ${s.get('today_pnl_cents',0)/100:+,.0f} |\n"
            )
    else:
        sleeve_rows = "_No sleeve data_\n"

    # Section 3: Agent Opening Reads
    agent_lines = []
    _SHORT = {
        "portfolio_manager": "BRICK (PM)",
        "chief_risk_officer": "DICK (CRO)",
        "equity_researcher": "NICK (ER)",
        "quant_researcher": "MICK (QR)",
        "macro_strategist": "RICK (MS)",
        "data_quality_watcher": "VICK (DQ)",
        "execution_auditor": "SLICK (EA)",
        "operations": "WICK (OPS)",
        "sentinel_devops": "PATRICK (DEV)",
    }
    for r in result.opening_reads:
        label = _SHORT.get(r.agent_name, r.agent_name.upper())
        if r.status != "ok":
            agent_lines.append(f"- {label}: [STATUS={r.status.upper()}]")
        else:
            snippet = r.what_im_seeing[:160]
            conf = r.confidence_in_book[:30] if r.confidence_in_book else "N/A"
            agent_lines.append(f"- {label}: {snippet} · confidence {conf}")

    # Dick unavailable banner
    dick_read = next((r for r in result.opening_reads if r.agent_name == "chief_risk_officer"), None)
    dick_unavailable_banner = ""
    if dick_read and dick_read.status != "ok":
        dick_unavailable_banner = "\n> **DICK UNAVAILABLE — NO VETO POLLS THIS MEETING**\n"

    # Section 4: Top 3 Items
    items_md = ""
    for i, item in enumerate(result.top_items, 1):
        veto_tag = " [VETOED]" if item.veto_used else ""
        items_md += f"\n### 4.{i} {item.title}  [{item.severity}]{veto_tag}\n"
        items_md += f"Surfaced by: {', '.join(item.surfaced_by)}\n"
        items_md += f"Tension: {item.tension}\n"
        if item.debate_round_1:
            items_md += "Round 1:\n"
            for rd in item.debate_round_1:
                items_md += f"- {rd.get('agent','?')}: {rd.get('position_words','')[:150]}\n"
        if item.debate_round_2:
            items_md += f"Round 2: {item.debate_round_2.get('response','')[:200]}\n"
        items_md += f"Resolution: {item.resolution}\n"
        if item.action_items:
            items_md += "Action items:\n"
            for act in item.action_items:
                items_md += f"- [{act.get('owner','?')}] {act.get('action','?')} — due {act.get('deadline_iso','?')}\n"

    # Section 5: Vetoes
    veto_md = f"{result.vetoes_used}."
    if result.vetoes_used > 0:
        vetoed_items = [it for it in result.top_items if it.veto_used]
        for vit in vetoed_items:
            veto_md += f"\n- Target: {vit.title} | Reason: {vit.veto_reason}"

    # Section 6: Open Commitments
    open_count = len(open_commitments)
    broken_count = sum(1 for c in open_commitments if c.get("strike_count", 0) >= 3)
    past_due = len(overdue_commitments)
    commit_lines = ""
    for c in overdue_commitments[:10]:
        prefix = "**OVER-STRIKE** " if c.get("strike_count", 0) >= 3 else ""
        commit_lines += (
            f"- {prefix}[{c.get('owner_agent','?')}] {c.get('action_description','?')[:100]} "
            f"— due {c.get('deadline','?')} (strikes: {c.get('strike_count',0)})\n"
        )

    # Section 7: Cost & Performance
    api_fallback_note = "0 (target — non-zero is a warning)"
    status_note = result.status
    if result.failure_reason:
        status_note += f" — {result.failure_reason}"

    # Section 8: Needs Brock
    needs_brock_items = ""
    if p0_items or open_vetoes or broken_count > 0:
        if p0_items:
            for pi in p0_items:
                needs_brock_items += f"- P0: {pi.title}\n"
        if open_vetoes:
            for vit in open_vetoes:
                needs_brock_items += f"- VETO pending override: {vit.title}\n"
        if broken_count > 0:
            needs_brock_items += f"- {broken_count} commitment(s) at OVER-STRIKE (3+ strikes)\n"

    partial_banner = ""
    if result.status in ("failed_budget", "failed_timeout", "failed_partial"):
        partial_banner = f"\n> **(PARTIAL — {result.failure_reason or result.status})**\n"

    md = f"""# CIO MORNING BRIEFING — {date_str}
{partial_banner}
> {summary}

## 1. Portfolio Snapshot
{s1}
## 2. Sleeve Read
{sleeve_rows}
## 3. Agent Opening Reads (≤2 lines per agent)
{dick_unavailable_banner}
{chr(10).join(agent_lines)}

## 4. Top 3 Items
{items_md if items_md else "_No items surfaced_"}

## 5. Vetoes Used This Meeting
{veto_md}

## 6. Open Commitments Carried Forward
{open_count} open  |  {past_due} past deadline (strike_count incremented)
{commit_lines if commit_lines else "_None_"}

## 7. Cost & Performance
Meeting cost: ${result.total_cost_usd:.4f} (cap ${1.50:.2f})
Duration: {result.duration_seconds}s (cap {600}s)
API fallback calls: {api_fallback_note}
Status: {status_note}

## 8. Needs Brock
{needs_brock_items if needs_brock_items else "_No immediate action required_"}

---
briefing_id=_pending_  · meeting_id={result.meeting_id}
"""
    return md
