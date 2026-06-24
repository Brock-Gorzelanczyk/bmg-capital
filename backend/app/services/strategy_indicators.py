"""
Per-strategy chart indicator specs for the Strategy Scout chart.

Each strategy declares which overlays / subpanels its chart should render.
The frontend's ScoutChartPage fetches this spec for the active strategy and
renders each IndicatorSpec via a lightweight-charts dispatcher.

This replaces the prior bug where every Scout chart hardcoded 50d + 200d SMA
regardless of the strategy's actual signal source.

Indicator type vocabulary (frontend dispatcher must understand each):
  "sma", "ema"               — single line overlay (price panel)
  "donchian"                 — channel envelope (2 lines on price panel)
  "bollinger"                — 3-line band (upper/mid/lower on price panel)
  "rsi"                      — line in subpanel_1 with 30/70 reference levels
  "macd"                     — line + signal + histogram in subpanel_1
  "vwap"                     — line overlay on price panel
  "vwap_bands"               — vwap +/- 1σ envelope (3 lines on price panel)
  "atr"                      — line in subpanel_1
  "bb_bandwidth"             — line in subpanel_1
  "zscore"                   — line in subpanel_1 with +/- 2 reference
  "prior_day_high_low"       — 2 horizontal price lines for prior session H/L
  "opening_range"            — 2 horizontal price lines for first N min H/L of session
  "ofi"                      — placeholder subpanel ("Coming soon")
  "delta"                    — placeholder subpanel ("Coming soon")
  "relative_strength_vs_spy" — placeholder subpanel ("Coming soon")
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class IndicatorSpec:
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    panel: str = "price"  # "price" | "subpanel_1" | "subpanel_2" | "volume"
    color: str = "#a78bfa"
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d.get("label"):
            d["label"] = self.type.upper()
        return d


# ── Reusable spec fragments ──────────────────────────────────────────────────

def _sma(period: int, color: str) -> IndicatorSpec:
    return IndicatorSpec(
        type="sma",
        params={"period": period},
        panel="price",
        color=color,
        label=f"SMA {period}",
    )


def _ema(period: int, color: str) -> IndicatorSpec:
    return IndicatorSpec(
        type="ema",
        params={"period": period},
        panel="price",
        color=color,
        label=f"EMA {period}",
    )


def _donchian(period: int, color: str) -> IndicatorSpec:
    return IndicatorSpec(
        type="donchian",
        params={"period": period},
        panel="price",
        color=color,
        label=f"Donchian({period})",
    )


def _bollinger(period: int = 20, std: float = 2.0) -> IndicatorSpec:
    return IndicatorSpec(
        type="bollinger",
        params={"period": period, "std": std},
        panel="price",
        color="#38bdf8",
        label=f"BB({period},{std})",
    )


def _rsi(period: int = 14) -> IndicatorSpec:
    return IndicatorSpec(
        type="rsi",
        params={"period": period, "overbought": 70, "oversold": 30},
        panel="subpanel_1",
        color="#fb923c",
        label=f"RSI({period})",
    )


def _macd() -> IndicatorSpec:
    return IndicatorSpec(
        type="macd",
        params={"fast": 12, "slow": 26, "signal": 9},
        panel="subpanel_1",
        color="#4ade80",
        label="MACD(12,26,9)",
    )


def _vwap() -> IndicatorSpec:
    return IndicatorSpec(
        type="vwap",
        params={},
        panel="price",
        color="#f59e0b",
        label="VWAP",
    )


def _vwap_bands() -> IndicatorSpec:
    return IndicatorSpec(
        type="vwap_bands",
        params={"std": 1.0},
        panel="price",
        color="#f59e0b",
        label="VWAP ±1σ",
    )


def _atr(period: int = 14) -> IndicatorSpec:
    return IndicatorSpec(
        type="atr",
        params={"period": period},
        panel="subpanel_1",
        color="#a78bfa",
        label=f"ATR({period})",
    )


def _bb_bandwidth() -> IndicatorSpec:
    return IndicatorSpec(
        type="bb_bandwidth",
        params={"period": 20},
        panel="subpanel_1",
        color="#38bdf8",
        label="BB Bandwidth",
    )


def _zscore(period: int = 20) -> IndicatorSpec:
    return IndicatorSpec(
        type="zscore",
        params={"period": period},
        panel="subpanel_1",
        color="#a78bfa",
        label=f"Z-score({period})",
    )


def _prior_day_hl() -> IndicatorSpec:
    return IndicatorSpec(
        type="prior_day_high_low",
        params={},
        panel="price",
        color="#fb923c",
        label="Prior day H/L",
    )


def _opening_range(minutes: int = 15) -> IndicatorSpec:
    return IndicatorSpec(
        type="opening_range",
        params={"minutes": minutes},
        panel="price",
        color="#4ade80",
        label=f"OR {minutes}m",
    )


def _placeholder(kind: str, label: str) -> IndicatorSpec:
    return IndicatorSpec(
        type=kind,
        params={"placeholder": True},
        panel="subpanel_2",
        color="#7e8e7e",
        label=f"{label} (coming soon)",
    )


# ── Per-strategy mapping ─────────────────────────────────────────────────────
# Keys must match real backend strategy filenames in
# backend/strategy_lab/strategies/*.py (stem). We also alias a few short names
# that the user references in the product copy.

STRATEGY_INDICATORS: Dict[str, List[IndicatorSpec]] = {
    # Trend / breakout
    "turtle_donchian_s2": [
        _donchian(55, "#22d3ee"),       # cyan
        _donchian(20, "#facc15"),       # yellow
        _atr(14),
    ],
    "turtle_donchian_s1": [
        _donchian(20, "#22d3ee"),
        _donchian(10, "#facc15"),
        _atr(14),
    ],
    "golden_cross": [
        _sma(50, "#a78bfa"),
        _sma(200, "#fb923c"),
    ],

    # Mean reversion / oscillators
    "rsi_oversold": [
        _rsi(14),
    ],
    "rsi2_mean_reversion": [
        _sma(200, "#fb923c"),
        _rsi(2),
    ],
    "rsi_bands": [
        _rsi(14),
    ],
    "macd_crossover": [
        _macd(),
    ],
    "bollinger_squeeze": [
        _bollinger(20, 2.0),
        _bb_bandwidth(),
    ],

    # VWAP family
    "vwap_rejection_fade": [
        _vwap(),
        _vwap_bands(),
    ],
    "vwap_reversion": [
        _vwap(),
        _vwap_bands(),
    ],
    "vwap_reversion_chop": [
        _vwap(),
        _vwap_bands(),
    ],

    # Opening range / PDH-PDL intraday
    "opening_range_breakdown": [
        _opening_range(15),
        _prior_day_hl(),
    ],
    "opening_range": [
        _opening_range(15),
        _prior_day_hl(),
    ],
    "pdh_breakout_continuation": [
        _prior_day_hl(),
        _vwap(),
    ],
    "pdh_breakout": [
        _prior_day_hl(),
        IndicatorSpec(type="volume", params={}, panel="volume", color="#4ade80", label="Volume"),
    ],
    "pdh_pdl_reversion": [
        _prior_day_hl(),
    ],

    # Multi-timeframe / momentum
    "mtf_aligned_momentum_surge": [
        _sma(20, "#22d3ee"),
        _sma(50, "#a78bfa"),
        _sma(200, "#fb923c"),
        _rsi(14),
    ],

    # Order flow / institutional
    "ofi_institutional_flow": [
        _vwap(),
        _placeholder("ofi", "OFI"),
    ],

    # Session continuation
    "london_ny_overlap_continuation": [
        _vwap(),
        _prior_day_hl(),
        IndicatorSpec(
            type="session_markers",
            params={"sessions": ["london_open", "ny_open", "london_ny_overlap"]},
            panel="price",
            color="#7e8e7e",
            label="Session markers",
        ),
    ],

    # Factor / cross-sectional
    "momentum_factor_model": [
        _placeholder("relative_strength_vs_spy", "RS vs SPY"),
    ],

    # Quant aliases (user-named shortcuts; no exact backend file but useful for /scout)
    "quant_mean_reversion": [
        _bollinger(20, 2.0),
        _zscore(20),
    ],
    "quant_aggressive": [
        _rsi(2),
        _bollinger(10, 2.0),
    ],
    "quant_scalper": [
        _vwap(),
        _placeholder("ofi", "OFI"),
        _placeholder("delta", "Delta"),
    ],
}

# A sensible default for any strategy not in the explicit map.
DEFAULT_INDICATORS: List[IndicatorSpec] = [
    _sma(20, "#a78bfa"),
    _sma(50, "#fb923c"),
]


# ── Per-strategy timeframe defaults / allowed set ────────────────────────────
# The Scout chart renders a chip rail above the chart that lets the user swap
# timeframes. Each strategy declares its native timeframe + the set the user is
# allowed to view; chips outside the allowed set are rendered disabled so the
# user can see that the strategy is, e.g., intraday-only and won't behave on
# daily bars. Keys mirror STRATEGY_INDICATORS above; anything not present here
# falls back to DEFAULT_TIMEFRAMES (1D-only swing default).
#
# Supported timeframe tokens (must match the keys the frontend translates to
# the bars endpoint's timeframe parameter):
#   "1D", "4H", "1H", "15m", "5m", "1m"

DEFAULT_TIMEFRAMES: Dict[str, Any] = {"default": "1D", "allowed": ["1D", "4H"]}

STRATEGY_TIMEFRAMES: Dict[str, Dict[str, Any]] = {
    "turtle_donchian_s2":      {"default": "1D", "allowed": ["1D", "4H"]},
    "golden_cross":            {"default": "1D", "allowed": ["1D", "4H"]},
    "rsi_oversold":            {"default": "1D", "allowed": ["1D", "4H", "1H"]},
    "vwap_rejection_fade":     {"default": "5m", "allowed": ["1m", "5m", "15m", "1H"]},
    "opening_range_breakdown": {"default": "5m", "allowed": ["1m", "5m", "15m"]},
    "stock_day":               {"default": "15m", "allowed": ["5m", "15m", "1H"]},
    "quant_scalper":           {"default": "1m", "allowed": ["1m", "5m"]},
    "ofi_institutional_flow":  {"default": "5m", "allowed": ["1m", "5m", "15m"]},
}


def get_timeframes_for_strategy(strategy_id: str) -> Dict[str, Any]:
    """Return {"default": tf, "allowed": [tf, ...]} for a strategy id.

    Falls back to DEFAULT_TIMEFRAMES (1D default, [1D, 4H] allowed) for anything
    not in the explicit table. Returns a fresh dict each call so callers can
    mutate freely without poisoning the module-level constant.
    """
    cfg = STRATEGY_TIMEFRAMES.get(strategy_id, DEFAULT_TIMEFRAMES)
    return {"default": cfg["default"], "allowed": list(cfg["allowed"])}


def get_indicators_for_strategy(strategy_id: str) -> List[IndicatorSpec]:
    """Return the indicator spec list for a strategy id (falls back to default)."""
    return STRATEGY_INDICATORS.get(strategy_id, DEFAULT_INDICATORS)


def indicators_as_dicts(strategy_id: str) -> List[Dict[str, Any]]:
    """JSON-serializable form for the API."""
    return [s.to_dict() for s in get_indicators_for_strategy(strategy_id)]


# ── Backend ↔ engine key mapping ─────────────────────────────────────────────
# For specs whose data the backend indicator engine can compute, return the
# `indicators=` query keys to pass to GET /api/bars/{symbol}. The frontend uses
# this to populate the bars query. Specs without a backend engine key
# (e.g. prior_day_high_low, opening_range, session_markers, ofi placeholders)
# are computed client-side from raw bars or shown as "coming soon".

def engine_keys_for_strategy(strategy_id: str) -> List[str]:
    keys: List[str] = []
    for spec in get_indicators_for_strategy(strategy_id):
        t = spec.type
        p = spec.params or {}
        if t == "sma":
            keys.append(f"SMA_{int(p.get('period', 20))}")
        elif t == "ema":
            keys.append(f"EMA_{int(p.get('period', 20))}")
        elif t == "rsi":
            keys.append(f"RSI_{int(p.get('period', 14))}")
        elif t == "macd":
            keys.append("MACD")
        elif t == "vwap":
            keys.append("VWAP")
        elif t == "vwap_bands":
            keys.append("VWAP")
            keys.append("VWAP_BANDS")
        elif t == "atr":
            period = int(p.get("period", 14))
            keys.append(f"ATR_{period}" if period != 14 else "ATR")
        elif t == "donchian":
            keys.append(f"DONCHIAN_{int(p.get('period', 20))}")
        elif t == "bollinger":
            keys.append(f"BB_{int(p.get('period', 20))}")
        elif t == "bb_bandwidth":
            keys.append("BBWIDTH")
        elif t == "zscore":
            keys.append("ZSCORE")
        # other types (prior_day_high_low, opening_range, ofi, delta,
        # relative_strength_vs_spy, session_markers, volume) — no engine key.
    # Deduplicate while preserving order.
    seen = set()
    deduped: List[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    return deduped
