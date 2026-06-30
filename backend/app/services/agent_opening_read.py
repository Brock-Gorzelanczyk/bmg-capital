"""agent_opening_read — per-agent structured opening read for CIO morning meetings.

Zero direct SDK usage. Zero calls to claude binary.
ALL inference routed through call_llm from app.services.llm_client.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm_client import call_llm

logger = logging.getLogger(__name__)

VALID_AGENTS: set[str] = {
    "portfolio_manager",
    "chief_risk_officer",
    "equity_researcher",
    "quant_researcher",
    "macro_strategist",
    "data_quality_watcher",
    "execution_auditor",
    "operations",
    "sentinel_devops",
}

# Short-name file map for prompt loading
_PROMPT_FILE_BY_ROLE: dict[str, str] = {
    "portfolio_manager":    "brick.md",
    "chief_risk_officer":   "dick.md",
    "equity_researcher":    "nick.md",
    "quant_researcher":     "mick.md",
    "macro_strategist":     "rick.md",
    "data_quality_watcher": "vick.md",
    "execution_auditor":    "slick.md",
    "operations":           "wick.md",
    "sentinel_devops":      "patrick.md",
}

# Per-agent agenda — appended to base prompt as "TODAY'S FOCUS — your seat"
_AGENDA_BY_ROLE: dict[str, str] = {
    "portfolio_manager":    "capital allocation by sleeve; sleeve P&L today + 30d; rebalance proposals; past-30d hit rate of own proposals",
    "chief_risk_officer":   "DD distance to -1.5% halt; concentration violations (8%/25%/cluster); vol regime; vetoes issued this week; unwind triggers armed",
    "equity_researcher":    "equity sleeve P&L; signal gate rate; AAPL/NVDA/MSFT/AMZN concentration; factor tilts (beta vs alpha decomp)",
    "quant_researcher":     "crypto Quant bot P&L (Aggressive/Mean Rev/Scalper); signal storms; alpha decay; candidate queue",
    "macro_strategist":     "regime read (BULL_TRENDING/CHOP/etc); realized + implied vol; sector tilts; BTC dominance; VIX",
    "data_quality_watcher": "per-source feed integrity (Alpaca, Kraken, Coinglass); P&L reconciliation; /admin/diagnostics divergence flags",
    "execution_auditor":    "slippage realized vs modeled (8 bps target); fill quality; broker reconcile diffs; options-vs-equity asset_class invariant",
    "operations":           "position count consistency (user-scoped vs fleet); watchlist health; candidate promotion queue; cross-sleeve quarantine queue size",
    "sentinel_devops":      "infra health; Railway deploy status; Discord worker liveness; capital_invariant watchdog; Sentinel autonomous fixes today; escalations",
}

# Shared system anchor appended via system_prompt arg to call_llm
SYSTEM_ANCHOR = (
    "You are an agent of BMG Capital reporting at the CIO morning meeting. "
    "Output STRICT JSON only — no markdown fences, no prose outside JSON. "
    "Cite numbers from the canonical snapshot. Never invent metrics. "
    "Standing decisions you must respect: DISCORD_SIGNAL_POSTING_ENABLED=false; "
    "vol-targeting cap 35% NAV; inception_capital_cents immutable; no auto mass-action."
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "agents" / "prompts"
_prompt_cache: dict[str, str] = {}


def _load_prompt(role: str) -> str:
    if role in _prompt_cache:
        return _prompt_cache[role]
    fname = _PROMPT_FILE_BY_ROLE.get(role, "")
    if not fname:
        return f"You are the {role} at BMG Capital."
    fpath = _PROMPTS_DIR / fname
    try:
        content = fpath.read_text(encoding="utf-8")
        _prompt_cache[role] = content
        return content
    except OSError:
        logger.warning("[agent_opening_read] prompt file not found: %s", fpath)
        return f"You are the {role} at BMG Capital."


@dataclass
class OpeningReadResult:
    agent_name: str
    meeting_id: str
    what_im_seeing: str
    whats_working: str
    whats_broken: str
    asks: str
    metrics_i_track: dict
    confidence_in_book: str
    cost_usd: float
    response_time_ms: int
    raw_text: str
    status: str          # ok|parse_error|timeout|budget_skip|relay_down
    error_text: Optional[str] = None


def _build_user_prompt(
    agent_name: str,
    canonical_snapshot: dict,
    recent_activity: list[dict],
    open_commitments: list[dict],
) -> str:
    base_prompt = _load_prompt(agent_name)
    agenda = _AGENDA_BY_ROLE.get(agent_name, "your full domain")
    snapshot_json = json.dumps(canonical_snapshot, indent=2, default=str)
    activity_json = json.dumps(recent_activity[:20], indent=2, default=str)
    commitments_json = json.dumps(open_commitments, indent=2, default=str)

    return (
        f"{base_prompt}"
        f"\n\nTODAY'S FOCUS — your seat:\n{agenda}"
        f"\n\nCANONICAL SNAPSHOT (fund-wide, user_id=1 only):\n```json\n{snapshot_json}\n```"
        f"\n\nYOUR RECENT ACTIVITY (last 24h, ≤20 items):\n```json\n{activity_json}\n```"
        f"\n\nYOUR OPEN COMMITMENTS:\n```json\n{commitments_json}\n```"
        "\n\nReturn JSON matching schema:"
        " {\"what_im_seeing\": \"str<=200w\","
        " \"whats_working\": \"str (1-3 bullets metric-bearing)\","
        " \"whats_broken\": \"str (1-3 bullets each tagged [P0|P1|P2])\","
        " \"asks\": \"str\","
        " \"metrics_i_track\": {},"
        " \"confidence_in_book\": \"N/10 — one-line\"}"
    )


def _get_agent_cost_usd(db: Session, agent_name: str, started_at_iso: str) -> float:
    """Sum estimated_cost_cents from llm_call_log for this agent since meeting started."""
    try:
        row = db.execute(
            text(
                "SELECT COALESCE(SUM(estimated_cost_cents), 0) FROM llm_call_log "
                "WHERE agent_name = :an AND created_at >= :ts"
            ),
            {"an": agent_name, "ts": started_at_iso},
        ).scalar()
        return float(row or 0) / 100.0
    except Exception:
        return 0.0


def run_opening_read(
    *,
    agent_name: str,
    meeting_id: str,
    canonical_snapshot: dict,
    recent_activity: list[dict],
    open_commitments: list[dict],
    db: Session,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 600,
    started_at_iso: str = "",
) -> OpeningReadResult:
    """Build agent-specific prompt, route through call_llm, parse JSON, persist row.

    NEVER imports anthropic. NEVER spawns `claude` subprocess.
    ALL inference via call_llm from app.services.llm_client.
    """
    user_prompt = _build_user_prompt(
        agent_name=agent_name,
        canonical_snapshot=canonical_snapshot,
        recent_activity=recent_activity,
        open_commitments=open_commitments,
    )

    t0 = time.monotonic()
    raw = ""
    status = "ok"
    error_text: Optional[str] = None

    try:
        raw = call_llm(
            model=model,
            prompt=user_prompt,
            system_prompt=SYSTEM_ANCHOR,
            max_tokens=max_tokens,
            agent_name=agent_name,
            db=db,
        )
    except RuntimeError as exc:
        # relay down + fallback off → fail-closed
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        error_text = str(exc)[:2000]
        status = "relay_down"
        result = OpeningReadResult(
            agent_name=agent_name,
            meeting_id=meeting_id,
            what_im_seeing="",
            whats_working="",
            whats_broken="",
            asks="",
            metrics_i_track={},
            confidence_in_book="",
            cost_usd=0.0,
            response_time_ms=elapsed_ms,
            raw_text="",
            status=status,
            error_text=error_text,
        )
        _persist_row(db, result, meeting_id)
        return result

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Parse JSON
    parsed: dict = {}
    try:
        # Strip markdown fences if model ignored instructions
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = json.loads(clean)
    except (json.JSONDecodeError, ValueError) as exc:
        status = "parse_error"
        error_text = f"{exc}: {raw[:500]}"
        parsed = {"_raw": raw}

    cost_usd = _get_agent_cost_usd(db, agent_name, started_at_iso) if started_at_iso else 0.0

    result = OpeningReadResult(
        agent_name=agent_name,
        meeting_id=meeting_id,
        what_im_seeing=str(parsed.get("what_im_seeing", ""))[:2000],
        whats_working=str(parsed.get("whats_working", "")),
        whats_broken=str(parsed.get("whats_broken", "")),
        asks=str(parsed.get("asks", "")),
        metrics_i_track=parsed.get("metrics_i_track", {}) if isinstance(parsed.get("metrics_i_track"), dict) else {},
        confidence_in_book=str(parsed.get("confidence_in_book", "")),
        cost_usd=cost_usd,
        response_time_ms=elapsed_ms,
        raw_text=raw[:2000],
        status=status,
        error_text=error_text,
    )
    _persist_row(db, result, meeting_id)
    return result


def _persist_row(db: Session, result: OpeningReadResult, meeting_id: str) -> None:
    """INSERT INTO agent_opening_reads — UNIQUE(meeting_id, agent_name) → IGNORE on conflict."""
    try:
        structured = json.dumps({
            "what_im_seeing": result.what_im_seeing,
            "whats_working": result.whats_working,
            "whats_broken": result.whats_broken,
            "asks": result.asks,
            "metrics_i_track": result.metrics_i_track,
            "confidence_in_book": result.confidence_in_book,
        })
        db.execute(
            text(
                "INSERT OR IGNORE INTO agent_opening_reads "
                "(meeting_id, agent_name, structured_read_json, response_time_ms, "
                " cost_usd, status, error_text) "
                "VALUES (:mid, :an, :srj, :rt, :cu, :st, :et)"
            ),
            {
                "mid": meeting_id,
                "an": result.agent_name,
                "srj": structured,
                "rt": result.response_time_ms,
                "cu": result.cost_usd,
                "st": result.status,
                "et": result.error_text,
            },
        )
        db.commit()
    except Exception as exc:
        logger.warning("[agent_opening_read] persist failed for %s: %s", result.agent_name, exc)
