"""
Financial math integrity checks (Category B).

All checks are P1 — one failure = immediate alert. zero tolerance.

Models available (from paper.py):
  PaperAccount:    id, user_id, cash, starting_balance, created_at
  PaperPosition:   id, user_id, symbol, qty, avg_cost, prev_close, opened_at
  PaperOrder:      id, user_id, symbol, side, qty, fill_price, fill_qty, status, created_at
  PaperTransaction:id, user_id, order_id, symbol, side, qty, fill_price, cost_basis, realized_pnl, created_at
"""
from __future__ import annotations
import math
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger(__name__)

TOLERANCE = 0.01  # $0.01 tolerance for float comparisons


def _bad(v) -> bool:
    """True if value is NaN or Infinity."""
    try:
        return v is not None and (math.isnan(float(v)) or math.isinf(float(v)))
    except (TypeError, ValueError):
        return False


async def check_no_negative_shares(db: Session) -> dict:
    from app.db.models.paper import PaperPosition
    bad = db.query(PaperPosition).filter(PaperPosition.qty < 0).all()
    if bad:
        detail = f"{len(bad)} position(s) with qty < 0: " + ", ".join(
            f"{p.symbol}(user={p.user_id},qty={p.qty:.4f})" for p in bad[:5]
        )
        return {"passed": False, "detail": detail}
    return {"passed": True, "detail": "All positions have qty >= 0"}


async def check_no_nan_infinity_monetary(db: Session) -> dict:
    from app.db.models.paper import PaperPosition, PaperAccount
    bad_pos = [
        p for p in db.query(PaperPosition).all()
        if _bad(p.qty) or _bad(p.avg_cost) or _bad(p.prev_close)
    ]
    bad_accts = [
        a for a in db.query(PaperAccount).all()
        if _bad(a.cash) or _bad(a.starting_balance)
    ]
    all_bad = len(bad_pos) + len(bad_accts)
    if all_bad:
        detail = f"{len(bad_pos)} position(s), {len(bad_accts)} account(s) with NaN/Inf values"
        return {"passed": False, "detail": detail}
    return {"passed": True, "detail": "No NaN/Infinity in monetary fields"}


async def check_no_negative_cash(db: Session) -> dict:
    from app.db.models.paper import PaperAccount
    bad = db.query(PaperAccount).filter(PaperAccount.cash < -TOLERANCE).all()
    if bad:
        detail = f"{len(bad)} account(s) with negative cash: " + ", ".join(
            f"user={a.user_id},cash={a.cash:.2f}" for a in bad[:5]
        )
        return {"passed": False, "detail": detail}
    return {"passed": True, "detail": "All accounts have cash >= 0"}


async def check_transaction_balance_reconciliation(db: Session) -> dict:
    """
    For each user: cash should equal
      starting_balance
      - sum(buy fills: fill_price * fill_qty)
      + sum(sell fills: fill_price * fill_qty)
    Compare to PaperAccount.cash.
    Tolerance: $1.00 (allows for minor float drift).
    """
    from app.db.models.paper import PaperAccount, PaperOrder
    CASH_TOLERANCE = 1.00

    accounts = db.query(PaperAccount).all()
    drifts = []
    for acct in accounts:
        filled_orders = (
            db.query(PaperOrder)
            .filter(
                PaperOrder.user_id == acct.user_id,
                PaperOrder.status == "filled",
                PaperOrder.fill_price.isnot(None),
                PaperOrder.fill_qty.isnot(None),
            )
            .all()
        )
        computed_cash = acct.starting_balance
        for order in filled_orders:
            impact = float(order.fill_price or 0) * float(order.fill_qty or 0)
            if order.side == "buy":
                computed_cash -= impact
            else:
                computed_cash += impact

        drift = abs(computed_cash - acct.cash)
        if drift > CASH_TOLERANCE:
            drifts.append(
                f"user={acct.user_id}: expected_cash={computed_cash:.2f}, "
                f"actual_cash={acct.cash:.2f}, drift=${drift:.2f}"
            )

    if drifts:
        return {
            "passed": False,
            "detail": f"{len(drifts)} account(s) with cash drift: " + " | ".join(drifts[:3]),
        }
    return {
        "passed": True,
        "detail": f"Cash reconciliation OK for {len(accounts)} account(s)",
    }


async def check_realized_pnl_consistency(db: Session) -> dict:
    """
    For each user, sum(paper_transactions.realized_pnl) should be non-NaN/Inf
    and consistent with itself (positive check — no cross-table ref to verify against
    since there's no stored lifetime_realized_pnl field).
    """
    from app.db.models.paper import PaperTransaction
    from sqlalchemy import func

    rows = (
        db.query(
            PaperTransaction.user_id,
            func.sum(PaperTransaction.realized_pnl).label("total"),
            func.count(PaperTransaction.id).label("cnt"),
        )
        .group_by(PaperTransaction.user_id)
        .all()
    )

    bad = [
        f"user={r.user_id}: realized_pnl sum is {r.total} (NaN/Inf)"
        for r in rows
        if _bad(r.total)
    ]

    if bad:
        return {"passed": False, "detail": " | ".join(bad)}
    return {
        "passed": True,
        "detail": f"Realized P&L sums are valid for {len(rows)} user(s)",
    }


async def check_cost_basis_math(db: Session) -> dict:
    """
    Every open position should have qty > 0 and avg_cost > 0.
    """
    from app.db.models.paper import PaperPosition
    bad = (
        db.query(PaperPosition)
        .filter(
            (PaperPosition.qty <= 0) | (PaperPosition.avg_cost <= 0)
        )
        .all()
    )
    if bad:
        detail = f"{len(bad)} position(s) with invalid cost basis: " + ", ".join(
            f"{p.symbol}(qty={p.qty},avg_cost={p.avg_cost})" for p in bad[:5]
        )
        return {"passed": False, "detail": detail}
    return {"passed": True, "detail": "All position cost bases are valid"}


async def check_trade_audit_completeness(db: Session) -> dict:
    """
    Every sell-side filled PaperOrder should have at least one PaperTransaction row.
    (Buys don't always generate a transaction — only sells that close positions do.)
    """
    from app.db.models.paper import PaperOrder, PaperTransaction

    filled_sells = (
        db.query(PaperOrder)
        .filter(
            PaperOrder.status == "filled",
            PaperOrder.side == "sell",
            PaperOrder.fill_price.isnot(None),
        )
        .all()
    )

    orphans = []
    for order in filled_sells:
        tx_count = (
            db.query(PaperTransaction)
            .filter(PaperTransaction.order_id == order.id)
            .count()
        )
        if tx_count == 0:
            orphans.append(f"order_id={order.id}(user={order.user_id},{order.symbol})")

    if orphans:
        return {
            "passed": False,
            "detail": f"{len(orphans)} filled sell order(s) with no transaction: "
                      + ", ".join(orphans[:5]),
        }
    return {
        "passed": True,
        "detail": f"All {len(filled_sells)} filled sell orders have transaction records",
    }


async def check_subscription_revenue_match_stripe(db: Session) -> dict:
    """
    Count active paid subscriptions in our DB vs Stripe's active subscription count.
    Flags if they differ by more than 2 (allows for webhook lag).
    """
    from app.db.models.tier import UserTier
    from app.config import settings

    internal_paid = (
        db.query(UserTier)
        .filter(
            UserTier.tier.in_(["plus", "premium"]),
            UserTier.status == "active",
            UserTier.stripe_subscription_id.isnot(None),
        )
        .count()
    )

    if not settings.stripe_secret_key:
        return {
            "passed": True,
            "detail": f"Stripe key not configured — internal paid count: {internal_paid}",
        }

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        subs = stripe.Subscription.list(status="active", limit=100)
        stripe_count = len(subs.data)
        drift = abs(internal_paid - stripe_count)
        if drift > 2:
            return {
                "passed": False,
                "detail": f"Internal paid={internal_paid}, Stripe active={stripe_count}, drift={drift}",
            }
        return {
            "passed": True,
            "detail": f"Internal={internal_paid}, Stripe={stripe_count} — within tolerance",
        }
    except Exception as exc:
        return {"passed": False, "detail": f"Stripe API call failed: {exc}"}
