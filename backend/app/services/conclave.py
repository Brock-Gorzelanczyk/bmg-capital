"""Agent Conclave — 4-agent LLM filter for trading signals.

Sits between signal creation (bot_signals row committed) and Discord
promotion (thread that posts to the Discord channel). Only master-
approved signals are promoted. All raw signals stay in bot_signals so
no data is lost.

Flow
----
  Signal row committed
    → Analyst (LLM):  structural coherence score 0-100
    → Oracle  (LLM):  next 10 candle sketch + confidence
    → Quant   (DB):   historical hit rate on same (bot, strategy)
    → Master  (LLM):  final approve / reject with reasoning
    → Verdict row written to signal_conclave_verdicts
    → If approve: chart PNG generated, Discord thread runs
    → If reject: Discord thread skipped, signal stays in bot_signals

Env vars
--------
  CONCLAVE_ENABLED             master switch, default false
  CONCLAVE_BOT_ALLOWLIST       comma-separated bot names, default empty
  CONCLAVE_MAX_CALLS_PER_HOUR  rate cap, default 200; skip (fail-open)
                               when exceeded
  CONCLAVE_APPROVE_ON_ERROR    default true; on LLM error the master
                               verdict is treated as approve so a
                               relay outage doesn't silently kill
                               every signal

Fail-open
---------
Every failure path (LLM raise, JSON parse error, rate limit, missing
row, matplotlib import error) returns a verdict with master_final =
approve when CONCLAVE_APPROVE_ON_ERROR is true. The row is still
written to signal_conclave_verdicts with fail_open=1 so we can count
fail-opens per hour.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS_PER_AGENT = 500


@dataclass
class Verdict:
    signal_id: int
    bot_name: str
    analyst_score: Optional[int]
    analyst_reasoning: str
    oracle_confidence: Optional[int]
    oracle_prediction: Optional[list]
    oracle_reasoning: str
    quant_win_rate: Optional[float]
    quant_sample_size: int
    quant_verdict: str
    master_final: str
    master_reasoning: str
    chart_path: Optional[str]
    latency_ms: int
    fail_open: bool


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


def _fail_open_default() -> str:
    return "approve" if _env_flag("CONCLAVE_APPROVE_ON_ERROR", "true") else "reject"


def _hourly_rate_ok(db: Session) -> bool:
    cap = int(os.getenv("CONCLAVE_MAX_CALLS_PER_HOUR", "200"))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    try:
        n = db.execute(
            text("SELECT COUNT(*) FROM signal_conclave_verdicts WHERE created_at >= :cut"),
            {"cut": cutoff},
        ).fetchone()
        used = int(n[0] or 0) if n else 0
    except Exception as exc:
        logger.warning("[conclave] rate check query failed: %s", exc)
        return True
    if used >= cap:
        logger.warning("[conclave] hourly cap %d reached (used=%d); skipping run", cap, used)
        return False
    return True


def _call_agent(system: str, user: str, agent_name: str, db: Session) -> str:
    """Wrap the relay call. Returns "" on any error."""
    from app.services.llm_client import call_llm
    try:
        return call_llm(
            model=_MODEL,
            prompt=user,
            system_prompt=system,
            max_tokens=_MAX_TOKENS_PER_AGENT,
            agent_name=agent_name,
            db=db,
        ) or ""
    except Exception as exc:
        logger.warning("[conclave] %s call_llm raised: %s", agent_name, exc)
        return ""


def _write_verdict(db: Session, v: Verdict) -> None:
    try:
        import json as _json
        db.execute(text("""
            INSERT INTO signal_conclave_verdicts (
                signal_id, bot_name, analyst_score, analyst_reasoning,
                oracle_prediction, oracle_confidence,
                quant_win_rate, quant_sample_size, quant_verdict,
                master_final, master_reasoning, chart_path, latency_ms,
                fail_open, created_at
            ) VALUES (
                :signal_id, :bot_name, :analyst_score, :analyst_reasoning,
                :oracle_prediction, :oracle_confidence,
                :quant_win_rate, :quant_sample_size, :quant_verdict,
                :master_final, :master_reasoning, :chart_path, :latency_ms,
                :fail_open, :created_at
            )
        """), {
            "signal_id": v.signal_id,
            "bot_name": v.bot_name,
            "analyst_score": v.analyst_score,
            "analyst_reasoning": v.analyst_reasoning,
            "oracle_prediction": _json.dumps(v.oracle_prediction) if v.oracle_prediction is not None else None,
            "oracle_confidence": v.oracle_confidence,
            "quant_win_rate": v.quant_win_rate,
            "quant_sample_size": v.quant_sample_size,
            "quant_verdict": v.quant_verdict,
            "master_final": v.master_final,
            "master_reasoning": v.master_reasoning,
            "chart_path": v.chart_path,
            "latency_ms": v.latency_ms,
            "fail_open": 1 if v.fail_open else 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("[conclave] verdict write failed for signal %d: %s",
                       v.signal_id, exc)


def run_conclave(signal_id: int, signal_dict: dict) -> Verdict:
    """Run all 4 agents and record the verdict.

    Never raises. Fail-open behavior is controlled by
    CONCLAVE_APPROVE_ON_ERROR.
    """
    from app.services import agents_analyst, agents_oracle, agents_quant, agents_master
    from app.services.conclave_chart import generate_chart

    t0 = time.monotonic()
    bot_name = str(signal_dict.get("bot") or "unknown")
    fail_open_verdict = _fail_open_default()
    fail_open = False

    db = SessionLocal()
    try:
        if not _hourly_rate_ok(db):
            fail_open = True
            v = Verdict(
                signal_id=signal_id, bot_name=bot_name,
                analyst_score=None, analyst_reasoning="rate cap hit",
                oracle_confidence=None, oracle_prediction=None,
                oracle_reasoning="rate cap hit",
                quant_win_rate=None, quant_sample_size=0, quant_verdict="skip",
                master_final=fail_open_verdict,
                master_reasoning=f"CONCLAVE_MAX_CALLS_PER_HOUR reached; fail-open={fail_open_verdict}",
                chart_path=None, latency_ms=int((time.monotonic() - t0) * 1000),
                fail_open=True,
            )
            _write_verdict(db, v)
            return v

        # 1. Analyst
        a_raw = _call_agent(agents_analyst.SYSTEM_PROMPT,
                            agents_analyst.build_prompt(signal_dict),
                            "conclave.analyst", db)
        if not a_raw:
            fail_open = True
        analyst = agents_analyst.parse_output(a_raw)

        # 2. Oracle
        o_raw = _call_agent(agents_oracle.SYSTEM_PROMPT,
                            agents_oracle.build_prompt(signal_dict),
                            "conclave.oracle", db)
        if not o_raw:
            fail_open = True
        oracle = agents_oracle.parse_output(o_raw)

        # 3. Quant (DB only)
        try:
            quant = agents_quant.evaluate(db, signal_dict)
        except Exception as exc:
            logger.warning("[conclave] quant raised: %s", exc)
            quant = {"win_rate": None, "sample_size": 0, "verdict": "approve",
                     "reasoning": f"quant error: {exc}"}

        # 4. Master (LLM synth)
        m_raw = _call_agent(agents_master.SYSTEM_PROMPT,
                            agents_master.build_prompt(signal_dict, analyst, oracle, quant),
                            "conclave.master", db)
        if not m_raw:
            fail_open = True
        master = agents_master.parse_output(m_raw)

        # Fail-open override — if any LLM path errored, respect
        # CONCLAVE_APPROVE_ON_ERROR rather than trusting a stub verdict.
        if fail_open and _env_flag("CONCLAVE_APPROVE_ON_ERROR", "true"):
            master = {"final": "approve",
                      "reasoning": "fail-open (relay error); "
                                   f"master returned {master.get('final')}"}

        chart_path: Optional[str] = None
        if master.get("final") == "approve":
            try:
                chart_path = generate_chart(
                    signal_id=signal_id,
                    symbol=str(signal_dict.get("symbol") or ""),
                    side=str(signal_dict.get("side") or ""),
                    entry=signal_dict.get("price"),
                    stop=signal_dict.get("stop"),
                    target=signal_dict.get("target"),
                )
            except Exception as exc:
                logger.warning("[conclave.chart] gen failed for signal %d: %s",
                               signal_id, exc)

        latency_ms = int((time.monotonic() - t0) * 1000)
        verdict = Verdict(
            signal_id=signal_id,
            bot_name=bot_name,
            analyst_score=analyst.get("score"),
            analyst_reasoning=analyst.get("reasoning") or "",
            oracle_confidence=oracle.get("confidence"),
            oracle_prediction=oracle.get("deltas_pct"),
            oracle_reasoning=oracle.get("reasoning") or "",
            quant_win_rate=quant.get("win_rate"),
            quant_sample_size=int(quant.get("sample_size") or 0),
            quant_verdict=str(quant.get("verdict") or "approve"),
            master_final=str(master.get("final") or fail_open_verdict),
            master_reasoning=str(master.get("reasoning") or ""),
            chart_path=chart_path,
            latency_ms=latency_ms,
            fail_open=fail_open,
        )
        _write_verdict(db, verdict)
        logger.warning(
            "[conclave] signal=%d bot=%s final=%s analyst=%s oracle_conf=%s "
            "quant=%s(n=%d,wr=%s) latency_ms=%d fail_open=%s",
            signal_id, bot_name, verdict.master_final,
            verdict.analyst_score, verdict.oracle_confidence,
            verdict.quant_verdict, verdict.quant_sample_size,
            verdict.quant_win_rate, latency_ms, fail_open,
        )
        return verdict
    finally:
        db.close()


def make_conclave_gate(bot_name: str) -> Optional[Callable[[int, dict], bool]]:
    """Return a callable suitable for log_signal's discord_gate arg.

    Returns None when conclave is disabled or the bot is not on the
    allowlist — the caller then hits the default (unfiltered) path.

    The callable returns True to promote the signal, False to hold it
    back from Discord.
    """
    if not _env_flag("CONCLAVE_ENABLED", "false"):
        return None
    allowlist = {
        b.strip()
        for b in os.getenv("CONCLAVE_BOT_ALLOWLIST", "").split(",")
        if b.strip()
    }
    if bot_name not in allowlist:
        return None

    def _gate(signal_id: int, signal_dict: dict) -> bool:
        verdict = run_conclave(signal_id, signal_dict)
        return verdict.master_final == "approve"

    return _gate


__all__ = ["Verdict", "run_conclave", "make_conclave_gate"]
