"""
Quant Researcher Agent — candidate pipeline manager for BMG Capital.

Responsibilities:
  1. Scan strategy_candidates table for pipeline state transitions
  2. Evaluate BacktestRun and WfaRun results against promotion gates
  3. Move candidates through: CANDIDATE → BACKTEST_QUEUED → BACKTEST_DONE → WFA_QUEUED → WFA_DONE → SHADOW_PAPER → PROMOTED
  4. Flag candidates that fail gates as RETIRED
  5. Post pipeline status digest to Discord
  6. Publish heartbeat to agent_messages bus

Gate thresholds:
  BACKTEST → WFA: net_sharpe >= 0.8, win_rate >= 0.45, max_drawdown_pct <= 0.25, n_trades >= 30
  WFA → SHADOW: aggregate_oos_sharpe >= 0.6, pbo <= 0.35, wfe >= 0.5
  SHADOW → PROMOTED: days_in_shadow >= 63, managed by Attention panel (CIO decision)

Called by: POST /api/agents/quant-researcher/run-pipeline
Also triggered by: Queen Agent daily standup at 7 AM ET
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Gate thresholds ───────────────────────────────────────────────────────────

BACKTEST_GATE = {
    "min_net_sharpe":      0.8,
    "min_win_rate":        0.45,
    "max_drawdown_pct":    0.25,
    "min_trades":          30,
}

WFA_GATE = {
    "min_oos_sharpe":  0.6,
    "max_pbo":         0.35,
    "min_wfe":         0.5,
}

SHADOW_DAYS_REQUIRED = 63


def _get_quant_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_QUANT_SIGNALS", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
        channel_id = (
            settings.discord_ch_quant_signals
            or settings.discord_ch_dev_log
            or channel_id
        )
    except Exception:
        pass
    return token, channel_id


def _post_discord(token: str, channel_id: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    try:
        import httpx
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json={"embeds": [embed]},
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[quant_researcher] Discord post failed: %s", exc)
        return False


def _transition_candidate(
    db: Session,
    candidate_id: int,
    from_state: str,
    to_state: str,
    reason: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("""
        UPDATE strategy_candidates
        SET state = :state, updated_at = :now
        WHERE id = :id
    """), {"state": to_state, "now": now, "id": candidate_id})
    db.execute(text("""
        INSERT INTO candidate_state_history
            (candidate_id, from_state, to_state, reason, triggered_by, created_at)
        VALUES (:cid, :from, :to, :reason, :agent, :now)
    """), {
        "cid": candidate_id, "from": from_state, "to": to_state,
        "reason": reason[:200], "agent": "quant_researcher", "now": now,
    })


def _evaluate_pipeline(db: Session) -> dict:
    """
    Scan all non-terminal candidates and apply gate checks.
    Returns summary of transitions made.
    """
    from app.db.models.pipeline import StrategyCandidate, BacktestRun, WfaRun

    transitions: list[dict] = []
    flags: list[str] = []

    candidates = db.query(StrategyCandidate).filter(
        StrategyCandidate.state.notin_(["PROMOTED", "RETIRED"])
    ).all()

    for cand in candidates:
        state = cand.state

        # ── BACKTEST_DONE → WFA_QUEUED (gate check) ──────────────────────────
        if state == "BACKTEST_DONE":
            bt = (
                db.query(BacktestRun)
                .filter(
                    BacktestRun.candidate_id == cand.id,
                    BacktestRun.status == "completed",
                )
                .order_by(BacktestRun.completed_at.desc())
                .first()
            )
            if bt:
                sharpe_ok  = bt.net_sharpe is not None and bt.net_sharpe >= BACKTEST_GATE["min_net_sharpe"]
                wr_ok      = bt.win_rate   is not None and bt.win_rate   >= BACKTEST_GATE["min_win_rate"]
                dd_ok      = bt.max_drawdown_pct is None or bt.max_drawdown_pct <= BACKTEST_GATE["max_drawdown_pct"]
                trades_ok  = bt.n_trades is not None and bt.n_trades >= BACKTEST_GATE["min_trades"]

                if sharpe_ok and wr_ok and dd_ok and trades_ok:
                    _transition_candidate(db, cand.id, "BACKTEST_DONE", "WFA_QUEUED",
                        f"Backtest gate passed: sharpe={bt.net_sharpe:.2f} wr={bt.win_rate:.2f} dd={bt.max_drawdown_pct}")
                    transitions.append({"candidate": cand.name, "from": "BACKTEST_DONE", "to": "WFA_QUEUED"})
                    logger.info("[quant_researcher] %s: BACKTEST_DONE → WFA_QUEUED", cand.name)
                else:
                    reasons = []
                    if not sharpe_ok:  reasons.append(f"sharpe={bt.net_sharpe:.2f}<{BACKTEST_GATE['min_net_sharpe']}")
                    if not wr_ok:      reasons.append(f"wr={bt.win_rate:.2f}<{BACKTEST_GATE['min_win_rate']}")
                    if not dd_ok:      reasons.append(f"dd={bt.max_drawdown_pct:.2f}>{BACKTEST_GATE['max_drawdown_pct']}")
                    if not trades_ok:  reasons.append(f"trades={bt.n_trades}<{BACKTEST_GATE['min_trades']}")
                    _transition_candidate(db, cand.id, "BACKTEST_DONE", "RETIRED",
                        "Backtest gate failed: " + ", ".join(reasons))
                    transitions.append({"candidate": cand.name, "from": "BACKTEST_DONE", "to": "RETIRED", "reason": ", ".join(reasons)})
                    flags.append(f"{cand.name} RETIRED (backtest): {', '.join(reasons)}")
                    logger.info("[quant_researcher] %s: BACKTEST_DONE → RETIRED (%s)", cand.name, reasons)

        # ── WFA_DONE → SHADOW_PAPER (gate check) ─────────────────────────────
        elif state == "WFA_DONE":
            wfa = (
                db.query(WfaRun)
                .filter(
                    WfaRun.candidate_id == cand.id,
                    WfaRun.status == "completed",
                )
                .order_by(WfaRun.completed_at.desc())
                .first()
            )
            if wfa:
                sharpe_ok = wfa.aggregate_oos_sharpe is not None and wfa.aggregate_oos_sharpe >= WFA_GATE["min_oos_sharpe"]
                pbo_ok    = wfa.pbo is None or wfa.pbo <= WFA_GATE["max_pbo"]
                wfe_ok    = wfa.wfe is None or wfa.wfe >= WFA_GATE["min_wfe"]

                if sharpe_ok and pbo_ok and wfe_ok:
                    _transition_candidate(db, cand.id, "WFA_DONE", "SHADOW_PAPER",
                        f"WFA gate passed: oos_sharpe={wfa.aggregate_oos_sharpe:.2f} pbo={wfa.pbo} wfe={wfa.wfe}")
                    transitions.append({"candidate": cand.name, "from": "WFA_DONE", "to": "SHADOW_PAPER"})
                    logger.info("[quant_researcher] %s: WFA_DONE → SHADOW_PAPER", cand.name)
                else:
                    reasons = []
                    if not sharpe_ok: reasons.append(f"oos_sharpe={wfa.aggregate_oos_sharpe:.2f}<{WFA_GATE['min_oos_sharpe']}")
                    if not pbo_ok:    reasons.append(f"pbo={wfa.pbo:.2f}>{WFA_GATE['max_pbo']}")
                    if not wfe_ok:    reasons.append(f"wfe={wfa.wfe:.2f}<{WFA_GATE['min_wfe']}")
                    _transition_candidate(db, cand.id, "WFA_DONE", "RETIRED",
                        "WFA gate failed: " + ", ".join(reasons))
                    transitions.append({"candidate": cand.name, "from": "WFA_DONE", "to": "RETIRED", "reason": ", ".join(reasons)})
                    flags.append(f"{cand.name} RETIRED (WFA): {', '.join(reasons)}")
                    logger.info("[quant_researcher] %s: WFA_DONE → RETIRED (%s)", cand.name, reasons)

    try:
        db.commit()
    except Exception as exc:
        logger.warning("[quant_researcher] commit failed: %s", exc)
        db.rollback()

    return {"transitions": transitions, "flags": flags}


def _pipeline_counts(db: Session) -> dict:
    """Return candidate counts by state."""
    try:
        rows = db.execute(text("""
            SELECT state, COUNT(*) as cnt
            FROM strategy_candidates
            GROUP BY state
        """)).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def _publish_heartbeat(db: Session, result: dict) -> None:
    try:
        db.execute(text("""
            INSERT INTO agent_messages (from_agent, channel, msg_type, subject, body, created_at)
            VALUES (:agent, :channel, :mtype, :subject, :body, :ts)
        """), {
            "agent":   "quant_researcher",
            "channel": "agent_heartbeats",
            "mtype":   "heartbeat",
            "subject": f"pipeline_scan:transitions={len(result.get('transitions', []))}",
            "body":    json.dumps(result),
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        db.commit()
    except Exception as exc:
        logger.warning("[quant_researcher] heartbeat publish failed: %s", exc)


def run_pipeline_scan(db: Session) -> dict:
    """Main entry point. Returns pipeline scan result."""
    started = datetime.now(timezone.utc)
    logger.info("[quant_researcher] Running pipeline scan")

    eval_result = _evaluate_pipeline(db)
    counts = _pipeline_counts(db)
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    result = {
        "transitions":   eval_result["transitions"],
        "flags":         eval_result["flags"],
        "pipeline":      counts,
        "elapsed_ms":    elapsed_ms,
        "scanned_at":    started.isoformat(),
    }

    _publish_heartbeat(db, result)

    # Discord post
    total      = sum(counts.values())
    shadow     = counts.get("SHADOW_PAPER", 0)
    wfa_done   = counts.get("WFA_DONE", 0)
    bt_done    = counts.get("BACKTEST_DONE", 0)
    promoted   = counts.get("PROMOTED", 0)
    trans_text = "\n".join(
        f"• {t['candidate']}: {t['from']} → {t['to']}" + (f" ⚠ {t.get('reason','')}" if t.get("reason") else "")
        for t in eval_result["transitions"]
    ) or "No transitions this cycle."

    embed = {
        "title":       f"📊 Pipeline Scan — {len(eval_result['transitions'])} transition(s)",
        "description": f"**{total} candidates total** · {shadow} shadow paper · {wfa_done} WFA done · {bt_done} backtest done · {promoted} promoted\n\n{trans_text}",
        "color":       0x818CF8,
        "footer":      {"text": f"Quant Researcher · {started.strftime('%Y-%m-%d %H:%M')} UTC · {elapsed_ms}ms"},
    }

    token, channel_id = _get_quant_channel()
    result["discord_posted"] = _post_discord(token, channel_id, embed)

    logger.info(
        "[quant_researcher] Done — transitions=%d elapsed_ms=%d",
        len(eval_result["transitions"]), elapsed_ms,
    )
    return result
