from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.exams import Certificate
from app.services.certification.cert_generator import _compute_hash


def verify_certificate(db: Session, cert_id: str) -> dict[str, Any]:
    """
    Loads cert from DB, recomputes hash, returns verification result.
    Returns {found, valid, recipient_name, display_title, score_pct,
             issued_at, is_revoked, revoked_reason}
    """
    cert = db.get(Certificate, cert_id)
    if not cert:
        return {
            "found": False,
            "valid": False,
            "recipient_name": None,
            "display_title": None,
            "score_pct": None,
            "issued_at": None,
            "is_revoked": False,
            "revoked_reason": None,
        }

    issued_at = cert.issued_at
    if issued_at and issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)

    # Recompute hash and compare
    expected_hash = _compute_hash(
        cert.id,
        cert.user_id,
        cert.cert_target,
        float(cert.score_pct),
        issued_at,
    )
    hash_valid = expected_hash == cert.verification_hash

    return {
        "found": True,
        "valid": hash_valid and not cert.is_revoked,
        "recipient_name": cert.recipient_name,
        "display_title": cert.display_title,
        "score_pct": float(cert.score_pct),
        "issued_at": issued_at.isoformat() if issued_at else None,
        "cert_id": cert.id,
        "is_revoked": cert.is_revoked,
        "revoked_reason": cert.revoked_reason,
    }
