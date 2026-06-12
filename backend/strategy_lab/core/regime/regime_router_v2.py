"""Playbook regime router — 6-regime composite detector with YAML routing matrix.

Composite signal weights (per spec):
  VIX level:            40%
  SPX vs 200MA:         30%
  HY spread 30d RoC:    20%  (proxy: HYG/IEF ratio)
  VIX term structure:   10%  (proxy: VIX/VIX3M)

6 regimes: BULL_TRENDING, BEAR_TRENDING, CHOPPY, CRISIS, LOW_VOL, RECOVERY
Persistence: 3 consecutive days required before confirming a regime switch.

Feature flag: REGIME_ROUTING_ENABLED (default OFF).
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

REGIME_ROUTING_ENABLED = os.getenv("REGIME_ROUTING_ENABLED", "false").lower() == "true"

_MATRIX_PATH = Path(__file__).parent / "routing_matrix.yaml"
_ROUTING_MATRIX: dict | None = None


def _load_routing_matrix() -> dict:
    global _ROUTING_MATRIX
    if _ROUTING_MATRIX is None:
        try:
            with open(_MATRIX_PATH) as f:
                data = yaml.safe_load(f)
            _ROUTING_MATRIX = data.get("regimes", {})
        except Exception as exc:
            logger.warning("Could not load routing_matrix.yaml: %s", exc)
            _ROUTING_MATRIX = {}
    return _ROUTING_MATRIX


# ── Regime thresholds ─────────────────────────────────────────────────────────

_VIX_LOW_VOL   = 13.0   # VIX < 13 → LOW_VOL signal
_VIX_CALM      = 18.0   # VIX < 18 → calm
_VIX_ELEVATED  = 25.0   # VIX 18-25 → elevated
_VIX_STRESS    = 30.0   # VIX > 30 → stress; > 40 → CRISIS


@dataclass
class RegimeReading:
    regime: str                   # confirmed (after persistence filter)
    raw_regime: str               # before persistence filter
    confidence: float
    vix_score: float
    spx_score: float
    hy_score: float
    vts_score: float
    vix_level: float | None
    spx_vs_200ma: float | None
    hy_proxy: float | None
    vix_ts_slope: float | None


def _score_vix(vix: float) -> tuple[str, float]:
    """Map VIX to a regime signal and score (0–1)."""
    if vix > 40:
        return "crisis", 1.0
    if vix > _VIX_STRESS:
        return "stress", min(1.0, (vix - _VIX_STRESS) / 20.0)
    if vix > _VIX_ELEVATED:
        return "elevated", (vix - _VIX_ELEVATED) / (_VIX_STRESS - _VIX_ELEVATED)
    if vix > _VIX_CALM:
        return "normal", 0.5
    if vix > _VIX_LOW_VOL:
        return "calm", 0.3
    return "low_vol", 0.0


def _score_spx_vs_200ma(ratio: float) -> str:
    """SPY close / 200MA ratio → trend label."""
    if ratio > 1.05:
        return "bull"
    if ratio > 1.0:
        return "slight_bull"
    if ratio > 0.95:
        return "slight_bear"
    return "bear"


def _score_hy_spread(hy_roc_30d: float) -> str:
    """HY spread 30d rate-of-change: positive = spreads widening (risk-off)."""
    if hy_roc_30d > 0.15:
        return "widening_fast"
    if hy_roc_30d > 0.05:
        return "widening"
    if hy_roc_30d < -0.10:
        return "tightening"
    return "stable"


def _score_vix_ts(slope: float) -> str:
    """VIX term structure slope = VIX/VIX3M. > 1 = inverted (backwardation = fear)."""
    if slope > 1.10:
        return "inverted_hard"
    if slope > 1.0:
        return "inverted"
    if slope < 0.90:
        return "steep_contango"
    return "contango"


def classify_regime(
    vix_level: float,
    spx_vs_200ma: float | None = None,
    hy_roc_30d: float | None = None,
    vix_ts_slope: float | None = None,
) -> tuple[str, float]:
    """Return (regime_label, confidence) using 4-signal weighted composite.

    Weights: VIX 40%, SPX vs 200MA 30%, HY spread 20%, VIX TS 10%.
    """
    vix_label, vix_score = _score_vix(vix_level)
    spx_label = _score_spx_vs_200ma(spx_vs_200ma) if spx_vs_200ma is not None else "slight_bull"
    hy_label  = _score_hy_spread(hy_roc_30d)       if hy_roc_30d  is not None else "stable"
    vts_label = _score_vix_ts(vix_ts_slope)         if vix_ts_slope is not None else "contango"

    # ── CRISIS — VIX > 40 OR (stress + inverted TS + widening spreads) ───────
    if vix_level > 40 or (vix_label == "stress" and vts_label in ("inverted", "inverted_hard") and hy_label in ("widening", "widening_fast")):
        return "CRISIS", 0.95

    # ── LOW_VOL — VIX < 13 AND in contango AND bull trend ────────────────────
    if vix_label == "low_vol" and vts_label in ("contango", "steep_contango") and spx_label in ("bull", "slight_bull"):
        return "LOW_VOL", 0.85

    # ── RECOVERY — VIX elevated but falling (contango), SPX turning up ───────
    if vix_label in ("elevated", "normal") and vts_label in ("contango", "steep_contango") and spx_label in ("slight_bull", "bull") and hy_label in ("tightening", "stable"):
        return "RECOVERY", 0.75

    # ── BULL_TRENDING — calm VIX, bull trend, stable/tightening credit ───────
    if vix_label in ("calm", "normal") and spx_label in ("bull", "slight_bull") and hy_label in ("stable", "tightening"):
        return "BULL_TRENDING", 0.80

    # ── BEAR_TRENDING — elevated/stress VIX, SPX below 200MA, widening credit
    if spx_label in ("slight_bear", "bear") and hy_label in ("widening", "widening_fast"):
        return "BEAR_TRENDING", 0.80

    # ── CHOPPY — default (mean-reverting environment) ─────────────────────────
    confidence = 0.60 if vts_label == "contango" else 0.50
    return "CHOPPY", confidence


def get_multiplier(strategy_type: str, regime: str) -> float:
    """Return allocation multiplier from routing_matrix.yaml.

    Returns 1.0 if regime or strategy_type not found.
    Feature-flagged: returns 1.0 if REGIME_ROUTING_ENABLED is False.
    """
    if not REGIME_ROUTING_ENABLED:
        return 1.0
    matrix = _load_routing_matrix()
    regime_row = matrix.get(regime, {})
    return float(regime_row.get(strategy_type, regime_row.get("other", 1.0)))


# ── Persistence filter (3 consecutive days, 2 for CRISIS) ────────────────────

class RegimePersistenceFilterV2:
    """Debounce regime flips — 3 consecutive days required for normal transitions.
    CRISIS transitions require only 2 consecutive days (faster entry into safety mode).
    """
    CRISIS_THRESHOLD = 2
    NORMAL_THRESHOLD = 3

    def __init__(self) -> None:
        self.current_regime: str = "CHOPPY"
        self.pending_regime: str | None = None
        self.consecutive_days: int = 0
        self.days_in_current: int = 0

    def update(self, raw_regime: str) -> str:
        """Feed daily raw regime; return confirmed regime."""
        if raw_regime == self.current_regime:
            self.pending_regime = None
            self.consecutive_days = 0
            self.days_in_current += 1
            return self.current_regime

        if raw_regime == self.pending_regime:
            self.consecutive_days += 1
        else:
            self.pending_regime = raw_regime
            self.consecutive_days = 1

        threshold = self.CRISIS_THRESHOLD if raw_regime == "CRISIS" else self.NORMAL_THRESHOLD
        if self.consecutive_days >= threshold:
            logger.info("RegimePersistenceFilterV2: %r → %r after %d days",
                        self.current_regime, raw_regime, self.consecutive_days)
            self.current_regime = raw_regime
            self.pending_regime = None
            self.consecutive_days = 0
            self.days_in_current = 1

        return self.current_regime

    def force_set(self, regime: str) -> None:
        self.current_regime = regime
        self.pending_regime = None
        self.consecutive_days = 0
        self.days_in_current = 1


# ── Daily snapshot persistence ────────────────────────────────────────────────

def persist_regime_snapshot(
    db,
    regime: str,
    raw_regime: str,
    confidence: float,
    vix_level: float | None = None,
    spx_vs_200ma: float | None = None,
    hy_proxy: float | None = None,
    vix_ts_slope: float | None = None,
    signals_json: str | None = None,
    snapshot_date: date | None = None,
) -> None:
    """Upsert today's regime snapshot to regime_snapshots table."""
    today = snapshot_date or date.today()
    try:
        from sqlalchemy import text as _text
        db.execute(_text("""
            INSERT INTO regime_snapshots
                (snapshot_date, regime, raw_regime, confidence, vix_level,
                 spx_vs_200ma, hy_spread_proxy, vix_ts_slope, signals_json, created_at)
            VALUES
                (:d, :regime, :raw, :conf, :vix, :spx, :hy, :vts, :sig, :now)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                regime        = excluded.regime,
                raw_regime    = excluded.raw_regime,
                confidence    = excluded.confidence,
                vix_level     = excluded.vix_level,
                spx_vs_200ma  = excluded.spx_vs_200ma,
                hy_spread_proxy = excluded.hy_spread_proxy,
                vix_ts_slope  = excluded.vix_ts_slope,
                signals_json  = excluded.signals_json
        """), {
            "d": today.isoformat(), "regime": regime, "raw": raw_regime,
            "conf": confidence, "vix": vix_level, "spx": spx_vs_200ma,
            "hy": hy_proxy, "vts": vix_ts_slope, "sig": signals_json,
            "now": datetime.now(timezone.utc).isoformat(),
        })
        db.commit()
    except Exception as exc:
        logger.warning("persist_regime_snapshot failed: %s", exc)


def get_current_regime(db) -> dict:
    """Read the most recent confirmed regime from DB. Falls back to CHOPPY."""
    try:
        from sqlalchemy import text as _text
        row = db.execute(_text(
            "SELECT regime, confidence, snapshot_date, vix_level FROM regime_snapshots"
            " ORDER BY snapshot_date DESC LIMIT 1"
        )).first()
        if row:
            today = date.today()
            snap_date = date.fromisoformat(str(row[2])) if row[2] else None
            days_ago = (today - snap_date).days if snap_date else 999
            return {
                "regime": row[0],
                "confidence": row[1],
                "snapshot_date": str(row[2]),
                "days_in_regime": _count_days_in_regime(db, row[0]),
                "days_since_snapshot": days_ago,
                "vix_level": row[3],
            }
    except Exception as exc:
        logger.warning("get_current_regime failed: %s", exc)
    return {"regime": "CHOPPY", "confidence": 0.5, "snapshot_date": None, "days_in_regime": 0}


def _count_days_in_regime(db, regime: str) -> int:
    """Count consecutive trailing days with the same regime."""
    try:
        from sqlalchemy import text as _text
        rows = db.execute(_text(
            "SELECT regime FROM regime_snapshots ORDER BY snapshot_date DESC LIMIT 30"
        )).fetchall()
        count = 0
        for row in rows:
            if row[0] == regime:
                count += 1
            else:
                break
        return count
    except Exception:
        return 0
