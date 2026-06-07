"""
Certification / Exam router.

GET  /api/exams/eligibility              — check eligibility
POST /api/exams/start                    — start an attempt
GET  /api/exams/{attempt_id}/question/{index}
POST /api/exams/{attempt_id}/answer
POST /api/exams/{attempt_id}/heartbeat
POST /api/exams/{attempt_id}/submit
GET  /api/exams/certificates             — list user's certs
GET  /api/exams/certificates/{cert_id}/download — serve PDF

Public:
GET  /api/verify/{cert_id}               — verify a certificate (no auth)
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.exams import Certificate
from app.services.certification import exam_runner, cert_verifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exams", tags=["exams"])
verify_router = APIRouter(tags=["exams-public"])

_CERT_DIR = Path(__file__).parent.parent.parent / "data" / "certificates"


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class StartExamBody(BaseModel):
    exam_target: str
    honor_code_accepted: bool
    honor_code_name: str


class AnswerBody(BaseModel):
    question_id: int
    question_index: int
    user_answer: str


class HeartbeatBody(BaseModel):
    tab_switches: int


# ── Eligibility ───────────────────────────────────────────────────────────────

@router.get("/eligibility")
def get_eligibility(
    exam_target: str = Query(default="learning_center"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return exam_runner.check_eligibility(db, user.id, "learning_center", exam_target)


# ── Start attempt ─────────────────────────────────────────────────────────────

@router.post("/start")
def start_exam(
    body: StartExamBody,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return exam_runner.start_attempt(
        db,
        user.id,
        "learning_center",
        body.exam_target,
        body.honor_code_accepted,
        body.honor_code_name,
    )


# ── Get question ──────────────────────────────────────────────────────────────

@router.get("/{attempt_id}/question/{index}")
def get_question(
    attempt_id: int,
    index: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return exam_runner.get_question(db, attempt_id, index, user.id)


# ── Record answer ─────────────────────────────────────────────────────────────

@router.post("/{attempt_id}/answer")
def record_answer(
    attempt_id: int,
    body: AnswerBody,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return exam_runner.record_answer(
        db,
        attempt_id,
        body.question_id,
        body.question_index,
        body.user_answer,
        user.id,
    )


# ── Heartbeat ─────────────────────────────────────────────────────────────────

@router.post("/{attempt_id}/heartbeat")
def heartbeat(
    attempt_id: int,
    body: HeartbeatBody,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return exam_runner.heartbeat(db, attempt_id, body.tab_switches, user.id)


# ── Submit ────────────────────────────────────────────────────────────────────

@router.post("/{attempt_id}/submit")
def submit_exam(
    attempt_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return exam_runner.submit_attempt(db, attempt_id, user.id)


# ── Certificates list ─────────────────────────────────────────────────────────

@router.get("/certificates")
def list_certificates(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    certs = (
        db.query(Certificate)
        .filter(Certificate.user_id == user.id)
        .order_by(Certificate.issued_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "cert_type": c.cert_type,
            "display_title": c.display_title,
            "score_pct": float(c.score_pct),
            "issued_at": c.issued_at.isoformat() if c.issued_at else None,
            "pdf_url": f"/api/exams/certificates/{c.id}/download",
        }
        for c in certs
    ]


# ── Certificate download ──────────────────────────────────────────────────────

@router.get("/certificates/{cert_id}/download")
def download_certificate(
    cert_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cert = db.get(Certificate, cert_id)
    if not cert or cert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Certificate not found.")

    # Try PDF first, fall back to HTML stub
    pdf_path = _CERT_DIR / f"{cert_id}.pdf"
    html_path = _CERT_DIR / f"{cert_id}.html"

    if pdf_path.exists():
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=f"BMG-Certificate-{cert_id}.pdf",
        )
    if html_path.exists():
        return FileResponse(
            str(html_path),
            media_type="text/html",
            filename=f"BMG-Certificate-{cert_id}.html",
        )
    raise HTTPException(status_code=404, detail="Certificate file not found.")


# ── Public verify endpoint ────────────────────────────────────────────────────

@verify_router.get("/api/verify/{cert_id}")
def verify_certificate(
    cert_id: str,
    db: Session = Depends(get_db),
):
    return cert_verifier.verify_certificate(db, cert_id)
