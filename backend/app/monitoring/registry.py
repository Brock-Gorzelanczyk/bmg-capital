"""
Check registry — declarative config for every monitoring check.

Adding a new check = add an entry here. No code deploy needed beyond the
check function itself. The engine reads this registry to know what to run,
when, and at what severity.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class CheckConfig:
    id: str                         # unique snake_case key, never changes
    category: str                   # "infrastructure" | "financial" | "security" | "vendors" | "ai" | "compliance"
    frequency: str                  # "minute" | "5min" | "15min" | "hourly" | "daily"
    severity_on_fail: str           # "P1" | "P2" | "P3"
    runbook: str                    # one-line: what it means + first action + common fix + escalation
    fn: Callable[..., Any]          # the check function — signature: async fn(db) or async fn()
    needs_db: bool = False          # True → engine passes a DB session
    expected_pass_rate: float = 1.0 # 1.0 = must always pass; 0.95 = occasional miss tolerated
    market_hours_only: bool = False # True → skip check outside NYSE market hours
    enabled: bool = True


def _load_registry() -> list[CheckConfig]:
    """Build registry lazily to avoid circular imports at module load time."""
    from app.monitoring.checks import infrastructure, financial, security, vendors, ai_behavior, compliance

    return [
        # ── A. Infrastructure ────────────────────────────────────────────────
        CheckConfig(
            id="service_health_backend_api",
            category="infrastructure",
            frequency="minute",
            severity_on_fail="P1",
            runbook="Backend /health returned non-200. To investigate: check Railway logs for crash. To resolve: redeploy or rollback. Escalate to: #incidents if persists > 2 min.",
            fn=infrastructure.check_backend_api_health,
        ),
        CheckConfig(
            id="db_ping_sqlite",
            category="infrastructure",
            frequency="minute",
            severity_on_fail="P1",
            runbook="DB SELECT 1 failed. To investigate: check if SQLite file is accessible and not locked. To resolve: restart service. Escalate to: #incidents immediately.",
            fn=infrastructure.check_db_ping,
            needs_db=True,
        ),
        CheckConfig(
            id="ssl_cert_expiry",
            category="infrastructure",
            frequency="hourly",
            severity_on_fail="P2",
            runbook="SSL cert expiring within 30 days. To investigate: run `openssl s_client` against domain. To resolve: renew cert via cert provider. Escalate to: #devops.",
            fn=infrastructure.check_ssl_cert_expiry,
        ),

        # ── B. Financial Math Integrity ───────────────────────────────────────
        CheckConfig(
            id="no_negative_shares",
            category="financial",
            frequency="15min",
            severity_on_fail="P1",
            runbook="Position with qty < 0 detected. To investigate: query paper_positions where qty < 0. To resolve: identify the order that caused this and correct the position. Escalate to: #financial-math immediately.",
            fn=financial.check_no_negative_shares,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="no_nan_infinity_monetary",
            category="financial",
            frequency="15min",
            severity_on_fail="P1",
            runbook="NaN or Infinity in monetary field. To investigate: query paper_positions and paper_accounts for NaN values. To resolve: reset the corrupted field; trace the order that caused it. Escalate to: #financial-math immediately.",
            fn=financial.check_no_nan_infinity_monetary,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="no_negative_cash",
            category="financial",
            frequency="15min",
            severity_on_fail="P1",
            runbook="Account with negative cash detected. To investigate: query paper_accounts where cash < 0. To resolve: check recent sell transactions for double-counting. Escalate to: #financial-math immediately.",
            fn=financial.check_no_negative_cash,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="transaction_balance_reconciliation",
            category="financial",
            frequency="15min",
            severity_on_fail="P1",
            runbook="Account cash balance doesn't reconcile with transactions. To investigate: recompute cash from transactions for affected account. To resolve: usually a missing transaction row — check paper_orders for orphan fills. Escalate to: #financial-math if drift > $1.",
            fn=financial.check_transaction_balance_reconciliation,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="realized_pnl_consistency",
            category="financial",
            frequency="15min",
            severity_on_fail="P1",
            runbook="Sum of realized P&L from transactions doesn't match expected. To investigate: recompute sum(paper_transactions.realized_pnl) per user. To resolve: check for duplicate transaction rows. Escalate to: #financial-math.",
            fn=financial.check_realized_pnl_consistency,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="cost_basis_math",
            category="financial",
            frequency="15min",
            severity_on_fail="P1",
            runbook="Position avg_cost or qty is zero/negative when position is open. To investigate: query the position record. To resolve: recalculate avg_cost from trade history. Escalate to: #financial-math.",
            fn=financial.check_cost_basis_math,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="trade_audit_completeness",
            category="financial",
            frequency="hourly",
            severity_on_fail="P1",
            runbook="Filled order has no matching transaction row. To investigate: find paper_orders with status=filled and no paper_transaction. To resolve: create the missing transaction row from the order data. Escalate to: #financial-math.",
            fn=financial.check_trade_audit_completeness,
            needs_db=True,
            expected_pass_rate=1.0,
        ),
        CheckConfig(
            id="subscription_revenue_match_stripe",
            category="financial",
            frequency="daily",
            severity_on_fail="P1",
            runbook="Internal subscription count doesn't match active Stripe subscriptions. To investigate: compare user_tiers table vs Stripe dashboard. To resolve: run stripe webhook replay for missed events. Escalate to: #billing.",
            fn=financial.check_subscription_revenue_match_stripe,
            needs_db=True,
            expected_pass_rate=1.0,
        ),

        # ── D. Security ───────────────────────────────────────────────────────
        CheckConfig(
            id="failed_login_anomaly",
            category="security",
            frequency="minute",
            severity_on_fail="P1",
            runbook="More than 5 failed logins from single IP in 1 min. To investigate: query login_attempts table for the IP. To resolve: block IP at firewall level. Escalate to: #security immediately.",
            fn=security.check_failed_login_anomaly,
            needs_db=True,
        ),
        CheckConfig(
            id="session_token_integrity",
            category="security",
            frequency="5min",
            severity_on_fail="P1",
            runbook="JWT signing or verification failed. To investigate: check JWT_SECRET env var is set correctly. To resolve: rotate JWT secret and force re-login. Escalate to: #security immediately.",
            fn=security.check_session_token_integrity,
        ),
        CheckConfig(
            id="secrets_in_logs_check",
            category="security",
            frequency="hourly",
            severity_on_fail="P1",
            runbook="Possible secret/key pattern found in recent logs. To investigate: grep recent log files for the pattern. To resolve: rotate the exposed secret immediately. Escalate to: #security immediately.",
            fn=security.check_secrets_in_logs,
        ),
        CheckConfig(
            id="pii_in_errors_check",
            category="security",
            frequency="hourly",
            severity_on_fail="P2",
            runbook="Email or PII pattern found in error logs. To investigate: check the log lines flagged. To resolve: sanitize the error handler that logged PII. Escalate to: #security.",
            fn=security.check_pii_in_errors,
        ),

        # ── K. Vendor Health ──────────────────────────────────────────────────
        CheckConfig(
            id="vendor_alpaca_up",
            category="vendors",
            frequency="minute",
            severity_on_fail="P1",
            runbook="Alpaca API not responding. To investigate: check https://status.alpaca.markets. To resolve: switch to cached data mode. Escalate to: #incidents.",
            fn=vendors.check_alpaca_up,
        ),
        CheckConfig(
            id="vendor_fmp_up",
            category="vendors",
            frequency="minute",
            severity_on_fail="P2",
            runbook="FMP (Financial Modeling Prep) API not responding. To investigate: check FMP status page. To resolve: use cached data or Alpaca fallback. Escalate to: #incidents if > 10 min.",
            fn=vendors.check_fmp_up,
        ),
        CheckConfig(
            id="vendor_anthropic_up",
            category="vendors",
            frequency="minute",
            severity_on_fail="P1",
            runbook="Anthropic API not responding — AI Copilot is down. To investigate: check https://status.anthropic.com. To resolve: show degraded mode banner. Escalate to: #incidents.",
            fn=vendors.check_anthropic_up,
        ),
        CheckConfig(
            id="vendor_stripe_up",
            category="vendors",
            frequency="minute",
            severity_on_fail="P1",
            runbook="Stripe API not responding — payments are broken. To investigate: check https://status.stripe.com. To resolve: show payment maintenance banner. Escalate to: #incidents.",
            fn=vendors.check_stripe_up,
        ),

        # ── E. AI Behavior (Wave 1 additions) ─────────────────────────────────
        CheckConfig(
            id="ai_provider_health",
            category="ai",
            frequency="hourly",
            severity_on_fail="P2",
            runbook="AI provider latency > SLA. To investigate: check Anthropic status page, review recent API response times. To resolve: implement retry logic or degrade gracefully. Escalate to: #ai-ops.",
            fn=ai_behavior.check_ai_provider_health,
        ),
        CheckConfig(
            id="prompt_drift_detection",
            category="ai",
            frequency="daily",
            severity_on_fail="P1",
            runbook="System prompts changed without authorization. To investigate: compare current prompts to baseline stored in monitoring_results. To resolve: identify who changed the prompt and revert if unauthorized. Escalate to: #security.",
            fn=ai_behavior.check_prompt_drift,
        ),
        CheckConfig(
            id="ai_cost_budget",
            category="ai",
            frequency="daily",
            severity_on_fail="P3",
            runbook="Daily AI spend is on pace to exceed monthly budget. To investigate: check Anthropic usage dashboard. To resolve: review high-token endpoints and add caching. Escalate to: #ai-ops.",
            fn=ai_behavior.check_ai_cost_budget,
        ),

        # ── I. Compliance (lightweight) ────────────────────────────────────────
        CheckConfig(
            id="audit_log_completeness",
            category="compliance",
            frequency="daily",
            severity_on_fail="P1",
            runbook="Expected audit events missing from audit_logs. To investigate: query audit_logs for recent gaps. To resolve: identify the code path that should log the event and add logging. Escalate to: #compliance.",
            fn=compliance.check_audit_log_completeness,
            needs_db=True,
        ),
        CheckConfig(
            id="audit_log_immutability",
            category="compliance",
            frequency="daily",
            severity_on_fail="P1",
            runbook="Audit log row count is lower than expected (possible deletion). To investigate: check recent audit_logs row counts in monitoring history. To resolve: restore from backup. Escalate to: #compliance immediately.",
            fn=compliance.check_audit_log_immutability,
            needs_db=True,
        ),
        CheckConfig(
            id="cross_table_referential_integrity",
            category="compliance",
            frequency="daily",
            severity_on_fail="P1",
            runbook="Orphan foreign keys detected. To investigate: run the referential integrity queries in the runbook doc. To resolve: clean up orphan rows. Escalate to: #engineering.",
            fn=compliance.check_cross_table_referential_integrity,
            needs_db=True,
        ),
    ]


# Singleton — loaded once on first access
_REGISTRY: list[CheckConfig] | None = None

def get_registry() -> list[CheckConfig]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load_registry()
    return _REGISTRY

def get_check(check_id: str) -> CheckConfig | None:
    return next((c for c in get_registry() if c.id == check_id), None)
