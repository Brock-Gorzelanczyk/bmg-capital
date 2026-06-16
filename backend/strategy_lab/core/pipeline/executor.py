"""
strategy_lab/core/pipeline/executor.py

Pipeline job executor — picks up BACKTEST_QUEUED / WFA_QUEUED rows and
runs them synchronously.  Intended to be called either:
  • from a FastAPI BackgroundTask (per-request, on-demand)
  • from the daily pipeline daemon in bot_scheduler.py

Never raises — all errors are caught and written to the job row's
error_message field so the API can surface them to the UI.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Promotion gate thresholds (must match scorer.py)
_BT_SHARPE_MIN_FOR_WFA = 0.0      # minimum gross Sharpe before WFA is worth running
_BT_TRADES_MIN_FOR_WFA = 30       # at least 30 trades in backtest
_WFA_PASS_WFE    = 0.50
_WFA_PASS_SHARPE = 0.75
_WFA_PASS_PBO    = 0.10
_WFA_PASS_DSR    = 0.0
_SHADOW_NET_SHARPE_MIN = 0.50
_SHADOW_DAYS_REQUIRED  = 63


# ── helpers ───────────────────────────────────────────────────────────────────

def _transition(db: Session, candidate, to_state: str, reason: str, triggered_by: str = "pipeline") -> None:
    from app.db.models.pipeline import CandidateStateHistory
    history = CandidateStateHistory(
        candidate_id=candidate.id,
        from_state=candidate.state,
        to_state=to_state,
        reason=reason,
        triggered_by=triggered_by,
    )
    candidate.state = to_state
    candidate.updated_at = datetime.now(timezone.utc)
    db.add(history)
    db.commit()
    logger.warning("[pipeline] %s → %s (%s)", candidate.name, to_state, reason)


def _shadow_entry_date(db: Session, candidate_id: int) -> Optional[datetime]:
    """Return the UTC datetime when this candidate entered SHADOW_PAPER, or None."""
    from app.db.models.pipeline import CandidateStateHistory
    row = (
        db.query(CandidateStateHistory)
        .filter(
            CandidateStateHistory.candidate_id == candidate_id,
            CandidateStateHistory.to_state == "SHADOW_PAPER",
        )
        .order_by(CandidateStateHistory.created_at.asc())
        .first()
    )
    return row.created_at if row else None


# ── Backtest executor ─────────────────────────────────────────────────────────

def execute_backtest(job_id: str, db: Session) -> None:
    """Run the backtest for the given BacktestRun job_id. Updates DB in-place."""
    from app.db.models.pipeline import BacktestRun, StrategyCandidate
    from strategy_lab.core.backtester import run_backtest

    run = db.query(BacktestRun).filter(BacktestRun.job_id == job_id).first()
    if not run:
        logger.error("[pipeline] backtest job_id=%s not found", job_id)
        return

    candidate = db.query(StrategyCandidate).filter(StrategyCandidate.id == run.candidate_id).first()
    if not candidate:
        logger.error("[pipeline] backtest job_id=%s has no candidate", job_id)
        return

    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()

    logger.warning("[pipeline] backtest starting: %s (job=%s)", candidate.name, job_id)
    try:
        params = json.loads(run.params_json or "{}") if run.params_json else {}
        start = run.start_date or "2020-01-01"
        end   = run.end_date   or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result = run_backtest(
            strategy_name=candidate.name,
            profile_config=params,
            start_date=start,
            end_date=end,
            capital=float(params.get("capital", 100_000)),
        )

        run.status            = "done"
        run.completed_at      = datetime.now(timezone.utc)
        run.gross_sharpe      = round(result.sharpe, 4)
        run.net_sharpe        = round(result.net_sharpe, 4)
        run.max_drawdown_pct  = round(result.max_drawdown_pct, 4)
        run.win_rate          = round(result.win_rate_pct / 100.0, 4)
        run.profit_factor     = round(result.profit_factor, 4)
        run.beta_spy          = round(result.beta_spy, 4)
        run.total_cost_pct    = round(result.total_cost_pct, 6)
        run.n_trades          = result.total_trades
        run.equity_curve_json = json.dumps(result.equity_curve)
        db.commit()

        _transition(db, candidate, "BACKTEST_DONE",
                    reason=f"net_sharpe={run.net_sharpe:.3f} n_trades={run.n_trades}")
        logger.warning("[pipeline] backtest done: %s sharpe=%.3f trades=%d",
                       candidate.name, result.net_sharpe, result.total_trades)

    except Exception as exc:
        logger.error("[pipeline] backtest failed: %s — %s", candidate.name, exc, exc_info=True)
        run.status        = "failed"
        run.completed_at  = datetime.now(timezone.utc)
        run.error_message = str(exc)[:2000]
        db.commit()
        _transition(db, candidate, "CANDIDATE",
                    reason=f"backtest failed: {str(exc)[:120]}")


# ── WFA executor ──────────────────────────────────────────────────────────────

def execute_wfa(job_id: str, db: Session) -> None:
    """Run walk-forward analysis for the given WfaRun job_id. Updates DB in-place."""
    from app.db.models.pipeline import WfaRun, BacktestRun, StrategyCandidate
    from strategy_lab.core.backtester import make_wfa_strategy_fn, _download, _get_universe, _load_module, _WARMUP_DAYS
    from strategy_lab.core.walk_forward.engine import run_walk_forward

    run = db.query(WfaRun).filter(WfaRun.job_id == job_id).first()
    if not run:
        logger.error("[pipeline] WFA job_id=%s not found", job_id)
        return

    candidate = db.query(StrategyCandidate).filter(StrategyCandidate.id == run.candidate_id).first()
    if not candidate:
        logger.error("[pipeline] WFA job_id=%s has no candidate", job_id)
        return

    run.status     = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()

    logger.warning("[pipeline] WFA starting: %s (job=%s)", candidate.name, job_id)
    try:
        is_years      = run.is_years or 5.0
        oos_years     = run.oos_years or 1.0
        embargo_days  = run.embargo_days or 21
        total_years   = is_years + oos_years + embargo_days / 252.0

        module = _load_module(candidate.name)
        universe = _get_universe(module, {})
        start = (datetime.now(timezone.utc) - timedelta(days=int(total_years * 365) + _WARMUP_DAYS * 2)).strftime("%Y-%m-%d")
        end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        price_data = _download(universe, start, end)
        if not price_data:
            raise RuntimeError(f"No price data for universe {universe}")

        import pandas as pd
        spy_or_first = next(iter(price_data.values()))
        bars_df = spy_or_first.copy()
        bars_df.columns = [c.lower() for c in bars_df.columns]
        bars_df = bars_df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})

        strategy_fn = make_wfa_strategy_fn(candidate.name, universe=universe, profile_config={})

        # Default param grid: just the default params (single point)
        param_grid_raw = getattr(module, "CANDIDATE_CONFIG", {}).get("param_grid")
        if param_grid_raw and isinstance(param_grid_raw, list):
            param_grid = param_grid_raw
        else:
            param_grid = [{}]

        wfa = run_walk_forward(
            strategy_fn=strategy_fn,
            bars=bars_df,
            param_grid=param_grid,
            strategy_name=candidate.name,
            is_years=is_years,
            oos_years=oos_years,
            embargo_days=embargo_days,
        )

        run.status               = "done"
        run.completed_at         = datetime.now(timezone.utc)
        run.wfe                  = round(wfa.wfe, 4)
        run.pbo                  = round(wfa.pbo, 4)
        run.dsr                  = round(wfa.dsr, 4)
        run.aggregate_oos_sharpe = round(wfa.aggregate_oos_sharpe, 4)
        run.aggregate_is_sharpe  = round(wfa.aggregate_is_sharpe, 4)
        run.n_walks              = len(wfa.walks)
        run.walks_json = json.dumps([
            {
                "walk_id": w.walk_id,
                "is_start": str(w.is_start.date()),
                "is_end": str(w.is_end.date()),
                "oos_start": str(w.oos_start.date()),
                "oos_end": str(w.oos_end.date()),
                "is_sharpe": round(w.is_sharpe, 4),
                "oos_sharpe": round(w.oos_sharpe, 4),
                "wfe": round(w.wfe, 4),
                "n_is_trades": w.n_is_trades,
                "n_oos_trades": w.n_oos_trades,
            }
            for w in wfa.walks
        ])
        db.commit()

        # Evaluate gate
        passes_wfe    = wfa.wfe    >= _WFA_PASS_WFE
        passes_sharpe = wfa.aggregate_oos_sharpe >= _WFA_PASS_SHARPE
        passes_pbo    = wfa.pbo    <= _WFA_PASS_PBO
        passes_dsr    = wfa.dsr    >= _WFA_PASS_DSR

        if passes_wfe and passes_sharpe and passes_pbo and passes_dsr:
            _transition(db, candidate, "WFA_DONE",
                        reason=f"wfe={wfa.wfe:.3f} oos_sharpe={wfa.aggregate_oos_sharpe:.3f} pbo={wfa.pbo:.3f}")
        else:
            failures = []
            if not passes_wfe:    failures.append(f"wfe={wfa.wfe:.3f}<{_WFA_PASS_WFE}")
            if not passes_sharpe: failures.append(f"oos_sharpe={wfa.aggregate_oos_sharpe:.3f}<{_WFA_PASS_SHARPE}")
            if not passes_pbo:    failures.append(f"pbo={wfa.pbo:.3f}>{_WFA_PASS_PBO}")
            if not passes_dsr:    failures.append(f"dsr={wfa.dsr:.3f}<{_WFA_PASS_DSR}")
            _transition(db, candidate, "BACKTEST_DONE",
                        reason=f"WFA gates failed: {'; '.join(failures)}")

        logger.warning("[pipeline] WFA done: %s wfe=%.3f oos_sharpe=%.3f pbo=%.3f",
                       candidate.name, wfa.wfe, wfa.aggregate_oos_sharpe, wfa.pbo)

    except Exception as exc:
        logger.error("[pipeline] WFA failed: %s — %s", candidate.name, exc, exc_info=True)
        run.status        = "failed"
        run.completed_at  = datetime.now(timezone.utc)
        run.error_message = str(exc)[:2000]
        db.commit()
        _transition(db, candidate, "BACKTEST_DONE", reason=f"WFA failed: {str(exc)[:120]}")


# ── Pipeline advancement daemon ───────────────────────────────────────────────

def advance_pipeline(db: Session) -> dict:
    """
    Advance all candidates one step through the pipeline.
    Called by the daily 2:30 AM ET scheduler job.

    Returns a summary dict with counts for each action taken.
    """
    from app.db.models.pipeline import StrategyCandidate, BacktestRun, WfaRun
    import uuid

    summary = {
        "backtests_started": 0,
        "wfas_started": 0,
        "shadow_started": 0,
        "promoted": 0,
        "retired_shadow_fail": 0,
    }

    candidates = db.query(StrategyCandidate).filter(
        StrategyCandidate.state.notin_(["RETIRED", "PROMOTED"])
    ).all()

    for c in candidates:
        try:
            # ── CANDIDATE → run backtest ──────────────────────────────────
            if c.state == "CANDIDATE":
                # Only start one if no queued/running/done run exists
                existing = db.query(BacktestRun).filter(
                    BacktestRun.candidate_id == c.id,
                    BacktestRun.status.in_(["queued", "running", "done"]),
                ).first()
                if not existing:
                    job_id = str(uuid.uuid4())
                    from datetime import date
                    today = date.today()
                    run = BacktestRun(
                        candidate_id=c.id,
                        job_id=job_id,
                        status="queued",
                        start_date="2020-01-01",
                        end_date=today.isoformat(),
                        params_json="{}",
                    )
                    db.add(run)
                    _transition(db, c, "BACKTEST_QUEUED", reason="pipeline daemon auto-enqueue")
                    db.commit()
                    execute_backtest(job_id, db)
                    summary["backtests_started"] += 1

            # ── BACKTEST_DONE → run WFA if BT passes initial filter ───────
            elif c.state == "BACKTEST_DONE":
                latest_bt = (
                    db.query(BacktestRun)
                    .filter(BacktestRun.candidate_id == c.id, BacktestRun.status == "done")
                    .order_by(BacktestRun.completed_at.desc())
                    .first()
                )
                if not latest_bt:
                    continue
                if (latest_bt.gross_sharpe or 0) < _BT_SHARPE_MIN_FOR_WFA:
                    _transition(db, c, "RETIRED", reason=f"BT Sharpe {latest_bt.gross_sharpe:.3f} below floor")
                    continue
                if (latest_bt.n_trades or 0) < _BT_TRADES_MIN_FOR_WFA:
                    _transition(db, c, "RETIRED", reason=f"Too few trades: {latest_bt.n_trades}")
                    continue
                # Enqueue WFA
                existing_wfa = db.query(WfaRun).filter(
                    WfaRun.candidate_id == c.id,
                    WfaRun.status.in_(["queued", "running", "done"]),
                ).first()
                if not existing_wfa:
                    job_id = str(uuid.uuid4())
                    run = WfaRun(
                        candidate_id=c.id,
                        job_id=job_id,
                        status="queued",
                        is_years=5.0,
                        oos_years=1.0,
                        embargo_days=21,
                    )
                    db.add(run)
                    _transition(db, c, "WFA_QUEUED", reason="pipeline daemon auto-enqueue")
                    db.commit()
                    execute_wfa(job_id, db)
                    summary["wfas_started"] += 1

            # ── WFA_DONE → enter shadow paper ────────────────────────────
            elif c.state == "WFA_DONE":
                _transition(db, c, "SHADOW_PAPER", reason="all WFA gates passed — 63-day shadow observation begins")
                summary["shadow_started"] += 1

            # ── SHADOW_PAPER → check 63-day window ───────────────────────
            elif c.state == "SHADOW_PAPER":
                shadow_start = _shadow_entry_date(db, c.id)
                if shadow_start is None:
                    continue
                shadow_days = (datetime.now(timezone.utc) - shadow_start.replace(tzinfo=timezone.utc)).days
                if shadow_days < _SHADOW_DAYS_REQUIRED:
                    logger.info("[pipeline] %s shadow day %d / %d", c.name, shadow_days, _SHADOW_DAYS_REQUIRED)
                    continue

                # Fetch shadow trades for net Sharpe estimate
                from app.db.models.pipeline import BacktestRun
                latest_bt = (
                    db.query(BacktestRun)
                    .filter(BacktestRun.candidate_id == c.id, BacktestRun.status == "done")
                    .order_by(BacktestRun.completed_at.desc())
                    .first()
                )
                shadow_net_sharpe = float(getattr(latest_bt, "net_sharpe", 0) or 0)

                if shadow_net_sharpe >= _SHADOW_NET_SHARPE_MIN:
                    _transition(db, c, "PROMOTED",
                                reason=f"shadow complete: {shadow_days}d, net_sharpe={shadow_net_sharpe:.3f}")
                    c.promoted_at = datetime.now(timezone.utc)
                    db.commit()
                    summary["promoted"] += 1
                    logger.warning("[pipeline] PROMOTED: %s after %d shadow days", c.name, shadow_days)
                else:
                    _transition(db, c, "RETIRED",
                                reason=f"shadow failed: net_sharpe={shadow_net_sharpe:.3f}<{_SHADOW_NET_SHARPE_MIN}")
                    summary["retired_shadow_fail"] += 1

        except Exception as exc:
            logger.error("[pipeline] advance_pipeline error for %s: %s", c.name, exc, exc_info=True)

    logger.warning("[pipeline] daemon run complete: %s", summary)
    return summary
