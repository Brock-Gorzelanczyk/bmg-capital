"""
BMG Capital — Founder Operating Mode Router
Prefix: /api/founder
Admin-only: all endpoints require current_user.email == "demo@bmgcapital.com"
"""
from __future__ import annotations

import csv
import io
import logging
import secrets
import string
from datetime import timezone, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.founder import Investor, ContentPost, WaitlistSignup
from app.db.models.playbook import PlaybookTask, PlaybookStart

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/founder", tags=["founder"])

ADMIN_EMAILS = {"demo@bmgcapital.com", "32bgorzelanczyk@gmail.com"}


# ── Admin guard ────────────────────────────────────────────────────────────────

def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


# ── Compliance checker ─────────────────────────────────────────────────────────

RISKY_PHRASES = [
    ("guaranteed returns", "blocked"),
    ("risk-free", "blocked"),
    ("will definitely", "blocked"),
    ("100% safe", "blocked"),
    ("will go up", "flagged"),
    ("will increase", "flagged"),
    ("price target", "flagged"),
    ("buy now", "flagged"),
]


def check_compliance(text: str) -> list[dict]:
    issues = []
    lower = text.lower()
    for phrase, severity in RISKY_PHRASES:
        if phrase in lower:
            issues.append({"phrase": phrase, "severity": severity})
    if not any(footer in lower for footer in ["not financial advice", "educational purposes", "investing involves risk"]):
        issues.append({"phrase": "missing compliance footer", "severity": "flagged"})
    return issues


# ── Email templates ────────────────────────────────────────────────────────────

EMAIL_TEMPLATES = [
    {
        "id": "v1_demo_first",
        "name": "V1 Demo-First",
        "subject": "Quick demo — BMG Capital (stocks + crypto + AI, one account)",
        "body": (
            "Hi {name},\n\n"
            "I'm building BMG Capital — the first platform that unifies stocks, crypto, and an AI co-pilot "
            "in a single account with $0 commissions. Targeting the 45M US investors who actively manage both.\n\n"
            "I have a 4-minute demo I'd love to show you. Would you have 20 minutes this week or next?\n\n"
            "Best,\nBrock\nBMG Capital\nbmgcapital.com"
        ),
    },
    {
        "id": "v2_specific_ask",
        "name": "V2 Specific-Ask",
        "subject": "BMG Capital — raising $750K seed, {firm} on my list",
        "body": (
            "Hi {name},\n\n"
            "I'm raising a $750K seed for BMG Capital. Given {firm}'s portfolio in fintech, I thought you'd "
            "be the right person to reach.\n\n"
            "BMG unifies stocks, crypto, and an AI co-pilot — one account, $0 commissions. "
            "500 on waitlist. Demo live.\n\n"
            "If {stage_focus} fits your current focus, I'd value 20 minutes. "
            "Happy to send the deck first.\n\n"
            "Best,\nBrock\nBMG Capital"
        ),
    },
]


# ── Content draft vault ────────────────────────────────────────────────────────

SEED_DRAFTS = [
    {
        "title": "Origin Tweet",
        "platform": "twitter",
        "content_type": "tweet",
        "body_md": (
            "92 days ago I quit pretending I'd ever find a co-founder.\n\n"
            "Today BMG Capital works: stocks, crypto, and an AI that actually understands your portfolio. One app.\n\n"
            "0 users. 0 waitlist. 0 followers.\n\n"
            "Tomorrow that changes. Building this in public until it's 1M."
        ),
    },
    {
        "title": "Demo GIF Tweet",
        "platform": "twitter",
        "content_type": "tweet",
        "body_md": (
            'I asked BMG\'s AI: "rebalance my portfolio for a recession, keep my crypto exposure."\n\n'
            "4 seconds. 11 trades. Full reasoning shown.\n\n"
            "This is what investing should have felt like 10 years ago.\n"
            "[8-sec GIF]\n\n"
            "Reply BMG for early access."
        ),
    },
    {
        "title": "Build Log Thread Template",
        "platform": "twitter",
        "content_type": "thread",
        "body_md": (
            "Solo founder day [N]:\n"
            "- [thing that broke]\n"
            "- [thing you shipped]\n"
            "- [thing you learned]\n\n"
            "[Product insight or user moment]\n\n"
            "Building in public. [CTA]"
        ),
    },
    {
        "title": "Failure/Honesty Post",
        "platform": "twitter",
        "content_type": "tweet",
        "body_md": (
            "[Specific thing that went wrong]\n\n"
            "[What you did about it]\n\n"
            "[One-line human moment]\n\n"
            "Building this anyway."
        ),
    },
    {
        "title": "Waitlist Launch",
        "platform": "twitter",
        "content_type": "tweet",
        "body_md": (
            "The BMG waitlist is live.\n\n"
            "Stocks + crypto + an AI co-pilot, one account, $0 commissions.\n\n"
            "First 1,000 get lifetime Pro free.\n"
            "Skip the line: each friend you invite moves you up 100 spots.\n\n"
            "Reply BMG, I'll DM the link.\n\n"
            "Not financial advice."
        ),
    },
]


# ── Seed investors ─────────────────────────────────────────────────────────────

SEED_INVESTORS = [
    {"name": "Sheel Mohnot", "firm": "Better Tomorrow Ventures", "twitter_handle": "@pitchsheel", "stage_focus": "pre-seed/seed", "check_size_target": "$250K-$1M"},
    {"name": "Charles Birnbaum", "firm": "Bessemer Venture Partners", "stage_focus": "Series A", "check_size_target": "$500K-$2M"},
    {"name": "Hadley Harris", "firm": "Eniac Ventures", "stage_focus": "pre-seed", "check_size_target": "$250K-$750K"},
    {"name": "Frank Rotman", "firm": "QED Investors", "twitter_handle": "@fintechjunkie", "stage_focus": "seed/Series A", "check_size_target": "$500K-$2M"},
    {"name": "Jillian Williams", "firm": "Cowboy Ventures", "stage_focus": "seed", "check_size_target": "$250K-$1M"},
    {"name": "Nik Milanović", "firm": "The Fintech Fund", "stage_focus": "pre-seed/seed", "check_size_target": "$100K-$500K"},
    {"name": "Charles Hudson", "firm": "Precursor Ventures", "stage_focus": "pre-seed", "check_size_target": "$100K-$500K"},
    {"name": "Lachy Groom", "firm": "Solo", "stage_focus": "seed", "check_size_target": "$250K-$1M"},
    {"name": "Immad Akhund", "firm": "Angel", "twitter_handle": "@immad", "stage_focus": "pre-seed/seed", "check_size_target": "$50K-$250K"},
    {"name": "Ryan Hoover", "firm": "Weekend Fund", "stage_focus": "pre-seed", "check_size_target": "$50K-$200K"},
]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class InvestorOut(BaseModel):
    id: int
    name: str
    firm: str
    role: str
    contact_email: Optional[str]
    twitter_handle: Optional[str]
    linkedin_url: Optional[str]
    intro_path: str
    status: str
    last_contact_at: Optional[datetime]
    next_action: Optional[str]
    notes_md: str
    check_size_target: Optional[str]
    stage_focus: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvestorCreate(BaseModel):
    name: str
    firm: str = ""
    role: str = ""
    contact_email: Optional[str] = None
    twitter_handle: Optional[str] = None
    linkedin_url: Optional[str] = None
    intro_path: str = "cold"
    status: str = "not_contacted"
    last_contact_at: Optional[datetime] = None
    next_action: Optional[str] = None
    notes_md: str = ""
    check_size_target: Optional[str] = None
    stage_focus: Optional[str] = None


class InvestorPatch(BaseModel):
    status: Optional[str] = None
    notes_md: Optional[str] = None
    next_action: Optional[str] = None
    last_contact_at: Optional[datetime] = None
    firm: Optional[str] = None
    role: Optional[str] = None
    contact_email: Optional[str] = None
    twitter_handle: Optional[str] = None
    linkedin_url: Optional[str] = None
    intro_path: Optional[str] = None
    check_size_target: Optional[str] = None
    stage_focus: Optional[str] = None


class ContentPostOut(BaseModel):
    id: int
    platform: str
    content_type: str
    title: str
    body_md: str
    scheduled_for: Optional[datetime]
    posted_at: Optional[datetime]
    status: str
    performance_data: dict
    compliance_checked: bool
    compliance_issues: list
    created_at: datetime

    model_config = {"from_attributes": True}


class ContentPostCreate(BaseModel):
    platform: str
    content_type: str
    title: str = ""
    body_md: str = ""
    scheduled_for: Optional[datetime] = None
    status: str = "draft"


class ContentPostPatch(BaseModel):
    title: Optional[str] = None
    body_md: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    status: Optional[str] = None


class WaitlistSignupOut(BaseModel):
    id: int
    email: str
    source: str
    referral_code: str
    position_in_queue: int
    referred_by_id: Optional[int]
    referral_count: int
    created_at: datetime
    activated_at: Optional[datetime]
    notes: str

    model_config = {"from_attributes": True}


class WaitlistSignupCreate(BaseModel):
    email: str
    source: str = "direct"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _gen_referral_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── INVESTORS ─────────────────────────────────────────────────────────────────

@router.get("/investors/export")
def export_investors(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> StreamingResponse:
    try:
        investors = db.query(Investor).order_by(Investor.id).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "name", "firm", "role", "contact_email", "twitter_handle",
            "linkedin_url", "intro_path", "status", "last_contact_at",
            "next_action", "check_size_target", "stage_focus", "created_at", "updated_at",
        ])
        for inv in investors:
            writer.writerow([
                inv.id, inv.name, inv.firm, inv.role, inv.contact_email,
                inv.twitter_handle, inv.linkedin_url, inv.intro_path, inv.status,
                inv.last_contact_at, inv.next_action, inv.check_size_target,
                inv.stage_focus, inv.created_at, inv.updated_at,
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=investors.csv"},
        )
    except Exception as exc:
        logger.error("export_investors error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Export failed")


@router.get("/investors/follow-up-due")
def get_follow_up_due(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[dict]:
    try:
        now = datetime.now(timezone.utc)
        results = []

        # 7+ days since email_sent with no reply → follow_up_due
        email_sent = db.query(Investor).filter(Investor.status == "email_sent").all()
        for inv in email_sent:
            if inv.last_contact_at and (now - inv.last_contact_at).days >= 7:
                results.append({"investor": InvestorOut.model_validate(inv), "reason": "follow_up_due"})

        # 24h+ since met with no thank-you → thank_you_due
        met_recent = db.query(Investor).filter(Investor.status == "met").all()
        for inv in met_recent:
            if inv.last_contact_at and (now - inv.last_contact_at).total_seconds() >= 86400:
                results.append({"investor": InvestorOut.model_validate(inv), "reason": "thank_you_due"})

        # 14+ days since met → decision_due
        met_old = db.query(Investor).filter(Investor.status == "following_up").all()
        for inv in met_old:
            if inv.last_contact_at and (now - inv.last_contact_at).days >= 14:
                results.append({"investor": InvestorOut.model_validate(inv), "reason": "decision_due"})

        return results
    except Exception as exc:
        logger.error("get_follow_up_due error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load follow-up list")


@router.get("/investors", response_model=list[InvestorOut])
def list_investors(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[InvestorOut]:
    try:
        return db.query(Investor).order_by(Investor.id).all()
    except Exception as exc:
        logger.error("list_investors error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load investors")


@router.post("/investors", response_model=InvestorOut, status_code=201)
def create_investor(
    body: InvestorCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> InvestorOut:
    try:
        inv = Investor(**body.model_dump())
        db.add(inv)
        db.commit()
        db.refresh(inv)
        return InvestorOut.model_validate(inv)
    except Exception as exc:
        db.rollback()
        logger.error("create_investor error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create investor")


@router.patch("/investors/{investor_id}", response_model=InvestorOut)
def patch_investor(
    investor_id: int,
    body: InvestorPatch,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> InvestorOut:
    try:
        inv = db.get(Investor, investor_id)
        if not inv:
            raise HTTPException(status_code=404, detail="Investor not found")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(inv, field, value)
        db.commit()
        db.refresh(inv)
        return InvestorOut.model_validate(inv)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("patch_investor error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update investor")


@router.delete("/investors/{investor_id}")
def delete_investor(
    investor_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> Response:
    try:
        inv = db.get(Investor, investor_id)
        if not inv:
            raise HTTPException(status_code=404, detail="Investor not found")
        db.delete(inv)
        db.commit()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("delete_investor error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete investor")


# ── EMAIL TEMPLATES ────────────────────────────────────────────────────────────

@router.get("/email-templates")
def get_email_templates(_admin: User = Depends(_require_admin)) -> dict:
    return {"templates": EMAIL_TEMPLATES}


@router.post("/email-templates/personalize")
def personalize_template(
    body: dict,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    try:
        template_id = body.get("template_id")
        investor_id = body.get("investor_id")

        tmpl = next((t for t in EMAIL_TEMPLATES if t["id"] == template_id), None)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")

        inv = db.get(Investor, investor_id)
        if not inv:
            raise HTTPException(status_code=404, detail="Investor not found")

        placeholders = {
            "name": inv.name.split()[0] if inv.name else "",
            "firm": inv.firm or "",
            "stage_focus": inv.stage_focus or "seed",
        }

        personalized_subject = tmpl["subject"].format(**placeholders)
        personalized_body = tmpl["body"].format(**placeholders)

        return {
            "template_id": template_id,
            "investor_id": investor_id,
            "subject": personalized_subject,
            "body": personalized_body,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("personalize_template error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not personalize template")


# ── CONTENT ────────────────────────────────────────────────────────────────────

@router.get("/content/drafts")
def get_draft_vault(_admin: User = Depends(_require_admin)) -> dict:
    return {"drafts": SEED_DRAFTS}


@router.get("/content/export")
def export_content(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> StreamingResponse:
    try:
        posts = db.query(ContentPost).order_by(ContentPost.id).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "platform", "content_type", "title", "status",
            "scheduled_for", "posted_at", "compliance_checked", "created_at",
        ])
        for p in posts:
            writer.writerow([
                p.id, p.platform, p.content_type, p.title, p.status,
                p.scheduled_for, p.posted_at, p.compliance_checked, p.created_at,
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=content_posts.csv"},
        )
    except Exception as exc:
        logger.error("export_content error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Export failed")


@router.get("/content", response_model=list[ContentPostOut])
def list_content(
    status: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[ContentPostOut]:
    try:
        q = db.query(ContentPost)
        if status:
            q = q.filter(ContentPost.status == status)
        if platform:
            q = q.filter(ContentPost.platform == platform)
        return q.order_by(ContentPost.id).all()
    except Exception as exc:
        logger.error("list_content error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load content")


@router.post("/content", response_model=ContentPostOut, status_code=201)
def create_content(
    body: ContentPostCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> ContentPostOut:
    try:
        post = ContentPost(**body.model_dump())
        db.add(post)
        db.commit()
        db.refresh(post)
        return ContentPostOut.model_validate(post)
    except Exception as exc:
        db.rollback()
        logger.error("create_content error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create post")


@router.patch("/content/{post_id}", response_model=ContentPostOut)
def patch_content(
    post_id: int,
    body: ContentPostPatch,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> ContentPostOut:
    try:
        post = db.get(ContentPost, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(post, field, value)
        db.commit()
        db.refresh(post)
        return ContentPostOut.model_validate(post)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("patch_content error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update post")


@router.delete("/content/{post_id}")
def delete_content(
    post_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> Response:
    try:
        post = db.get(ContentPost, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        db.delete(post)
        db.commit()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("delete_content error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete post")


@router.post("/content/{post_id}/check-compliance")
def content_check_compliance(
    post_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    try:
        post = db.get(ContentPost, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        issues = check_compliance(post.body_md)
        post.compliance_checked = True
        post.compliance_issues = issues
        db.commit()
        db.refresh(post)
        return {"post_id": post_id, "issues": issues, "passed": len(issues) == 0}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("content_check_compliance error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Compliance check failed")


# ── WAITLIST ───────────────────────────────────────────────────────────────────

@router.get("/waitlist/stats")
def waitlist_stats(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())

        total = db.query(WaitlistSignup).count()
        today_count = db.query(WaitlistSignup).filter(
            WaitlistSignup.created_at >= today_start
        ).count()
        week_count = db.query(WaitlistSignup).filter(
            WaitlistSignup.created_at >= week_start
        ).count()
        activated = db.query(WaitlistSignup).filter(
            WaitlistSignup.activated_at.isnot(None)
        ).count()
        activation_rate = round(activated / total * 100, 1) if total else 0.0

        # Viral K: average referrals per signup
        total_referrals = db.query(
            sa_func.sum(WaitlistSignup.referral_count)
        ).scalar() or 0
        viral_k = round(total_referrals / total, 2) if total else 0.0

        # Top sources
        source_rows = (
            db.query(WaitlistSignup.source, sa_func.count(WaitlistSignup.id).label("n"))
            .group_by(WaitlistSignup.source)
            .order_by(sa_func.count(WaitlistSignup.id).desc())
            .all()
        )
        top_sources = [{"source": r.source, "count": r.n} for r in source_rows]

        return {
            "total": total,
            "today": today_count,
            "this_week": week_count,
            "activation_rate": activation_rate,
            "viral_k": viral_k,
            "top_sources": top_sources,
        }
    except Exception as exc:
        logger.error("waitlist_stats error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load waitlist stats")


@router.get("/waitlist/leaderboard")
def waitlist_leaderboard(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[WaitlistSignupOut]:
    try:
        return (
            db.query(WaitlistSignup)
            .order_by(WaitlistSignup.referral_count.desc())
            .limit(50)
            .all()
        )
    except Exception as exc:
        logger.error("waitlist_leaderboard error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load leaderboard")


@router.get("/waitlist/growth")
def waitlist_growth(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[dict]:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        rows = (
            db.query(
                sa_func.date(WaitlistSignup.created_at).label("date"),
                sa_func.count(WaitlistSignup.id).label("count"),
            )
            .filter(WaitlistSignup.created_at >= cutoff)
            .group_by(sa_func.date(WaitlistSignup.created_at))
            .order_by(sa_func.date(WaitlistSignup.created_at))
            .all()
        )
        return [{"date": str(r.date), "count": r.count} for r in rows]
    except Exception as exc:
        logger.error("waitlist_growth error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load growth data")


@router.get("/waitlist/signups", response_model=list[WaitlistSignupOut])
def list_waitlist(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[WaitlistSignupOut]:
    try:
        return (
            db.query(WaitlistSignup)
            .order_by(WaitlistSignup.position_in_queue)
            .offset(skip)
            .limit(limit)
            .all()
        )
    except Exception as exc:
        logger.error("list_waitlist error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load waitlist")


@router.post("/waitlist/signups", response_model=WaitlistSignupOut, status_code=201)
def add_waitlist_signup(
    body: WaitlistSignupCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> WaitlistSignupOut:
    try:
        existing = db.query(WaitlistSignup).filter(WaitlistSignup.email == body.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already on waitlist")

        # Generate a unique referral code
        for _ in range(10):
            code = _gen_referral_code()
            if not db.query(WaitlistSignup).filter(WaitlistSignup.referral_code == code).first():
                break

        total = db.query(WaitlistSignup).count()
        signup = WaitlistSignup(
            email=body.email,
            source=body.source,
            referral_code=code,
            position_in_queue=total + 1,
        )
        db.add(signup)
        db.commit()
        db.refresh(signup)
        return WaitlistSignupOut.model_validate(signup)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("add_waitlist_signup error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not add signup")


# ── DAILY SUMMARY ──────────────────────────────────────────────────────────────

@router.get("/daily-summary")
def daily_summary(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())

        # Day number from PlaybookStart
        start_row = db.query(PlaybookStart).first()
        if start_row and start_row.started_at:
            day_number = min((now - start_row.started_at).days + 1, 90)
        else:
            day_number = 1

        # Investor pipeline
        total_investors = db.query(Investor).count()
        meetings_this_week = db.query(Investor).filter(
            Investor.status.in_(["meeting_scheduled", "met"]),
            Investor.last_contact_at >= week_start,
        ).count()

        # Follow-ups due (simplified count)
        follow_up_due_count = db.query(Investor).filter(
            Investor.status == "email_sent",
            Investor.last_contact_at <= now - timedelta(days=7),
        ).count()

        # Content: unfilled slots today (scheduled_for today but not posted)
        unfilled_today = db.query(ContentPost).filter(
            ContentPost.scheduled_for >= today_start,
            ContentPost.scheduled_for < today_start + timedelta(days=1),
            ContentPost.status == "scheduled",
        ).count()

        scheduled_count = db.query(ContentPost).filter(
            ContentPost.status == "scheduled"
        ).count()

        # Waitlist today
        waitlist_total = db.query(WaitlistSignup).count()
        waitlist_today = db.query(WaitlistSignup).filter(
            WaitlistSignup.created_at >= today_start
        ).count()

        # Today's top incomplete task (lowest priority P0 > P1 > P2, then sort_order)
        playbook_task = None
        task = (
            db.query(PlaybookTask)
            .filter(PlaybookTask.status != "complete")
            .order_by(PlaybookTask.priority, PlaybookTask.sort_order)
            .first()
        )
        if task:
            playbook_task = {
                "title": task.title,
                "description": task.description,
                "priority": task.priority,
            }

        return {
            "day_number": day_number,
            "investor_pipeline": {
                "total": total_investors,
                "meetings_this_week": meetings_this_week,
                "follow_ups_due": follow_up_due_count,
            },
            "content": {
                "unfilled_slots_today": unfilled_today,
                "scheduled_count": scheduled_count,
            },
            "waitlist": {
                "total": waitlist_total,
                "today_count": waitlist_today,
            },
            "playbook_task": playbook_task,
        }
    except Exception as exc:
        logger.error("daily_summary error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load daily summary")


# ── SEED ───────────────────────────────────────────────────────────────────────

@router.post("/seed")
def seed_founder_data(
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    try:
        investors_added = 0
        for data in SEED_INVESTORS:
            exists = db.query(Investor).filter(Investor.name == data["name"]).first()
            if not exists:
                db.add(Investor(**data))
                investors_added += 1

        posts_added = 0
        for data in SEED_DRAFTS:
            exists = db.query(ContentPost).filter(ContentPost.title == data["title"]).first()
            if not exists:
                db.add(ContentPost(**data))
                posts_added += 1

        db.commit()
        return {
            "seeded": True,
            "investors_added": investors_added,
            "posts_added": posts_added,
        }
    except Exception as exc:
        db.rollback()
        logger.error("seed_founder_data error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Seed failed")
