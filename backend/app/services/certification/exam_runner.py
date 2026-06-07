from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.exams import ExamAttempt, ExamQuestion, ExamResponse, Certificate
from app.db.models.learning import LearningModule
from app.services.certification.anti_cheat import (
    check_time_expired,
    should_disqualify,
    compute_time_remaining,
    TAB_SWITCH_DISQUALIFY,
    TIME_LIMIT_SECONDS,
)
from app.services.certification.question_picker import pick_questions

_MAX_ATTEMPTS_PER_90_DAYS = 3
_COOLDOWN_DAYS = 14
_QUESTIONS_PER_EXAM = 150
_PASSING_PCT = 90.0


# ── Eligibility ───────────────────────────────────────────────────────────────

def check_eligibility(
    db: Session,
    user_id: int,
    exam_type: str,
    exam_target: str,
) -> dict[str, Any]:
    """
    Returns {eligible, reason, attempts_used, next_attempt_available_at, cooldown_seconds}
    Rules:
    - Learning Center exam: ALL published modules across ALL tracks must be complete
    - Max 3 attempts per 90-day rolling window
    - 14-day cooldown between any two attempts
    - In-progress attempt blocks new start
    """
    now = datetime.now(timezone.utc)

    # Check for in-progress attempt
    in_progress = (
        db.query(ExamAttempt)
        .filter(
            ExamAttempt.user_id == user_id,
            ExamAttempt.exam_target == exam_target,
            ExamAttempt.status == "in_progress",
        )
        .first()
    )
    if in_progress:
        # Check if it's actually expired
        if check_time_expired(in_progress):
            in_progress.status = "failed"
            in_progress.ended_at = now
            db.commit()
        else:
            return {
                "eligible": False,
                "reason": "You have an exam already in progress.",
                "attempts_used": 0,
                "next_attempt_available_at": None,
                "cooldown_seconds": 0,
            }

    # Require all published modules across all tracks to be completed
    from app.db.models.learning import LearningProgress, LearningTrack
    all_published = (
        db.query(LearningModule)
        .filter(LearningModule.is_published.is_(True))
        .all()
    )
    if not all_published:
        return {
            "eligible": False,
            "reason": "No published modules found. Complete the Learning Center first.",
            "attempts_used": 0,
            "next_attempt_available_at": None,
            "cooldown_seconds": 0,
        }
    completed_ids = {
        row.module_id
        for row in db.query(LearningProgress).filter(
            LearningProgress.user_id == user_id,
            LearningProgress.completed.is_(True),
        ).all()
    }
    incomplete = [m for m in all_published if m.id not in completed_ids]
    if incomplete:
        return {
            "eligible": False,
            "reason": f"Complete all Learning Center modules first. {len(incomplete)} module(s) remaining.",
            "attempts_used": 0,
            "next_attempt_available_at": None,
            "cooldown_seconds": 0,
        }

    # Check 90-day rolling window
    window_start = now - timedelta(days=90)
    attempts_in_window = (
        db.query(ExamAttempt)
        .filter(
            ExamAttempt.user_id == user_id,
            ExamAttempt.exam_target == exam_target,
            ExamAttempt.status != "in_progress",
            ExamAttempt.started_at >= window_start,
        )
        .count()
    )

    if attempts_in_window >= _MAX_ATTEMPTS_PER_90_DAYS:
        # Find when oldest attempt in window falls off
        oldest_in_window = (
            db.query(ExamAttempt)
            .filter(
                ExamAttempt.user_id == user_id,
                ExamAttempt.exam_target == exam_target,
                ExamAttempt.status != "in_progress",
                ExamAttempt.started_at >= window_start,
            )
            .order_by(ExamAttempt.started_at.asc())
            .first()
        )
        started = oldest_in_window.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        unlock_at = started + timedelta(days=90)
        cooldown_secs = int((unlock_at - now).total_seconds())
        return {
            "eligible": False,
            "reason": f"Maximum {_MAX_ATTEMPTS_PER_90_DAYS} attempts per 90 days reached.",
            "attempts_used": attempts_in_window,
            "next_attempt_available_at": unlock_at.isoformat(),
            "cooldown_seconds": max(cooldown_secs, 0),
        }

    # Check 7-day cooldown between attempts
    last_attempt = (
        db.query(ExamAttempt)
        .filter(
            ExamAttempt.user_id == user_id,
            ExamAttempt.exam_target == exam_target,
            ExamAttempt.status != "in_progress",
        )
        .order_by(ExamAttempt.started_at.desc())
        .first()
    )
    if last_attempt:
        last_started = last_attempt.started_at
        if last_started.tzinfo is None:
            last_started = last_started.replace(tzinfo=timezone.utc)
        cooldown_until = last_started + timedelta(days=_COOLDOWN_DAYS)
        if now < cooldown_until:
            cooldown_secs = int((cooldown_until - now).total_seconds())
            return {
                "eligible": False,
                "reason": f"Please wait {_COOLDOWN_DAYS} days between attempts.",
                "attempts_used": attempts_in_window,
                "next_attempt_available_at": cooldown_until.isoformat(),
                "cooldown_seconds": cooldown_secs,
            }

    return {
        "eligible": True,
        "reason": None,
        "attempts_used": attempts_in_window,
        "next_attempt_available_at": None,
        "cooldown_seconds": 0,
    }


# ── Start attempt ─────────────────────────────────────────────────────────────

def start_attempt(
    db: Session,
    user_id: int,
    exam_type: str,
    exam_target: str,
    honor_code_accepted: bool,
    honor_code_name: str,
) -> dict[str, Any]:
    """
    Creates ExamAttempt row, picks questions, shuffles option order.
    Returns attempt_id + question count + time_limit_seconds.
    """
    if not honor_code_accepted:
        raise HTTPException(status_code=400, detail="Honor code must be accepted to start exam.")

    eligibility = check_eligibility(db, user_id, exam_type, exam_target)
    if not eligibility["eligible"]:
        raise HTTPException(status_code=409, detail=eligibility["reason"])

    # Pick questions
    question_ids = pick_questions(db, exam_target, n=_QUESTIONS_PER_EXAM)
    if not question_ids:
        raise HTTPException(status_code=422, detail="No questions available for this exam.")

    # Shuffle MC options per question
    questions = db.query(ExamQuestion).filter(ExamQuestion.id.in_(question_ids)).all()
    q_map = {q.id: q for q in questions}

    question_order: dict[str, list[int]] = {}
    for qid in question_ids:
        q = q_map.get(qid)
        if q and q.options:
            indices = list(range(len(q.options)))
            random.shuffle(indices)
            question_order[str(qid)] = indices

    now = datetime.now(timezone.utc)
    time_limit = TIME_LIMIT_SECONDS.get(exam_type, TIME_LIMIT_SECONDS["learning_center"])

    attempt = ExamAttempt(
        user_id=user_id,
        exam_type=exam_type,
        exam_target=exam_target,
        started_at=now,
        status="in_progress",
        honor_code_accepted=True,
        honor_code_name=honor_code_name,
        question_ids=question_ids,
        question_order=question_order,
        time_remaining_seconds=time_limit,
        tab_switch_count=0,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return {
        "attempt_id": attempt.id,
        "question_count": len(question_ids),
        "time_limit_seconds": time_limit,
        "started_at": now.isoformat(),
    }


# ── Get question ──────────────────────────────────────────────────────────────

def get_question(
    db: Session,
    attempt_id: int,
    question_index: int,
    user_id: int,
) -> dict[str, Any]:
    """
    Returns question for display. NEVER includes correct_answer or explanation.
    Uses the shuffled option order stored in attempt.question_order.
    """
    attempt = _get_active_attempt(db, attempt_id, user_id)

    question_ids: list[int] = attempt.question_ids or []
    if question_index < 0 or question_index >= len(question_ids):
        raise HTTPException(status_code=404, detail="Question index out of range.")

    qid = question_ids[question_index]
    q = db.get(ExamQuestion, qid)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found.")

    # Apply shuffled option order
    options = None
    if q.options:
        order = (attempt.question_order or {}).get(str(qid))
        if order:
            options = [q.options[i] for i in order]
        else:
            options = list(q.options)

    # Check if already answered
    existing_response = (
        db.query(ExamResponse)
        .filter(
            ExamResponse.attempt_id == attempt_id,
            ExamResponse.question_index == question_index,
        )
        .first()
    )

    time_remaining = compute_time_remaining(attempt)

    return {
        "id": q.id,
        "index": question_index,
        "body": q.body,
        "question_type": q.question_type,
        "options": options,
        "chart_image_url": q.chart_image_url,
        "already_answered": existing_response is not None,
        "time_remaining_seconds": time_remaining,
        "total_questions": len(question_ids),
    }


# ── Record answer ─────────────────────────────────────────────────────────────

def record_answer(
    db: Session,
    attempt_id: int,
    question_id: int,
    question_index: int,
    user_answer: str,
    user_id: int,
) -> dict[str, Any]:
    """
    Records answer, checks if already answered (no re-answering allowed).
    Returns {saved, time_remaining_seconds}.
    Does NOT reveal whether correct.
    """
    attempt = _get_active_attempt(db, attempt_id, user_id)

    # Check time
    if check_time_expired(attempt):
        _auto_submit(db, attempt)
        raise HTTPException(status_code=409, detail="Time expired. Exam auto-submitted.")

    # No re-answering
    existing = (
        db.query(ExamResponse)
        .filter(
            ExamResponse.attempt_id == attempt_id,
            ExamResponse.question_index == question_index,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="This question has already been answered.")

    q = db.get(ExamQuestion, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found.")

    # Check correctness (server-side; not returned to client)
    is_correct = _check_answer(q, user_answer, attempt)

    response = ExamResponse(
        attempt_id=attempt_id,
        question_id=question_id,
        question_index=question_index,
        user_answer=user_answer,
        is_correct=is_correct,
        answered_at=datetime.now(timezone.utc),
    )
    db.add(response)
    db.commit()

    time_remaining = compute_time_remaining(attempt)
    return {"saved": True, "time_remaining_seconds": time_remaining}


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def heartbeat(
    db: Session,
    attempt_id: int,
    tab_switches: int,
    user_id: int,
) -> dict[str, Any]:
    """
    Updates tab_switch_count, checks time limit.
    If time expired: auto-submit.
    If tab_switches >= 3: disqualify.
    Returns {status, time_remaining_seconds, warning?}
    """
    attempt = _get_active_attempt(db, attempt_id, user_id)

    # Update tab switch count (only increase)
    if tab_switches > attempt.tab_switch_count:
        attempt.tab_switch_count = tab_switches
        db.commit()

    # Check disqualification
    if should_disqualify(attempt.tab_switch_count):
        attempt.status = "disqualified"
        attempt.ended_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "status": "disqualified",
            "time_remaining_seconds": 0,
            "warning": "Exam disqualified due to excessive tab switching.",
        }

    # Check time expiry
    if check_time_expired(attempt):
        result = _auto_submit(db, attempt)
        return {
            "status": "submitted",
            "time_remaining_seconds": 0,
            "auto_submitted": True,
            **result,
        }

    time_remaining = compute_time_remaining(attempt)
    attempt.time_remaining_seconds = time_remaining
    db.commit()

    warning = None
    if attempt.tab_switch_count == 1:
        warning = "Warning 1/2: Switching tabs is not allowed during the exam."
    elif attempt.tab_switch_count == 2:
        warning = "Final warning: One more tab switch will disqualify your exam."

    return {
        "status": "in_progress",
        "time_remaining_seconds": time_remaining,
        "warning": warning,
    }


# ── Submit ────────────────────────────────────────────────────────────────────

def submit_attempt(db: Session, attempt_id: int, user_id: int) -> dict[str, Any]:
    """
    Server-side scoring. Marks attempt passed/failed. Generates cert if passed.
    Returns {passed, score_pct, questions_correct, questions_total,
             breakdown_by_module, certificate_id?, failed_questions_with_explanations}
    """
    attempt = _get_active_attempt(db, attempt_id, user_id)
    return _score_and_finalize(db, attempt)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_active_attempt(db: Session, attempt_id: int, user_id: int) -> ExamAttempt:
    attempt = db.get(ExamAttempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    if attempt.status != "in_progress":
        raise HTTPException(status_code=409, detail=f"Attempt is already {attempt.status}.")
    return attempt


def _auto_submit(db: Session, attempt: ExamAttempt) -> dict[str, Any]:
    """Auto-submit when time expires."""
    return _score_and_finalize(db, attempt)


def _check_answer(q: ExamQuestion, user_answer: str, attempt: ExamAttempt) -> bool:
    """Check whether the user's answer is correct."""
    if q.question_type == "calc" and q.numeric_tolerance is not None:
        try:
            user_val = float(user_answer)
            correct_val = float(q.correct_answer)
            tolerance = float(q.numeric_tolerance)
            return abs(user_val - correct_val) <= tolerance
        except (ValueError, TypeError):
            return False
    elif q.question_type == "mc":
        # user_answer is the index (0-based) of the option as displayed (shuffled order)
        order = (attempt.question_order or {}).get(str(q.id))
        if order and user_answer.isdigit():
            # Map display index back to original index
            display_idx = int(user_answer)
            if 0 <= display_idx < len(order):
                original_idx = order[display_idx]
                # correct_answer is the index (0-based) in original options
                return str(original_idx) == q.correct_answer
        return user_answer.strip().lower() == q.correct_answer.strip().lower()
    else:
        return user_answer.strip().lower() == q.correct_answer.strip().lower()


def _score_and_finalize(db: Session, attempt: ExamAttempt) -> dict[str, Any]:
    """Score all responses, update attempt status, generate cert if passed."""
    from app.services.certification.cert_generator import generate_certificate

    now = datetime.now(timezone.utc)
    question_ids: list[int] = attempt.question_ids or []
    questions = db.query(ExamQuestion).filter(ExamQuestion.id.in_(question_ids)).all()
    q_map = {q.id: q for q in questions}

    responses = (
        db.query(ExamResponse)
        .filter(ExamResponse.attempt_id == attempt.id)
        .all()
    )
    resp_map = {r.question_index: r for r in responses}

    questions_total = len(question_ids)
    questions_correct = 0
    failed_questions = []
    breakdown: dict[str, dict[str, int]] = {}

    for idx, qid in enumerate(question_ids):
        q = q_map.get(qid)
        if not q:
            continue

        module_slug = q.module_slug or "unknown"
        if module_slug not in breakdown:
            breakdown[module_slug] = {"correct": 0, "total": 0}
        breakdown[module_slug]["total"] += 1

        resp = resp_map.get(idx)
        if resp and resp.is_correct:
            questions_correct += 1
            breakdown[module_slug]["correct"] += 1
        else:
            # Collect failed question details
            user_answer_display = resp.user_answer if resp else "(no answer)"
            # Reconstruct correct answer display
            correct_display = q.correct_answer
            if q.question_type == "mc" and q.options:
                try:
                    correct_idx = int(q.correct_answer)
                    if 0 <= correct_idx < len(q.options):
                        correct_display = q.options[correct_idx]
                except (ValueError, TypeError):
                    correct_display = q.correct_answer

            # Map user answer back to option text if MC
            user_answer_text = user_answer_display
            if q.question_type == "mc" and q.options and resp and resp.user_answer:
                order = (attempt.question_order or {}).get(str(q.id))
                if order and resp.user_answer.isdigit():
                    display_idx = int(resp.user_answer)
                    if 0 <= display_idx < len(order):
                        original_idx = order[display_idx]
                        if 0 <= original_idx < len(q.options):
                            user_answer_text = q.options[original_idx]

            failed_questions.append({
                "body": q.body,
                "your_answer": user_answer_text,
                "correct_answer": correct_display,
                "explanation": q.explanation,
                "module_slug": module_slug,
            })

    score_pct = round((questions_correct / questions_total) * 100, 1) if questions_total > 0 else 0.0
    passed = score_pct >= _PASSING_PCT

    attempt.ended_at = now
    attempt.questions_correct = questions_correct
    attempt.questions_total = questions_total
    attempt.score_pct = score_pct
    attempt.status = "passed" if passed else "failed"
    db.commit()

    cert_id = None
    if passed:
        try:
            cert = generate_certificate(db, attempt.user_id, attempt.id)
            cert_id = cert.id
        except Exception:
            pass  # cert generation failure is non-fatal for scoring

    breakdown_list = [
        {"module_slug": slug, "correct": vals["correct"], "total": vals["total"]}
        for slug, vals in breakdown.items()
    ]

    return {
        "passed": passed,
        "score_pct": float(score_pct),
        "questions_correct": questions_correct,
        "questions_total": questions_total,
        "breakdown_by_module": breakdown_list,
        "certificate_id": cert_id,
        "failed_questions": failed_questions,
    }
