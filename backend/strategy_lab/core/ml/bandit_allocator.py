"""
Thompson Sampling Bandit Allocator — Priority 6.

Multi-armed bandit for weekly capital reallocation across bot profiles.
Each bot is an arm; reward = weekly Sharpe ratio.  Thompson sampling
draws from Beta(alpha, beta) posteriors and allocates proportionally.

Integrated via:
  POST /api/strategy-lab/rebalance  — triggers allocation update
  Weekly cron in Railway cron config

Usage
-----
allocator = BanditAllocator(arms=["stock_day", "stock_st", "crypto_lt"])
allocator.update("stock_day", reward=0.8)   # after weekly pnl
weights = allocator.allocate()              # {"stock_day": 0.45, ...}
"""
from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STATE_DIR = Path(__file__).parent.parent.parent / "ml_models"
_STATE_DIR.mkdir(parents=True, exist_ok=True)
_STATE_PATH = _STATE_DIR / "bandit_state.json"

# Reward normalization: Sharpe < -1 → 0.0, Sharpe > 2 → 1.0
_SHARPE_MIN = -1.0
_SHARPE_MAX = 2.0


def _sharpe_to_reward(sharpe: float) -> float:
    """Normalize weekly Sharpe into [0, 1] for Beta distribution update."""
    clipped = max(_SHARPE_MIN, min(_SHARPE_MAX, sharpe))
    return (clipped - _SHARPE_MIN) / (_SHARPE_MAX - _SHARPE_MIN)


class BanditAllocator:
    """
    Thompson Sampling with Beta(alpha, beta) priors per arm.

    Each reward observation is treated as a Bernoulli trial:
    reward ∈ [0,1] → fractional success.  We add (reward) to alpha
    and (1 - reward) to beta, which is mathematically equivalent to
    a continuous Beta update.
    """

    def __init__(
        self,
        arms: list[str],
        alpha_init: float = 1.0,
        beta_init: float = 1.0,
    ) -> None:
        self.arms = arms
        self._state: dict[str, dict[str, float]] = {
            arm: {"alpha": alpha_init, "beta": beta_init, "n": 0}
            for arm in arms
        }
        self._load()

    # ── Public API ──────────────────────────────────────────────────────────

    def update(self, arm: str, sharpe: float) -> None:
        """Record a weekly Sharpe observation for one arm."""
        if arm not in self._state:
            logger.warning("[bandit] unknown arm: %s", arm)
            return
        reward = _sharpe_to_reward(sharpe)
        self._state[arm]["alpha"] += reward
        self._state[arm]["beta"] += (1.0 - reward)
        self._state[arm]["n"] += 1
        self._save()
        logger.info("[bandit] arm=%s sharpe=%.3f reward=%.3f alpha=%.2f beta=%.2f",
                    arm, sharpe, reward,
                    self._state[arm]["alpha"], self._state[arm]["beta"])

    def allocate(self, n_samples: int = 5000) -> dict[str, float]:
        """
        Draw from each arm's posterior and compute mean allocation weights.

        Parameters
        ----------
        n_samples : Monte Carlo samples per arm for smooth weight estimation

        Returns
        -------
        dict mapping arm → weight (sums to 1.0)
        """
        draws: dict[str, float] = {}
        for arm in self.arms:
            a = self._state[arm]["alpha"]
            b = self._state[arm]["beta"]
            # Thompson draw: sample the probability of success
            draw = random.betavariate(a, b)
            draws[arm] = draw

        total = sum(draws.values())
        if total == 0:
            n = len(self.arms)
            return {arm: 1.0 / n for arm in self.arms}

        weights = {arm: round(v / total, 4) for arm, v in draws.items()}
        logger.info("[bandit] allocation: %s", weights)
        return weights

    def allocate_stable(self, n_samples: int = 5000) -> dict[str, float]:
        """
        Smooth allocation by averaging over n_samples Thompson draws.
        More stable than single draw — use for actual capital decisions.
        """
        accum: dict[str, float] = {arm: 0.0 for arm in self.arms}
        for _ in range(n_samples):
            draws = {arm: random.betavariate(
                self._state[arm]["alpha"], self._state[arm]["beta"]
            ) for arm in self.arms}
            total = sum(draws.values()) or 1.0
            for arm in self.arms:
                accum[arm] += draws[arm] / total

        return {arm: round(accum[arm] / n_samples, 4) for arm in self.arms}

    def state_summary(self) -> list[dict]:
        """Return posterior stats for each arm (for API response)."""
        out = []
        for arm in self.arms:
            a = self._state[arm]["alpha"]
            b = self._state[arm]["beta"]
            mean = a / (a + b)
            # Mode of Beta distribution
            mode = (a - 1) / (a + b - 2) if (a > 1 and b > 1) else (0.0 if a <= 1 else 1.0)
            out.append({
                "arm": arm,
                "alpha": round(a, 3),
                "beta": round(b, 3),
                "mean_reward": round(mean, 4),
                "mode_reward": round(mode, 4),
                "n_observations": int(self._state[arm]["n"]),
            })
        return out

    def reset_arm(self, arm: str) -> None:
        if arm in self._state:
            self._state[arm] = {"alpha": 1.0, "beta": 1.0, "n": 0}
            self._save()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            with open(_STATE_PATH, "w") as f:
                json.dump({"arms": self.arms, "state": self._state}, f)
        except Exception as exc:
            logger.warning("[bandit] save error: %s", exc)

    def _load(self) -> None:
        if not _STATE_PATH.exists():
            return
        try:
            with open(_STATE_PATH) as f:
                saved = json.load(f)
            # Only restore state for arms that exist in current config
            for arm in self.arms:
                if arm in saved.get("state", {}):
                    self._state[arm] = saved["state"][arm]
        except Exception as exc:
            logger.warning("[bandit] load error: %s", exc)


# ── Default singleton ─────────────────────────────────────────────────────────

_DEFAULT_ARMS = ["stock_day", "stock_st", "stock_lt", "crypto_lt", "options_theta"]
_allocator: Optional[BanditAllocator] = None


def get_allocator(arms: Optional[list[str]] = None) -> BanditAllocator:
    global _allocator
    if _allocator is None or (arms is not None and set(arms) != set(_allocator.arms)):
        _allocator = BanditAllocator(arms or _DEFAULT_ARMS)
    return _allocator
