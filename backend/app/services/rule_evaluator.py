"""Rule evaluator — auto-scores every confluence pick against decision rules.

**Source of truth:** `~/Documents/BMG-Capital-Vault/research/decision-rules.md`

This service takes a ConfluencePick instance and returns a compliance record
JSON that names each rule and its verdict. The record is stored on the pick
BEFORE the outcome is known, per the anti-hindsight discipline in the vault.

**Verdicts:**
  SATISFIED   — rule condition met (positive for SELECT, safe for REJECT)
  VIOLATED    — rule condition failed (negative for SELECT, unsafe for REJECT)
  APPLIED     — HAIRCUT rule was applied with a numeric factor
  UNTESTABLE  — required data source not available (labeled, not silently skipped)
  N/A         — rule doesn't apply to this pick type

**Rules NOT evaluated per-pick** (they operate at strategy-design or fund level,
not at individual pick time):
  RULE-M01 (DSR) — evaluated once per new signal added to framework
  RULE-M05 (N>=20) — scorecard-level, not pick-level
  RULE-D01..D06  — strategy-design gates checked BEFORE code ships

Rules evaluated per-pick:
  RULE-M02 (McLean-Pontiff haircut) — APPLIED based on framework pub year
  RULE-M03 (arb-cost haircut)       — APPLIED based on universe liquidity
  RULE-M04 (family diversity)       — SATISFIED / VIOLATED based on signal families
  RULE-S01 (sentiment sizing)       — UNTESTABLE until BW ETL ships
  RULE-S02 (short in high sent)     — UNTESTABLE until BW ETL ships
  RULE-S03 (Item 1A weighting)      — UNTESTABLE until sub-section signal ships
  RULE-S04 (cross-family confluence) — SATISFIED / VIOLATED
  RULE-S05 (ORB stocks-in-play)     — N/A for confluence picks (day-trading rule)
  RULE-S06 (Faber SMA gate)         — SATISFIED / VIOLATED based on SPX vs 10mo SMA
  RULE-S07 (vol-managed sizing)     — UNTESTABLE (BMG uses fixed size for confluence)
  RULE-H01 (insider alpha haircut)  — APPLIED
  RULE-H02 (VW expectation)         — APPLIED (used automatically in size math)
  RULE-H03 (short alpha halve)      — N/A (confluence picks are long-only currently)

As data sources come online, UNTESTABLE rules become evaluable — no schema
change needed. The evaluator is versioned via RULES_VERSION so scorecard
comparisons across versions can be filtered.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RULES_VERSION = "2026-08-30-v1"

# ─── Signal family map (needed by RULE-M04, RULE-S04) ─────────────
# Each ConfluencePick signal is tagged by family for cross-family diversity checks.
SIGNAL_FAMILIES = {
    "insider_cluster": "insider",
    "short_surprise_dir": "market",   # short-interest is price/volume-derived
    "analyst_revisions_dir": "analyst",
    "fundamental_momentum": "fundamental",
    "inst_13f_net_add": "institutional",
}

# ─── Framework pub-year lookup (needed by RULE-M02 McLean-Pontiff haircut) ──
# Year the underlying academic source was published. Used to compute time-decay
# per McLean-Pontiff 2016 (26% haircut yrs 0-2, 45-50% yrs 3-5, 58% yrs 5+).
FRAMEWORK_SIGNAL_PUB_YEAR = {
    "insider_cluster": 2012,       # Cohen-Malloy-Pomorski JF
    "short_surprise_dir": 2015,    # Hong-Li-Ni DTC / SR literature
    "analyst_revisions_dir": 2000, # analyst revision anomalies well-established
    "fundamental_momentum": 2010,  # Novy-Marx profitability / Chen-Novy-Marx-Zhang
    "inst_13f_net_add": 2005,      # 13F breadth literature
}

NOW_YEAR = datetime.now(timezone.utc).year


def _mclean_pontiff_haircut(pub_year: int) -> float:
    """Return multiplier for expected alpha given years since publication."""
    years_since = NOW_YEAR - pub_year
    if years_since <= 2:
        return 0.74   # 26% haircut
    elif years_since <= 5:
        return 0.55   # 45% haircut
    else:
        return 0.42   # 58% haircut


def _get_spx_sma_regime() -> Optional[str]:
    """RULE-S06: SPX above 10mo SMA -> 'above'; below -> 'below'; unknown -> None.

    Uses Alpaca bars if available. Returns None if data fetch fails so the
    rule is labeled UNTESTABLE rather than silently defaulting.
    """
    try:
        from app.services.alpaca_client import get_bars_monthly  # if exists
        bars = get_bars_monthly("SPY", limit=11)
        if not bars or len(bars) < 11:
            return None
        # Latest close vs mean of last 10 monthly closes
        closes = [b.close for b in bars]
        sma10 = sum(closes[-11:-1]) / 10.0
        current = closes[-1]
        return "above" if current >= sma10 else "below"
    except Exception as e:
        logger.debug("[rule_eval] SPX SMA fetch failed: %s", e)
        return None


def evaluate_pick(pick: Any) -> Dict[str, Any]:
    """Evaluate all applicable rules against a ConfluencePick.

    Returns dict serializable to JSON. Call json.dumps() before writing to DB.
    """
    rules: Dict[str, Dict[str, Any]] = {}

    # ─── Fund-level META rules ──────────────────────────────

    # RULE-M02 — McLean-Pontiff haircut
    # Apply per-signal haircut, take weighted avg for the pick.
    fired_signals = _fired_signal_names(pick)
    if fired_signals:
        haircuts = [_mclean_pontiff_haircut(FRAMEWORK_SIGNAL_PUB_YEAR.get(s, 2015))
                    for s in fired_signals]
        avg_haircut = sum(haircuts) / len(haircuts)
        rules["RULE-M02"] = {
            "verdict": "APPLIED",
            "factor": round(avg_haircut, 3),
            "notes": f"avg post-pub haircut across {len(fired_signals)} fired signals: "
                     f"{[FRAMEWORK_SIGNAL_PUB_YEAR.get(s, 2015) for s in fired_signals]}"
        }
    else:
        rules["RULE-M02"] = {"verdict": "UNTESTABLE", "notes": "no signals fired"}

    # RULE-M03 — arb-cost haircut (liquidity/idio-risk based)
    # UNTESTABLE without ADV + idio-vol per-symbol data. Framework filters mid-caps
    # by design, so assume moderate arb cost (0.9 multiplier).
    rules["RULE-M03"] = {
        "verdict": "APPLIED",
        "factor": 0.9,
        "notes": "default 0.9 for mid-cap universe; TODO: pull ADV + idio-vol from bars"
    }

    # RULE-M04 — family diversity (REJECT if all signals same family)
    families = _fired_signal_families(pick)
    if len(families) == 0:
        rules["RULE-M04"] = {"verdict": "UNTESTABLE", "notes": "no signals fired"}
    elif len(families) == 1:
        rules["RULE-M04"] = {
            "verdict": "VIOLATED",
            "notes": f"all signals from single family: {list(families)[0]}"
        }
    else:
        rules["RULE-M04"] = {
            "verdict": "SATISFIED",
            "notes": f"{len(families)} families: {sorted(families)}"
        }

    # ─── Pick-level SELECT rules ────────────────────────────

    # RULE-S01 — sentiment sizing (Baker-Wurgler)
    rules["RULE-S01"] = {
        "verdict": "UNTESTABLE",
        "notes": "BW sentiment index ETL not yet built"
    }

    # RULE-S02 — prefer shorts in high sentiment
    rules["RULE-S02"] = {
        "verdict": "UNTESTABLE",
        "notes": "BW sentiment index ETL not yet built; also confluence is long-only currently"
    }

    # RULE-S03 — Item 1A weighting on Lazy Prices signal
    # Not part of current confluence signal set — Lazy Prices not yet a confluence input
    rules["RULE-S03"] = {
        "verdict": "N/A",
        "notes": "Lazy Prices not in current 5-signal framework; add to feed to enable"
    }

    # RULE-S04 — cross-family confluence (>=2 families)
    if len(families) >= 2:
        rules["RULE-S04"] = {
            "verdict": "SATISFIED",
            "notes": f"{len(families)} families firing: {sorted(families)}"
        }
    elif len(families) == 1:
        rules["RULE-S04"] = {
            "verdict": "VIOLATED",
            "notes": f"only 1 family: {list(families)[0]}"
        }
    else:
        rules["RULE-S04"] = {"verdict": "UNTESTABLE", "notes": "no signals fired"}

    # RULE-S05 — ORB stocks-in-play — N/A for confluence (day-trading rule)
    rules["RULE-S05"] = {"verdict": "N/A", "notes": "confluence is not a day-trading strategy"}

    # RULE-S06 — Faber 10mo SMA gate on SPX
    regime = _get_spx_sma_regime()
    if regime is None:
        rules["RULE-S06"] = {"verdict": "UNTESTABLE", "notes": "SPX monthly bars fetch failed"}
    elif regime == "above":
        rules["RULE-S06"] = {"verdict": "SATISFIED", "notes": "SPX above 10-mo SMA (risk-on)"}
    else:
        rules["RULE-S06"] = {"verdict": "VIOLATED", "notes": "SPX below 10-mo SMA (risk-off)"}

    # RULE-S07 — vol-managed sizing
    rules["RULE-S07"] = {
        "verdict": "UNTESTABLE",
        "notes": "confluence uses fixed $5K size; add vol-scaling to enable"
    }

    # ─── HAIRCUT rules ──────────────────────────────────────

    # RULE-H01 — insider-signal alpha haircut (30-50% of paper)
    if pick.insider_cluster:
        rules["RULE-H01"] = {
            "verdict": "APPLIED",
            "factor": 0.4,
            "notes": "insider paper alpha haircut to 40% for realistic expectation"
        }
    else:
        rules["RULE-H01"] = {"verdict": "N/A", "notes": "no insider signal on this pick"}

    # RULE-H02 — VW expectation (always applied by convention)
    rules["RULE-H02"] = {
        "verdict": "APPLIED",
        "factor": 1.0,
        "notes": "expected returns already use VW paper numbers in framework"
    }

    # RULE-H03 — short alpha halve — N/A (long-only)
    rules["RULE-H03"] = {"verdict": "N/A", "notes": "confluence is long-only currently"}

    # ─── Composite expected alpha (product of all APPLIED factors) ────
    composite_haircut = 1.0
    for rid, r in rules.items():
        if r["verdict"] == "APPLIED" and "factor" in r:
            composite_haircut *= r["factor"]

    return {
        "rules_version": RULES_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluated_by": "rule_evaluator/v1",
        "composite_haircut": round(composite_haircut, 4),
        "families_fired": sorted(list(families)) if families else [],
        "rules": rules,
    }


def evaluate_pick_json(pick: Any) -> str:
    """Convenience: return JSON string ready to store in rule_compliance column."""
    return json.dumps(evaluate_pick(pick), separators=(",", ":"))


def _fired_signal_names(pick: Any) -> list:
    """Which of the 5 framework signals fired for this pick?"""
    fired = []
    if pick.insider_cluster:
        fired.append("insider_cluster")
    if pick.short_surprise_dir is not None and pick.short_surprise_dir != 0:
        fired.append("short_surprise_dir")
    if pick.analyst_revisions_dir is not None and pick.analyst_revisions_dir != 0:
        fired.append("analyst_revisions_dir")
    if pick.fundamental_momentum:
        fired.append("fundamental_momentum")
    if pick.inst_13f_net_add:
        fired.append("inst_13f_net_add")
    return fired


def _fired_signal_families(pick: Any) -> set:
    """Set of family names for signals that fired on this pick."""
    return {SIGNAL_FAMILIES[s] for s in _fired_signal_names(pick)}
