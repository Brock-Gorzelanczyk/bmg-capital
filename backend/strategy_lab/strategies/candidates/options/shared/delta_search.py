"""Find option strikes that match a target delta using Black-Scholes bisection."""
from __future__ import annotations
from .greeks import call_delta, put_delta


def find_call_strike(S: float, T: float, r: float, sigma: float, target_delta: float = 0.16, tol: float = 0.001) -> float | None:
    """Bisection to find K where call_delta ≈ target_delta (e.g. 0.16 for 16-delta)."""
    # call delta decreases as K increases; search K in [0.5*S, 2.0*S]
    lo, hi = 0.5 * S, 2.0 * S
    for _ in range(100):
        mid = (lo + hi) / 2
        d = call_delta(S, mid, T, r, sigma)
        if abs(d - target_delta) < tol:
            return round(mid, 2)
        if d > target_delta:
            lo = mid  # delta too high → increase K
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def find_put_strike(S: float, T: float, r: float, sigma: float, target_delta: float = -0.16, tol: float = 0.001) -> float | None:
    """Bisection to find K where put_delta ≈ target_delta (e.g. -0.16 for 16-delta put)."""
    # put delta increases (less negative) as K decreases; search K in [0.5*S, 2.0*S]
    lo, hi = 0.5 * S, 2.0 * S
    for _ in range(100):
        mid = (lo + hi) / 2
        d = put_delta(S, mid, T, r, sigma)
        if abs(d - target_delta) < tol:
            return round(mid, 2)
        if d < target_delta:
            lo = mid  # delta too negative → increase K (OTM less)
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def strikes_for_condor(S: float, T: float, r: float, sigma: float, short_delta: float = 0.16, wing_width: float = 10.0) -> dict | None:
    """Compute all 4 strikes for a symmetric iron condor."""
    sc = find_call_strike(S, T, r, sigma, short_delta)
    sp = find_put_strike(S, T, r, sigma, -short_delta)
    if sc is None or sp is None:
        return None
    return {
        "short_call": sc,
        "long_call":  round(sc + wing_width, 2),
        "short_put":  sp,
        "long_put":   round(sp - wing_width, 2),
    }


def strikes_for_strangle(S: float, T: float, r: float, sigma: float, target_delta: float = 0.16) -> dict | None:
    """Compute call + put strikes for a strangle at target delta."""
    sc = find_call_strike(S, T, r, sigma, target_delta)
    sp = find_put_strike(S, T, r, sigma, -target_delta)
    if sc is None or sp is None:
        return None
    return {"short_call": sc, "short_put": sp}
