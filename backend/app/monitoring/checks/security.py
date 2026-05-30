"""Security checks (Category D)."""
from __future__ import annotations
import re
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Patterns that suggest secrets in logs
SECRET_PATTERNS = [
    re.compile(r'sk_live_[A-Za-z0-9]{24,}', re.IGNORECASE),      # Stripe live key
    re.compile(r'sk-ant-[A-Za-z0-9\-_]{20,}', re.IGNORECASE),    # Anthropic key
    re.compile(r'AKIA[0-9A-Z]{16}', re.IGNORECASE),               # AWS access key
    re.compile(r'ghp_[A-Za-z0-9]{36}', re.IGNORECASE),            # GitHub PAT
    re.compile(r'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+'),  # JWT
    re.compile(r'-----BEGIN (RSA|EC|DSA) PRIVATE KEY-----'),
]

PII_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # email
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),                                   # SSN
    re.compile(r'\b4[0-9]{12}(?:[0-9]{3})?\b'),                            # Visa card number
]


async def check_failed_login_anomaly(db: Session) -> dict:
    """Flag any IP with > 5 failed logins in the last 1 minute."""
    from app.db.models.monitoring import LoginAttempt
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    rows = (
        db.query(
            LoginAttempt.ip_address,
            func.count(LoginAttempt.id).label("cnt"),
        )
        .filter(
            LoginAttempt.success == False,
            LoginAttempt.timestamp >= since,
        )
        .group_by(LoginAttempt.ip_address)
        .all()
    )

    suspects = [r for r in rows if r.cnt > 5]
    if suspects:
        detail = "Brute-force suspects: " + ", ".join(
            f"{r.ip_address}({r.cnt} fails)" for r in suspects[:5]
        )
        return {"passed": False, "detail": detail}
    return {"passed": True, "detail": "No brute-force anomalies in last 1 min"}


async def check_session_token_integrity() -> dict:
    """Verify that our JWT library can sign and verify a test token."""
    try:
        from app.config import settings
        from jose import jwt as jose_jwt
        payload = {"sub": "monitoring-test", "iat": int(datetime.now(timezone.utc).timestamp())}
        token = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        decoded = jose_jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if decoded.get("sub") != "monitoring-test":
            return {"passed": False, "detail": "JWT encode/decode mismatch"}
        return {"passed": True, "detail": "JWT sign/verify OK"}
    except Exception as exc:
        return {"passed": False, "detail": f"JWT integrity check failed: {exc}"}


async def check_secrets_in_logs() -> dict:
    """Scan the last 1000 lines of the application log for secret patterns."""
    import os
    log_paths = [
        "/tmp/bmg-capital.log",
        "/var/log/bmg-capital.log",
    ]
    # Check Python logging handlers for file paths
    import logging as _logging
    for handler in _logging.root.handlers:
        if hasattr(handler, 'baseFilename'):
            log_paths.insert(0, handler.baseFilename)

    findings = []
    for log_path in log_paths:
        if not os.path.exists(log_path):
            continue
        try:
            with open(log_path, 'r', errors='ignore') as f:
                lines = f.readlines()
            recent = lines[-1000:] if len(lines) > 1000 else lines
            for i, line in enumerate(recent):
                for pat in SECRET_PATTERNS:
                    if pat.search(line):
                        findings.append(f"Pattern found at line ~{len(lines)-len(recent)+i}: {pat.pattern[:30]}...")
                        break
        except Exception as exc:
            logger.warning("Could not scan log %s: %s", log_path, exc)

    if not findings:
        return {"passed": True, "detail": "No secret patterns in recent logs"}
    return {"passed": False, "detail": f"{len(findings)} potential secrets found: " + "; ".join(findings[:3])}


async def check_pii_in_errors() -> dict:
    """Scan recent error-level log lines for PII patterns."""
    import os
    log_paths = ["/tmp/bmg-capital.log", "/var/log/bmg-capital.log"]
    import logging as _logging
    for handler in _logging.root.handlers:
        if hasattr(handler, 'baseFilename'):
            log_paths.insert(0, handler.baseFilename)

    findings = []
    for log_path in log_paths:
        if not os.path.exists(log_path):
            continue
        try:
            with open(log_path, 'r', errors='ignore') as f:
                lines = f.readlines()
            error_lines = [l for l in lines[-500:] if 'ERROR' in l or 'EXCEPTION' in l or 'Traceback' in l]
            for line in error_lines:
                for pat in PII_PATTERNS:
                    if pat.search(line):
                        findings.append("PII pattern found in error log line")
                        break
        except Exception as exc:
            logger.warning("Could not scan log for PII: %s", exc)

    if not findings:
        return {"passed": True, "detail": "No PII patterns in recent error logs"}
    return {"passed": False, "detail": f"{len(findings)} potential PII exposures in error logs"}
