"""Daily IC metrics rollup — runs at 2:30 AM ET after the stats rollup."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _post_ic_alert_to_discord(strategy_name: str, old_cls: str, new_cls: str, ic: float, p_val: float, n: int, rec: str) -> None:
    """Post a classification change alert to #sentinel-ops."""
    try:
        from app.services.discord_notifier import send_sentinel_embed
        emoji = "🟡" if new_cls in ("MARGINAL", "NOISE") else "🔴" if new_cls == "INVERTED" else "🟢"
        send_sentinel_embed(
            title=f"{emoji} Signal Quality Change: {strategy_name}",
            description=(
                f"**{old_cls} → {new_cls}**\n"
                f"IC 63d: {ic:+.4f} (p={p_val:.3f}, n={n})\n"
                f"Recommendation: **{rec}**"
            ),
            color=0xfbbf24 if new_cls in ("MARGINAL", "NOISE") else 0xf43f5e if new_cls == "INVERTED" else 0x22c55e,
        )
    except Exception as exc:
        logger.debug("IC Discord post failed (non-fatal): %s", exc)


def run() -> None:
    """Compute IC for all strategies with signals in last 90 days."""
    from strategy_lab.core.ml.ic_tracker import compute_strategy_ic, WINDOWS
    from app.db.models.ic_metrics import SignalIcMetric, SignalIcAlert

    db = SessionLocal()
    today = date.today()

    try:
        # Get all distinct strategy names with signals in last 90 days
        rows = db.execute(text("""
            SELECT DISTINCT COALESCE(s.strategy, p.name) as strategy_name
            FROM bot_signals s
            JOIN bot_allocations a ON s.allocation_id = a.id
            JOIN bot_profiles p ON a.profile_id = p.id
            WHERE s.ts >= date('now', '-90 days')
              AND s.side IN ('buy', 'sell')
        """)).fetchall()

        strategy_names = [r[0] for r in rows if r[0]]
        if not strategy_names:
            logger.info("compute_ic_metrics: no strategies with recent signals")
            return

        logger.info("compute_ic_metrics: computing IC for %d strategies, windows=%s", len(strategy_names), WINDOWS)

        for strategy_name in strategy_names:
            for window in WINDOWS:
                try:
                    result = compute_strategy_ic(strategy_name, window_days=window, end_date=today, db=db)

                    # UPSERT
                    existing = db.query(SignalIcMetric).filter(
                        SignalIcMetric.strategy_name == strategy_name,
                        SignalIcMetric.snapshot_date == today,
                        SignalIcMetric.window_days == window,
                    ).first()

                    old_cls = existing.classification if existing else None

                    if existing:
                        existing.n_signals           = result.n_signals
                        existing.ic_spearman         = result.ic_spearman
                        existing.ic_pearson          = result.ic_pearson
                        existing.ic_p_value          = result.ic_p_value
                        existing.ic_t_stat           = result.ic_t_stat
                        existing.direction_hit_rate  = result.direction_hit_rate
                        existing.confidence_correlation = result.confidence_correlation
                        existing.classification      = result.classification
                        existing.recommendation      = result.recommendation
                    else:
                        row = SignalIcMetric(
                            strategy_name=strategy_name,
                            snapshot_date=today,
                            window_days=window,
                            n_signals=result.n_signals,
                            ic_spearman=result.ic_spearman,
                            ic_pearson=result.ic_pearson,
                            ic_p_value=result.ic_p_value,
                            ic_t_stat=result.ic_t_stat,
                            direction_hit_rate=result.direction_hit_rate,
                            confidence_correlation=result.confidence_correlation,
                            classification=result.classification,
                            recommendation=result.recommendation,
                        )
                        db.add(row)

                    db.commit()

                    # Check for classification change on 63d window
                    if window == 63 and old_cls and old_cls != result.classification:
                        alert = SignalIcAlert(
                            strategy_name=strategy_name,
                            ic_value=result.ic_spearman,
                            classification=result.classification,
                            previous_classification=old_cls,
                        )
                        db.add(alert)
                        db.commit()

                        if result.classification in ("NOISE", "INVERTED", "MARGINAL"):
                            _post_ic_alert_to_discord(
                                strategy_name, old_cls, result.classification,
                                result.ic_spearman, result.ic_p_value,
                                result.n_signals, result.recommendation,
                            )

                except Exception as exc:
                    logger.warning("IC compute failed for %s/%dd: %s", strategy_name, window, exc)
                    db.rollback()

        logger.info("compute_ic_metrics: done for %d strategies", len(strategy_names))

    except Exception as exc:
        logger.error("compute_ic_metrics run() failed: %s", exc, exc_info=True)
    finally:
        db.close()
