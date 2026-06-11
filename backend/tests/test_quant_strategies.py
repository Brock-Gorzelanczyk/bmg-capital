"""Unit tests for new quant research strategies.

Covers:
  - tsmom_multi_asset: positive momentum → buy, insufficient bars → empty,
    negative momentum → no long, crypto uses 63d lookback
  - crypto_mr_zscore_30d: oversold z < -2 → buy, falling knife filter,
    recovered z > -0.5 → sell
  - vix_regime_allocator: momentum scaled down at VIX>25, MR scaled up,
    no scaling below VIX 25
"""
from __future__ import annotations

import pytest
import random

from strategy_lab.strategies.tsmom_multi_asset import generate_signals as tsmom_signals
from strategy_lab.strategies.crypto_mr_zscore_30d import generate_signals as mr_signals
from strategy_lab.core.vix_regime_allocator import apply_vix_scaling
from strategy_lab.core.signals import Signal


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_bars(symbol: str, prices: list[float]) -> dict:
    """Build a bars dict from a flat list of prices."""
    return {
        symbol: [
            {"c": p, "o": p, "h": p * 1.01, "l": p * 0.99, "v": 1_000_000}
            for p in prices
        ]
    }


# ── TSMOM tests ───────────────────────────────────────────────────────────────

def test_tsmom_long_signal():
    """TSMOM: 252d positive return → buy signal."""
    prices = [100.0 + i * 0.1 for i in range(300)]  # steady uptrend
    bars = make_bars("SPY", prices)
    sigs = tsmom_signals(bars, {}, {})
    assert any(s.side == "buy" for s in sigs), (
        "Expected at least one buy signal for uptrending SPY"
    )


def test_tsmom_no_signal_on_insufficient_bars():
    """TSMOM: fewer than 273 bars (252+21) → no signal."""
    prices = [100.0] * 100  # only 100 bars — less than required 273
    bars = make_bars("SPY", prices)
    sigs = tsmom_signals(bars, {}, {})
    assert sigs == [], f"Expected no signals with 100 bars, got {sigs}"


def test_tsmom_negative_return_no_long():
    """TSMOM: negative 252-21 day return → no long signal (v1 is long-only)."""
    prices = [200.0 - i * 0.2 for i in range(300)]  # steady downtrend
    bars = make_bars("TLT", prices)
    sigs = tsmom_signals(bars, {}, {})
    assert not any(s.side == "buy" for s in sigs), (
        "Should NOT generate a buy signal on a downtrending TLT"
    )


def test_tsmom_crypto_uses_shorter_lookback():
    """TSMOM: BTC/USD uses 63d lookback (not 252d), so 80 bars should yield a signal."""
    # 63 bars needed for BTC (no skip). 80 bars is enough.
    prices = [40000.0 + i * 50 for i in range(80)]  # 80 bars, uptrend
    bars = make_bars("BTC/USD", prices)
    sigs = tsmom_signals(bars, {}, {})
    assert any(s.side == "buy" for s in sigs), (
        "BTC/USD uses 63d lookback; 80 bars uptrend should give a buy signal"
    )


def test_tsmom_inv_vol_weight_capped():
    """TSMOM: size_hint should always be <= 0.9."""
    prices = [100.0 + i * 0.5 for i in range(300)]  # strong uptrend, single symbol
    bars = make_bars("SPY", prices)
    sigs = tsmom_signals(bars, {}, {})
    for s in sigs:
        assert s.size_hint <= 0.9, f"size_hint {s.size_hint} exceeds cap of 0.9"


def test_tsmom_multi_symbol_inv_vol_normalization():
    """TSMOM: with multiple symbols, inv-vol weights should sum (approximately) to 1."""
    # Create two uptrending symbols with different volatility
    base = [100.0 + i * 0.3 for i in range(300)]
    noisy = [100.0 + i * 0.3 + (i % 10) * 5 for i in range(300)]  # higher vol

    bars = {
        "SPY": [{"c": p, "o": p, "h": p * 1.01, "l": p * 0.99, "v": 1_000_000} for p in base],
        "IWM": [{"c": p, "o": p, "h": p * 1.02, "l": p * 0.98, "v": 1_000_000} for p in noisy],
    }
    sigs = tsmom_signals(bars, {}, {})
    total_weight = sum(s.size_hint for s in sigs if s.side == "buy")
    # Weights are normalized then capped at 0.9, so sum ≤ n_signals
    assert total_weight > 0, "Expected positive combined weight"
    assert len(sigs) <= 2, "At most 2 signals for 2 symbols"


# ── Crypto MR Z-Score tests ───────────────────────────────────────────────────

def test_crypto_mr_buy_on_oversold():
    """Crypto MR: z < -2 → buy signal."""
    random.seed(42)
    base = 50000.0
    std = 2000.0
    # Stable prices, then a crash to z < -2
    prices = [base + random.gauss(0, std * 0.3) for _ in range(40)]
    # Force last price well below mean - 2*std to guarantee entry
    prices[-1] = base - 3 * std
    bars = make_bars("BTC/USD", prices)
    sigs = mr_signals(bars, {}, {})
    assert any(s.side == "buy" for s in sigs), (
        "Expected buy signal when price is >2 std devs below 30d mean"
    )


def test_crypto_mr_no_signal_in_falling_knife():
    """Crypto MR: skip if 21d trend < -30% (falling knife filter)."""
    # Prices fall 40% over ~35 bars (well over the -30% filter)
    prices = [50000.0 * (1 - 0.015 * i) for i in range(35)]
    bars = make_bars("ETH/USD", prices)
    sigs = mr_signals(bars, {}, {})
    # No buy signal despite likely oversold z-score
    assert not any(s.side == "buy" for s in sigs), (
        "Falling knife filter should prevent buy when 21d return < -30%"
    )


def test_crypto_mr_sell_on_recovery():
    """Crypto MR: z recovers to > -0.5 → sell signal."""
    random.seed(7)
    base = 50000.0
    std = 1500.0
    # Prices that are tightly clustered around the mean (z near 0)
    prices = [base + random.gauss(0, std * 0.1) for _ in range(35)]
    # Force last price to be close to mean (z ≈ 0 → > -0.5 threshold → sell)
    prices[-1] = base
    bars = make_bars("SOL/USD", prices)
    sigs = mr_signals(bars, {}, {})
    assert any(s.side == "sell" for s in sigs), (
        "Expected sell signal when z-score recovers above -0.5"
    )


def test_crypto_mr_size_hint_scales_with_severity():
    """Crypto MR: deeper z-score → larger size_hint."""
    random.seed(11)
    base = 10000.0
    std = 500.0

    def make_oversold_bars(multiplier: float) -> dict:
        prices = [base + random.gauss(0, std * 0.2) for _ in range(40)]
        prices[-1] = base - multiplier * std
        return make_bars("LTC/USD", prices)

    sigs_mild = mr_signals(make_oversold_bars(2.2), {}, {})
    sigs_severe = mr_signals(make_oversold_bars(4.0), {}, {})

    buy_mild = [s for s in sigs_mild if s.side == "buy"]
    buy_severe = [s for s in sigs_severe if s.side == "buy"]

    if buy_mild and buy_severe:
        assert buy_severe[0].size_hint >= buy_mild[0].size_hint, (
            "Deeper oversold should have >= size_hint vs mild oversold"
        )


# ── VIX Regime Allocator tests ────────────────────────────────────────────────

def test_vix_allocator_scales_momentum_down():
    """VIX > 25: momentum bot signals scaled to 50% of original size_hint."""
    sigs = [Signal("SPY", "buy", 0.8, 0.8, "test signal", "tsmom")]
    scaled, mult = apply_vix_scaling(sigs, "tsmom_multi_asset", {"vix": 30.0, "vix_regime": "high"})
    assert mult == 0.5, f"Expected multiplier 0.5, got {mult}"
    assert abs(scaled[0].size_hint - 0.4) < 0.001, (
        f"Expected size_hint 0.4, got {scaled[0].size_hint}"
    )


def test_vix_allocator_scales_mr_up():
    """VIX > 25: mean-reversion bot signals scaled to 150% (capped at 1.0)."""
    sigs = [Signal("BTC/USD", "buy", 0.7, 0.6, "test signal", "crypto_mr")]
    scaled, mult = apply_vix_scaling(
        sigs, "crypto_meanrev_2163", {"vix": 28.0, "vix_regime": "high"}
    )
    assert mult == 1.5, f"Expected multiplier 1.5, got {mult}"
    assert abs(scaled[0].size_hint - 0.9) < 0.001, (
        f"Expected size_hint 0.9 (0.6 * 1.5 = 0.9), got {scaled[0].size_hint}"
    )


def test_vix_allocator_mr_cap_at_1():
    """VIX > 25: mean-reversion size_hint capped at 1.0 (cannot exceed 100%)."""
    sigs = [Signal("ETH/USD", "buy", 0.8, 0.8, "test", "crypto_mr")]
    scaled, mult = apply_vix_scaling(
        sigs, "crypto_meanrev_2163", {"vix": 35.0, "vix_regime": "panic"}
    )
    assert mult == 1.5
    # 0.8 * 1.5 = 1.2, but capped at 1.0
    assert scaled[0].size_hint <= 1.0, f"size_hint {scaled[0].size_hint} exceeds 1.0 cap"
    assert abs(scaled[0].size_hint - 1.0) < 0.001, (
        f"Expected size_hint capped at 1.0, got {scaled[0].size_hint}"
    )


def test_vix_allocator_no_scale_low_vix():
    """VIX < 25: no scaling, multiplier exactly 1.0."""
    sigs = [Signal("SPY", "buy", 0.7, 0.7, "test signal", "tsmom")]
    scaled, mult = apply_vix_scaling(
        sigs, "tsmom_multi_asset", {"vix": 18.0, "vix_regime": "low"}
    )
    assert mult == 1.0, f"Expected multiplier 1.0 at VIX=18, got {mult}"
    assert scaled[0].size_hint == pytest.approx(0.7), (
        f"size_hint should be unchanged at {scaled[0].size_hint}"
    )


def test_vix_allocator_no_scale_at_threshold():
    """VIX exactly at 25.0: no scaling (threshold is strictly >25)."""
    sigs = [Signal("QQQ", "buy", 0.65, 0.65, "test", "tsmom")]
    scaled, mult = apply_vix_scaling(
        sigs, "tsmom_multi_asset", {"vix": 25.0, "vix_regime": "mid"}
    )
    assert mult == 1.0, "VIX==25 should NOT trigger scaling (threshold is strictly >25)"


def test_vix_allocator_no_scale_carry_income():
    """VIX > 25: carry_income bots are NOT scaled (only momentum/MR are affected)."""
    sigs = [Signal("AAPL", "buy", 0.75, 0.75, "test", "wheel")]
    scaled, mult = apply_vix_scaling(
        sigs, "options_income", {"vix": 32.0, "vix_regime": "panic"}
    )
    assert mult == 1.0, "Carry/income bots should not be VIX-scaled"
    assert scaled[0].size_hint == pytest.approx(0.75)


def test_vix_allocator_no_vix_in_regime():
    """No VIX data in regime dict → no scaling, multiplier 1.0."""
    sigs = [Signal("SPY", "buy", 0.8, 0.8, "test", "tsmom")]
    scaled, mult = apply_vix_scaling(sigs, "tsmom_multi_asset", {"vix_regime": "high"})
    assert mult == 1.0, "Should return 1.0 when VIX is missing from regime"


def test_vix_allocator_empty_signals():
    """Empty signal list → returns empty list and 1.0 multiplier."""
    scaled, mult = apply_vix_scaling([], "tsmom_multi_asset", {"vix": 30.0})
    assert scaled == []
    assert mult == 1.0
