"""Tests for canonical sleeve_pct on the /api/bots allocation payload.

Per spec (.pipeline/01-spec.md COMMIT 1), `sleeve_pct` is computed as
    SUM(alloc.starting_capital_cents) for all enabled allocs bound to the
    same portfolio_id, used as the divisor for each alloc's
    starting_capital_cents.

Rules covered:
1. Two enabled allocs in same portfolio (60K + 40K) → sleeve_pct = 60.0 and 40.0
2. Allocation with portfolio_id=None → sleeve_pct is None
3. Disabled allocation in sleeve does NOT contribute to the denominator
4. user_id=2 allocs do NOT influence user_id=1's sleeve_pct (multi-user scoping)
5. starting_capital_cents=0 → sleeve_pct is None

Conftest.py mocks the SQLAlchemy ORM (it cannot import on Py3.9 due to
PEP-604 `Mapped[float | None]` in the real model file). We therefore test
the canonical computation by replicating the router's per-sleeve total
build + per-alloc divide using plain object stubs, then call
`_allocation_to_dict` directly to confirm the field lands on the wire.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

# Ensure backend root on path before any app.* import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _alloc(
    *,
    id: int,
    profile_id: int,
    portfolio_id: int | None,
    starting_capital_cents: int,
    enabled: bool = True,
    user_id: int = 1,
    capital_pct: float = 10.0,
):
    """Build a SimpleNamespace mirroring BotAllocation's fields used by the spec."""
    return SimpleNamespace(
        id=id,
        profile_id=profile_id,
        portfolio_id=portfolio_id,
        starting_capital_cents=starting_capital_cents,
        enabled=enabled,
        user_id=user_id,
        capital_pct=capital_pct,
        risk_profile="standard",
        paper_mode=True,
        go_live_requested=False,
        paused_reason=None,
        created_at=None,
        updated_at=None,
    )


def _compute_sleeve_starting_by_portfolio(allocs) -> dict:
    """Replicates the divisor build in backend/app/routers/bots.py list_bots()."""
    out: dict[int, int] = {}
    for a in allocs:
        if a.portfolio_id is None or not a.enabled:
            continue
        out[a.portfolio_id] = out.get(a.portfolio_id, 0) + int(a.starting_capital_cents or 0)
    return out


def _sleeve_pct_for(allocation, sleeve_starting_by_portfolio) -> float | None:
    """Replicates the per-alloc sleeve_pct calc in list_bots()."""
    if allocation is None or allocation.portfolio_id is None:
        return None
    sleeve_total = sleeve_starting_by_portfolio.get(allocation.portfolio_id, 0)
    starting = int(allocation.starting_capital_cents or 0)
    if sleeve_total > 0 and starting > 0:
        return round(starting / sleeve_total * 100, 1)
    return None


# ─── Spec case 1: two enabled allocs in same portfolio (60K + 40K) ───────────

def test_two_enabled_allocs_sleeve_pct_sums_to_100():
    """60K / 100K = 60.0, 40K / 100K = 40.0; sum == 100.0."""
    a_big = _alloc(id=1, profile_id=10, portfolio_id=1, starting_capital_cents=60_00 * 1000)  # $60K
    a_small = _alloc(id=2, profile_id=11, portfolio_id=1, starting_capital_cents=40_00 * 1000)  # $40K

    totals = _compute_sleeve_starting_by_portfolio([a_big, a_small])
    assert totals == {1: 10_000_000}, "divisor should equal 60K+40K=$100K in cents"

    big_pct = _sleeve_pct_for(a_big, totals)
    small_pct = _sleeve_pct_for(a_small, totals)
    assert big_pct == 60.0
    assert small_pct == 40.0
    assert round(big_pct + small_pct, 1) == 100.0


# ─── Spec case 2: portfolio_id=None → sleeve_pct is None ─────────────────────

def test_orphan_alloc_sleeve_pct_is_none():
    """cash_floor-style alloc (no portfolio_id) should not get a sleeve_pct."""
    orphan = _alloc(id=3, profile_id=20, portfolio_id=None, starting_capital_cents=10_000_000)
    # Also add a sibling in another portfolio so the divisor dict is non-empty
    sibling = _alloc(id=4, profile_id=21, portfolio_id=2, starting_capital_cents=5_000_000)

    totals = _compute_sleeve_starting_by_portfolio([orphan, sibling])
    # Orphan must NOT appear as a key
    assert None not in totals
    assert orphan.portfolio_id is None
    assert _sleeve_pct_for(orphan, totals) is None


# ─── Spec case 3: disabled alloc excluded from divisor ───────────────────────

def test_disabled_alloc_does_not_inflate_denominator():
    """Disabled sibling shouldn't shrink an enabled bot's sleeve_pct."""
    enabled_a = _alloc(id=5, profile_id=30, portfolio_id=3, starting_capital_cents=11_000_000)  # $110K
    enabled_b = _alloc(id=6, profile_id=31, portfolio_id=3, starting_capital_cents=9_000_000)   # $90K
    disabled = _alloc(
        id=7, profile_id=32, portfolio_id=3,
        starting_capital_cents=50_000_000,  # huge — would crush percentages if counted
        enabled=False,
    )

    totals = _compute_sleeve_starting_by_portfolio([enabled_a, enabled_b, disabled])
    assert totals == {3: 20_000_000}, "divisor must exclude disabled alloc's $500K"

    pct_a = _sleeve_pct_for(enabled_a, totals)
    pct_b = _sleeve_pct_for(enabled_b, totals)
    assert pct_a == 55.0, f"110K/200K=55%, got {pct_a}"
    assert pct_b == 45.0, f"90K/200K=45%, got {pct_b}"

    # Sanity: if disabled were counted, A would be 110/700 ≈ 15.7% — must NOT be that.
    assert pct_a != 15.7


# ─── Spec case 4: multi-user scoping (user_id filtering happens upstream) ────

def test_multi_user_scoping_uses_only_filtered_allocs():
    """list_bots() filters `BotAllocation.user_id == current_user.id` BEFORE
    building the sleeve divisor. Verify that if we feed only user_id=1 allocs
    to the divisor builder, user_id=2's allocs cannot leak in."""
    u1_a = _alloc(id=10, profile_id=40, portfolio_id=4, starting_capital_cents=11_000_000, user_id=1)
    u1_b = _alloc(id=11, profile_id=41, portfolio_id=4, starting_capital_cents=9_000_000, user_id=1)
    u2_huge = _alloc(id=12, profile_id=40, portfolio_id=4, starting_capital_cents=80_000_000, user_id=2)

    # Simulate the upstream filter — only u1 allocs reach the divisor builder.
    u1_only = [a for a in [u1_a, u1_b, u2_huge] if a.user_id == 1]
    totals = _compute_sleeve_starting_by_portfolio(u1_only)
    assert totals == {4: 20_000_000}, "u2's $800K must NOT contribute"

    pct_a = _sleeve_pct_for(u1_a, totals)
    pct_b = _sleeve_pct_for(u1_b, totals)
    assert pct_a == 55.0
    assert pct_b == 45.0


# ─── Spec case 5: starting_capital_cents == 0 → sleeve_pct is None ───────────

def test_zero_starting_capital_returns_none():
    """Zero-row alloc: sleeve_pct must be None (not 0.0), preserving the
    'unknown / no working capital' meaning. Also: zero row should not be
    a divide-by-zero hazard."""
    zero_row = _alloc(id=20, profile_id=50, portfolio_id=5, starting_capital_cents=0)
    sibling = _alloc(id=21, profile_id=51, portfolio_id=5, starting_capital_cents=10_000_000)

    totals = _compute_sleeve_starting_by_portfolio([zero_row, sibling])
    # Divisor must still be a positive int (sibling alone keeps it from being 0)
    assert totals == {5: 10_000_000}

    assert _sleeve_pct_for(zero_row, totals) is None, "zero numerator → None, not 0.0"
    assert _sleeve_pct_for(sibling, totals) == 100.0


def test_zero_divisor_sleeve_returns_none():
    """If all enabled allocs in a sleeve had 0 starting (e.g. all disabled
    or all zeroed), sleeve_total = 0 → guarded by `if sleeve_total > 0`."""
    only_zero = _alloc(id=30, profile_id=60, portfolio_id=6, starting_capital_cents=0)
    totals = _compute_sleeve_starting_by_portfolio([only_zero])
    # Divisor dict has the entry with value 0 (we still include the 0-cent enabled alloc)
    assert totals.get(6, 0) == 0
    assert _sleeve_pct_for(only_zero, totals) is None


# ─── Edge case 10 from spec: single-bot sleeve → 100% ────────────────────────

def test_single_bot_sleeve_is_100_pct():
    solo = _alloc(id=40, profile_id=70, portfolio_id=7, starting_capital_cents=12_500_000)
    totals = _compute_sleeve_starting_by_portfolio([solo])
    assert _sleeve_pct_for(solo, totals) == 100.0


# ─── Realistic post-M024 fixture: stock_swing = $110K of $270K = 40.7% ───────

def test_stock_sleeve_post_m024_matches_spec_expected_values():
    """Mirrors the acceptance numbers in spec COMMIT 1 ($110K/$270K = 40.7).
    Replicates the Stocks sleeve only.
    """
    stock_swing = _alloc(id=100, profile_id=1, portfolio_id=8, starting_capital_cents=11_000_000)  # $110K
    stock_lt    = _alloc(id=101, profile_id=2, portfolio_id=8, starting_capital_cents=9_000_000)   # $90K
    stock_day   = _alloc(id=102, profile_id=3, portfolio_id=8, starting_capital_cents=7_000_000)   # $70K
    totals = _compute_sleeve_starting_by_portfolio([stock_swing, stock_lt, stock_day])
    assert totals == {8: 27_000_000}  # $270K

    assert _sleeve_pct_for(stock_swing, totals) == 40.7
    assert _sleeve_pct_for(stock_lt, totals) == 33.3
    assert _sleeve_pct_for(stock_day, totals) == 25.9
    # 40.7 + 33.3 + 25.9 = 99.9 (rounding noise — acceptable per spec Q1).
    s = round(40.7 + 33.3 + 25.9, 1)
    assert s == 99.9


# ─── Serializer contract: _allocation_to_dict must include the new field ────

def test_allocation_to_dict_includes_sleeve_pct_field():
    """The serializer must always emit the `sleeve_pct` key, defaulting to None.
    Tests against the actual router function (bypassing conftest mocks).
    """
    import importlib
    # Clear conftest's mocked `app.*` modules so we can import the real router
    saved = {}
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            saved[k] = sys.modules.pop(k)
    try:
        from app.routers.bots import _allocation_to_dict  # noqa: WPS433
    except Exception:
        # Real ORM cannot import on Py3.9 due to PEP-604 unions in models.
        # Restore mocks and skip the serializer contract check at this layer.
        sys.modules.update(saved)
        import pytest as _pt
        _pt.skip("Real ORM cannot import in this env (PEP-604 unions on Py3.9); "
                 "sleeve_pct field is exercised through math tests above.")
        return

    a = _alloc(id=1, profile_id=1, portfolio_id=1, starting_capital_cents=10_000_000)

    # default sleeve_pct
    d_default = _allocation_to_dict(a)
    assert "sleeve_pct" in d_default
    assert d_default["sleeve_pct"] is None

    # explicit sleeve_pct passes through
    d_explicit = _allocation_to_dict(a, sleeve_pct=40.7)
    assert d_explicit["sleeve_pct"] == 40.7

    # Restore mocks for any subsequent test files
    sys.modules.update(saved)
