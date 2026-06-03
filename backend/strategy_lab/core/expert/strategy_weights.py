"""
Thompson sampling for online strategy reweighting.

Each strategy starts with base_weight = 1/N where N = total strategies.
After each trade, update weight based on win/loss (Beta distribution).

Thompson sampling: sample from Beta(wins+1, losses+1) for each strategy.
Normalize samples → weights. These weights used in ensemble voting.

Persists to StrategyWeight DB table. User can lock a weight (user_locked=True).
"""
from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)


def _beta_sample(wins: int, losses: int) -> float:
    """Sample from Beta(wins+1, losses+1) using the standard library."""
    # Beta distribution: shape parameters alpha=wins+1, beta=losses+1
    # Python random module: betavariate(alpha, beta)
    alpha = wins + 1
    beta = losses + 1
    try:
        return random.betavariate(alpha, beta)
    except Exception:
        # Fallback: return mean of the Beta distribution
        return alpha / (alpha + beta)


def _get_or_create_weight(profile_id: int, strategy_name: str, db):
    """Get or create a StrategyWeight row."""
    try:
        from app.db.models.bots import StrategyWeight
        row = (
            db.query(StrategyWeight)
            .filter(
                StrategyWeight.profile_id == profile_id,
                StrategyWeight.strategy_name == strategy_name,
            )
            .first()
        )
        if row is None:
            row = StrategyWeight(
                profile_id=profile_id,
                strategy_name=strategy_name,
                wins=0,
                losses=0,
                weight=1.0,  # will be normalized
                user_locked=False,
            )
            db.add(row)
            db.flush()
        return row
    except Exception as exc:
        logger.debug("[strategy_weights] StrategyWeight table not available: %s", exc)
        return None


def get_weights(
    profile_id: int,
    strategy_names: list[str],
    db,
) -> dict[str, float]:
    """Returns {strategy_name: weight} normalized to sum 1.0."""
    if not strategy_names:
        return {}

    rows = {}
    for name in strategy_names:
        row = _get_or_create_weight(profile_id, name, db)
        rows[name] = row

    try:
        db.commit()
    except Exception:
        db.rollback()

    # Thompson sampling: sample from Beta for each unlocked strategy
    samples: dict[str, float] = {}
    for name in strategy_names:
        row = rows.get(name)
        if row is None:
            samples[name] = 1.0  # fallback equal weight
            continue

        if getattr(row, "user_locked", False):
            # Use the stored weight directly for locked strategies
            samples[name] = getattr(row, "weight", 1.0) or 1.0
        else:
            wins = getattr(row, "wins", 0) or 0
            losses = getattr(row, "losses", 0) or 0
            samples[name] = _beta_sample(wins, losses)

    total = sum(samples.values())
    if total <= 0:
        # Fallback: equal weights
        n = len(strategy_names)
        return {name: 1.0 / n for name in strategy_names}

    normalized = {name: sample / total for name, sample in samples.items()}

    logger.debug(
        "[strategy_weights] profile=%d weights=%s",
        profile_id,
        {k: f"{v:.4f}" for k, v in normalized.items()},
    )
    return normalized


def record_trade_outcome(
    profile_id: int,
    strategy_name: str,
    won: bool,  # True if trade was profitable
    db,
) -> None:
    """Update StrategyWeight with new trade outcome."""
    row = _get_or_create_weight(profile_id, strategy_name, db)
    if row is None:
        return

    if getattr(row, "user_locked", False):
        logger.debug(
            "[strategy_weights] Strategy %s is user-locked, skipping outcome update",
            strategy_name,
        )
        return

    if won:
        row.wins = (getattr(row, "wins", 0) or 0) + 1
    else:
        row.losses = (getattr(row, "losses", 0) or 0) + 1

    try:
        db.commit()
        logger.debug(
            "[strategy_weights] Recorded %s outcome for %s (profile=%d): wins=%d losses=%d",
            "win" if won else "loss", strategy_name, profile_id,
            row.wins, row.losses,
        )
    except Exception as exc:
        logger.warning("[strategy_weights] Could not persist outcome: %s", exc)
        db.rollback()
